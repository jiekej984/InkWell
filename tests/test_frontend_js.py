"""前端逻辑单测（Node 内置 test runner，零第三方依赖）。

覆盖：
    · 2.4 自动保存时序：停输 3s / 最长 30s / 失败重试 1s+3s+9s / 3002 不重试
    · 回归 15：重试耗尽 → 双份暂存 → 重启恢复 → 自动补写并清理

Node 缺失时跳过（不阻断后端测试）；CI 与本地开发机上 Node 存在即执行。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NODE = shutil.which("node")
JS_TESTS = sorted((ROOT / "tests" / "js").glob("*.test.js"))


@pytest.mark.skipif(NODE is None, reason="未安装 Node.js，跳过前端逻辑单测")
def test_frontend_js_suite() -> None:
    """跑 ``tests/js/*.test.js``（逐个传文件，兼容不支持目录发现的 Node）。"""
    assert JS_TESTS, "未找到 tests/js/*.test.js"
    completed = subprocess.run(
        [NODE, "--test", *[str(path.relative_to(ROOT)) for path in JS_TESTS]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
    )
    detail = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode == 0, f"前端逻辑单测失败：\n{detail}"
