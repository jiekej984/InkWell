"""单实例守卫单测（阶段四 4.2 / 回归 10 / NFR-S3）。

钉住四件事：
- 互斥量名按**数据目录**归一化生成：同一目录（含大小写 / 末尾斜杠差异）同名，不同目录不同名；
- 同一目录第二次 `acquire()` 必须失败（内核互斥量是真锁，不是进程内标记）；
- 释放之后可以重新拿到；
- 找不到窗口时 `activate_existing_window()` 返回 False 且不抛错（第二实例不能因为
  「叫不醒窗口」而崩在启动路径上）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from backend.single_instance import (
    MUTEX_PREFIX,
    SingleInstance,
    activate_existing_window,
    instance_name,
)


def test_instance_name_normalizes_same_directory(tmp_path: Path) -> None:
    base = instance_name(tmp_path)
    assert base.startswith(MUTEX_PREFIX)
    assert instance_name(Path(str(tmp_path) + "\\")) == base
    assert instance_name(Path(str(tmp_path).upper())) == base


def test_instance_name_differs_per_data_directory(tmp_path: Path) -> None:
    first = instance_name(tmp_path / "library-a")
    second = instance_name(tmp_path / "library-b")
    assert first != second


def test_second_acquire_fails_until_released(tmp_path: Path) -> None:
    guard = SingleInstance(tmp_path)
    assert guard.acquire() is True
    try:
        # 同名互斥量：即使在同一进程里再建一次也会拿到 ERROR_ALREADY_EXISTS
        second = SingleInstance(tmp_path)
        assert second.acquire() is False
    finally:
        guard.release()
    retry = SingleInstance(tmp_path)
    assert retry.acquire() is True
    retry.release()


def test_different_data_directories_do_not_block_each_other(tmp_path: Path) -> None:
    first = SingleInstance(tmp_path / "one")
    second = SingleInstance(tmp_path / "two")
    assert first.acquire() is True
    try:
        assert second.acquire() is True
        second.release()
    finally:
        first.release()


def test_release_is_idempotent(tmp_path: Path) -> None:
    guard = SingleInstance(tmp_path)
    guard.release()  # 没拿到过也能安全调用
    assert guard.acquire() is True
    guard.release()
    guard.release()


def test_activate_window_returns_false_when_missing() -> None:
    assert activate_existing_window("InkwellNoSuchWindowTitle-4c1f") is False


@pytest.mark.skipif(sys.platform != "win32", reason="互斥量实现是 Windows 专用")
def test_mutex_name_matches_win32_format(tmp_path: Path) -> None:
    name = instance_name(tmp_path)
    assert name.startswith("Local\\Inkwell-")
    assert len(name.split("-")[-1]) == 16
