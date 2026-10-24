"""角色关系业务逻辑（V2.0 / FR-8.12~8.15）。

对应接口 **#65~#67**。要点：

    · 20 类固定类型 + ``custom_label``；默认方向按类型带出，逐条可覆盖
    · 生效章区间（可空 = 一直有效），区间倒置直接 1001
    · 唯一性：同一对角色 + 同类型 + 同标签只允许一条活跃关系（DB 部分唯一索引）
    · 删除是软删，删掉后可重建同一条（否则会「删了加不回来」）
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Character, CharacterRelation
from ..schemas import CODE_DELETED, CODE_NOT_FOUND, CODE_PARAM_INVALID, ApiError
from ..timeutil import iso, utc_now
from . import character_service
from .character_meta import (
    RELATION_DEFAULT_BIDIRECTIONAL,
    RELATION_LABELS,
    RELATION_TYPES,
)
from .organization_service import validate_chapter_range

MAX_DESCRIPTION = 500
MAX_CUSTOM_LABEL = 30


def _clean_relation_type(value: Any) -> str:
    kind = str(value or "").strip()
    if kind not in RELATION_TYPES:
        raise ApiError(
            CODE_PARAM_INVALID, f"关系类型必须是 {'/'.join(RELATION_TYPES)} 之一"
        )
    return kind


def _clean_custom_label(value: Any) -> str:
    """空串而非 None：NULL 不参与唯一比较（自审 B1）。"""
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > MAX_CUSTOM_LABEL:
        raise ApiError(
            CODE_PARAM_INVALID, f"自定义标签不能超过 {MAX_CUSTOM_LABEL} 个字符"
        )
    return text


def _clean_description(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > MAX_DESCRIPTION:
        raise ApiError(CODE_PARAM_INVALID, f"描述不能超过 {MAX_DESCRIPTION} 个字符")
    return text


def require_character_relation(session: Session, relation_id: int) -> CharacterRelation:
    row = session.get(CharacterRelation, relation_id)
    if row is None:
        raise ApiError(CODE_NOT_FOUND, "角色关系不存在")
    if row.is_deleted:
        raise ApiError(CODE_DELETED, "角色关系已删除")
    return row


def serialize_relation(
    row: CharacterRelation, names: dict[int, str] | None = None
) -> dict[str, Any]:
    lookup = names or {}
    return {
        "id": row.id,
        "project_id": row.project_id,
        "from_id": row.from_id,
        "to_id": row.to_id,
        "from_name": lookup.get(int(row.from_id)),
        "to_name": lookup.get(int(row.to_id)),
        "relation_type": row.relation_type,
        "relation_label": RELATION_LABELS.get(row.relation_type, row.relation_type),
        "custom_label": row.custom_label or None,
        "description": row.description,
        "is_bidirectional": bool(row.is_bidirectional),
        "is_secret": bool(row.is_secret),
        "from_chapter_id": row.from_chapter_id,
        "to_chapter_id": row.to_chapter_id,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def _name_map(session: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = session.execute(
        select(Character.id, Character.name).where(Character.id.in_(ids))
    ).all()
    return {int(cid): name for cid, name in rows}


def list_character_relations(
    session: Session, character_id: int, *, include_expired: bool = True
) -> dict[str, Any]:
    """§6.2 #67：某角色的关系（小面板用，含失效关系标记）。"""
    character_service.require_character(session, character_id)
    statement = select(CharacterRelation).where(
        CharacterRelation.is_deleted == 0,
        or_(
            CharacterRelation.from_id == character_id,
            CharacterRelation.to_id == character_id,
        ),
    )
    rows = session.execute(statement.order_by(CharacterRelation.id)).scalars().all()
    other_ids = {
        int(row.to_id) if int(row.from_id) == character_id else int(row.from_id)
        for row in rows
    }
    names = _name_map(session, other_ids)
    items = []
    for row in rows:
        outgoing = int(row.from_id) == character_id
        item = serialize_relation(row, names)
        item["outgoing"] = outgoing
        item["other_id"] = int(row.to_id) if outgoing else int(row.from_id)
        item["other_name"] = names.get(item["other_id"])
        item["active"] = row.to_chapter_id is None
        if not include_expired and not item["active"]:
            continue
        items.append(item)
    return {"character_id": character_id, "items": items, "total": len(items)}


def create_character_relation(
    session: Session,
    from_id: int,
    *,
    to_id: int,
    relation_type: str = "other",
    custom_label: Any = None,
    description: Any = None,
    is_bidirectional: bool | None = None,
    is_secret: bool = False,
    from_chapter_id: int | None = None,
    to_chapter_id: int | None = None,
) -> CharacterRelation:
    """§6.2 #65：新建角色关系。"""
    source = character_service.require_character(session, from_id)
    target = session.get(Character, int(to_id))
    if target is None or target.is_deleted:
        raise ApiError(CODE_NOT_FOUND, "对方角色不存在")
    if int(to_id) == int(from_id):
        raise ApiError(CODE_PARAM_INVALID, "角色不能和自己建立关系")
    if target.project_id != source.project_id:
        raise ApiError(CODE_PARAM_INVALID, "两个角色必须属于同一本书")

    kind = _clean_relation_type(relation_type)
    label = _clean_custom_label(custom_label)
    duplicate = session.execute(
        select(CharacterRelation.id).where(
            CharacterRelation.from_id == int(from_id),
            CharacterRelation.to_id == int(to_id),
            CharacterRelation.relation_type == kind,
            CharacterRelation.custom_label == label,
            CharacterRelation.is_deleted == 0,
        )
    ).scalar()
    if duplicate is not None:
        raise ApiError(
            CODE_PARAM_INVALID,
            "这两个角色之间已有同类型同标签的关系；可改自定义标签或先删除旧关系",
        )
    validate_chapter_range(
        session,
        source.project_id,
        int(from_chapter_id) if from_chapter_id is not None else None,
        int(to_chapter_id) if to_chapter_id is not None else None,
    )
    bidirectional = (
        bool(RELATION_DEFAULT_BIDIRECTIONAL[kind])
        if is_bidirectional is None
        else bool(is_bidirectional)
    )

    now = utc_now()
    row = CharacterRelation(
        project_id=source.project_id,
        from_id=int(from_id),
        to_id=int(to_id),
        relation_type=kind,
        custom_label=label,
        description=_clean_description(description),
        is_bidirectional=1 if bidirectional else 0,
        is_secret=1 if is_secret else 0,
        from_chapter_id=(int(from_chapter_id) if from_chapter_id is not None else None),
        to_chapter_id=int(to_chapter_id) if to_chapter_id is not None else None,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(
            CODE_PARAM_INVALID,
            "这两个角色之间已有同类型同标签的关系；可改自定义标签或先删除旧关系",
        ) from exc
    return row


def update_character_relation(
    session: Session, relation_id: int, **fields: Any
) -> CharacterRelation:
    """§6.2 #66（PATCH）。"""
    row = require_character_relation(session, relation_id)
    new_type = row.relation_type
    new_label = row.custom_label
    if fields.get("relation_type") is not None:
        new_type = _clean_relation_type(fields["relation_type"])
    if fields.get("custom_label") is not None:
        new_label = _clean_custom_label(fields["custom_label"])
    if new_type != row.relation_type or new_label != row.custom_label:
        duplicate = session.execute(
            select(CharacterRelation.id).where(
                CharacterRelation.from_id == row.from_id,
                CharacterRelation.to_id == row.to_id,
                CharacterRelation.relation_type == new_type,
                CharacterRelation.custom_label == new_label,
                CharacterRelation.is_deleted == 0,
                CharacterRelation.id != relation_id,
            )
        ).scalar()
        if duplicate is not None:
            raise ApiError(CODE_PARAM_INVALID, "关系与现有记录冲突")
    if fields.get("relation_type") is not None:
        row.relation_type = new_type
        if fields.get("is_bidirectional") is None:
            row.is_bidirectional = RELATION_DEFAULT_BIDIRECTIONAL[new_type]
    if fields.get("custom_label") is not None:
        row.custom_label = new_label
    if "description" in fields:
        row.description = _clean_description(fields["description"])
    if fields.get("is_bidirectional") is not None:
        row.is_bidirectional = 1 if fields["is_bidirectional"] else 0
    if fields.get("is_secret") is not None:
        row.is_secret = 1 if fields["is_secret"] else 0
    if "from_chapter_id" in fields or "to_chapter_id" in fields:
        from_id = fields.get("from_chapter_id", row.from_chapter_id)
        to_id = fields.get("to_chapter_id", row.to_chapter_id)
        validate_chapter_range(
            session,
            row.project_id,
            int(from_id) if from_id is not None else None,
            int(to_id) if to_id is not None else None,
        )
        row.from_chapter_id = int(from_id) if from_id is not None else None
        row.to_chapter_id = int(to_id) if to_id is not None else None
    row.updated_at = utc_now()
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(CODE_PARAM_INVALID, "关系与现有记录冲突") from exc
    return row


def delete_character_relation(session: Session, relation_id: int) -> dict[str, Any]:
    """§6.2 #66（DELETE）：软删，之后可重建同一条。"""
    row = require_character_relation(session, relation_id)
    row.is_deleted = 1
    row.deleted_at = utc_now()
    row.updated_at = row.deleted_at
    session.flush()
    return {"id": relation_id, "deleted": True}
