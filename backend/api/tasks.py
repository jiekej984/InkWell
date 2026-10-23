"""长任务状态查询（§6.2 **新增 #45**，任务 2.12 / 决策 S2-03）。

    GET    /tasks/{tid}  —— 查询任务状态
    DELETE /tasks/{tid}  —— 清理任务记录（前端读取 result 后调用）

报告 §6.2 清单中无此接口，按 §8.4 Definition of Done 第 3 条，落地时同步补进清单。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import CODE_NOT_FOUND, ApiError, ok
from ..services.tasks import TASK_MAX_SECONDS, TaskManager

router = APIRouter(tags=["tasks"])


def _manager(request: Request) -> TaskManager:
    manager = getattr(request.app.state, "tasks", None)
    if manager is None:  # pragma: no cover - 由 create_app 保证注入
        raise ApiError(CODE_NOT_FOUND, "任务管理器未初始化")
    return manager


@router.get("/tasks/{tid}")
def get_task(request: Request, tid: str) -> dict:
    """查询任务状态；不存在返回 2001。

    前端约定：提交后 500ms 轮询一次，``state=success`` 读 ``result``，
    随后调用 ``DELETE /tasks/{tid}`` 清理。失败任务保留 5 分钟供查看。
    """
    snapshot = _manager(request).snapshot(tid)
    if snapshot is None:
        raise ApiError(CODE_NOT_FOUND, "任务不存在或已清理")
    return ok({**snapshot, "max_seconds": TASK_MAX_SECONDS})


@router.delete("/tasks/{tid}")
def delete_task(request: Request, tid: str) -> dict:
    """删除任务记录；不存在返回 2001。"""
    if not _manager(request).delete(tid):
        raise ApiError(CODE_NOT_FOUND, "任务不存在或已清理")
    return ok({"tid": tid, "deleted": True})
