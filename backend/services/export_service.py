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
from ..schemas import CODE_FILE_INVALID, CODE_PARAM_INVALID, ApiError
from . import chapter_service, media, project_service, sanitize, wordcount
from .wordcount import extract_text

FORMATS = ("txt", "md")
BATCH_SIZE = 50
EXPORT_SUBDIR = "exports"
MAX_NAME_LENGTH = 60
MAX_CHAPTER_TITLE_LENGTH = 200
# 单章导出可带客户端当前正文（失败态导出尚未保存的内容），与暂存同一档上限
MAX_EXPORT_HTML_BYTES = 8 * 1024 * 1024

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


# --------------------------------------------------------------------------
# 阶段三 3.5 / C-03：单章导出（#50）
# --------------------------------------------------------------------------


def _clean_chapter_title(title: str | None) -> str | None:
    """客户端标题只做长度与空白收敛；为空返回 ``None``（回退库内标题）。"""
    value = (title or "").strip()
    if not value:
        return None
    if len(value) > MAX_CHAPTER_TITLE_LENGTH:
        raise ApiError(
            CODE_PARAM_INVALID,
            f"章节标题长度不能超过 {MAX_CHAPTER_TITLE_LENGTH} 个字符",
        )
    return value


def _write_chapter_file(
    target: Path,
    *,
    title: str,
    text: str,
    fmt: str,
) -> None:
    """原子写入单章正文：先写 ``.tmp`` 再 ``os.replace``（BR-7，不留半截文件）。"""
    tmp = target.with_name(target.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            if fmt == "txt":
                underline = "=" * max(4, min(len(title), 40))
                handle.write(f"{title}\n{underline}\n\n")
                handle.write(f"{text}\n" if text else "（暂无正文）\n")
            else:
                handle.write(f"# {_md_heading(title)}\n\n")
                if text:
                    handle.write("\n\n".join(_paragraphs(text)))
                    handle.write("\n")
                else:
                    handle.write("（暂无正文）\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def export_chapter(
    database: Database,
    data_dir: Path,
    chapter_id: int,
    fmt: str,
    *,
    content_html: str | None = None,
    title: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """#50：导出单章 TXT/MD（C-03 失败态「导出本章」）。

    ``content_html`` 由前端传入**编辑器当前正文**：保存失败时库内正文是旧的，
    导出旧正文没有意义；传了就按与保存同一条链路（图片路径还原 → 消毒 →
    纯文本/字数）生成，不落库。未传时导出库内已保存正文，字数取章节缓存值。

    文件名 ``{书名}_{章节标题}_{YYYYMMDD_HHMMSS}.{fmt}``，沿用整本导出的
    安全文件名与去重规则；写盘沿用 BR-7（tmp + 原子替换）。
    """
    fmt = (fmt or "").lower()
    if fmt not in FORMATS:
        raise ApiError(CODE_PARAM_INVALID, "导出格式只能是 txt 或 md")

    payload = content_html
    if payload is not None and len(payload.encode("utf-8")) > MAX_EXPORT_HTML_BYTES:
        raise ApiError(CODE_FILE_INVALID, "导出内容超过 8MB 上限")

    now = now or datetime.now()
    with session_scope(database.engine) as session:
        chapter = chapter_service.require_chapter(session, chapter_id)
        project_id = session.execute(
            select(Volume.project_id).where(Volume.id == chapter.volume_id)
        ).scalar_one_or_none()
        if project_id is None:  # pragma: no cover - 外键保证
            raise ApiError(CODE_PARAM_INVALID, "章节所属卷不存在")
        project = project_service.require_project(session, int(project_id))
        project_title = project.title
        chapter_title = _clean_chapter_title(title) or chapter.title
        stored_html = chapter.content or ""
        stored_words = int(chapter.word_count)

    if payload is not None:
        normalized = media.normalize_content_images(payload)
        text, words = wordcount.count_html(sanitize.sanitize_html(normalized))
        source = "client"
    else:
        text = extract_text(stored_html)
        words = stored_words
        source = "stored"

    target = _unique_path(data_dir, f"{project_title}_{chapter_title}", fmt, now)
    _write_chapter_file(target, title=chapter_title, text=text, fmt=fmt)

    return {
        "format": fmt,
        "chapter_id": chapter_id,
        "chapter_title": chapter_title,
        "project_id": int(project_id),
        "project_title": project_title,
        "filename": target.name,
        "relpath": f"{EXPORT_SUBDIR}/{target.name}",
        "path": str(target.resolve()),
        "size": target.stat().st_size,
        "word_count": words,
        "empty": not text,
        "source": source,
    }
