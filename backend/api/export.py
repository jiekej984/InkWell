"""导出接口（§6.2 #35 整本 / #50 单章）。

POST /projects/{pid}/export   导出 TXT/MD【长任务】（任务 2.10）
POST /chapters/{cid}/export   导出单章 TXT/MD（阶段三 3.5 / C-03「导出本章」）
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..config import AppConfig
from ..database import Database
from ..models import session_scope
from ..schemas import CODE_NOT_FOUND, CODE_PARAM_INVALID, ApiError, ok
from ..services import export_service, project_service
from .maintenance import submit_task

router = APIRouter(tags=["export"])


class ExportRequest(BaseModel):
    """导出格式。"""

    format: str = "txt"


class ChapterExportRequest(BaseModel):
    """单章导出入参（#50）。

    ``content_html`` 为编辑器当前正文：保存失败时用它导出**尚未保存**的内容；
    缺省则导出库内已保存正文。``title`` 缺省用库内章节标题。
    """

    format: str = "txt"
    title: str | None = None
    content_html: str | None = None


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


def _config(request: Request) -> AppConfig:
    return request.app.state.config


def _clean_format(payload: ExportRequest | ChapterExportRequest) -> str:
    fmt = (payload.format or "").lower()
    if fmt not in export_service.FORMATS:
        raise ApiError(CODE_PARAM_INVALID, "导出格式只能是 txt 或 md")
    return fmt


@router.post("/projects/{pid}/export")
def export_project(request: Request, pid: int, payload: ExportRequest) -> dict:
    """§6.2 #35：导出 TXT/MD（长任务）。"""
    fmt = _clean_format(payload)

    database = _database(request)
    config = _config(request)
    with session_scope(database.engine) as session:
        project_service.require_project(session, pid)  # 同步校验项目存在

    return submit_task(
        request,
        "export",
        lambda report: export_service.export_project(
            database, config.data_dir, pid, fmt, report=report
        ),
    )


@router.post("/chapters/{cid}/export")
def export_chapter(request: Request, cid: int, payload: ChapterExportRequest) -> dict:
    """§6.2 #50：导出单章 TXT/MD（失败态「导出本章」，C-03）。

    同步执行：单章体量小（≤8MB 入参、成稿 ≤8 万字），无需长任务轮询。
    """
    fmt = _clean_format(payload)
    data = export_service.export_chapter(
        _database(request),
        _config(request).data_dir,
        cid,
        fmt,
        content_html=payload.content_html,
        title=payload.title,
    )
    return ok(data)
