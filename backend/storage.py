"""静态资源签名签发 / 校验与路径白名单。

对应 ADR-009、D-10、D-11、NFR-S7（路径穿越防护）、NFR-S8（静态资源鉴权）。

签名格式：``<expiry_unix_seconds>.<base64url(HMAC-SHA256("<规范化相对路径>:<expiry>"))>``
签名绑定路径与过期时间，任何一项不匹配即视为无效。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from urllib.parse import unquote

DEFAULT_TTL_SECONDS = 30 * 60  # D-11：签名有效期 30 分钟（假设）
ALLOWED_ROOTS = ("covers", "media")  # 仅这两个子目录可被外部访问

_SIG_SEP = "."
_SECRET: bytes | None = None


def _secret() -> bytes:
    """进程内一次性签名密钥；重启后旧签名失效（前端需重新签发）。"""
    global _SECRET
    if _SECRET is None:
        _SECRET = secrets.token_bytes(32)
    return _SECRET


def reset_secret() -> None:
    """重置签名密钥。仅供测试使用。"""
    global _SECRET
    _SECRET = None


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def normalize_relpath(relpath: str) -> str | None:
    """把请求中的相对路径规范化为 posix 风格；非法返回 ``None``。

    拒绝：非字符串、空串、绝对路径、盘符、``..`` 段、控制字符，
    以及首段不在白名单根目录（``covers`` / ``media``）内的路径。
    """
    if not isinstance(relpath, str) or not relpath:
        return None

    candidate = relpath.replace("\\", "/")
    try:
        candidate = unquote(candidate)
    except Exception:
        return None

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in candidate):
        return None
    if candidate.startswith("/"):
        return None

    parts: list[str] = []
    for segment in candidate.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            return None
        if len(segment) > 1 and segment[1] == ":" and segment[0].isalpha():
            return None  # 盘符（C: 等）
        parts.append(segment)

    if not parts or parts[0] not in ALLOWED_ROOTS:
        return None
    return "/".join(parts)


def resolve_path(data_dir: Path, relpath: str) -> Path | None:
    """解析为数据目录下的绝对路径；越界或非法返回 ``None``（→ 4003）。"""
    normalized = normalize_relpath(relpath)
    if normalized is None:
        return None

    base = Path(data_dir).resolve()
    target = (base / normalized).resolve()
    if target == base or not target.is_relative_to(base):
        return None
    return target


def _mac(normalized: str, expires_at: int) -> bytes:
    message = f"{normalized}:{expires_at}".encode()
    return hmac.new(_secret(), message, hashlib.sha256).digest()


def sign(
    relpath: str, *, ttl: int = DEFAULT_TTL_SECONDS, now: float | None = None
) -> str | None:
    """为相对路径签发签名；路径非法返回 ``None``。"""
    normalized = normalize_relpath(relpath)
    if normalized is None or ttl <= 0:
        return None

    issued = time.time() if now is None else now
    expires_at = int(issued) + int(ttl)
    return f"{expires_at}{_SIG_SEP}{_b64encode(_mac(normalized, expires_at))}"


def verify(relpath: str, signature: str | None, *, now: float | None = None) -> bool:
    """校验签名是否有效且未过期；路径与签名绑定。"""
    normalized = normalize_relpath(relpath)
    if normalized is None or not signature:
        return False

    try:
        raw_expiry, raw_mac = signature.split(_SIG_SEP, 1)
        expires_at = int(raw_expiry)
        provided = _b64decode(raw_mac)
    except Exception:
        return False

    current = time.time() if now is None else now
    if current >= expires_at:
        return False

    return hmac.compare_digest(provided, _mac(normalized, expires_at))


def ensure_parent(path: Path) -> None:
    """确保父目录存在（写入前调用，避免 4001）。"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def atomic_write_bytes(dest: Path, payload: bytes) -> Path:
    """原子写入：先写 ``.tmp`` 再 ``os.replace``（BR-7）。

    保证任一时刻目标文件要么是旧版本、要么是完整的新版本，不会留下半截文件。
    """
    dest = Path(dest)
    ensure_parent(dest)
    tmp = dest.with_name(dest.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, dest)
    return dest
