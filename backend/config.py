"""应用配置与数据目录解析。

对应报告 §4.4「数据存储与路径策略」，优先级从高到低：

    INKWELL_DATA_DIR  >  portable 模式  >  打包模式  >  开发模式
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

DATA_SUBDIRS = ("covers", "media", "backups", "drafts", "logs", "exports")

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


def resolve_data_dir() -> Path:
    """按 §4.4 解析数据目录。"""
    override = os.environ.get("INKWELL_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "portable.txt").exists():
            return exe_dir / "portable_data"
        return Path.home() / "Documents" / APP_NAME
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
