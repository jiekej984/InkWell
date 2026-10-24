"""WebView2 运行时检测与引导（阶段四 4.3 / 回归 9 / NFR-C2 / R-8）。

Inkwell 的窗口依赖 **Microsoft Edge WebView2 Runtime**。缺它的时候 pywebview 只会在
.NET 层抛一个 `WebView2RuntimeNotFoundException`，用户看到的是一个空弹窗或者直接退出——
回归 9 要求「没有 WebView2 时给出正确引导」，所以：

1. **检测**：读 EdgeUpdate 的 Client 键（`pv` 值）。按 Microsoft 文档的三处都查：
   - `HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{GUID}`（64 位系统的主流位置，本机即此处）
   - `HKLM\\SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\{GUID}`（32 位系统）
   - `HKCU\\Software\\Microsoft\\EdgeUpdate\\Clients\\{GUID}`（按用户安装）
   `pv` 为空 / 缺失 / `0.0.0.0` 一律视为未安装（微软约定的占位值）。
2. **引导**：没有 WebView2 时连 HTML 页面都渲染不出来，所以引导必须是**原生对话框**：
   说清缺什么、给官方下载页、问要不要现在打开；选「是」用默认浏览器打开下载页。
3. **兜底**：检测通过但 WebView2 初始化仍然失败（装坏了 / 被策略禁用）时，
   `is_webview2_failure()` 能认出这类异常，走同一条引导而不是甩堆栈。

排障开关：`INKWELL_FAKE_NO_WEBVIEW2=1` 强制按「缺失」处理（演示引导 / 验收回归 9 用），
`main.py --check-webview2` 只做检测并返回退出码（0 = 已安装，1 = 缺失）。
"""

from __future__ import annotations

import sys
import webbrowser

RUNTIME_CLIENT_ID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
DOWNLOAD_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"
GUIDANCE_TITLE = "Inkwell 需要 Microsoft Edge WebView2 运行时"
FAKE_MISSING_ENV = "INKWELL_FAKE_NO_WEBVIEW2"
MISSING_PLACEHOLDERS = frozenset({"", "0.0.0.0"})

_REGISTRY_PATHS = (
    (
        "HKLM",
        rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{RUNTIME_CLIENT_ID}",
    ),
    ("HKLM", rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{RUNTIME_CLIENT_ID}"),
    ("HKCU", rf"Software\Microsoft\EdgeUpdate\Clients\{RUNTIME_CLIENT_ID}"),
)

_HIVES = {
    "HKLM": 0x80000002,
    "HKCU": 0x80000001,
}  # winreg.HKEY_LOCAL_MACHINE / HKEY_CURRENT_USER


def _read_registry_pv(hive: str, path: str) -> str | None:
    """读 `pv`；键或值不存在返回 None（不抛错）。"""
    if sys.platform != "win32":
        return None
    import winreg

    hive_handle = _HIVES[hive]
    try:
        with winreg.OpenKey(hive_handle, path) as key:
            value, _ = winreg.QueryValueEx(key, "pv")
    except OSError:
        return None
    return str(value).strip() if value is not None else None


def runtime_version(reader=None) -> str | None:
    """返回已安装的 WebView2 Runtime 版本；未安装返回 None。

    `reader(hive, path) -> str | None` 可注入，单测用它模拟三种安装位置。
    """
    read = reader or _read_registry_pv
    for hive, path in _REGISTRY_PATHS:
        value = read(hive, path)
        if value and value not in MISSING_PLACEHOLDERS:
            return value
    return None


def guidance_text(detail: str = "") -> str:
    """引导文案（对话框正文；单测也断言它带官方下载页）。"""
    head = (
        "Inkwell 需要 Microsoft Edge WebView2 运行时才能显示窗口，"
        "但当前系统上还没检测到它。\n\n"
        "Windows 11 和新版 Windows 10 一般已自带；如果确实缺失，"
        "请安装「WebView2 Runtime」（Evergreen 版）：\n"
        f"{DOWNLOAD_URL}\n\n"
        "安装完成后重新打开 Inkwell 即可。\n\n"
        "现在用默认浏览器打开下载页吗？"
    )
    if detail:
        return f"{head}\n\n（技术信息：{detail}）"
    return head


def is_webview2_failure(exc: BaseException) -> bool:
    """异常是否属于「WebView2 起不来」（装坏了 / 被禁用 / 找不到运行时）。"""
    module = (type(exc).__module__ or "").lower()
    text = f"{type(exc).__name__}: {exc}".lower()
    if "webview2" in text:
        return True
    return module.startswith("webview") and ("runtime" in text or "webview2" in module)


def _default_confirm(message: str, title: str) -> bool:
    """原生确认框：是 = 打开下载页。非 Windows 环境退化为打印。"""
    if sys.platform != "win32":
        print(message, file=sys.stderr)
        return False
    import ctypes

    MB_YESNO = 0x00000004
    MB_ICONERROR = 0x00000010
    IDYES = 6
    result = ctypes.windll.user32.MessageBoxW(
        None, message, title, MB_YESNO | MB_ICONERROR
    )
    return result == IDYES


def _default_open_url(url: str) -> None:
    webbrowser.open(url)


def show_guidance_dialog(
    detail: str = "",
    *,
    confirm=None,
    open_url=None,
) -> bool:
    """弹「缺 WebView2」的原生引导；返回是否打开了下载页。

    `confirm` / `open_url` 可注入，单测据此断言「选是才开下载页」而不用真弹窗。
    """
    ask = confirm or _default_confirm
    opener = open_url or _default_open_url
    accepted = ask(guidance_text(detail), GUIDANCE_TITLE)
    if accepted:
        opener(DOWNLOAD_URL)
    return bool(accepted)


def check_or_guide(*, force_missing: bool = False, prompt=None) -> bool:
    """检查运行时；缺失时弹引导并返回 False（调用方据此退出）。"""
    if not force_missing and runtime_version():
        return True
    (prompt or show_guidance_dialog)()
    return False
