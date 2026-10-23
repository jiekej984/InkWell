"""长任务框架（任务 2.12 / 决策 S2-03）。

报告 §6.2 中 #32 备份 / #34 恢复 / #35 导出 / #42 重建索引 / #43 重算字数
五个接口标注【长任务】，但清单里**没有任务状态查询接口**，故本模块按方案 A 补齐：

    · 进程内**内存**任务表（不落库、不新增业务表）
    · **互斥**：SQLite 写串行（NFR-R2），同时只允许一个长任务；
      第二个提交直接抛 :class:`TaskConflict`（→ HTTP 409 + code 3004），
      **不排队、不静默挂起**
    · 任务对象 ``{tid, type, state, progress, message, result, error, created_at}``
    · **不做取消、不做持久化**：V1 长任务 ≤120s，进程重启任务本就失效
    · 已完成任务保留 ``TASK_TTL_SECONDS``（5 分钟）后惰性清理：
      成功任务由前端读取 ``result`` 后主动 ``DELETE``；失败任务保留供查看

前端约定：提交后拿 ``tid``，**500ms 轮询** ``GET /tasks/{tid}``；
``state=success`` 读 ``result`` 后调用 ``DELETE /tasks/{tid}`` 清理。
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# V1 长任务的时间上界（设计假设，不做强制超时，仅用于文档与调用方自律）
TASK_MAX_SECONDS = 120
# 已完成任务（success / failed）的保留时长
TASK_TTL_SECONDS = 300

STATE_PENDING = "pending"
STATE_RUNNING = "running"
STATE_SUCCESS = "success"
STATE_FAILED = "failed"

_ACTIVE_STATES = (STATE_PENDING, STATE_RUNNING)
_FINISHED_STATES = (STATE_SUCCESS, STATE_FAILED)

# 进度回调：``report(progress, message=None)``
ProgressReporter = Callable[..., None]
TaskFunc = Callable[[ProgressReporter], Any]


class TaskConflict(RuntimeError):
    """已有长任务在执行；调用方应转换为 409 + code 3004。"""


@dataclass
class Task:
    """任务对象（对应 S2-03 约定的 8 个字段）。"""

    tid: str
    type: str
    state: str = STATE_PENDING
    progress: int = 0
    message: str = ""
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tid": self.tid,
            "type": self.type,
            "state": self.state,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
        }


class TaskManager:
    """进程内长任务管理器（线程安全）。"""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    # -- 提交 ------------------------------------------------------------

    def submit(self, task_type: str, func: TaskFunc) -> str:
        """提交一个长任务，立即返回 ``tid``；任务在后台线程执行。

        Raises:
            TaskConflict: 已有 pending / running 的任务（互斥，S2-03 ①）。
        """
        with self._lock:
            self._purge_expired()
            running = [
                task for task in self._tasks.values() if task.state in _ACTIVE_STATES
            ]
            if running:
                raise TaskConflict(
                    f"已有任务进行中: {running[0].type} ({running[0].tid})"
                )
            tid = uuid.uuid4().hex
            self._tasks[tid] = Task(tid=tid, type=task_type)

        thread = threading.Thread(
            target=self._run,
            args=(tid, func),
            name=f"inkwell-task-{tid[:8]}",
            daemon=True,
        )
        thread.start()
        return tid

    # -- 查询 / 清理 ------------------------------------------------------

    def get(self, tid: str) -> Task | None:
        with self._lock:
            task = self._tasks.get(tid)
            if task is None:
                return None
            return task

    def snapshot(self, tid: str) -> dict[str, Any] | None:
        """返回任务的字典快照（避免调用方拿到内部对象）。"""
        task = self.get(tid)
        return None if task is None else task.to_dict()

    def delete(self, tid: str) -> bool:
        """删除任务记录；返回是否存在。"""
        with self._lock:
            return self._tasks.pop(tid, None) is not None

    def has_active(self) -> bool:
        with self._lock:
            return any(task.state in _ACTIVE_STATES for task in self._tasks.values())

    # -- 内部 ------------------------------------------------------------

    def _run(self, tid: str, func: TaskFunc) -> None:
        task = self.get(tid)
        if task is None:  # pragma: no cover - 提交后必然存在
            return
        task.state = STATE_RUNNING
        try:
            task.result = func(
                lambda progress, message=None: self._report(task, progress, message)
            )
        except Exception as exc:
            task.state = STATE_FAILED
            task.error = f"{type(exc).__name__}: {exc}"
            task.message = "任务失败"
        else:
            task.state = STATE_SUCCESS
            task.progress = 100
            if not task.message:
                task.message = "任务完成"
        finally:
            task.finished_at = time.time()

    def _report(self, task: Task, progress: int, message: str | None) -> None:
        task.progress = max(0, min(100, int(progress)))
        if message:
            task.message = message

    def _purge_expired(self) -> None:
        """清理超过 TTL 的已完成任务（惰性，调用方持锁）。"""
        now = time.time()
        expired = [
            tid
            for tid, task in self._tasks.items()
            if task.state in _FINISHED_STATES
            and task.finished_at is not None
            and now - task.finished_at > TASK_TTL_SECONDS
        ]
        for tid in expired:
            del self._tasks[tid]
