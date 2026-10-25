"""卷章业务逻辑（任务 2.2 / FR-2）。

对应 FR-2.1~2.2、BR-3（步长排序与局部重整）、BR-6（默认卷）、BR-4（软删除）、
§6.2 #10~#17 / #22。

设计约定（与 2.1 保持一致）：
    · 纯业务函数，接收 ``Session``、不自己开事务，便于单测（NFR-M1）
    · 时间统一走 :func:`backend.timeutil.utc_now`（BR-8：持久化用 UTC）
    · 错误一律抛 :class:`backend.schemas.ApiError`，由统一异常处理器转成响应

默认卷（BR-6）：
    · 每个项目恰好一条 ``is_default=1`` 的卷，``order_index`` 固定 0
    · 不可删除、不可重命名，不参与卷排序
    · ``GET /projects/{pid}/volumes`` 把默认卷放在 ``default_volume`` 字段，
      不混入 ``volumes`` —— 对应「大纲树默认隐藏，项目无其他卷时才显示」；
      前端在 ``volumes`` 为空时显示 ``default_volume``

排序（BR-3）：
    · 步长 1000；头部 = 后一项 − 1000，尾部 = 前一项 + 1000，中间取两者均值
    · 相邻差 ≤1（或头部落到 ≤0）时**整体重整**为 1000、2000、3000 …
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Chapter, Volume, active
from ..schemas import (
    CODE_DELETED,
    CODE_NOT_FOUND,
    CODE_PARAM_INVALID,
    CODE_VERSION_CONFLICT,
    ApiError,
)
from ..timeutil import iso, utc_now
from . import media, project_service, sanitize, version_service, wordcount

ORDER_STEP = 1000
DEFAULT_VOLUME_TITLE = project_service.DEFAULT_VOLUME_TITLE
MAX_TITLE_LENGTH = 200
MAX_SUMMARY_LENGTH = 5000
CHAPTER_STATUSES = ("draft", "first", "final")
DELETE_MODES = ("move", "cascade")


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------


def _clean_title(title: str | None, label: str = "标题") -> str:
    value = (title or "").strip()
    if not value:
        raise ApiError(CODE_PARAM_INVALID, f"{label}不能为空")
    if len(value) > MAX_TITLE_LENGTH:
        raise ApiError(
            CODE_PARAM_INVALID, f"{label}长度不能超过 {MAX_TITLE_LENGTH} 个字符"
        )
    # FR-2.2：章节标题允许重复，这里**故意不做**唯一校验
    return value


def _clean_summary(summary: str | None) -> str | None:
    if summary is None:
        return None
    value = summary.strip()
    if len(value) > MAX_SUMMARY_LENGTH:
        raise ApiError(
            CODE_PARAM_INVALID, f"梗概长度不能超过 {MAX_SUMMARY_LENGTH} 个字符"
        )
    return value or None


def _clean_chapter_status(status: str | None) -> str:
    value = (status or "draft").strip()
    if value not in CHAPTER_STATUSES:
        raise ApiError(
            CODE_PARAM_INVALID,
            f"章节状态必须是 {'/'.join(CHAPTER_STATUSES)} 之一",
        )
    return value


def _clean_target(value: int | None) -> int:
    if value is None:
        return 0
    if value < 0:
        raise ApiError(CODE_PARAM_INVALID, "目标字数不能为负数")
    return int(value)


def _touch_project(session: Session, project_id: int) -> None:
    """卷章变动后刷新项目的 ``updated_at``（列表按更新时间倒序）。"""
    project = project_service.require_project(session, project_id)
    project.updated_at = utc_now()


# --------------------------------------------------------------------------
# 查询与不变量
# --------------------------------------------------------------------------


def require_volume(session: Session, volume_id: int) -> Volume:
    """按 id 取活跃卷；不存在 → 2001，已删除 → 2002。"""
    volume = session.execute(
        select(Volume).where(Volume.id == volume_id)
    ).scalar_one_or_none()
    if volume is None:
        raise ApiError(CODE_NOT_FOUND, "卷不存在")
    if volume.is_deleted:
        raise ApiError(CODE_DELETED, "卷已删除，可在回收站恢复")
    return volume


def require_chapter(session: Session, chapter_id: int) -> Chapter:
    """按 id 取活跃章节；不存在 → 2001，已删除 → 2002。"""
    chapter = session.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    ).scalar_one_or_none()
    if chapter is None:
        raise ApiError(CODE_NOT_FOUND, "章节不存在")
    if chapter.is_deleted:
        raise ApiError(CODE_DELETED, "章节已删除，可在回收站恢复")
    return chapter


def get_default_volume(session: Session, project_id: int) -> Volume:
    """取项目默认卷；缺失属于数据异常，返回 2001 并提示。"""
    volume = session.execute(
        select(Volume).where(
            Volume.project_id == project_id,
            Volume.is_default == 1,
            Volume.is_deleted == 0,
        )
    ).scalar_one_or_none()
    if volume is None:
        raise ApiError(CODE_NOT_FOUND, "项目缺少默认卷，请从备份恢复")
    return volume


def ensure_default_volume(session: Session, project_id: int) -> Volume:
    """确保默认卷存在（恢复项目 / 导入旧稿时由调用方使用，§5.1 不变量）。"""
    volume = session.execute(
        select(Volume).where(
            Volume.project_id == project_id,
            Volume.is_default == 1,
            Volume.is_deleted == 0,
        )
    ).scalar_one_or_none()
    if volume is not None:
        return volume
    now = utc_now()
    volume = Volume(
        project_id=project_id,
        title=DEFAULT_VOLUME_TITLE,
        order_index=0,
        is_default=1,
        created_at=now,
        updated_at=now,
    )
    session.add(volume)
    session.flush()
    return volume


def _active_chapters(session: Session, volume_id: int) -> Sequence[Chapter]:
    statement = (
        active(Chapter)
        .where(Chapter.volume_id == volume_id)
        .order_by(Chapter.order_index, Chapter.id)
    )
    return session.execute(statement).scalars().all()


def _active_volumes(session: Session, project_id: int) -> Sequence[Volume]:
    statement = (
        active(Volume)
        .where(Volume.project_id == project_id, Volume.is_default == 0)
        .order_by(Volume.order_index, Volume.id)
    )
    return session.execute(statement).scalars().all()


def _volume_word_counts(
    session: Session, volume_ids: Sequence[int]
) -> dict[int, tuple[int, int]]:
    """批量取卷的（章节数，字数）——避免 N+1。"""
    if not volume_ids:
        return {}
    rows = session.execute(
        select(
            Chapter.volume_id,
            func.count(Chapter.id),
            func.coalesce(func.sum(Chapter.word_count), 0),
        )
        .where(Chapter.volume_id.in_(volume_ids), Chapter.is_deleted == 0)
        .group_by(Chapter.volume_id)
    ).all()
    return {int(vid): (int(count), int(words)) for vid, count, words in rows}


# --------------------------------------------------------------------------
# 序列化
# --------------------------------------------------------------------------


def serialize_chapter_meta(chapter: Chapter) -> dict[str, Any]:
    """章节列表项（**仅元数据**，§6.1「大列表接口」约定）。"""
    return {
        "id": chapter.id,
        "volume_id": chapter.volume_id,
        "title": chapter.title,
        "status": chapter.status,
        "summary": chapter.summary,
        "target_word_count": chapter.target_word_count,
        "order_index": chapter.order_index,
        "word_count": chapter.word_count,
        "version_no": chapter.version_no,
        "created_at": iso(chapter.created_at),
        "updated_at": iso(chapter.updated_at),
    }


def serialize_volume(
    volume: Volume,
    chapters: Sequence[Chapter],
    counts: tuple[int, int] | None = None,
) -> dict[str, Any]:
    if counts is None:
        chapter_count = len(chapters)
        word_count = sum(chapter.word_count for chapter in chapters)
    else:
        chapter_count, word_count = counts
    return {
        "id": volume.id,
        "project_id": volume.project_id,
        "title": volume.title,
        "summary": volume.summary,
        "order_index": volume.order_index,
        "is_default": bool(volume.is_default),
        "chapter_count": chapter_count,
        "word_count": word_count,
        "chapters": [serialize_chapter_meta(chapter) for chapter in chapters],
    }


def list_volume_tree(session: Session, project_id: int) -> dict[str, Any]:
    """§6.2 #10：卷列表 + 章节树（仅元数据；默认卷单列，BR-6）。"""
    project_service.require_project(session, project_id)
    volumes = _active_volumes(session, project_id)
    default_volume = get_default_volume(session, project_id)

    all_ids = [volume.id for volume in volumes] + [default_volume.id]
    counts = _volume_word_counts(session, all_ids)

    items = []
    for volume in volumes:
        chapters = _active_chapters(session, volume.id)
        items.append(serialize_volume(volume, chapters, counts.get(volume.id)))

    default_chapters = _active_chapters(session, default_volume.id)
    return {
        "volumes": items,
        "default_volume": serialize_volume(
            default_volume, default_chapters, counts.get(default_volume.id)
        ),
    }


def list_chapters(session: Session, volume_id: int) -> dict[str, Any]:
    """§6.2 #16：章节列表（仅元数据）。"""
    volume = require_volume(session, volume_id)
    chapters = _active_chapters(session, volume_id)
    return {
        "volume": {"id": volume.id, "title": volume.title},
        "items": [serialize_chapter_meta(chapter) for chapter in chapters],
        "total": len(chapters),
    }


# --------------------------------------------------------------------------
# 卷写入
# --------------------------------------------------------------------------


def create_volume(
    session: Session,
    project_id: int,
    *,
    title: str,
    summary: str | None = None,
) -> Volume:
    """新建卷，序号排在现有卷末尾（默认卷 order_index=0 不参与）。"""
    project_service.require_project(session, project_id)
    max_index = session.execute(
        select(func.max(Volume.order_index)).where(
            Volume.project_id == project_id,
            Volume.is_default == 0,
            Volume.is_deleted == 0,
        )
    ).scalar()
    order_index = (int(max_index) + ORDER_STEP) if max_index is not None else ORDER_STEP

    now = utc_now()
    volume = Volume(
        project_id=project_id,
        title=_clean_title(title, "卷名"),
        summary=_clean_summary(summary),
        order_index=order_index,
        is_default=0,
        created_at=now,
        updated_at=now,
    )
    session.add(volume)
    session.flush()
    _touch_project(session, project_id)
    return volume


def update_volume(
    session: Session,
    volume_id: int,
    **fields: Any,
) -> Volume:
    """§6.2 #12：改卷名/梗概；默认卷拒绝（BR-6）。"""
    volume = require_volume(session, volume_id)
    if volume.is_default:
        raise ApiError(CODE_PARAM_INVALID, "默认卷不可重命名或修改梗概")

    if "title" in fields and fields["title"] is not None:
        volume.title = _clean_title(fields["title"], "卷名")
    if "summary" in fields:
        volume.summary = _clean_summary(fields["summary"])
    volume.updated_at = utc_now()
    _touch_project(session, volume.project_id)
    return volume


def _soft_delete_chapter(chapter: Chapter, now: Any) -> None:
    chapter.is_deleted = 1
    chapter.deleted_at = now
    chapter.updated_at = now


def delete_volume(
    session: Session,
    volume_id: int,
    mode: str | None = None,
) -> dict[str, Any]:
    """§6.2 #13：删卷（BR-4 / FR-2.1）。

    · 默认卷不可删（BR-6）
    · 非空卷必须 ``mode=move``（章节移入默认卷末尾）或 ``mode=cascade``
      （章节一并软删除）；缺 mode → 1001
    · 空卷可直接删除
    """
    volume = require_volume(session, volume_id)
    if volume.is_default:
        raise ApiError(CODE_PARAM_INVALID, "默认卷不可删除")

    chapters = _active_chapters(session, volume_id)
    if chapters and mode not in DELETE_MODES:
        raise ApiError(
            CODE_PARAM_INVALID,
            "卷内还有章节，必须指定 mode=move（移入默认卷）或 "
            "mode=cascade（一并删除）",
        )
    if mode is not None and mode not in DELETE_MODES:
        raise ApiError(CODE_PARAM_INVALID, "mode 只能是 move 或 cascade")

    now = utc_now()
    moved = 0
    deleted_chapters = 0
    removed_words = 0

    if mode == "move" and chapters:
        target = get_default_volume(session, volume.project_id)
        max_index = session.execute(
            select(func.max(Chapter.order_index)).where(
                Chapter.volume_id == target.id, Chapter.is_deleted == 0
            )
        ).scalar()
        next_index = (
            int(max_index) + ORDER_STEP if max_index is not None else ORDER_STEP
        )
        for chapter in chapters:
            chapter.volume_id = target.id
            chapter.order_index = next_index
            next_index += ORDER_STEP
            chapter.updated_at = now
            moved += 1
    elif mode == "cascade":
        for chapter in chapters:
            removed_words += int(chapter.word_count)
            _soft_delete_chapter(chapter, now)
            deleted_chapters += 1

    volume.is_deleted = 1
    volume.deleted_at = now
    volume.updated_at = now

    project = project_service.require_project(session, volume.project_id)
    if removed_words:
        # 级联删除的章节不计入全书字数（与章节软删、统计口径一致）
        project.total_word_count = max(0, int(project.total_word_count) - removed_words)
    project.updated_at = now

    return {
        "id": volume_id,
        "deleted": True,
        "mode": mode,
        "moved_chapters": moved,
        "deleted_chapters": deleted_chapters,
    }


# --------------------------------------------------------------------------
# BR-3 排序
# --------------------------------------------------------------------------


def branch_insert_index(
    prev_index: int | None,
    next_index: int | None,
) -> tuple[int, bool]:
    """按 BR-3 计算插入序号，返回 ``(order_index, 是否需要整体重整)``。

    · 空列表 → 1000
    · 头部 → 下一项 − 1000（≤0 时重整）
    · 尾部 → 上一项 + 1000
    · 中间 → floor((前 + 后) / 2)；相邻差 ≤1 时重整
    """
    if prev_index is None and next_index is None:
        return ORDER_STEP, False
    if prev_index is None:
        candidate = int(next_index) - ORDER_STEP
        return (candidate, False) if candidate > 0 else (ORDER_STEP, True)
    if next_index is None:
        return int(prev_index) + ORDER_STEP, False

    prev_value = int(prev_index)
    next_value = int(next_index)
    if next_value - prev_value <= 1:
        return ORDER_STEP, True
    return (prev_value + next_value) // 2, False


def _resolve_position(
    ordered: Sequence[Any],
    prev_id: int | None,
    next_id: int | None,
    label: str,
) -> tuple[int, int | None, int | None]:
    """把 prev/next 解析为 ``(插入下标, 前项序号, 后项序号)``。

    同父级内除了被移动项之外的兄弟列表已经排好序；插入下标即「插到第几个位置」。
    """
    positions = {item.id: index for index, item in enumerate(ordered)}

    if prev_id is not None and prev_id not in positions:
        raise ApiError(CODE_PARAM_INVALID, f"{label} prev_id 不属于同一父级")
    if next_id is not None and next_id not in positions:
        raise ApiError(CODE_PARAM_INVALID, f"{label} next_id 不属于同一父级")
    if prev_id is not None and prev_id == next_id:
        raise ApiError(CODE_PARAM_INVALID, "prev_id 与 next_id 不能相同")

    if prev_id is None and next_id is None:
        # 追加到末尾
        if not ordered:
            return 0, None, None
        return len(ordered), ordered[-1].order_index, None

    if prev_id is None:
        position = positions[next_id]  # type: ignore[index]
        prev_index = ordered[position - 1].order_index if position > 0 else None
        return position, prev_index, ordered[position].order_index

    position = positions[prev_id] + 1
    next_index = ordered[position].order_index if position < len(ordered) else None
    if next_id is not None:
        if positions[next_id] != position:  # type: ignore[index]
            raise ApiError(CODE_PARAM_INVALID, "prev_id 与 next_id 必须相邻")
    return position, ordered[position - 1].order_index, next_index


def _rebalance(siblings: Sequence[Any], moved: Any, position: int) -> None:
    """按 1000 步长重排：把 ``moved`` 插到 ``position`` 后整体编号。"""
    ordered = list(siblings)
    ordered.insert(position, moved)
    for index, item in enumerate(ordered, start=1):
        item.order_index = index * ORDER_STEP


def reorder_volume(
    session: Session,
    project_id: int,
    volume_id: int,
    *,
    prev_id: int | None = None,
    next_id: int | None = None,
) -> Volume:
    """§6.2 #14：卷排序（BR-3，支持拖拽到头部/尾部/中间）。"""
    project_service.require_project(session, project_id)
    volume = require_volume(session, volume_id)
    if volume.project_id != project_id:
        raise ApiError(CODE_PARAM_INVALID, "卷不属于该项目")
    if volume.is_default:
        raise ApiError(CODE_PARAM_INVALID, "默认卷不参与排序")

    siblings = [
        item for item in _active_volumes(session, project_id) if item.id != volume_id
    ]
    position, prev_index, next_index = _resolve_position(
        siblings, prev_id, next_id, "卷"
    )
    order_index, rebalance = branch_insert_index(prev_index, next_index)

    if rebalance:
        _rebalance(siblings, volume, position)
    else:
        volume.order_index = order_index

    volume.updated_at = utc_now()
    _touch_project(session, project_id)
    return volume


# --------------------------------------------------------------------------
# 章节写入
# --------------------------------------------------------------------------


def create_chapter(
    session: Session,
    volume_id: int,
    *,
    title: str,
    status: str | None = "draft",
    summary: str | None = None,
    target_word_count: int | None = 0,
) -> Chapter:
    """§6.2 #17：新建章节，序号排在卷内末尾。"""
    volume = require_volume(session, volume_id)
    max_index = session.execute(
        select(func.max(Chapter.order_index)).where(
            Chapter.volume_id == volume_id, Chapter.is_deleted == 0
        )
    ).scalar()
    order_index = (int(max_index) + ORDER_STEP) if max_index is not None else ORDER_STEP

    now = utc_now()
    chapter = Chapter(
        volume_id=volume_id,
        title=_clean_title(title, "章节标题"),
        content=None,
        content_text=None,
        word_count=0,
        status=_clean_chapter_status(status),
        summary=_clean_summary(summary),
        target_word_count=_clean_target(target_word_count),
        order_index=order_index,
        version_no=0,
        created_at=now,
        updated_at=now,
    )
    session.add(chapter)
    session.flush()
    _touch_project(session, volume.project_id)
    return chapter


def reorder_chapter(
    session: Session,
    volume_id: int,
    chapter_id: int,
    *,
    prev_id: int | None = None,
    next_id: int | None = None,
    target_volume_id: int | None = None,
) -> Chapter:
    """§6.2 #22：章节排序 / 跨卷移动（BR-3）。

    ``volume_id`` 为路径参数（来源卷）；``target_volume_id`` 缺省表示同卷内排序。
    跨卷移动时同样按目标卷内相邻项计算序号，源卷留下的空隙无需重整。
    """
    source = require_volume(session, volume_id)
    chapter = require_chapter(session, chapter_id)
    if chapter.volume_id != source.id:
        raise ApiError(CODE_PARAM_INVALID, "章节不属于该卷")

    target = (
        require_volume(session, target_volume_id)
        if target_volume_id is not None
        else source
    )
    if target.project_id != source.project_id:
        # 章节属于 source 所在项目；跨项目移动会造成 A 书的正文出现在 B 书里
        raise ApiError(CODE_PARAM_INVALID, "不能跨项目移动章节")

    siblings = [
        item for item in _active_chapters(session, target.id) if item.id != chapter_id
    ]
    position, prev_index, next_index = _resolve_position(
        siblings, prev_id, next_id, "章节"
    )
    order_index, rebalance = branch_insert_index(prev_index, next_index)

    if rebalance:
        _rebalance(siblings, chapter, position)
    else:
        chapter.order_index = order_index
    chapter.volume_id = target.id
    chapter.updated_at = utc_now()
    _touch_project(session, source.project_id)
    return chapter


def _append_all_chapters(session: Session, source: Volume, target: Volume) -> int:
    """把源卷全部活跃章节按原顺序追加到目标卷末尾，返回移动数量。"""
    chapters = _active_chapters(session, source.id)
    if not chapters:
        return 0

    max_index = session.execute(
        select(func.max(Chapter.order_index)).where(
            Chapter.volume_id == target.id, Chapter.is_deleted == 0
        )
    ).scalar()
    next_index = int(max_index) + ORDER_STEP if max_index is not None else ORDER_STEP
    now = utc_now()
    for chapter in chapters:
        chapter.volume_id = target.id
        chapter.order_index = next_index
        chapter.updated_at = now
        next_index += ORDER_STEP
    _touch_project(session, target.project_id)
    return len(chapters)


def move_chapters_to_volume(
    session: Session,
    source_volume_id: int,
    target_volume_id: int,
) -> int:
    """把源卷全部章节追加到目标卷末尾（C-03 数据层预留，V1.1 合并卷复用）。"""
    source = require_volume(session, source_volume_id)
    target = require_volume(session, target_volume_id)
    if source.project_id != target.project_id:
        raise ApiError(CODE_PARAM_INVALID, "不能跨项目移动章节")
    if source.is_default:
        raise ApiError(CODE_PARAM_INVALID, "默认卷不支持合并")

    return _append_all_chapters(session, source, target)


def adopt_default_chapters(session: Session, target_volume_id: int) -> dict[str, Any]:
    """C-04：把默认卷章节一次性迁入**首个**命名卷（之后默认卷继续保持隐藏）。"""
    target = require_volume(session, target_volume_id)
    if target.is_default:
        raise ApiError(CODE_PARAM_INVALID, "目标卷不能是默认卷")

    named = session.execute(
        select(func.count())
        .select_from(Volume)
        .where(
            Volume.project_id == target.project_id,
            Volume.is_default == 0,
            Volume.is_deleted == 0,
        )
    ).scalar()
    if int(named or 0) != 1:
        raise ApiError(CODE_PARAM_INVALID, "仅首个命名卷可接收默认卷章节")

    source = get_default_volume(session, target.project_id)
    moved = _append_all_chapters(session, source, target)
    return {"volume_id": target.id, "moved": moved}


# --------------------------------------------------------------------------
# 章节详情 / 正文保存 / 删除（任务 2.3，§6.2 #18~#21）
# --------------------------------------------------------------------------


def _project_id_of_chapter(session: Session, chapter: Chapter) -> int:
    project_id = session.execute(
        select(Volume.project_id).where(Volume.id == chapter.volume_id)
    ).scalar_one_or_none()
    if project_id is None:  # pragma: no cover - 外键保证
        raise ApiError(CODE_NOT_FOUND, "章节所属卷不存在")
    return int(project_id)


def get_chapter_detail(session: Session, chapter_id: int) -> dict[str, Any]:
    """§6.2 #18：章节详情（正文图片临时替换为签名 URL）。"""
    chapter = require_chapter(session, chapter_id)
    project_id = _project_id_of_chapter(session, chapter)
    project = project_service.require_project(session, project_id)
    return {
        **serialize_chapter_meta(chapter),
        "project_id": project_id,
        "project_title": project.title,
        "project_word_count": project.total_word_count,
        "content": media.sign_content_images(chapter.content or ""),
        "content_text": chapter.content_text,
    }


def update_chapter(
    session: Session,
    chapter_id: int,
    **fields: Any,
) -> Chapter:
    """§6.2 #19：改标题/状态/梗概/目标字数（不含正文）。"""
    chapter = require_chapter(session, chapter_id)

    if "title" in fields and fields["title"] is not None:
        chapter.title = _clean_title(fields["title"], "章节标题")
    if "status" in fields and fields["status"] is not None:
        chapter.status = _clean_chapter_status(fields["status"])
    if "summary" in fields:
        chapter.summary = _clean_summary(fields["summary"])
    if "target_word_count" in fields and fields["target_word_count"] is not None:
        chapter.target_word_count = _clean_target(fields["target_word_count"])

    chapter.updated_at = utc_now()
    _touch_project(session, _project_id_of_chapter(session, chapter))
    return chapter


def save_chapter_content(
    session: Session,
    chapter_id: int,
    *,
    content_html: str | None,
    expect_version: int | None = None,
    client_saved_at: str | None = None,
) -> dict[str, Any]:
    """§6.2 #20：正文保存（消毒 + 图片路径还原 + 字数 + 乐观锁）。

    · ``expect_version`` 与 ``chapter.version_no`` 不一致 → **3002**
      （前端须先落暂存再提示刷新，BR-2）
    · 每次成功保存 ``version_no += 1``（BR-9：单调递增、永不回退）
    · 2.6 将在此之后接入分级快照；当前返回 ``snapshot_created=false``

    ``client_saved_at`` 仅作契约字段接收，服务端不采信客户端时间（BR-8）。
    """
    chapter = require_chapter(session, chapter_id)
    expected = None if expect_version is None else int(expect_version)

    normalized = media.normalize_content_images(content_html)
    clean = sanitize.sanitize_html(normalized)
    plain, words = wordcount.count_html(clean)

    old_words = int(chapter.word_count)
    now = utc_now()

    # 乐观锁必须是「条件 UPDATE」而不是「先读后写」：两个并发的自动保存
    # 各自读到同一个 version_no，再各自写入，后写者会静默覆盖前者的正文。
    # 条件更新把比较和写入放进同一条 SQL，SQLite 单写者 + busy_timeout
    # 保证第二个请求看到 +1 后的版本号，从而得到 3002。
    statement = (
        Chapter.__table__.update()
        .where(Chapter.id == chapter.id)
        .values(
            content=clean,
            content_text=plain,
            word_count=words,
            version_no=Chapter.version_no + 1,
            updated_at=now,
        )
    )
    if expected is not None:
        statement = statement.where(Chapter.version_no == expected)
    result = session.execute(statement)
    if result.rowcount != 1:
        if expected is not None:
            raise ApiError(
                CODE_VERSION_CONFLICT,
                "章节已在别处更新（版本冲突），请先暂存本地内容并刷新",
            )
        raise ApiError(CODE_NOT_FOUND, "章节不存在")
    session.refresh(chapter)

    project_id = _project_id_of_chapter(session, chapter)
    project = project_service.require_project(session, project_id)
    project.total_word_count = max(0, int(project.total_word_count) + words - old_words)
    project.updated_at = now

    # 2.6：按 D-04 判断是否创建 auto 快照（失败不影响正文保存）
    snapshot = version_service.maybe_create_auto_snapshot(session, chapter)

    return {
        "chapter_id": chapter.id,
        "word_count": words,
        "project_word_count": project.total_word_count,
        "saved_at": iso(now),
        "version_no": chapter.version_no,
        "client_saved_at": client_saved_at,
        "snapshot_created": snapshot is not None,
        "snapshot_version_no": snapshot.version_no if snapshot is not None else None,
    }


def delete_chapter(session: Session, chapter_id: int) -> dict[str, Any]:
    """§6.2 #21：软删除章节（BR-4），并从项目总字数中扣减。"""
    chapter = require_chapter(session, chapter_id)
    project_id = _project_id_of_chapter(session, chapter)
    now = utc_now()

    chapter.is_deleted = 1
    chapter.deleted_at = now
    chapter.updated_at = now

    project = project_service.require_project(session, project_id)
    project.total_word_count = max(
        0, int(project.total_word_count) - int(chapter.word_count)
    )
    project.updated_at = now
    return {
        "id": chapter.id,
        "volume_id": chapter.volume_id,
        "deleted": True,
        "word_count": int(chapter.word_count),
    }
