"""任务 2.12 测试：长任务框架（S2-03 方案 A）。

覆盖：任务提交与状态流转、互斥（409 + 3004）、失败保留 error、
DELETE 清理、不存在的 tid 返回 2001、接口需 token、TTL 惰性清理。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER
from backend.services.tasks import (
    STATE_FAILED,
    STATE_SUCCESS,
    TASK_TTL_SECONDS,
    TaskConflict,
    TaskManager,
)


def _wait_state(manager: TaskManager, tid: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = manager.snapshot(tid)
        assert snapshot is not None
        if snapshot["state"] in (STATE_SUCCESS, STATE_FAILED):
            return snapshot
        time.sleep(0.01)
    raise AssertionError("任务未在超时前结束")


# --------------------------------------------------------------------------
# 管理器层
# --------------------------------------------------------------------------


def test_task_runs_to_success_with_progress() -> None:
    manager = TaskManager()
    started = threading.Event()

    def work(report):
        started.set()
        report(50, "一半")
        return {"count": 42}

    tid = manager.submit("demo", work)
    assert started.wait(2.0)
    snapshot = _wait_state(manager, tid)
    assert snapshot["state"] == STATE_SUCCESS
    assert snapshot["progress"] == 100
    assert snapshot["result"] == {"count": 42}
    assert snapshot["error"] is None
    assert snapshot["type"] == "demo"


def test_task_fields_match_s2_03_contract() -> None:
    """任务对象必须包含 S2-03 约定的 8 个字段。"""
    manager = TaskManager()
    tid = manager.submit("demo", lambda report: None)
    snapshot = _wait_state(manager, tid)
    assert set(snapshot) == {
        "tid",
        "type",
        "state",
        "progress",
        "message",
        "result",
        "error",
        "created_at",
    }


def test_mutex_rejects_second_task() -> None:
    """互斥：同时只允许一个长任务，第二个直接冲突（不排队、不静默挂起）。"""
    manager = TaskManager()
    gate = threading.Event()
    manager.submit(
        "first",
        lambda report: gate.wait(5.0),
    )
    assert manager.has_active()
    with pytest.raises(TaskConflict):
        manager.submit("second", lambda report: None)
    gate.set()


def test_failed_task_keeps_error_message() -> None:
    manager = TaskManager()

    def boom(report):
        raise RuntimeError("磁盘写满")

    tid = manager.submit("backup", boom)
    snapshot = _wait_state(manager, tid)
    assert snapshot["state"] == STATE_FAILED
    assert "磁盘写满" in (snapshot["error"] or "")
    assert snapshot["message"] == "任务失败"


def test_progress_is_clamped() -> None:
    manager = TaskManager()
    tid = manager.submit("demo", lambda report: report(500))
    snapshot = _wait_state(manager, tid)
    assert snapshot["progress"] == 100


def test_finished_tasks_are_purged_after_ttl() -> None:
    """已完成任务超过 TTL 后惰性清理（失败任务保留 5 分钟供查看）。"""
    manager = TaskManager()
    tid = manager.submit("demo", lambda report: None)
    _wait_state(manager, tid)

    manager.get(tid).finished_at = time.time() - TASK_TTL_SECONDS - 1
    # 下一次提交触发惰性清理，且不应因旧任务而误判为「有任务在跑」
    new_tid = manager.submit("demo2", lambda report: None)
    assert new_tid != tid
    assert manager.get(tid) is None
    _wait_state(manager, new_tid)


def test_delete_removes_task() -> None:
    manager = TaskManager()
    tid = manager.submit("demo", lambda report: None)
    _wait_state(manager, tid)
    assert manager.delete(tid) is True
    assert manager.delete(tid) is False
    assert manager.snapshot(tid) is None


# --------------------------------------------------------------------------
# 接口层（§6.2 新增 #45）
# --------------------------------------------------------------------------


def test_get_task_requires_token(client, config) -> None:
    response = client.get("/api/tasks/whatever")
    assert response.status_code == 401
    assert response.json()["code"] == 1002


def test_get_unknown_task_returns_2001(client, config) -> None:
    response = client.get(
        "/api/tasks/does-not-exist", headers={TOKEN_HEADER: config.token}
    )
    assert response.status_code == 200
    assert response.json()["code"] == 2001


def test_get_and_delete_task_via_api(client, config) -> None:
    manager = client.app.state.tasks
    tid = manager.submit("demo", lambda report: {"ok": True})
    _wait_state(manager, tid)

    response = client.get(f"/api/tasks/{tid}", headers={TOKEN_HEADER: config.token})
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["state"] == STATE_SUCCESS
    assert body["data"]["result"] == {"ok": True}
    assert "max_seconds" in body["data"]

    deleted = client.delete(f"/api/tasks/{tid}", headers={TOKEN_HEADER: config.token})
    assert deleted.status_code == 200
    assert deleted.json()["code"] == 0

    gone = client.get(f"/api/tasks/{tid}", headers={TOKEN_HEADER: config.token})
    assert gone.json()["code"] == 2001


def test_task_conflict_maps_to_409_with_3004(client, config) -> None:
    """S2-03 ①：互斥冲突必须表达为 HTTP 409 + code 3004。"""
    from backend.schemas import CODE_TASK_CONFLICT, status_for

    assert status_for(CODE_TASK_CONFLICT) == 409

    manager = client.app.state.tasks
    gate = threading.Event()
    manager.submit("first", lambda report: gate.wait(5.0))
    try:
        with pytest.raises(TaskConflict):
            manager.submit("second", lambda report: None)
    finally:
        gate.set()
