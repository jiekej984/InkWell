"""本地暂存（任务 2.4 / BR-2 / 回归 15）。

保存失败或版本冲突时，前端把当前正文同时写两份：

    · localStorage：即时兜底（关闭/强杀也能保留最后一次写入）
    · ``drafts/chapter_{cid}.json``：由后端落盘，重启后仍可恢复

文件格式（UTF-8 JSON）：:

    {"chapter_id": 12, "title": "第一章", "content_html": "...",
     "client_saved_at": "...", "reason": "...", "saved_at": "2026-..."}

本模块只做文件层；不校验章节是否存在（由 API 层校验），读取时忽略损坏文件。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..schemas import CODE_FILE_INVALID, CODE_NOT_FOUND, ApiError
from ..storage import atomic_write_bytes
from ..timeutil import iso, utc_now

DRAFT_SUBDIR = "drafts"
MAX_DRAFT_BYTES = 8 * 1024 * 1024  # 与单章上限 5 万字留足余量


def draft_path(data_dir: Path, chapter_id: int) -> Path:
    """暂存文件路径（chapter_id 来自 int，天然防穿越）。"""
    return Path(data_dir) / DRAFT_SUBDIR / f"chapter_{int(chapter_id)}.json"


def save_draft(
    data_dir: Path,
    *,
    chapter_id: int,
    title: str | None,
    content_html: str,
    client_saved_at: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """写入（覆盖）某章节的暂存，返回摘要。"""
    content = content_html or ""
    if len(content.encode("utf-8")) > MAX_DRAFT_BYTES:
        raise ApiError(CODE_FILE_INVALID, "暂存内容超过 8MB 上限")

    now = utc_now()
    payload = {
        "chapter_id": int(chapter_id),
        "title": title,
        "content_html": content,
        "client_saved_at": client_saved_at,
        "reason": reason,
        "saved_at": iso(now),
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    atomic_write_bytes(draft_path(data_dir, chapter_id), raw)
    return {
        "chapter_id": int(chapter_id),
        "title": title,
        "saved_at": payload["saved_at"],
        "reason": reason,
        "size": len(raw),
    }


def _read(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "chapter_id" not in data:
        return None
    return data


def list_drafts(data_dir: Path) -> list[dict[str, Any]]:
    """列出全部暂存摘要（按 saved_at 倒序；损坏文件忽略）。"""
    directory = Path(data_dir) / DRAFT_SUBDIR
    if not directory.is_dir():
        return []
    items = []
    for path in directory.glob("chapter_*.json"):
        data = _read(path)
        if data is None:
            continue
        try:
            size = path.stat().st_size
        except OSError:  # pragma: no cover - 文件刚被删除
            continue
        items.append(
            {
                "chapter_id": int(data.get("chapter_id", 0)),
                "title": data.get("title"),
                "saved_at": data.get("saved_at"),
                "reason": data.get("reason"),
                "size": size,
            }
        )
    items.sort(key=lambda item: str(item.get("saved_at") or ""), reverse=True)
    return items


def get_draft(data_dir: Path, chapter_id: int) -> dict[str, Any] | None:
    """读取某章节的暂存全文；不存在返回 ``None``。"""
    return _read(draft_path(data_dir, chapter_id))


def delete_draft(data_dir: Path, chapter_id: int) -> bool:
    """删除暂存文件；返回是否确实删除。"""
    path = draft_path(data_dir, chapter_id)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:  # pragma: no cover - 权限异常
        raise ApiError(CODE_NOT_FOUND, f"暂存删除失败：{exc}") from exc
    return True
