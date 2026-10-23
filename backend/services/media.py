"""正文图片：校验、保存、内容中图片路径的规范化与签名（BR-5 / ADR-009）。

存储约定：
    · 文件落 ``media/{chapter_id}/{uuid}.{ext}``，库内 HTML 只存相对路径
      ``<img src="media/12/abc.png">``
    · 返回给前端时由 :func:`sign_content_images` 临时替换为签名 URL
      ``/files/media/12/abc.png?sig=<exp>.<mac>``（30 分钟，D-11）
    · 编辑器回传的签名 URL 在落库前由 :func:`normalize_content_images`
      还原为相对路径，避免把过期签名写进正文
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

from ..schemas import CODE_FILE_INVALID, ApiError
from ..storage import atomic_write_bytes, resolve_path, sign

ALLOWED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
_PIL_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}

_IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]*)(")', re.IGNORECASE | re.DOTALL)
_MEDIA_SRC_RE = re.compile(
    r'(<img\b[^>]*?\bsrc=")(media/[^"]*)(")', re.IGNORECASE | re.DOTALL
)


def validate_image(payload: bytes, filename: str | None) -> str:
    """校验图片并返回**规范扩展名**（不含点）；非法抛 4002。

    顺序与封面上传一致：先看扩展名白名单，再用 Pillow 校验真实格式，
    防止「.png 扩展名 + 非图片内容」的伪装。
    """
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise ApiError(
            CODE_FILE_INVALID,
            f"图片格式必须是 {'/'.join(ALLOWED_IMAGE_EXTENSIONS)} 之一",
        )
    if not payload:
        raise ApiError(CODE_FILE_INVALID, "图片文件为空")
    if len(payload) > MAX_IMAGE_BYTES:
        raise ApiError(CODE_FILE_INVALID, "图片文件不能超过 10MB")

    try:
        from PIL import Image

        with Image.open(BytesIO(payload)) as image:
            image_format = image.format
    except Exception as exc:
        raise ApiError(CODE_FILE_INVALID, "图片文件无法解析") from exc

    if image_format not in _PIL_FORMATS:
        raise ApiError(CODE_FILE_INVALID, "图片文件内容与扩展名不符")
    return _PIL_FORMATS[image_format]


def save_image(
    data_dir: Path, folder: str, payload: bytes, filename: str | None
) -> str:
    """校验并落盘到 ``media/{folder}/``，返回库内相对路径。"""
    extension = validate_image(payload, filename)
    relpath = f"media/{folder}/{uuid4().hex}.{extension}"
    target = resolve_path(data_dir, relpath)
    if target is None:  # pragma: no cover - relpath 由本函数生成
        raise ApiError(CODE_FILE_INVALID, "图片路径非法")
    atomic_write_bytes(target, payload)
    return relpath


def save_chapter_image(
    data_dir: Path,
    chapter_id: int,
    payload: bytes,
    filename: str | None,
) -> str:
    """正文图片：``media/{cid}/{uuid}.{ext}``。"""
    return save_image(data_dir, str(int(chapter_id)), payload, filename)


def save_document_image(
    data_dir: Path,
    document_id: int,
    payload: bytes,
    filename: str | None,
) -> str:
    """设定文档图片：``media/documents/{did}/``（避免与章节 id 冲突）。"""
    return save_image(data_dir, f"documents/{int(document_id)}", payload, filename)


def _extract_media_path(src: str) -> str | None:
    """从签名 URL / 绝对 URL / 相对路径中提取 ``media/...``；非法返回 None。"""
    candidate = src.strip()
    if candidate.startswith("/files/"):
        candidate = candidate[len("/files/") :]
    elif "://" in candidate:
        parsed = urlparse(candidate)
        if not parsed.path.startswith("/files/"):
            return None
        candidate = parsed.path[len("/files/") :]
    candidate = unquote(candidate.split("?", 1)[0])
    if not candidate.startswith("media/"):
        return None
    return candidate


def normalize_content_images(html: str | None) -> str:
    """把签名 URL 还原为相对路径（落库前调用）。"""
    if not html:
        return ""

    def repl(match: re.Match[str]) -> str:
        path = _extract_media_path(match.group(2))
        if path is None:
            return match.group(0)
        return f"{match.group(1)}{path}{match.group(3)}"

    return _IMG_SRC_RE.sub(repl, html)


def sign_content_images(html: str | None, *, now: float | None = None) -> str:
    """把相对路径临时替换为签名 URL（返回给前端时调用）。"""
    if not html:
        return ""

    def repl(match: re.Match[str]) -> str:
        relpath = match.group(2)
        signature = sign(relpath, now=now)
        if signature is None:  # pragma: no cover - 路径来自库内
            return match.group(0)
        return f"{match.group(1)}/files/{relpath}?sig={signature}{match.group(3)}"

    return _MEDIA_SRC_RE.sub(repl, html)
