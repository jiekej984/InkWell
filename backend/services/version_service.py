"""版本快照、回滚与清理（任务 2.6 / FR-5、BR-9、D-04）。

版本号语义（S2-08 / S2-10）：
    · ``chapter.version_no`` 是**修订号**：每次正文保存 +1；
      手动 / 里程碑快照再 +1；回滚也 +1
    · 快照行 ``chapter_version.version_no`` = 创建时的修订号，唯一约束
      ``(chapter_id, version_no)`` 保证同号只有一条

分级策略（D-04）：
    · auto：距最近快照 ≥5 分钟 **且** 字数变化 ≥200 时自动创建
    · manual / milestone：永久保留
    · restore：回滚前把当前正文存为永久快照
    · auto 保留最近 30 条；**每日首条**额外保留 30 天

回滚语义（S2-10）：
    1. 先把**回滚前**正文存为 ``restore`` 永久快照（新修订号 #N）
    2. 用目标版本内容覆盖正文（重新消毒 + 重算字数）
    3. ``chapter.version_no`` 保持 #N（不再二次递增）
    UI 文案：「由 #7 回滚，已生成 #14（回滚前快照）」。

快照失败是非致命错误：自动快照异常只记日志，不影响正文保存主路径。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from ..models import Chapter, ChapterVersion, Volume
from ..schemas import CODE_NOT_FOUND, CODE_PARAM_INVALID, ApiError
from ..timeutil import iso, utc_now
from . import media, project_service, sanitize, wordcount

log = logging.getLogger(__name__)

AUTO_MIN_INTERVAL = timedelta(minutes=5)
AUTO_MIN_WORDS_CHANGED = 200
AUTO_KEEP = 30
AUTO_DAILY_KEEP_DAYS = 30
MANUAL_CHANGE_TYPES = ("manual", "milestone")
CHANGE_TYPE_LABELS = {
    "auto": "自动",
    "manual": "手动",
    "milestone": "里程碑",
    "restore": "回滚",
}
_DAILY_SNAPSHOT_KEY = "last_snapshot_daily_date"


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------


def require_version(session: Session, version_id: int) -> ChapterVersion:
    """按 id 取版本快照；不存在 → 2001。"""
    row = session.get(ChapterVersion, version_id)
    if row is None:
        raise ApiError(CODE_NOT_FOUND, "版本不存在")
    return row


def list_versions(session: Session, chapter_id: int) -> Sequence[ChapterVersion]:
    """版本列表：新 → 旧（§6.2 #23）。"""
    return (
        session.execute(
            select(ChapterVersion)
            .where(ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.version_no.desc(), ChapterVersion.id.desc())
        )
        .scalars()
        .all()
    )


def latest_snapshot(session: Session, chapter_id: int) -> ChapterVersion | None:
    return (
        session.execute(
            select(ChapterVersion)
            .where(ChapterVersion.chapter_id == chapter_id)
            .order_by(ChapterVersion.version_no.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def serialize_version(row: ChapterVersion) -> dict[str, Any]:
    return {
        "id": row.id,
        "chapter_id": row.chapter_id,
        "version_no": row.version_no,
        "title": row.title,
        "word_count": row.word_count,
        "diff_word_count": row.diff_word_count,
        "change_type": row.change_type,
        "change_type_label": CHANGE_TYPE_LABELS.get(row.change_type, row.change_type),
        "created_at": iso(row.created_at),
    }


def serialize_version_detail(row: ChapterVersion) -> dict[str, Any]:
    return {
        **serialize_version(row),
        "content": media.sign_content_images(row.content or ""),
    }


# --------------------------------------------------------------------------
# 内部
# --------------------------------------------------------------------------


def _project_id_of_chapter(session: Session, chapter: Chapter) -> int:
    project_id = session.execute(
        select(Volume.project_id).where(Volume.id == chapter.volume_id)
    ).scalar_one_or_none()
    if project_id is None:  # pragma: no cover - 外键保证
        raise ApiError(CODE_NOT_FOUND, "章节所属卷不存在")
    return int(project_id)


def _insert_snapshot(
    session: Session,
    chapter: Chapter,
    *,
    version_no: int,
    change_type: str,
    content: str,
    word_count: int,
    title: str | None,
) -> ChapterVersion:
    previous = latest_snapshot(session, chapter.id)
    previous_words = int(previous.word_count) if previous is not None else 0
    row = ChapterVersion(
        chapter_id=chapter.id,
        version_no=int(version_no),
        title=title,
        content=content or "",
        word_count=int(word_count),
        diff_word_count=int(word_count) - previous_words,
        change_type=change_type,
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


def _set_meta(session: Session, key: str, value: str) -> None:
    session.execute(
        text(
            "INSERT INTO app_meta(key, value) VALUES (:key, :value) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        ),
        {"key": key, "value": value},
    )


def _local_date(value: datetime) -> Any:
    """把库内 naive UTC 时间换算为本地日期（BR-8：日期类策略用本地日期）。"""
    return value.replace(tzinfo=UTC).astimezone().date()


def _touch_project(session: Session, chapter: Chapter) -> None:
    project = project_service.require_project(
        session, _project_id_of_chapter(session, chapter)
    )
    project.updated_at = utc_now()


# --------------------------------------------------------------------------
# 创建
# --------------------------------------------------------------------------


def create_snapshot(
    session: Session,
    chapter: Chapter,
    change_type: str = "manual",
) -> ChapterVersion:
    """手动 / 里程碑快照：**递增修订号**后保存当前正文（永久保留）。"""
    if change_type not in MANUAL_CHANGE_TYPES:
        raise ApiError(CODE_PARAM_INVALID, "手动快照类型只能是 manual 或 milestone")

    version_no = int(chapter.version_no) + 1
    row = _insert_snapshot(
        session,
        chapter,
        version_no=version_no,
        change_type=change_type,
        content=chapter.content or "",
        word_count=int(chapter.word_count),
        title=chapter.title,
    )
    chapter.version_no = version_no
    chapter.updated_at = utc_now()
    _touch_project(session, chapter)
    return row


def maybe_create_auto_snapshot(
    session: Session,
    chapter: Chapter,
) -> ChapterVersion | None:
    """正文保存后按 D-04 判断是否创建 auto 快照（失败不影响保存）。"""
    try:
        latest = latest_snapshot(session, chapter.id)
        if latest is not None:
            now = utc_now()
            if now - latest.created_at < AUTO_MIN_INTERVAL:
                return None
            if (
                abs(int(chapter.word_count) - int(latest.word_count))
                < AUTO_MIN_WORDS_CHANGED
            ):
                return None
        elif int(chapter.word_count) < AUTO_MIN_WORDS_CHANGED:
            return None

        version_no = int(chapter.version_no)
        existing = session.execute(
            select(ChapterVersion).where(
                ChapterVersion.chapter_id == chapter.id,
                ChapterVersion.version_no == version_no,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return None

        row = _insert_snapshot(
            session,
            chapter,
            version_no=version_no,
            change_type="auto",
            content=chapter.content or "",
            word_count=int(chapter.word_count),
            title=chapter.title,
        )
        _set_meta(session, _DAILY_SNAPSHOT_KEY, _local_date(row.created_at).isoformat())
        prune_auto_snapshots(session, chapter.id)
        return row
    except Exception:
        log.warning("自动快照创建失败，正文保存不受影响", exc_info=True)
        return None


# --------------------------------------------------------------------------
# 清理
# --------------------------------------------------------------------------


def prune_auto_snapshots(session: Session, chapter_id: int) -> int:
    """D-04：auto 保留最近 30 条 + 每日首条额外 30 天；返回删除条数。"""
    rows = (
        session.execute(
            select(ChapterVersion)
            .where(
                ChapterVersion.chapter_id == chapter_id,
                ChapterVersion.change_type == "auto",
            )
            .order_by(ChapterVersion.created_at.desc(), ChapterVersion.id.desc())
        )
        .scalars()
        .all()
    )
    if len(rows) <= AUTO_KEEP:
        return 0

    keep_ids = {row.id for row in rows[:AUTO_KEEP]}

    # 每日首条（同日最早的一条 auto）额外保留 30 天
    daily_first: dict[Any, ChapterVersion] = {}
    for row in reversed(rows):  # 旧 → 新，先出现的是当天最早
        daily_first.setdefault(_local_date(row.created_at), row)
    cutoff = utc_now() - timedelta(days=AUTO_DAILY_KEEP_DAYS)
    keep_ids.update(row.id for row in daily_first.values() if row.created_at >= cutoff)

    remove_ids = [row.id for row in rows if row.id not in keep_ids]
    if remove_ids:
        session.execute(delete(ChapterVersion).where(ChapterVersion.id.in_(remove_ids)))
    return len(remove_ids)


# --------------------------------------------------------------------------
# 回滚 / 删除
# --------------------------------------------------------------------------


def restore_version(
    session: Session,
    chapter: Chapter,
    version_id: int,
) -> dict[str, Any]:
    """回滚到指定版本（S2-10）：先存回滚前快照，再覆盖正文、递增修订号。"""
    target = require_version(session, version_id)
    if target.chapter_id != chapter.id:
        raise ApiError(CODE_NOT_FOUND, "版本不存在")

    old_words = int(chapter.word_count)
    new_no = int(chapter.version_no) + 1

    # 1) 回滚前正文存为 restore 永久快照
    _insert_snapshot(
        session,
        chapter,
        version_no=new_no,
        change_type="restore",
        content=chapter.content or "",
        word_count=old_words,
        title=chapter.title,
    )

    # 2) 覆盖正文（重新消毒 + 图片路径还原 + 重算字数）
    normalized = media.normalize_content_images(target.content or "")
    clean = sanitize.sanitize_html(normalized)
    plain, words = wordcount.count_html(clean)
    chapter.content = clean
    chapter.content_text = plain
    chapter.word_count = words

    # 3) 修订号 = 新号（不再二次递增）
    chapter.version_no = new_no
    chapter.updated_at = utc_now()

    project = project_service.require_project(
        session, _project_id_of_chapter(session, chapter)
    )
    project.total_word_count = max(0, int(project.total_word_count) + words - old_words)
    project.updated_at = chapter.updated_at

    return {
        "chapter_id": chapter.id,
        "restored_from": target.version_no,
        "version_no": new_no,
        "snapshot_version_no": new_no,
        "word_count": words,
        "project_word_count": project.total_word_count,
        "content": media.sign_content_images(clean),
        "saved_at": iso(chapter.updated_at),
    }


def delete_version(session: Session, version_id: int) -> dict[str, Any]:
    """§6.2 #27：删快照（物理删除，非回收站语义 —— 勘误 E-03）。"""
    row = require_version(session, version_id)
    chapter_id = row.chapter_id
    version_no = row.version_no
    session.delete(row)
    return {"id": version_id, "chapter_id": chapter_id, "version_no": version_no}
