"""维护接口（§6.2 #42 / #43，任务 2.5 与 2.11）。

POST /maintenance/rebuild-wordcount  重算字数【长任务】（2.5）
POST /maintenance/rebuild-fts        重建全文索引【长任务】（2.11）

长任务统一返回 ``{tid, type}``，前端 500ms 轮询 ``GET /tasks/{tid}``（S2-03）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request

from ..database import Database
from ..schemas import CODE_NOT_FOUND, CODE_TASK_CONFLICT, ApiError, ok
from ..services import maintenance_service
from ..services.tasks import TaskConflict, TaskManager

router = APIRouter(tags=["maintenance"])


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


def _tasks(request: Request) -> TaskManager:
    tasks = getattr(request.app.state, "tasks", None)
    if tasks is None:  # pragma: no cover - 由 create_app 注入
        raise ApiError(CODE_NOT_FOUND, "任务管理器未初始化")
    return tasks


def submit_task(
    request: Request,
    task_type: str,
    job: Callable[[Callable[..., None]], Any],
) -> dict:
    """提交长任务；已有任务进行中 → 409 + 3004（不排队，S2-03）。"""
    try:
        tid = _tasks(request).submit(task_type, job)
    except TaskConflict as exc:
        raise ApiError(CODE_TASK_CONFLICT, f"已有长任务进行中：{exc}") from exc
    return ok({"tid": tid, "type": task_type})


@router.post("/maintenance/rebuild-wordcount")
def rebuild_wordcount(request: Request) -> dict:
    """#43：重算全部章节字数【长任务】。"""
    database = _database(request)
    return submit_task(
        request,
        "rebuild-wordcount",
        lambda report: maintenance_service.rebuild_wordcount(database, report),
    )


@router.post("/maintenance/rebuild-fts")
def rebuild_fts(request: Request) -> dict:
    """#42：重建全文索引【长任务】（任务 2.11）。"""
    database = _database(request)
    return submit_task(
        request,
        "rebuild-fts",
        lambda report: maintenance_service.rebuild_fts(database, report),
    )
