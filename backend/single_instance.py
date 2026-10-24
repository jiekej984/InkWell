"""单实例守卫（阶段四 4.2 / 回归 10 / NFR-S3）。

同一个数据目录只允许一个实例：第二次双击不再起第二套后端——否则随机端口各起一套、
两套 WAL 写入 + 两套后台备份/清理会互相踩；重复双击的正确行为是**把已有窗口叫到前台**
然后立刻退出。

实现要点：

- **Windows**：命名互斥量 `Local\\Inkwell-<sha1(数据目录)[:16]>`。
  `CreateMutexW` 之后 `ERROR_ALREADY_EXISTS` 即「已有实例」。`Local\\` 前缀表示
  「每登录会话一个命名空间」：同一用户桌面下互斥，不同用户互不影响（不需要跨会话抢锁）。
- **名字带数据目录哈希**：不同书库可以各开一个（开发用 `data/`、打包产物用 exe 同目录
  `data/` 也能同时跑）；同一个目录重复双击才拦。
- **其它平台**：`<数据目录>/.inkwell.lock` 上 `flock`。V1 只发 Windows，这层是给开发/
  CI 环境用的保底。
- **句柄必须活到进程退出**：`main.py` 把它挂成模块级变量。对象被 GC 掉会关闭句柄，
  第二个实例就能进来了——所以这里不实现 `__del__`。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

WINDOW_TITLE = "Inkwell"
MUTEX_PREFIX = "Local\\Inkwell-"
LOCK_FILENAME = ".inkwell.lock"
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9


def instance_name(data_dir: Path) -> str:
    """按数据目录生成互斥量名：同目录互斥、不同目录互不干扰。

    归一化（绝对路径 → 小写 → 正斜杠）保证 `D:\\小说辅助\\data`、
    `D:\\小说辅助\\data\\`、大小写差异都落到同一个名字上。
    """
    normalized = str(Path(data_dir).resolve()).replace("\\", "/").lower()
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{MUTEX_PREFIX}{digest}"


class SingleInstance:
    """一个数据目录一把锁：`acquire()` 返回 False 表示已有实例在跑。"""

    def __init__(self, data_dir: Path, name: str | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.name = name or instance_name(self.data_dir)
        self._handle: int | None = None
        self._lock_file = None

    def acquire(self) -> bool:
        if sys.platform == "win32":
            return self._acquire_win32()
        return self._acquire_posix()

    def release(self) -> None:
        """显式释放（测试与正常退出用）；进程退出时系统也会回收。"""
        if self._handle is not None:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None
        if self._lock_file is not None:
            try:
                self._lock_file.close()
            finally:
                self._lock_file = None

    # -- Windows -----------------------------------------------------------
    def _acquire_win32(self) -> bool:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            # 拿不到锁也别把应用拦死：打不开窗口比多开一个实例更糟（尽力而为）
            return True
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = int(handle)
        return True

    # -- POSIX（开发/CI 保底）----------------------------------------------
    def _acquire_posix(self) -> bool:
        import fcntl

        self.data_dir.mkdir(parents=True, exist_ok=True)
        handle = open(self.data_dir / LOCK_FILENAME, "w", encoding="utf-8")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._lock_file = handle
        return True


def activate_existing_window(title: str = WINDOW_TITLE) -> bool:
    """把已有实例的窗口切到前台；找不到就返回 False（尽力而为，不抛错）。"""
    if sys.platform != "win32":
        return False

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.EnumWindows.argtypes = [
        ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
        wintypes.LPARAM,
    ]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]

    matches: list[int] = []

    def callback(hwnd, _lparam) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if title in buffer.value:
            matches.append(int(hwnd))
            return False
        return True

    try:
        user32.EnumWindows(
            ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(callback),
            0,
        )
        if not matches:
            return False
        hwnd = matches[0]
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:  # pragma: no cover - 纯尽力而为，绝不影响第二实例退出
        return False
