"""系统级接口。

GET  /system/health      健康检查（§6.2 #1）
GET  /system/meta        版本、数据目录、端口、最近项目（§6.2 #2）
GET  /system/integrity   数据库自检：计数 / 体积 / 磁盘 / quick_check（§6.2 #52，3.6）
GET  /system/diagnostics 诊断包（#49）
POST /system/logs        前端异常上报（#44）
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..models import (
    Chapter,
    ChapterVersion,
    Document,
    Project,
    Volume,
    active,
    session_scope,
)
from ..schemas import CODE_NOT_FOUND, CODE_PARAM_INVALID, ApiError, ok
from ..services import drafts as drafts_service
from ..services import logging_service, project_service

router = APIRouter(tags=["system"])


class ClientLog(BaseModel):
    """前端异常 / 请求超时上报入参（#44）。"""

    level: str = "error"
    message: str = Field(min_length=1, max_length=1000)
    context: dict[str, Any] | None = None


def utc_now_iso() -> str:
    """ISO 8601（UTC，带 Z），遵循 §6.1 时间格式约定。"""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@router.get("/system/health")
def health(request: Request) -> dict:
    """健康检查。

    完整路径为 ``/api/system/health``（§6.1 基址 ``/api`` + §6.2 路径）。
    该接口同样受 token 校验保护（决策 S1-04）。
    """
    config = request.app.state.config
    return ok(
        {
            "status": "ok",
            "version": config.version,
            "schema_version": request.app.state.schema_version,
            "time": utc_now_iso(),
        }
    )


@router.get("/system/meta")
def meta(request: Request) -> dict:
    """启动元信息（§6.2 #2）：版本、数据目录、端口、最近项目。

    「最近项目」取 ``last_opened_at`` 最新的活跃项目（FR-1.5）；
    数据库尚未注入时该项为 ``None``，不影响其余字段返回。
    """
    config = request.app.state.config
    data = {
        "version": config.version,
        "schema_version": request.app.state.schema_version,
        "data_dir": str(config.data_dir),
        "host": config.host,
        "port": config.port,
        "base_url": config.base_url,
        "recent_project": None,
    }

    database = getattr(request.app.state, "database", None)
    if database is None:
        return ok(data)

    with session_scope(database.engine) as session:
        recent = (
            session.execute(
                active(Project)
                .where(Project.last_opened_at.is_not(None))
                .order_by(Project.last_opened_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        if recent is not None:
            data["recent_project"] = project_service.serialize_project(recent)
    return ok(data)


@router.post("/system/logs")
def client_log(payload: ClientLog) -> dict:
    """§6.2 #44：前端异常 / 请求超时上报（脱敏后落盘）。

    NFR-M4：除 ``redact`` 的 token / 签名脱敏外，再做正文兜底
    （去 HTML 标签、正文字段整值省略、限长），防止误传正文片段进日志。
    """
    level = (payload.level or "error").lower()
    if level not in ("info", "warning", "warn", "error"):
        raise ApiError(CODE_PARAM_INVALID, "level 只能是 info/warning/error")
    message, context = logging_service.sanitize_client_report(
        payload.message, payload.context
    )
    logging_service.log_event(level, message, scope="frontend", context=context)
    return ok({"logged": True})


def _active_count(session: Any, model: Any) -> int:
    """活跃行计数（统一走 ``active()``，避免遗漏软删除过滤）。"""
    statement = select(func.count()).select_from(active(model).subquery())
    return int(session.execute(statement).scalar() or 0)


def _size_of(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


@router.get("/system/integrity")
def integrity(
    request: Request,
    full: bool = Query(default=False, description="true 时执行完整 integrity_check"),
) -> dict:
    """§6.2 #52：数据库自检（P9「数据库自检」）。

    默认 ``quick_check``（毫秒级，随页面打开刷新）；``?full=1`` 执行完整
    ``integrity_check``（大库可能数秒，用于排查）。返回计数 / 体积 / 磁盘余量，
    **不含正文**。
    """
    config = request.app.state.config
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")

    healthy, messages = database.integrity_check() if full else database.quick_check()
    counts: dict[str, int] = {}
    with session_scope(database.engine) as session:
        counts = {
            "projects": _active_count(session, Project),
            "volumes": _active_count(session, Volume),
            "chapters": _active_count(session, Chapter),
            "documents": _active_count(session, Document),
            "versions": int(
                session.execute(select(func.count(ChapterVersion.id))).scalar() or 0
            ),
        }
    counts["drafts"] = len(drafts_service.list_drafts(config.data_dir))
    backups_dir = Path(config.data_dir) / "backups"
    counts["backups"] = (
        len(list(backups_dir.glob("*.db"))) if backups_dir.is_dir() else 0
    )

    usage = shutil.disk_usage(config.data_dir)
    return ok(
        {
            "ok": healthy,
            "mode": "full" if full else "quick",
            "quick_check": "ok" if healthy else "；".join(messages) or "未知错误",
            "schema_version": request.app.state.schema_version,
            "expected_schema_version": config.schema_version,
            "data_dir": str(config.data_dir),
            "db_path": str(config.db_path),
            "db_size": _size_of(config.db_path),
            "wal_size": _size_of(
                config.db_path.with_name(config.db_path.name + "-wal")
            ),
            "counts": counts,
            "disk": {"total": usage.total, "used": usage.used, "free": usage.free},
            "checked_at": utc_now_iso(),
        }
    )


@router.get("/system/diagnostics")
def diagnostics(request: Request) -> Response:
    """诊断包（NFR-M4 / §8.2）：日志 + 库结构摘要，不含正文 / token / 签名。"""
    config = request.app.state.config
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    payload = logging_service.build_diagnostics(config, database)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="inkwell-diagnostics.zip"'
        },
    )
