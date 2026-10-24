"""大立场业务逻辑（V2.0 / FR-8.7、8.11）。

对应接口 **#68~#72**。界面 Tab 叫「阵营」，数据实体叫 ``faction``，同一个东西。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Faction, FactionRelation, Organization, active
from ..schemas import CODE_DELETED, CODE_NOT_FOUND, CODE_PARAM_INVALID, ApiError
from ..timeutil import iso, utc_now
from . import project_service
from .character_meta import (
    FACTION_RELATION_LABELS,
    FACTION_RELATION_TYPES,
)

MAX_NAME_LENGTH = 100
MAX_DESCRIPTION = 500
ORDER_STEP = 1000
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clean_name(name: str | None) -> str:
    value = (name or "").strip()
    if not value:
        raise ApiError(CODE_PARAM_INVALID, "立场名称不能为空")
    if len(value) > MAX_NAME_LENGTH:
        raise ApiError(CODE_PARAM_INVALID, f"立场名称不能超过 {MAX_NAME_LENGTH} 个字符")
    return value


def _clean_color(color: Any) -> str | None:
    if color is None:
        return None
    value = str(color).strip()
    if not value:
        return None
    if not _COLOR_RE.match(value):
        raise ApiError(CODE_PARAM_INVALID, "颜色必须是 #RRGGBB 格式")
    return value.lower()


def _clean_description(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > MAX_DESCRIPTION:
        raise ApiError(CODE_PARAM_INVALID, f"简介不能超过 {MAX_DESCRIPTION} 个字符")
    return text


def _clean_order(value: int | None) -> int:
    if value is None:
        raise ApiError(CODE_PARAM_INVALID, "排序值不能为空")
    if int(value) < 0:
        raise ApiError(CODE_PARAM_INVALID, "排序值不能为负数")
    return int(value)


def require_faction(session: Session, faction_id: int) -> Faction:
    faction = session.get(Faction, faction_id)
    if faction is None:
        raise ApiError(CODE_NOT_FOUND, "大立场不存在")
    if faction.is_deleted:
        raise ApiError(CODE_DELETED, "大立场已删除，可在回收站恢复")
    return faction


def serialize_faction(faction: Faction, org_count: int = 0) -> dict[str, Any]:
    return {
        "id": faction.id,
        "project_id": faction.project_id,
        "name": faction.name,
        "color": faction.color,
        "description": faction.description,
        "order_index": faction.order_index,
        "organization_count": org_count,
        "created_at": iso(faction.created_at),
        "updated_at": iso(faction.updated_at),
    }


def _org_counts(session: Session, project_id: int) -> dict[int, int]:
    rows = session.execute(
        select(Organization.faction_id, func.count(Organization.id))
        .where(
            Organization.project_id == project_id,
            Organization.is_deleted == 0,
            Organization.faction_id.is_not(None),
        )
        .group_by(Organization.faction_id)
    ).all()
    return {int(fid): int(count) for fid, count in rows if fid is not None}


def list_factions(session: Session, project_id: int) -> dict[str, Any]:
    """§6.2 #68：立场列表（含组织数）。"""
    project_service.require_project(session, project_id)
    counts = _org_counts(session, project_id)
    rows = (
        session.execute(
            active(Faction)
            .where(Faction.project_id == project_id)
            .order_by(Faction.order_index, Faction.id)
        )
        .scalars()
        .all()
    )
    return {
        "project_id": project_id,
        "items": [serialize_faction(row, counts.get(int(row.id), 0)) for row in rows],
        "total": len(rows),
    }


def _next_order(session: Session, project_id: int) -> int:
    max_index = session.execute(
        select(func.max(Faction.order_index)).where(
            Faction.project_id == project_id, Faction.is_deleted == 0
        )
    ).scalar()
    return (int(max_index) + ORDER_STEP) if max_index is not None else ORDER_STEP


def _ensure_name_free(
    session: Session, project_id: int, name: str, *, exclude_id: int | None = None
) -> None:
    """先查重再写：唯一约束只作兜底，正常重名走这里报 1001。"""
    statement = select(Faction.id).where(
        Faction.project_id == project_id,
        Faction.name == name,
        Faction.is_deleted == 0,
    )
    if exclude_id is not None:
        statement = statement.where(Faction.id != exclude_id)
    if session.execute(statement).scalar() is not None:
        raise ApiError(CODE_PARAM_INVALID, f"立场「{name}」已存在")


def create_faction(
    session: Session, project_id: int, *, name: str, **fields: Any
) -> Faction:
    """§6.2 #69：新建立场。"""
    project_service.require_project(session, project_id)
    clean_name = _clean_name(name)
    _ensure_name_free(session, project_id, clean_name)
    now = utc_now()
    faction = Faction(
        project_id=project_id,
        name=clean_name,
        color=_clean_color(fields.get("color")),
        description=_clean_description(fields.get("description")),
        order_index=(
            _clean_order(fields["order_index"])
            if fields.get("order_index") is not None
            else _next_order(session, project_id)
        ),
        created_at=now,
        updated_at=now,
    )
    session.add(faction)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(CODE_PARAM_INVALID, f"立场「{clean_name}」已存在") from exc
    return faction


def update_faction(session: Session, faction_id: int, **fields: Any) -> Faction:
    """§6.2 #70（PATCH）。"""
    faction = require_faction(session, faction_id)
    if fields.get("name") is not None:
        clean_name = _clean_name(fields["name"])
        _ensure_name_free(
            session, faction.project_id, clean_name, exclude_id=faction_id
        )
        faction.name = clean_name
    if "color" in fields:
        faction.color = _clean_color(fields["color"])
    if "description" in fields:
        faction.description = _clean_description(fields["description"])
    if fields.get("order_index") is not None:
        faction.order_index = _clean_order(fields["order_index"])
    faction.updated_at = utc_now()
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(CODE_PARAM_INVALID, "同名立场已存在") from exc
    return faction


def delete_faction(session: Session, faction_id: int) -> dict[str, Any]:
    """§6.2 #70（DELETE）：仍有组织归属时**拒绝删除**（C-19）。"""
    faction = require_faction(session, faction_id)
    count = int(
        session.execute(
            select(func.count(Organization.id)).where(
                Organization.faction_id == faction_id,
                Organization.is_deleted == 0,
            )
        ).scalar_one()
    )
    if count:
        raise ApiError(
            CODE_PARAM_INVALID,
            f"该立场下还有 {count} 个组织，请先迁移组织或改为中立",
        )
    faction.is_deleted = 1
    faction.deleted_at = utc_now()
    faction.updated_at = faction.deleted_at
    session.flush()
    return {"id": faction_id, "deleted": True}


def restore_faction(session: Session, faction_id: int) -> dict[str, Any]:
    faction = session.get(Faction, faction_id)
    if faction is None:
        raise ApiError(CODE_NOT_FOUND, "大立场不存在")
    if not faction.is_deleted:
        raise ApiError(CODE_PARAM_INVALID, "立场未被删除，无法恢复")
    faction.is_deleted = 0
    faction.deleted_at = None
    faction.updated_at = utc_now()
    session.flush()
    return {"id": faction_id, "restored": True}


# --------------------------------------------------------------------------
# 立场间关系（#71 / #72）
# --------------------------------------------------------------------------


def require_faction_relation(session: Session, relation_id: int) -> FactionRelation:
    row = session.get(FactionRelation, relation_id)
    if row is None:
        raise ApiError(CODE_NOT_FOUND, "立场关系不存在")
    if row.is_deleted:
        raise ApiError(CODE_DELETED, "立场关系已删除")
    return row


def serialize_faction_relation(
    row: FactionRelation, names: dict[int, str]
) -> dict[str, Any]:
    return {
        "id": row.id,
        "from_id": row.from_id,
        "to_id": row.to_id,
        "from_name": names.get(row.from_id),
        "to_name": names.get(row.to_id),
        "relation_type": row.relation_type,
        "relation_label": FACTION_RELATION_LABELS.get(
            row.relation_type, row.relation_type
        ),
        "description": row.description,
        "is_bidirectional": bool(row.is_bidirectional),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def list_faction_relations(session: Session, project_id: int) -> dict[str, Any]:
    """§6.2 #71（GET）。"""
    project_service.require_project(session, project_id)
    rows = (
        session.execute(
            select(FactionRelation)
            .where(
                FactionRelation.project_id == project_id,
                FactionRelation.is_deleted == 0,
            )
            .order_by(FactionRelation.id)
        )
        .scalars()
        .all()
    )
    names = {
        fid: name
        for fid, name in session.execute(
            select(Faction.id, Faction.name).where(Faction.project_id == project_id)
        ).all()
    }
    return {
        "project_id": project_id,
        "items": [serialize_faction_relation(row, names) for row in rows],
        "total": len(rows),
        "types": [
            {"value": value, "label": FACTION_RELATION_LABELS[value]}
            for value in FACTION_RELATION_TYPES
        ],
    }


def create_faction_relation(
    session: Session,
    project_id: int,
    *,
    from_id: int,
    to_id: int,
    relation_type: str = "neutral",
    description: str | None = None,
    is_bidirectional: bool = True,
) -> FactionRelation:
    """§6.2 #71（POST）。"""
    project_service.require_project(session, project_id)
    if int(from_id) == int(to_id):
        raise ApiError(CODE_PARAM_INVALID, "立场之间不能自己指向自己")
    for fid in (from_id, to_id):
        faction = require_faction(session, int(fid))
        if faction.project_id != project_id:
            raise ApiError(CODE_PARAM_INVALID, "两个立场必须属于同一本书")
    kind = (relation_type or "neutral").strip()
    if kind not in FACTION_RELATION_TYPES:
        raise ApiError(
            CODE_PARAM_INVALID,
            f"关系类型必须是 {'/'.join(FACTION_RELATION_TYPES)} 之一",
        )
    duplicate = session.execute(
        select(FactionRelation.id).where(
            FactionRelation.from_id == int(from_id),
            FactionRelation.to_id == int(to_id),
            FactionRelation.relation_type == kind,
            FactionRelation.is_deleted == 0,
        )
    ).scalar()
    if duplicate is not None:
        raise ApiError(CODE_PARAM_INVALID, "这两个立场之间已有同类型关系")
    now = utc_now()
    row = FactionRelation(
        project_id=project_id,
        from_id=int(from_id),
        to_id=int(to_id),
        relation_type=kind,
        description=_clean_description(description),
        is_bidirectional=1 if is_bidirectional else 0,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(CODE_PARAM_INVALID, "这两个立场之间已有同类型关系") from exc
    return row


def update_faction_relation(
    session: Session, relation_id: int, **fields: Any
) -> FactionRelation:
    row = require_faction_relation(session, relation_id)
    if fields.get("relation_type") is not None:
        kind = str(fields["relation_type"]).strip()
        if kind not in FACTION_RELATION_TYPES:
            raise ApiError(CODE_PARAM_INVALID, "关系类型不合法")
        duplicate = session.execute(
            select(FactionRelation.id).where(
                FactionRelation.from_id == row.from_id,
                FactionRelation.to_id == row.to_id,
                FactionRelation.relation_type == kind,
                FactionRelation.is_deleted == 0,
                FactionRelation.id != relation_id,
            )
        ).scalar()
        if duplicate is not None:
            raise ApiError(CODE_PARAM_INVALID, "同类型关系已存在")
        row.relation_type = kind
    if "description" in fields:
        row.description = _clean_description(fields["description"])
    if "is_bidirectional" in fields and fields["is_bidirectional"] is not None:
        row.is_bidirectional = 1 if fields["is_bidirectional"] else 0
    row.updated_at = utc_now()
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(CODE_PARAM_INVALID, "同类型关系已存在") from exc
    return row


def delete_faction_relation(session: Session, relation_id: int) -> dict[str, Any]:
    row = require_faction_relation(session, relation_id)
    row.is_deleted = 1
    row.deleted_at = utc_now()
    row.updated_at = row.deleted_at
    session.flush()
    return {"id": relation_id, "deleted": True}


def search_factions(session: Session, project_id: int) -> list[tuple[int, str]]:
    """轻量查询（供组织卡下拉用）。"""
    rows = session.execute(
        select(Faction.id, Faction.name)
        .where(Faction.project_id == project_id, Faction.is_deleted == 0)
        .order_by(Faction.order_index, Faction.id)
    ).all()
    return [(int(fid), name) for fid, name in rows]


__all__ = [
    "create_faction",
    "create_faction_relation",
    "delete_faction",
    "delete_faction_relation",
    "list_faction_relations",
    "list_factions",
    "require_faction",
    "require_faction_relation",
    "restore_faction",
    "serialize_faction",
    "serialize_faction_relation",
    "update_faction",
    "update_faction_relation",
]
