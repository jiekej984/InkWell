"""角色业务逻辑（V2.0 / FR-8.1~8.6、8.23、8.24）。

对应接口 **#55~#63**（列表 / 新建 / 详情 / PATCH / 删除 / 别名 / 自定义字段 / 立绘）。

约定：
    · 软删除：角色与别名同事务标记；成员与关系保留（恢复后仍在）
    · 别名唯一性 = **项目内**（DB 部分唯一索引）+ 「与别的角色姓名冲突」应用层校验
    · ``force`` 只能跳过「与姓名冲突」，跳不过真正的别名占用（那是数据损坏）
    · 文本字段一律纯文本（不走 Quill / ``innerHTML``），前端用 ``textContent`` 渲染
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    Character,
    CharacterAlias,
    CharacterField,
    CharacterRelation,
    Organization,
    OrgMember,
    active,
)
from ..schemas import CODE_DELETED, CODE_NOT_FOUND, CODE_PARAM_INVALID, ApiError
from ..timeutil import iso, utc_now
from . import project_service
from .character_meta import (
    FIELD_TYPE_LABELS,
    FIELD_TYPES,
    RELATION_LABELS,
    ROLE_LABELS,
    ROLES,
    SORT_LABELS,
    SORTS,
    STATUS_LABELS,
    STATUSES,
)

MAX_NAME_LENGTH = 100
MAX_ALIAS_LENGTH = 50
MAX_ALIASES = 30
MAX_FIELD_KEY = 50
MAX_TAGS = 20
MAX_TAG_LENGTH = 30
MAX_TEXT = 2000
MAX_LONGTEXT = 20000
ORDER_STEP = 1000
MAX_PAGE_SIZE = 200
TEXT_FIELDS = (
    "gender",
    "age",
    "height",
    "appearance",
    "personality",
    "background",
    "abilities",
    "catchphrase",
    "motivation",
    "note",
)


# --------------------------------------------------------------------------
# 校验小工具
# --------------------------------------------------------------------------


def _clean_name(name: str | None) -> str:
    value = (name or "").strip()
    if not value:
        raise ApiError(CODE_PARAM_INVALID, "角色姓名不能为空")
    if len(value) > MAX_NAME_LENGTH:
        raise ApiError(CODE_PARAM_INVALID, f"角色姓名不能超过 {MAX_NAME_LENGTH} 个字符")
    return value


def _clean_enum(value: str | None, allowed: tuple[str, ...], label: str) -> str:
    candidate = (value or "").strip()
    if candidate not in allowed:
        raise ApiError(CODE_PARAM_INVALID, f"{label}必须是 {'/'.join(allowed)} 之一")
    return candidate


def _clean_text(value: Any, limit: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > limit:
        raise ApiError(CODE_PARAM_INVALID, f"文本不能超过 {limit} 个字符")
    return text


def _clean_order(value: int | None) -> int:
    if value is None:
        raise ApiError(CODE_PARAM_INVALID, "排序值不能为空")
    if int(value) < 0:
        raise ApiError(CODE_PARAM_INVALID, "排序值不能为负数")
    return int(value)


def _clean_tags(value: Any) -> str | None:
    """标签存 JSON 数组字符串；最多 20 个、单个 ≤30 字。"""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError as exc:
            raise ApiError(CODE_PARAM_INVALID, "标签必须是字符串数组") from exc
        value = parsed
    if not isinstance(value, list):
        raise ApiError(CODE_PARAM_INVALID, "标签必须是字符串数组")
    cleaned: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        if len(text) > MAX_TAG_LENGTH:
            raise ApiError(
                CODE_PARAM_INVALID, f"单个标签不能超过 {MAX_TAG_LENGTH} 个字符"
            )
        if text not in cleaned:
            cleaned.append(text)
    if len(cleaned) > MAX_TAGS:
        raise ApiError(CODE_PARAM_INVALID, f"标签最多 {MAX_TAGS} 个")
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


def tags_of(character: Character) -> list[str]:
    if not character.tags:
        return []
    try:
        parsed = json.loads(character.tags)
    except ValueError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------


def require_character(session: Session, character_id: int) -> Character:
    """按 id 取活跃角色；不存在 → 2001，已删除 → 2002。"""
    character = session.get(Character, character_id)
    if character is None:
        raise ApiError(CODE_NOT_FOUND, "角色不存在")
    if character.is_deleted:
        raise ApiError(CODE_DELETED, "角色已删除，可在回收站恢复")
    return character


def serialize_character(character: Character) -> dict[str, Any]:
    """角色核心字段（不含别名/字段/关系，列表与详情共用）。"""
    return {
        "id": character.id,
        "project_id": character.project_id,
        "name": character.name,
        "role": character.role,
        "role_label": ROLE_LABELS.get(character.role, character.role),
        "gender": character.gender,
        "age": character.age,
        "height": character.height,
        "appearance": character.appearance,
        "personality": character.personality,
        "background": character.background,
        "abilities": character.abilities,
        "catchphrase": character.catchphrase,
        "motivation": character.motivation,
        "note": character.note,
        "status": character.status,
        "status_label": STATUS_LABELS.get(character.status, character.status),
        "avatar_path": character.avatar_path,
        "tags": tags_of(character),
        "source": character.source,
        "order_index": character.order_index,
        "created_at": iso(character.created_at),
        "updated_at": iso(character.updated_at),
    }


def _org_subtree(session: Session, project_id: int, root_id: int) -> list[int]:
    """组织子树 id（含自身）；查询参数用，委托给组织服务。"""
    from . import organization_service

    return organization_service.collect_subtree_ids(session, project_id, root_id)


def _paginate(page: int | None, page_size: int | None) -> tuple[int, int]:
    current = 1 if page is None else int(page)
    size = 50 if page_size is None else int(page_size)
    if current < 1:
        raise ApiError(CODE_PARAM_INVALID, "页码必须从 1 开始")
    if size < 1 or size > MAX_PAGE_SIZE:
        raise ApiError(CODE_PARAM_INVALID, f"每页条数必须在 1~{MAX_PAGE_SIZE} 之间")
    return current, size


def list_characters(
    session: Session,
    project_id: int,
    *,
    keyword: str | None = None,
    role: str | None = None,
    org_id: int | None = None,
    status: str | None = None,
    sort: str = "order",
    page: int | None = None,
    page_size: int | None = None,
) -> dict[str, Any]:
    """§6.2 #55：角色列表（搜索 / 定位 / 组织 / 状态 / 排序 / 分页）。"""
    project_service.require_project(session, project_id)
    statement = active(Character).where(Character.project_id == project_id)

    if keyword:
        text = keyword.strip()
        if text:
            # LIKE 通配符要转义：搜「%」「_」时按字面匹配，而不是命中全部角色
            pattern = (
                "%"
                + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%"
            )
            alias_ids = select(CharacterAlias.character_id).where(
                CharacterAlias.project_id == project_id,
                CharacterAlias.is_deleted == 0,
                CharacterAlias.alias.like(pattern, escape="\\"),
            )
            statement = statement.where(
                or_(
                    Character.name.like(pattern, escape="\\"),
                    Character.id.in_(alias_ids),
                )
            )
    if role:
        statement = statement.where(Character.role == _clean_enum(role, ROLES, "定位"))
    if status:
        statement = statement.where(
            Character.status == _clean_enum(status, STATUSES, "状态")
        )
    if org_id is not None:
        from . import organization_service

        organization_service.require_organization(session, int(org_id))
        org_ids = _org_subtree(session, project_id, int(org_id))
        member_ids = select(OrgMember.character_id).where(
            OrgMember.org_id.in_(org_ids), OrgMember.is_deleted == 0
        )
        statement = statement.where(Character.id.in_(member_ids))

    current, size = _paginate(page, page_size)
    sort_key = (sort or "order").strip()
    if sort_key not in SORTS:
        raise ApiError(CODE_PARAM_INVALID, f"排序必须是 {'/'.join(SORTS)} 之一")
    order_by = {
        "order": (Character.order_index, Character.id),
        "created": (Character.created_at.desc(), Character.id.desc()),
        "name": (Character.name, Character.id),
    }[sort_key]

    total = int(
        session.execute(
            select(func.count()).select_from(statement.subquery())
        ).scalar_one()
    )
    rows = (
        session.execute(
            statement.order_by(*order_by).limit(size).offset((current - 1) * size)
        )
        .scalars()
        .all()
    )
    return {
        "project_id": project_id,
        "items": [serialize_character(row) for row in rows],
        "total": total,
        "page": current,
        "page_size": size,
        "sorts": [{"value": value, "label": SORT_LABELS[value]} for value in SORTS],
    }


def _alias_list(session: Session, character_id: int) -> list[str]:
    rows = (
        session.execute(
            select(CharacterAlias.alias)
            .where(
                CharacterAlias.character_id == character_id,
                CharacterAlias.is_deleted == 0,
            )
            .order_by(CharacterAlias.id)
        )
        .scalars()
        .all()
    )
    return list(rows)


def _field_list(session: Session, character_id: int) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            select(CharacterField)
            .where(CharacterField.character_id == character_id)
            .order_by(CharacterField.order_index, CharacterField.id)
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "key": row.key,
            "value": row.value,
            "field_type": row.field_type,
            "field_type_label": FIELD_TYPE_LABELS.get(row.field_type, row.field_type),
            "order_index": row.order_index,
        }
        for row in rows
    ]


def _relation_list(session: Session, character_id: int) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            select(CharacterRelation)
            .where(
                CharacterRelation.is_deleted == 0,
                or_(
                    CharacterRelation.from_id == character_id,
                    CharacterRelation.to_id == character_id,
                ),
            )
            .order_by(CharacterRelation.id)
        )
        .scalars()
        .all()
    )
    other_ids = {
        row.to_id if row.from_id == character_id else row.from_id for row in rows
    }
    names = (
        {
            cid: name
            for cid, name in session.execute(
                select(Character.id, Character.name).where(Character.id.in_(other_ids))
            ).all()
        }
        if other_ids
        else {}
    )
    result = []
    for row in rows:
        outgoing = row.from_id == character_id
        other_id = row.to_id if outgoing else row.from_id
        result.append(
            {
                "id": row.id,
                "from_id": row.from_id,
                "to_id": row.to_id,
                "outgoing": outgoing,
                "other_id": other_id,
                "other_name": names.get(other_id),
                "relation_type": row.relation_type,
                "relation_label": RELATION_LABELS.get(
                    row.relation_type, row.relation_type
                ),
                "custom_label": row.custom_label or None,
                "description": row.description,
                "is_bidirectional": bool(row.is_bidirectional),
                "is_secret": bool(row.is_secret),
                "from_chapter_id": row.from_chapter_id,
                "to_chapter_id": row.to_chapter_id,
            }
        )
    return result


def _membership_list(session: Session, character_id: int) -> list[dict[str, Any]]:
    rows = session.execute(
        select(OrgMember, Organization)
        .join(Organization, Organization.id == OrgMember.org_id)
        .where(
            OrgMember.character_id == character_id,
            OrgMember.is_deleted == 0,
            Organization.is_deleted == 0,
        )
        .order_by(OrgMember.is_primary.desc(), OrgMember.id)
    ).all()
    return [
        {
            "id": member.id,
            "org_id": org.id,
            "org_name": org.name,
            "position": member.position,
            "is_primary": bool(member.is_primary),
            "is_secret": bool(member.is_secret),
            "from_chapter_id": member.from_chapter_id,
            "to_chapter_id": member.to_chapter_id,
        }
        for member, org in rows
    ]


def get_character_detail(session: Session, character_id: int) -> dict[str, Any]:
    """§6.2 #57：详情一次返回别名 / 自定义字段 / 关系 / 组织身份。"""
    character = require_character(session, character_id)
    return {
        **serialize_character(character),
        "aliases": _alias_list(session, character_id),
        "fields": _field_list(session, character_id),
        "relations": _relation_list(session, character_id),
        "memberships": _membership_list(session, character_id),
    }


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------


def _next_order(session: Session, project_id: int) -> int:
    max_index = session.execute(
        select(func.max(Character.order_index)).where(
            Character.project_id == project_id, Character.is_deleted == 0
        )
    ).scalar()
    return (int(max_index) + ORDER_STEP) if max_index is not None else ORDER_STEP


def _apply_text_fields(character: Character, fields: dict[str, Any]) -> None:
    for key in TEXT_FIELDS:
        if key in fields:
            character.__setattr__(key, _clean_text(fields[key]))


def create_character(session: Session, project_id: int, **fields: Any) -> Character:
    """§6.2 #56：新建角色。"""
    project_service.require_project(session, project_id)
    now = utc_now()
    role = _clean_enum(fields.get("role") or "supporting", ROLES, "定位")
    status = _clean_enum(fields.get("status") or "alive", STATUSES, "状态")
    character = Character(
        project_id=project_id,
        name=_clean_name(fields.get("name")),
        role=role,
        status=status,
        tags=_clean_tags(fields.get("tags")),
        order_index=(
            _clean_order(fields["order_index"])
            if fields.get("order_index") is not None
            else _next_order(session, project_id)
        ),
        source="manual",
        created_at=now,
        updated_at=now,
    )
    _apply_text_fields(character, fields)
    if fields.get("avatar_path") is not None:
        character.avatar_path = str(fields["avatar_path"])
    session.add(character)
    session.flush()
    return character


def update_character(session: Session, character_id: int, **fields: Any) -> Character:
    """§6.2 #58：部分更新（字段级保存）。"""
    character = require_character(session, character_id)
    if fields.get("name") is not None:
        character.name = _clean_name(fields["name"])
    if fields.get("role") is not None:
        character.role = _clean_enum(fields["role"], ROLES, "定位")
    if fields.get("status") is not None:
        character.status = _clean_enum(fields["status"], STATUSES, "状态")
    if "tags" in fields:
        character.tags = _clean_tags(fields["tags"])
    if fields.get("order_index") is not None:
        character.order_index = _clean_order(fields["order_index"])
    if "avatar_path" in fields:
        value = fields["avatar_path"]
        character.avatar_path = str(value) if value else None
    _apply_text_fields(character, fields)
    character.updated_at = utc_now()
    session.flush()
    return character


def delete_character(
    session: Session, character_id: int, *, force: bool = False
) -> dict[str, Any]:
    """§6.2 #59：软删除（默认）或彻底删除（``force``）。

    软删：同事务把别名置 ``is_deleted=1``，让出唯一键；关系与成员保留。
    彻底删除：物理删除，DB 级联别名 / 字段 / 关系 / 成员。
    """
    character = require_character(session, character_id)
    if force:
        session.delete(character)
        session.flush()
        return {"id": character_id, "deleted": True, "force": True}

    now = utc_now()
    character.is_deleted = 1
    character.deleted_at = now
    character.updated_at = now
    session.execute(
        CharacterAlias.__table__.update()
        .where(
            CharacterAlias.character_id == character_id,
            CharacterAlias.is_deleted == 0,
        )
        .values(is_deleted=1)
    )
    session.flush()
    return {"id": character_id, "deleted": True, "force": False}


def restore_character(session: Session, character_id: int) -> dict[str, Any]:
    """回收站恢复：角色 + 别名；别名被占用则跳过并返回清单。"""
    character = session.get(Character, character_id)
    if character is None:
        raise ApiError(CODE_NOT_FOUND, "角色不存在")
    if not character.is_deleted:
        raise ApiError(CODE_PARAM_INVALID, "角色未被删除，无法恢复")

    character.is_deleted = 0
    character.deleted_at = None
    character.updated_at = utc_now()

    inactive = (
        session.execute(
            select(CharacterAlias).where(
                CharacterAlias.character_id == character_id,
                CharacterAlias.is_deleted == 1,
            )
        )
        .scalars()
        .all()
    )
    taken = {
        alias
        for (alias,) in session.execute(
            select(CharacterAlias.alias).where(
                CharacterAlias.project_id == character.project_id,
                CharacterAlias.is_deleted == 0,
            )
        ).all()
    }
    restored: list[str] = []
    skipped: list[str] = []
    for row in inactive:
        if row.alias in taken:
            skipped.append(row.alias)
            continue
        row.is_deleted = 0
        taken.add(row.alias)
        restored.append(row.alias)
    session.flush()
    return {
        "id": character_id,
        "restored": True,
        "aliases_restored": restored,
        "aliases_skipped": skipped,
    }


# --------------------------------------------------------------------------
# 别名
# --------------------------------------------------------------------------


def _clean_aliases(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ApiError(CODE_PARAM_INVALID, "别名必须是字符串数组")
    cleaned: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text or text == name:
            continue
        if len(text) > MAX_ALIAS_LENGTH:
            raise ApiError(
                CODE_PARAM_INVALID, f"别名不能超过 {MAX_ALIAS_LENGTH} 个字符"
            )
        if text not in cleaned:
            cleaned.append(text)
    if len(cleaned) > MAX_ALIASES:
        raise ApiError(CODE_PARAM_INVALID, f"别名最多 {MAX_ALIASES} 个")
    return cleaned


def set_aliases(
    session: Session,
    character_id: int,
    aliases: Any,
    *,
    force: bool = False,
) -> list[str]:
    """§6.2 #60：整体替换别名。

    冲突分两类：
        · 与**别的角色姓名**相同 → 可 ``force`` 覆盖（提示后仍要加）
        · 与**别的角色别名**相同 → 一律拒绝，那是真的重复占用
    """
    character = require_character(session, character_id)
    cleaned = _clean_aliases(aliases, character.name)

    if cleaned:
        name_conflicts = (
            session.execute(
                select(Character.name).where(
                    Character.project_id == character.project_id,
                    Character.is_deleted == 0,
                    Character.id != character_id,
                    Character.name.in_(cleaned),
                )
            )
            .scalars()
            .all()
        )
        if name_conflicts and not force:
            raise ApiError(
                CODE_PARAM_INVALID,
                "别名与已有角色姓名冲突："
                + "、".join(name_conflicts)
                + "（确认仍要添加可传 force=true）",
            )

        alias_conflicts = session.execute(
            select(CharacterAlias.alias, Character.name)
            .join(Character, Character.id == CharacterAlias.character_id)
            .where(
                CharacterAlias.project_id == character.project_id,
                CharacterAlias.is_deleted == 0,
                CharacterAlias.character_id != character_id,
                CharacterAlias.alias.in_(cleaned),
            )
        ).all()
        if alias_conflicts:
            detail = "、".join(
                f"{alias}（{owner}）" for alias, owner in alias_conflicts
            )
            raise ApiError(CODE_PARAM_INVALID, f"别名已被占用：{detail}")

    session.execute(
        CharacterAlias.__table__.update()
        .where(
            CharacterAlias.character_id == character_id,
            CharacterAlias.is_deleted == 0,
        )
        .values(is_deleted=1)
    )
    session.flush()

    now = utc_now()
    for alias in cleaned:
        session.add(
            CharacterAlias(
                project_id=character.project_id,
                character_id=character_id,
                alias=alias,
                created_at=now,
            )
        )
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(CODE_PARAM_INVALID, "别名冲突，请刷新后重试") from exc
    character.updated_at = now
    return cleaned


# --------------------------------------------------------------------------
# 自定义字段
# --------------------------------------------------------------------------


def require_field(session: Session, field_id: int) -> CharacterField:
    field = session.get(CharacterField, field_id)
    if field is None:
        raise ApiError(CODE_NOT_FOUND, "自定义字段不存在")
    return field


def _clean_field_value(field_type: str, value: Any) -> str | None:
    text = _clean_text(value, MAX_LONGTEXT)
    if text is None:
        return None
    if field_type == "number":
        try:
            float(text)
        except ValueError as exc:
            raise ApiError(CODE_PARAM_INVALID, "该字段必须是数字") from exc
    if field_type == "date":
        from ..timeutil import parse_iso

        if parse_iso(text) is None:
            raise ApiError(CODE_PARAM_INVALID, "该字段必须是日期（YYYY-MM-DD）")
    if field_type in ("text", "date") and len(text) > MAX_TEXT:
        raise ApiError(CODE_PARAM_INVALID, f"该字段不能超过 {MAX_TEXT} 个字符")
    return text


def add_field(
    session: Session,
    character_id: int,
    *,
    key: str,
    value: Any = None,
    field_type: str = "text",
    order_index: int | None = None,
) -> CharacterField:
    """§6.2 #61（POST）：新增自定义字段。"""
    require_character(session, character_id)
    clean_key = _clean_text(key, MAX_FIELD_KEY)
    if not clean_key:
        raise ApiError(CODE_PARAM_INVALID, "字段名不能为空")
    kind = _clean_enum(field_type or "text", FIELD_TYPES, "字段类型")

    exists = session.execute(
        select(CharacterField.id).where(
            CharacterField.character_id == character_id,
            CharacterField.key == clean_key,
        )
    ).scalar()
    if exists is not None:
        raise ApiError(CODE_PARAM_INVALID, f"字段「{clean_key}」已存在")

    now = utc_now()
    index = (
        _clean_order(order_index)
        if order_index is not None
        else _next_field_order(session, character_id)
    )
    field = CharacterField(
        character_id=character_id,
        key=clean_key,
        value=_clean_field_value(kind, value),
        field_type=kind,
        order_index=index,
        created_at=now,
        updated_at=now,
    )
    session.add(field)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(CODE_PARAM_INVALID, f"字段「{clean_key}」已存在") from exc
    return field


def _next_field_order(session: Session, character_id: int) -> int:
    max_index = session.execute(
        select(func.max(CharacterField.order_index)).where(
            CharacterField.character_id == character_id
        )
    ).scalar()
    return (int(max_index) + ORDER_STEP) if max_index is not None else ORDER_STEP


def update_field(session: Session, field_id: int, **fields: Any) -> CharacterField:
    """§6.2 #62（PATCH）：改值 / 类型 / 排序 / 键名。"""
    field = require_field(session, field_id)
    kind = field.field_type
    if fields.get("field_type") is not None:
        kind = _clean_enum(fields["field_type"], FIELD_TYPES, "字段类型")
        field.field_type = kind
        # 改类型但不改值时也要校验旧值：text「十六七岁」不能直接变成 number
        if "value" not in fields and field.value is not None:
            _clean_field_value(kind, field.value)
    if fields.get("key") is not None:
        clean_key = _clean_text(fields["key"], MAX_FIELD_KEY)
        if not clean_key:
            raise ApiError(CODE_PARAM_INVALID, "字段名不能为空")
        duplicate = session.execute(
            select(CharacterField.id).where(
                CharacterField.character_id == field.character_id,
                CharacterField.key == clean_key,
                CharacterField.id != field_id,
            )
        ).scalar()
        if duplicate is not None:
            raise ApiError(CODE_PARAM_INVALID, f"字段「{clean_key}」已存在")
        field.key = clean_key
    if "value" in fields:
        field.value = _clean_field_value(kind, fields["value"])
    if fields.get("order_index") is not None:
        field.order_index = _clean_order(fields["order_index"])
    field.updated_at = utc_now()
    session.flush()
    return field


def delete_field(session: Session, field_id: int) -> dict[str, Any]:
    """§6.2 #62（DELETE）：物理删除（字段无软删除）。"""
    field = require_field(session, field_id)
    session.delete(field)
    session.flush()
    return {"id": field_id, "deleted": True}
