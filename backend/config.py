"""应用配置与数据目录解析。

对应报告 §4.4「数据存储与路径策略」，优先级从高到低：

    INKWELL_DATA_DIR  >  portable 模式  >  打包模式（程序同目录）  >  开发模式

打包模式下一律优先写「程序所在目录」，装到哪个盘数据就落在哪个盘；
只有该目录不可写（如安装在 Program Files）时才回退到用户「文档」目录。
"""

from __future__ import annotations

import os
import secrets
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Inkwell"
APP_VERSION = "0.1.0"  # D-12：SemVer（【暂定】待 Q-03 确认发布渠道）
SCHEMA_VERSION = (
    2  # 必须与 backend.migrate 中最后一个迁移的版本号一致（0002 起含 document_fts）
)

HOST = "127.0.0.1"
TOKEN_HEADER = "X-Inkwell-Token"
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})

WINDOW_TITLE = "Inkwell"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800
WINDOW_MIN_SIZE = (1024, 640)

DATA_SUBDIRS = ("covers", "media", "backups", "drafts", "logs", "exports", "webview")

# 打包模式下，默认数据目录取「程序所在目录」下的这个子目录（与程序同盘）
DEFAULT_DATA_DIRNAME = "data"

# 探测目录可写时使用的临时文件名，用完即删
_PROBE_NAME = ".inkwell-write-probe"

# R-17：这些变量会让「遵循环境代理」的 HTTP 客户端把本地请求行改写为 absolute-form
_PROXY_ENV_VARS = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
)


def is_frozen() -> bool:
    """True 表示运行在 PyInstaller 打包产物中（§4.4 判定方式）。"""
    return bool(getattr(sys, "frozen", False))


def source_root() -> Path:
    """源码根目录（main.py 所在目录）。"""
    return Path(__file__).resolve().parent.parent


def is_writable_dir(path: Path) -> bool:
    """实际写一个探针文件来判断目录可写。

    ``os.access`` 在 Windows 上对 ``Program Files`` 这类受保护目录会因 UAC
    虚拟化误报为可写，因此这里真正创建再删除探针文件。
    """
    probe = Path(path) / _PROBE_NAME
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
    except OSError:
        return False
    try:
        probe.unlink()
    except OSError:
        pass
    return True


def packaged_data_dir() -> Path:
    """打包模式的默认数据目录：**优先程序所在目录**，避免占用系统盘。

    程序装在 D 盘等普通可写位置时，数据与程序同盘，不会写 C 盘；
    只有装在 ``Program Files`` 这类不可写位置时，才回退到用户「文档」目录
    （通常位于系统盘）。需要强制指定时用 ``INKWELL_DATA_DIR`` 或
    ``portable.txt`` 标记文件。
    """
    exe_dir = Path(sys.executable).resolve().parent
    candidate = exe_dir / DEFAULT_DATA_DIRNAME
    if is_writable_dir(candidate):
        return candidate
    return Path.home() / "Documents" / APP_NAME


def resolve_data_dir() -> Path:
    """按下方优先级解析数据目录（§4.4 修订版，见 DECISIONS.md S3-04）。"""
    override = os.environ.get("INKWELL_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "portable.txt").exists():
            return exe_dir / "portable_data"
        return packaged_data_dir()
    return source_root() / "data"


def frontend_dir() -> Path:
    return source_root() / "frontend"


def generate_token() -> str:
    """每次启动生成一次性随机 token（§6.1 / NFR-S2）。"""
    return secrets.token_urlsafe(32)


def clear_proxy_env() -> list[str]:
    """清除本进程的代理环境变量，返回被清除的变量名。

    R-17 缓解措施 ②：必须在创建 WebView 之前调用，避免子进程继承代理设置。
    """
    removed: list[str] = []
    for name in _PROXY_ENV_VARS:
        if os.environ.pop(name, None) is not None:
            removed.append(name)
    return removed


def pick_free_port(host: str = HOST) -> int:
    """向内核申请一个空闲端口并返回端口号（随机端口，R-3）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


@dataclass(frozen=True)
class AppConfig:
    """进程级不可变配置。"""

    version: str
    schema_version: int
    data_dir: Path
    db_path: Path
    frontend_dir: Path
    token: str
    host: str
    port: int
    dev: bool

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def subdir(self, name: str) -> Path:
        if name not in DATA_SUBDIRS:
            raise ValueError(f"未知的数据子目录: {name}")
        return self.data_dir / name

    @property
    def webview_storage_dir(self) -> Path:
        """WebView2 用户数据（缓存 / localStorage / IndexedDB）目录。

        不显式指定时，pywebview 会把 WebView2 的 ``UserDataFolder`` 放在
        ``%APPDATA%\\pywebview``（即系统盘），随使用不断增长；这里固定放进
        数据目录，保证「数据与程序同盘」。
        """
        return self.subdir("webview")


def load_config() -> AppConfig:
    """构建配置：解析数据目录、生成 token、挑选随机端口。"""
    data_dir = resolve_data_dir()
    return AppConfig(
        version=APP_VERSION,
        schema_version=SCHEMA_VERSION,
        data_dir=data_dir,
        db_path=data_dir / "inkwell.db",
        frontend_dir=frontend_dir(),
        token=generate_token(),
        host=HOST,
        port=pick_free_port(),
        dev=not is_frozen(),
    )


def ensure_data_dirs(config: AppConfig) -> None:
    """创建数据目录及子目录；不可用则抛出明确异常而非静默（NFR-R10）。"""
    try:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        for name in DATA_SUBDIRS:
            config.subdir(name).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"数据目录不可用: {config.data_dir} ({exc})") from exc
    if not os.access(config.data_dir, os.W_OK):
        raise RuntimeError(f"数据目录不可写: {config.data_dir}")
