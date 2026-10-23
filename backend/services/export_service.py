"""导出 TXT / Markdown（任务 2.10 / FR-6.4、6.5 / §6.2 #35）。

设计：
    · 输出到数据目录 ``exports/``，文件名 ``{安全书名}_{YYYYMMDD_HHMMSS}.{fmt}``
    · **流式写入**：先写 ``.tmp`` 再 ``os.replace``（BR-7），按 50 章一批读取正文，
      避免整本驻留内存（V-07 / NFR-P6）
    · 只导出正文（卷/章），不含设定文档；空项目也要输出书名、简介与说明
    · 正文由 ``wordcount.extract_text`` 去标签，与字数统计同一套纯文本口径

导出不写数据库；``word_count`` 为章节缓存字数之和（AC-6 口径）。
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..database import Database
from ..models import Chapter, Volume, active, session_scope
from ..schemas import CODE_PARAM_INVALID, ApiError
from . import project_service
from .wordcount import extract_text

FORMATS = ("txt", "md")
BATCH_SIZE = 50
EXPORT_SUBDIR = "exports"
MAX_NAME_LENGTH = 60

_ILLEGAL_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


def sanitize_filename(title: str) -> str:
    """把书名转成安全文件名（保留中文，替换非法字符）。"""
    cleaned = _ILLEGAL_FILENAME.sub("_", title or "").strip().strip(".")
    cleaned = _WHITESPACE.sub("_", cleaned)
    cleaned = cleaned[:MAX_NAME_LENGTH].strip("_")
    return cleaned or "untitled"


def _unique_path(data_dir: Path, title: str, fmt: str, now: datetime) -> Path:
    directory = Path(data_dir) / EXPORT_SUBDIR
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{sanitize_filename(title)}_{now.strftime('%Y%m%d_%H%M%S')}"
    candidate = directory / f"{stem}.{fmt}"
    index = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{index}.{fmt}"
        index += 1
    return candidate


def _chapter_plan(
    session: Any, project_id: int
) -> tuple[list[tuple[str, bool, list[tuple[int, str]]]], int, int]:
    """返回 ``([(卷名, 是否默认卷, [(章id, 章名)])], 章数, 字数)``。"""
    volumes = (
        session.execute(
            active(Volume)
            .where(Volume.project_id == project_id)
            .order_by(Volume.order_index, Volume.id)
        )
        .scalars()
        .all()
    )
    plan: list[tuple[str, bool, list[tuple[int, str]]]] = []
    total_chapters = 0
    total_words = 0
    for volume in volumes:
        chapters = session.execute(
            select(Chapter.id, Chapter.title, Chapter.word_count)
            .where(Chapter.volume_id == volume.id, Chapter.is_deleted == 0)
            .order_by(Chapter.order_index, Chapter.id)
        ).all()
        entries = [(int(row[0]), row[1]) for row in chapters]
        total_chapters += len(entries)
        total_words += sum(int(row[2]) for row in chapters)
        plan.append((volume.title, bool(volume.is_default), entries))
    return plan, total_chapters, total_words


def _load_contents(database: Database, chapter_ids: list[int]) -> dict[int, str]:
    """按 id 批量读取正文（调用方按 BATCH_SIZE 分批）。"""
    if not chapter_ids:
        return {}
    with session_scope(database.engine) as session:
        rows = session.execute(
            select(Chapter.id, Chapter.content).where(Chapter.id.in_(chapter_ids))
        ).all()
    return {int(row[0]): row[1] or "" for row in rows}


def _md_heading(text: str) -> str:
    return _WHITESPACE.sub(" ", (text or "").strip()).replace("#", "＃")


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n") if part.strip()]


def export_project(
    database: Database,
    data_dir: Path,
    project_id: int,
    fmt: str,
    *,
    now: datetime | None = None,
    report: Any = None,
) -> dict[str, Any]:
    """#35：导出项目正文（长任务函数）。"""
    fmt = (fmt or "").lower()
    if fmt not in FORMATS:
        raise ApiError(CODE_PARAM_INVALID, "导出格式只能是 txt 或 md")

    now = now or datetime.now()
    with session_scope(database.engine) as session:
        project = project_service.require_project(session, project_id)
        title = project.title
        description = project.description
        plan, chapter_count, total_words = _chapter_plan(session, project_id)

    target = _unique_path(data_dir, title, fmt, now)
    tmp = target.with_name(target.name + ".tmp")
    written = 0
    has_other_volume = any(not is_default for _, is_default, _ in plan)

    if report:
        report(0, f"准备导出 {chapter_count} 章")

    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            if fmt == "txt":
                handle.write(f"{title}\n{'=' * max(4, min(len(title), 40))}\n\n")
                if description:
                    handle.write(f"{description}\n\n")
                if chapter_count == 0:
                    handle.write("（暂无正文）\n")
            else:
                handle.write(f"# {_md_heading(title)}\n\n")
                if description:
                    handle.write(f"> {description.strip()}\n\n")
                if chapter_count == 0:
                    handle.write("## 目录\n\n（暂无章节）\n")

            for volume_title, _is_default, entries in plan:
                if not entries:
                    continue
                if has_other_volume:
                    if fmt == "txt":
                        handle.write(f"\n{volume_title}\n{'-' * len(volume_title)}\n\n")
                    else:
                        handle.write(f"## {_md_heading(volume_title)}\n\n")

                for start in range(0, len(entries), BATCH_SIZE):
                    batch = entries[start : start + BATCH_SIZE]
                    contents = _load_contents(database, [cid for cid, _ in batch])
                    for chapter_id, chapter_title in batch:
                        if fmt == "txt":
                            handle.write(f"{chapter_title}\n\n")
                        else:
                            handle.write(f"### {_md_heading(chapter_title)}\n\n")
                        text = extract_text(contents.get(chapter_id, ""))
                        if text:
                            if fmt == "txt":
                                handle.write(f"{text}\n\n")
                            else:
                                handle.write("\n\n".join(_paragraphs(text)))
                                handle.write("\n\n")
                        written += 1
                        if report and chapter_count:
                            report(
                                int(written * 100 / chapter_count),
                                f"已导出 {written}/{chapter_count} 章",
                            )

            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()

    if report:
        report(100, "导出完成")

    return {
        "format": fmt,
        "filename": target.name,
        "relpath": f"{EXPORT_SUBDIR}/{target.name}",
        "size": target.stat().st_size,
        "chapters": chapter_count,
        "word_count": total_words,
        "exported_chapters": written,
        "empty": chapter_count == 0,
    }
