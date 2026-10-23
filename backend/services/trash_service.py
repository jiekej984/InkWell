"""回收站与父链恢复（任务 2.8 / BR-4 / FR-1.6）。

规则：
    · 全软删除；回收站保留 **30 天**（清理动作由 2.9 后台流程执行）
    · **父链校验**：父资源仍在回收站 → 返回 ``requires_parent``（HTTP 200，非错误），
      前端提示「一并恢复」；带 ``with_parent=true`` 时按批次级联恢复
    · 父已物理删除 → 章节挂默认卷（外键级联下实际不可达，保留兜底分支）
    · 恢复后重算项目总字数（``maintenance_service.recompute_project_totals``）
    · ``DELETE /trash/empty`` 与过期清理均为**物理删除**（DB 外键级联 + FTS 触发器同步）

批次语义：
    项目/卷删除时，被级联的子项共享同一个 ``deleted_at``；恢复父资源只恢复
    **同一批次**的子项，之前单独删除的内容仍留在回收站。
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chapter, Document, Project, Volume
from ..schemas import CODE_NOT_FOUND, CODE_PARAM_INVALID, ApiError
from ..timeutil import iso, utc_now
from . import chapter_service, maintenance_service

TRASH_RETENTION_DAYS = 30
TRASH_TYPES = ("project", "volume", "chapter", "document")
_TYPE_LABELS = {
    "project": "项目",
    "volume": "卷",
    "chapter": "章节",
    "document": "设定文档",
}
_MODELS = {
    "project": Project,
    "volume": Volume,
    "chapter": Chapter,
    "document": Document,
}


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------


def _days_left(deleted_at: Any) -> int:
    if deleted_at is None:
        return 0
    remaining = deleted_at + timedelta(days=TRASH_RETENTION_DAYS) - utc_now()
    return max(0, math.ceil(remaining.total_seconds() / 86400))


def _deleted(session: Session, model: Any) -> list[Any]:
    return (
        session.execute(
            select(model)
            .where(model.is_deleted == 1)
            .order_by(model.deleted_at.desc(), model.id.desc())
        )
        .scalars()
        .all()
    )


def list_trash(session: Session) -> dict[str, Any]:
    """§6.2 #39：回收站列表（按类型分组，含父级与剩余天数）。"""
    projects = _deleted(session, Project)
    volumes = _deleted(session, Volume)
    chapters = _deleted(session, Chapter)
    documents = _deleted(session, Document)

    volumes_all = {
        row.id: row for row in session.execute(select(Volume)).scalars().all()
    }
    all_projects = {
        row.id: row for row in session.execute(select(Project)).scalars().all()
    }

    items = {
        "projects": [],
        "volumes": [],
        "chapters": [],
        "documents": [],
    }

    for project in projects:
        items["projects"].append(
            {
                "type": "project",
                "id": project.id,
                "title": project.title,
                "deleted_at": iso(project.deleted_at),
                "days_left": _days_left(project.deleted_at),
            }
        )

    for volume in volumes:
        project = all_projects.get(volume.project_id)
        items["volumes"].append(
            {
                "type": "volume",
                "id": volume.id,
                "title": volume.title,
                "project_id": volume.project_id,
                "project_title": project.title if project else None,
                "project_deleted": bool(project.is_deleted) if project else True,
                "deleted_at": iso(volume.deleted_at),
                "days_left": _days_left(volume.deleted_at),
            }
        )

    for chapter in chapters:
        volume = volumes_all.get(chapter.volume_id)
        project = all_projects.get(volume.project_id) if volume else None
        items["chapters"].append(
            {
                "type": "chapter",
                "id": chapter.id,
                "title": chapter.title,
                "volume_id": chapter.volume_id,
                "volume_title": volume.title if volume else None,
                "project_id": project.id if project else None,
                "project_title": project.title if project else None,
                "project_deleted": bool(project.is_deleted) if project else True,
                "volume_deleted": bool(volume.is_deleted) if volume else True,
                "word_count": chapter.word_count,
                "deleted_at": iso(chapter.deleted_at),
                "days_left": _days_left(chapter.deleted_at),
            }
        )

    for document in documents:
        project = all_projects.get(document.project_id)
        items["documents"].append(
            {
                "type": "document",
                "id": document.id,
                "title": document.title,
                "category": document.category,
                "project_id": document.project_id,
                "project_title": project.title if project else None,
                "project_deleted": bool(project.is_deleted) if project else True,
                "word_count": document.word_count,
                "deleted_at": iso(document.deleted_at),
                "days_left": _days_left(document.deleted_at),
            }
        )

    total = sum(len(group) for group in items.values())
    return {
        **items,
        "total": total,
        "retention_days": TRASH_RETENTION_DAYS,
    }


# --------------------------------------------------------------------------
# 恢复
# --------------------------------------------------------------------------


def _require_row(session: Session, model: Any, item_id: int, label: str) -> Any:
    row = session.get(model, item_id)
    if row is None:
        raise ApiError(CODE_NOT_FOUND, f"{label}不存在")
    if not row.is_deleted:
        raise ApiError(CODE_PARAM_INVALID, f"{label}不在回收站")
    return row


def _restore_row(row: Any) -> None:
    row.is_deleted = 0
    row.deleted_at = None
    row.updated_at = utc_now()


def _requires_parent(parent_type: str, parent: Any) -> dict[str, Any]:
    return {
        "restored": False,
        "requires_parent": True,
        "parent": {
            "type": parent_type,
            "id": parent.id,
            "title": parent.title,
        },
        "message": f"父{_TYPE_LABELS[parent_type]}「{parent.title}」在回收站，"
        f"请选择一并恢复",
    }


def _restore_project_batch(session: Session, project: Project) -> None:
    """恢复项目及**同批次**级联的卷/章/文档。"""
    stamp = project.deleted_at
    _restore_row(project)

    volumes = (
        session.execute(select(Volume).where(Volume.project_id == project.id))
        .scalars()
        .all()
    )
    for volume in volumes:
        if volume.is_deleted and volume.deleted_at == stamp:
            _restore_row(volume)

    volume_ids = [volume.id for volume in volumes]
    if volume_ids:
        chapters = (
            session.execute(select(Chapter).where(Chapter.volume_id.in_(volume_ids)))
            .scalars()
            .all()
        )
        for chapter in chapters:
            if chapter.is_deleted and chapter.deleted_at == stamp:
                _restore_row(chapter)

    documents = (
        session.execute(select(Document).where(Document.project_id == project.id))
        .scalars()
        .all()
    )
    for document in documents:
        if document.is_deleted and document.deleted_at == stamp:
            _restore_row(document)

    chapter_service.ensure_default_volume(session, project.id)


def _restore_volume_batch(session: Session, volume: Volume) -> None:
    stamp = volume.deleted_at
    _restore_row(volume)
    chapters = (
        session.execute(select(Chapter).where(Chapter.volume_id == volume.id))
        .scalars()
        .all()
    )
    for chapter in chapters:
        if chapter.is_deleted and chapter.deleted_at == stamp:
            _restore_row(chapter)
    chapter_service.ensure_default_volume(session, volume.project_id)


def _finish(
    session: Session, project_id: int, result: dict[str, Any]
) -> dict[str, Any]:
    maintenance_service.recompute_project_totals(session)
    return {**result, "restored": True, "project_id": project_id}


def restore_project(session: Session, project_id: int) -> dict[str, Any]:
    project = _require_row(session, Project, project_id, "项目")
    _restore_project_batch(session, project)
    return _finish(
        session,
        project.id,
        {"type": "project", "id": project.id, "title": project.title},
    )


def restore_volume(
    session: Session, volume_id: int, *, with_parent: bool = False
) -> dict[str, Any]:
    volume = _require_row(session, Volume, volume_id, "卷")
    project = session.get(Project, volume.project_id)
    if project is None:  # pragma: no cover - 外键级联保证
        raise ApiError(CODE_NOT_FOUND, "所属项目不存在")

    if project.is_deleted:
        if not with_parent:
            return _requires_parent("project", project)
        _restore_project_batch(session, project)
        return _finish(
            session,
            project.id,
            {
                "type": "volume",
                "id": volume.id,
                "title": volume.title,
                "restored_parent": {"type": "project", "id": project.id},
            },
        )

    _restore_volume_batch(session, volume)
    return _finish(
        session,
        project.id,
        {"type": "volume", "id": volume.id, "title": volume.title},
    )


def restore_chapter(
    session: Session, chapter_id: int, *, with_parent: bool = False
) -> dict[str, Any]:
    chapter = _require_row(session, Chapter, chapter_id, "章节")
    volume = session.get(Volume, chapter.volume_id)
    if volume is None:
        # 父卷已物理删除：兜底挂到项目默认卷（外键级联下通常不可达）
        raise ApiError(CODE_NOT_FOUND, "章节所属卷已不存在，无法恢复")

    project = session.get(Project, volume.project_id)
    if project is None:  # pragma: no cover
        raise ApiError(CODE_NOT_FOUND, "章节所属项目不存在")

    if project.is_deleted:
        if not with_parent:
            return _requires_parent("project", project)
        _restore_project_batch(session, project)
        return _finish(
            session,
            project.id,
            {
                "type": "chapter",
                "id": chapter.id,
                "title": chapter.title,
                "restored_parent": {"type": "project", "id": project.id},
            },
        )

    if volume.is_deleted:
        if not with_parent:
            return _requires_parent("volume", volume)
        _restore_volume_batch(session, volume)

    if chapter.is_deleted:
        _restore_row(chapter)

    chapter_service.ensure_default_volume(session, project.id)
    return _finish(
        session,
        project.id,
        {"type": "chapter", "id": chapter.id, "title": chapter.title},
    )


def restore_document(
    session: Session, document_id: int, *, with_parent: bool = False
) -> dict[str, Any]:
    document = _require_row(session, Document, document_id, "设定文档")
    project = session.get(Project, document.project_id)
    if project is None:  # pragma: no cover
        raise ApiError(CODE_NOT_FOUND, "所属项目不存在")

    if project.is_deleted:
        if not with_parent:
            return _requires_parent("project", project)
        _restore_project_batch(session, project)
        return _finish(
            session,
            project.id,
            {
                "type": "document",
                "id": document.id,
                "title": document.title,
                "restored_parent": {"type": "project", "id": project.id},
            },
        )

    if document.is_deleted:
        _restore_row(document)
    return _finish(
        session,
        project.id,
        {"type": "document", "id": document.id, "title": document.title},
    )


_RESTORERS = {
    "project": lambda session, item_id, with_parent: restore_project(session, item_id),
    "volume": lambda session, item_id, with_parent: restore_volume(
        session, item_id, with_parent=with_parent
    ),
    "chapter": lambda session, item_id, with_parent: restore_chapter(
        session, item_id, with_parent=with_parent
    ),
    "document": lambda session, item_id, with_parent: restore_document(
        session, item_id, with_parent=with_parent
    ),
}


def restore(
    session: Session, item_type: str, item_id: int, *, with_parent: bool = False
) -> dict[str, Any]:
    """§6.2 #40：按类型恢复；未知类型 → 1001。"""
    if item_type not in _RESTORERS:
        raise ApiError(CODE_PARAM_INVALID, f"未知的回收站类型：{item_type}")
    return _RESTORERS[item_type](session, item_id, with_parent)


# --------------------------------------------------------------------------
# 物理删除 / 过期清理
# --------------------------------------------------------------------------


def _purge_scope(
    session: Session,
    cutoff: Any,
    counts: dict[str, int],
) -> None:
    """物理删除 ``deleted_at < cutoff`` 的回收站数据（项目优先，级联子项）。"""
    projects = (
        session.execute(
            select(Project).where(Project.is_deleted == 1, Project.deleted_at < cutoff)
        )
        .scalars()
        .all()
    )
    for project in projects:
        session.delete(project)
    counts["projects"] = len(projects)
    session.flush()

    for key, model in (
        ("volumes", Volume),
        ("chapters", Chapter),
        ("documents", Document),
    ):
        rows = (
            session.execute(
                select(model).where(model.is_deleted == 1, model.deleted_at < cutoff)
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.delete(row)
        counts[key] = len(rows)
        session.flush()


def empty_trash(session: Session) -> dict[str, Any]:
    """§6.2 #41：清空回收站（物理删除，含已物理删除父级的残留子项）。"""
    counts = {"projects": 0, "volumes": 0, "chapters": 0, "documents": 0}
    _purge_scope(session, utc_now() + timedelta(days=1), counts)
    session.flush()
    return {**counts, "emptied": True}


def purge_expired_trash(session: Session, *, now: Any = None) -> dict[str, Any]:
    """BR-4：清理超过 30 天的回收站数据（由 2.9 启动后台流程调用）。"""
    cutoff = (now or utc_now()) - timedelta(days=TRASH_RETENTION_DAYS)
    counts = {"projects": 0, "volumes": 0, "chapters": 0, "documents": 0}
    _purge_scope(session, cutoff, counts)
    session.flush()
    return {**counts, "purged": sum(counts.values())}
