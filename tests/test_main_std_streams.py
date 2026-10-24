"""冻结/窗口构建的 stdout 兜底单测（阶段四 4.1 回归）。

背景：PyInstaller `console=False` 的窗口进程里 `sys.stdout` / `sys.stderr` 是 `None`，
而 uvicorn 的 `DefaultFormatter` 会调用 `sys.stdout.isatty()`。第一版兜底只塞了个
`write/flush` 的哑对象，打包后**启动即崩**（`'_NullWriter' object has no attribute
'isatty'`）。这里钉住三件事：补出来的流是真实可写的、带 isatty、原有流不被覆盖。
"""

from __future__ import annotations

import io
import sys

import pytest

from main import _ensure_std_streams


@pytest.fixture()
def restore_streams():
    original_out, original_err = sys.stdout, sys.stderr
    yield
    sys.stdout, sys.stderr = original_out, original_err


def test_null_streams_are_replaced_with_usable_stream(restore_streams):
    sys.stdout = None  # type: ignore[assignment]
    sys.stderr = None  # type: ignore[assignment]

    _ensure_std_streams()

    assert sys.stdout is not None
    assert sys.stderr is not None
    # uvicorn 的 DefaultFormatter 会问 isatty；缺这个属性就是打包后启动即崩
    # （Windows 上 nul 设备本身报告 isatty=True，这里只要求「有且可调用」）
    assert callable(getattr(sys.stdout, "isatty", None))
    assert sys.stdout.isatty() in (True, False)
    assert sys.stdout.write("x") >= 0
    sys.stdout.flush()
    assert str(getattr(sys.stdout, "encoding", "")).lower().startswith("utf")


def test_existing_streams_are_left_untouched(restore_streams):
    buffer = io.StringIO()
    sys.stdout = buffer  # type: ignore[assignment]
    sys.stderr = buffer  # type: ignore[assignment]

    _ensure_std_streams()

    assert sys.stdout is buffer
    assert sys.stderr is buffer
