"""系统级接口。

GET /system/health  健康检查（§6.2 #1）
GET /system/meta    版本、数据目录、端口、最近项目（§6.2 #2）
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from ..models import Project, active, session_scope
from ..schemas import CODE_NOT_FOUND, CODE_PARAM_INVALID, ApiError, ok
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
