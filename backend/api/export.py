"""导出接口（§6.2 #35，任务 2.10）。

POST /projects/{pid}/export  导出 TXT/MD【长任务】
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..config import AppConfig
from ..database import Database
from ..models import session_scope
from ..schemas import CODE_NOT_FOUND, CODE_PARAM_INVALID, ApiError
from ..services import export_service, project_service
from .maintenance import submit_task

router = APIRouter(tags=["export"])


class ExportRequest(BaseModel):
    """导出格式。"""

    format: str = "txt"


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


def _config(request: Request) -> AppConfig:
    return request.app.state.config


@router.post("/projects/{pid}/export")
def export_project(request: Request, pid: int, payload: ExportRequest) -> dict:
    """§6.2 #35：导出 TXT/MD（长任务）。"""
    fmt = (payload.format or "").lower()
    if fmt not in export_service.FORMATS:
        raise ApiError(CODE_PARAM_INVALID, "导出格式只能是 txt 或 md")

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
