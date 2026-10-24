"""WebView2 检测与引导单测（阶段四 4.3 / 回归 9 / NFR-C2）。

钉住四件事：
- 三处注册表位置（64 位主位置 / 32 位 / 按用户安装）都能识别，`0.0.0.0` 与空值算未安装；
- 引导文案必须带官方下载页（用户照着就能装）；
- 只有用户点「是」才打开下载页，点「否」不能乱开浏览器；
- 认得出「WebView2 起不来」这类异常（装坏 / 被禁用），再走同一条引导而不是甩堆栈。
"""

from __future__ import annotations

import sys

import pytest

from backend import webview2


def _reader(values: dict[str, str | None]):
    """按「hive:路径」子串返回固定值；未列出的路径当作不存在。"""

    def read(hive: str, path: str) -> str | None:
        joined = f"{hive}:{path}".lower()
        for key, value in values.items():
            if key.lower() in joined:
                return value
        return None

    return read


def test_runtime_version_reads_machine_wide_install() -> None:
    reader = _reader({"WOW6432Node": "155.0.4283.62"})
    assert webview2.runtime_version(reader=reader) == "155.0.4283.62"


def test_runtime_version_falls_back_to_32bit_and_per_user(tmp_path) -> None:
    only_hkcu = _reader({"hkcu:": "120.0.1.0"})
    assert webview2.runtime_version(reader=only_hkcu) == "120.0.1.0"

    # 第一条（WOW6432Node）没有，第二条（32 位系统位置）有
    second_path = _reader({r"hklm:software\microsoft\edgeupdate": "130.0.0.1"})
    assert webview2.runtime_version(reader=second_path) == "130.0.0.1"


@pytest.mark.parametrize("placeholder", [None, "", "0.0.0.0"])
def test_runtime_version_treats_placeholders_as_missing(placeholder) -> None:
    reader = _reader({"WOW6432Node": placeholder, "hkcu:": placeholder})
    assert webview2.runtime_version(reader=reader) is None


def test_runtime_version_empty_reader_means_missing() -> None:
    assert webview2.runtime_version(reader=lambda _hive, _path: None) is None


def test_guidance_text_points_at_official_download_page() -> None:
    text = webview2.guidance_text()
    assert "WebView2" in text
    assert webview2.DOWNLOAD_URL in text
    assert "WebView2 Runtime" in text


def test_guidance_text_appends_technical_detail() -> None:
    text = webview2.guidance_text("WebView2 初始化失败：HRESULT 0x8007xxxx")
    assert "技术信息" in text
    assert "0x8007xxxx" in text


def test_show_guidance_opens_download_page_only_when_confirmed() -> None:
    opened: list[str] = []
    asked: list[tuple[str, str]] = []

    def confirm(message: str, title: str) -> bool:
        asked.append((message, title))
        return True

    assert (
        webview2.show_guidance_dialog(confirm=confirm, open_url=opened.append) is True
    )
    assert opened == [webview2.DOWNLOAD_URL]
    assert asked[0][1] == webview2.GUIDANCE_TITLE
    assert webview2.DOWNLOAD_URL in asked[0][0]

    declined: list[str] = []
    assert (
        webview2.show_guidance_dialog(
            confirm=lambda _message, _title: False, open_url=declined.append
        )
        is False
    )
    assert declined == []


def test_check_or_guide_prompts_only_when_missing(monkeypatch) -> None:
    prompts: list[int] = []

    monkeypatch.setattr(webview2, "runtime_version", lambda: "155.0.4283.62")
    assert webview2.check_or_guide(prompt=lambda: prompts.append(1)) is True
    assert prompts == []

    monkeypatch.setattr(webview2, "runtime_version", lambda: None)
    assert webview2.check_or_guide(prompt=lambda: prompts.append(2)) is False
    assert prompts == [2]

    # 强制模拟缺失：即使装了也要走引导（验收 / 排障用）
    monkeypatch.setattr(webview2, "runtime_version", lambda: "155.0.4283.62")
    assert (
        webview2.check_or_guide(force_missing=True, prompt=lambda: prompts.append(3))
        is False
    )
    assert prompts == [2, 3]


def test_is_webview2_failure_recognises_runtime_errors() -> None:
    assert webview2.is_webview2_failure(RuntimeError("WebView2 runtime not found"))

    class WebViewRuntimeError(Exception):
        pass

    WebViewRuntimeError.__module__ = "webview.errors"
    assert webview2.is_webview2_failure(WebViewRuntimeError("Runtime not found"))

    # 与 WebView2 无关的异常不能被误判成「缺运行时」，否则会把真 bug 引导成重装
    assert webview2.is_webview2_failure(ValueError("普通错误")) is False
    assert webview2.is_webview2_failure(OSError("磁盘只读")) is False


@pytest.mark.skipif(sys.platform != "win32", reason="注册表检测是 Windows 专用")
def test_real_runtime_detection_does_not_raise() -> None:
    """本机装了 WebView2（155.x）；这里只要求「能跑通并给出字符串或 None」。"""
    version = webview2.runtime_version()
    assert version is None or isinstance(version, str)
