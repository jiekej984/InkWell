"""组织与成员业务逻辑（V2.0 / FR-8.8~8.10）。

对应接口 **#73~#79**。本模块的边界最多，逐条对应报告 §5.3：

    · 成环：改父级时向上遍历祖先，命中自己 → 1001
    · 软删**递归**：父组织删除时同事务标记全部子组织与成员，避免孤儿节点
    · 删除三选一：``cascade``（一并删）/ ``promote``（子组织与成员上移一级）；
      根组织没有父级可挂 → ``promote`` 直接 1001（C-18）
    · 主组织：每个角色最多一个 ``is_primary``；主组织被删只降级、不自动改选（C-17）
    · 立场继承：组织未设 ``faction_id`` 时向上取最近祖先的立场
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    Chapter,
    Character,
    Document,
    Organization,
    OrgMember,
    OrgRelation,
    Volume,
    active,
)
from ..schemas import CODE_DELETED, CODE_NOT_FOUND, CODE_PARAM_INVALID, ApiError
from ..timeutil import iso, utc_now
from . import project_service
from .character_meta import (
    ORG_KIND_LABELS,
    ORG_KINDS,
    ORG_RELATION_LABELS,
    ORG_RELATION_TYPES,
)

MAX_NAME_LENGTH = 100
MAX_POSITION = 50
MAX_DESCRIPTION = 500
ORDER_STEP = 1000
DELETE_STRATEGIES = ("cascade", "promote")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------


def _clean_name(name: str | None) -> str:
    value = (name or "").strip()
    if not value:
        raise ApiError(CODE_PARAM_INVALID, "组织名称不能为空")
    if len(value) > MAX_NAME_LENGTH:
        raise ApiError(CODE_PARAM_INVALID, f"组织名称不能超过 {MAX_NAME_LENGTH} 个字符")
    return value


def _clean_enum(value: Any, allowed: tuple[str, ...], label: str) -> str:
    candidate = str(value or "").strip()
    if candidate not in allowed:
        raise ApiError(CODE_PARAM_INVALID, f"{label}必须是 {'/'.join(allowed)} 之一")
    return candidate


def _clean_text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > limit:
        raise ApiError(CODE_PARAM_INVALID, f"文本不能超过 {limit} 个字符")
    return text


def _clean_color(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not _COLOR_RE.match(text):
        raise ApiError(CODE_PARAM_INVALID, "颜色必须是 #RRGGBB 格式")
    return text.lower()


def _clean_order(value: int | None) -> int:
    if value is None:
        raise ApiError(CODE_PARAM_INVALID, "排序值不能为空")
    if int(value) < 0:
        raise ApiError(CODE_PARAM_INVALID, "排序值不能为负数")
    return int(value)


def _clean_bool(value: Any) -> int:
    return 1 if value else 0


# --------------------------------------------------------------------------
# 查询与序列化
# --------------------------------------------------------------------------


def require_organization(session: Session, org_id: int) -> Organization:
    org = session.get(Organization, org_id)
    if org is None:
        raise ApiError(CODE_NOT_FOUND, "组织不存在")
    if org.is_deleted:
        raise ApiError(CODE_DELETED, "组织已删除，可在回收站恢复")
    return org


def _active_org_map(session: Session, project_id: int) -> dict[int, Organization]:
    rows = (
        session.execute(
            active(Organization).where(Organization.project_id == project_id)
        )
        .scalars()
        .all()
    )
    return {int(row.id): row for row in rows}


def collect_subtree_ids(session: Session, project_id: int, root_id: int) -> list[int]:
    """活跃组织子树（含自身）；根不存在于该项目时返回空列表。"""
    rows = session.execute(
        select(Organization.id, Organization.parent_id).where(
            Organization.project_id == project_id,
            Organization.is_deleted == 0,
        )
    ).all()
    children: dict[int, list[int]] = defaultdict(list)
    known: set[int] = set()
    for oid, parent_id in rows:
        known.add(int(oid))
        if parent_id is not None:
            children[int(parent_id)].append(int(oid))
    root = int(root_id)
    if root not in known:
        return []
    result: list[int] = []
    stack = [root]
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.append(current)
        stack.extend(children.get(current, []))
    return result


def effective_faction_id(
    org: Organization, by_id: dict[int, Organization]
) -> int | None:
    """立场继承：自身没有就向上取最近祖先的立场（防环保护 50 层）。"""
    current: Organization | None = org
    seen: set[int] = set()
    for _ in range(50):
        if current is None or int(current.id) in seen:
            return None
        seen.add(int(current.id))
        if current.faction_id is not None:
            return int(current.faction_id)
        if current.parent_id is None:
            return None
        current = by_id.get(int(current.parent_id))
    return None


def _member_counts(session: Session, org_ids: list[int]) -> dict[int, int]:
    if not org_ids:
        return {}
    rows = session.execute(
        select(OrgMember.org_id, func.count(OrgMember.id))
        .join(Character, Character.id == OrgMember.character_id)
        .where(
            OrgMember.org_id.in_(org_ids),
            OrgMember.is_deleted == 0,
            Character.is_deleted == 0,
        )
        .group_by(OrgMember.org_id)
    ).all()
    return {int(oid): int(count) for oid, count in rows}


def serialize_organization(
    org: Organization,
    *,
    faction_id: int | None = None,
    member_count: int = 0,
    child_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": org.id,
        "project_id": org.project_id,
        "parent_id": org.parent_id,
        "name": org.name,
        "kind": org.kind,
        "kind_label": ORG_KIND_LABELS.get(org.kind, org.kind),
        "faction_id": org.faction_id,
        "effective_faction_id": faction_id,
        "leader_id": org.leader_id,
        "description": org.description,
        "document_id": org.document_id,
        "color": org.color,
        "order_index": org.order_index,
        "member_count": member_count,
        "child_count": child_count,
        "created_at": iso(org.created_at),
        "updated_at": iso(org.updated_at),
    }


def list_organizations(
    session: Session,
    project_id: int,
    *,
    tree: bool = False,
    faction_id: int | None = None,
    org_id: int | None = None,
) -> dict[str, Any]:
    """§6.2 #73：扁平列表或嵌套树（``tree=1``）。"""
    project_service.require_project(session, project_id)
    by_id = _active_org_map(session, project_id)

    selected = list(by_id.values())
    if org_id is not None:
        subtree = set(collect_subtree_ids(session, project_id, int(org_id)))
        selected = [row for row in selected if int(row.id) in subtree]
    if faction_id is not None:
        selected = [
            row
            for row in selected
            if effective_faction_id(row, by_id) == int(faction_id)
        ]

    ids = [int(row.id) for row in selected]
    counts = _member_counts(session, ids)
    child_counts: dict[int, int] = defaultdict(int)
    for row in by_id.values():
        if row.parent_id is not None:
            child_counts[int(row.parent_id)] += 1

    items = [
        serialize_organization(
            row,
            faction_id=effective_faction_id(row, by_id),
            member_count=counts.get(int(row.id), 0),
            child_count=child_counts.get(int(row.id), 0),
        )
        for row in selected
    ]
    items.sort(key=lambda item: (item["order_index"], item["id"]))

    if not tree:
        return {
            "project_id": project_id,
            "items": items,
            "total": len(items),
        }

    nodes = {item["id"]: {**item, "children": []} for item in items}
    roots: list[dict[str, Any]] = []
    for item in items:
        node = nodes[item["id"]]
        parent_id = item["parent_id"]
        if parent_id is not None and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return {"project_id": project_id, "items": roots, "total": len(items)}


def get_organization(session: Session, org_id: int) -> dict[str, Any]:
    """组织详情（含立场继承结果与成员数）。"""
    org = require_organization(session, org_id)
    by_id = _active_org_map(session, org.project_id)
    counts = _member_counts(session, [int(org.id)])
    child_count = int(
        session.execute(
            select(func.count(Organization.id)).where(
                Organization.parent_id == org.id,
                Organization.is_deleted == 0,
            )
        ).scalar_one()
    )
    return serialize_organization(
        org,
        faction_id=effective_faction_id(org, by_id),
        member_count=counts.get(int(org.id), 0),
        child_count=child_count,
    )


# --------------------------------------------------------------------------
# 组织写入
# --------------------------------------------------------------------------


def _validate_faction(
    session: Session, project_id: int, faction_id: int | None
) -> None:
    if faction_id is None:
        return
    from . import faction_service

    faction = faction_service.require_faction(session, int(faction_id))
    if faction.project_id != project_id:
        raise ApiError(CODE_PARAM_INVALID, "立场必须属于同一本书")


def _validate_parent(session: Session, project_id: int, parent_id: int | None) -> None:
    if parent_id is None:
        return
    parent = require_organization(session, int(parent_id))
    if parent.project_id != project_id:
        raise ApiError(CODE_PARAM_INVALID, "父组织必须属于同一本书")


def _validate_leader(session: Session, project_id: int, leader_id: int | None) -> None:
    if leader_id is None:
        return
    leader = session.get(Character, int(leader_id))
    if leader is None or leader.is_deleted:
        raise ApiError(CODE_NOT_FOUND, "首领角色不存在")
    if leader.project_id != project_id:
        raise ApiError(CODE_PARAM_INVALID, "首领必须属于同一本书")


def _validate_document(
    session: Session, project_id: int, document_id: int | None
) -> None:
    if document_id is None:
        return
    document = session.get(Document, int(document_id))
    if document is None or document.is_deleted:
        raise ApiError(CODE_NOT_FOUND, "关联的设定文档不存在")
    if document.project_id != project_id:
        raise ApiError(CODE_PARAM_INVALID, "设定文档必须属于同一本书")


def _assert_no_cycle(
    session: Session, project_id: int, org_id: int, parent_id: int | None
) -> None:
    """改父级防成环：从新父级向上走，命中自己即拒绝。"""
    if parent_id is None:
        return
    if int(parent_id) == int(org_id):
        raise ApiError(CODE_PARAM_INVALID, "不能把组织挂到自己下面")
    by_id = _active_org_map(session, project_id)
    current = by_id.get(int(parent_id))
    seen: set[int] = set()
    while current is not None and int(current.id) not in seen:
        if int(current.id) == int(org_id):
            raise ApiError(CODE_PARAM_INVALID, "不能把组织挂到自己的子孙下")
        seen.add(int(current.id))
        if current.parent_id is None:
            return
        current = by_id.get(int(current.parent_id))


def _next_order(session: Session, project_id: int) -> int:
    max_index = session.execute(
        select(func.max(Organization.order_index)).where(
            Organization.project_id == project_id,
            Organization.is_deleted == 0,
        )
    ).scalar()
    return (int(max_index) + ORDER_STEP) if max_index is not None else ORDER_STEP


def _ensure_name_free(
    session: Session, project_id: int, name: str, *, exclude_id: int | None = None
) -> None:
    """先查重再写：唯一约束只作兜底，正常重名走这里报 1001。"""
    statement = select(Organization.id).where(
        Organization.project_id == project_id,
        Organization.name == name,
        Organization.is_deleted == 0,
    )
    if exclude_id is not None:
        statement = statement.where(Organization.id != exclude_id)
    if session.execute(statement).scalar() is not None:
        raise ApiError(CODE_PARAM_INVALID, f"组织「{name}」已存在")


def create_organization(
    session: Session, project_id: int, *, name: str, **fields: Any
) -> Organization:
    """§6.2 #74：新建组织。"""
    project_service.require_project(session, project_id)
    clean_name = _clean_name(name)
    _ensure_name_free(session, project_id, clean_name)
    parent_id = (
        int(fields["parent_id"]) if fields.get("parent_id") is not None else None
    )
    faction_id = (
        int(fields["faction_id"]) if fields.get("faction_id") is not None else None
    )
    _validate_parent(session, project_id, parent_id)
    _validate_faction(session, project_id, faction_id)
    _validate_leader(
        session,
        project_id,
        int(fields["leader_id"]) if fields.get("leader_id") is not None else None,
    )
    _validate_document(
        session,
        project_id,
        int(fields["document_id"]) if fields.get("document_id") is not None else None,
    )

    now = utc_now()
    org = Organization(
        project_id=project_id,
        faction_id=faction_id,
        parent_id=parent_id,
        name=clean_name,
        kind=_clean_enum(fields.get("kind") or "other", ORG_KINDS, "组织类型"),
        leader_id=(
            int(fields["leader_id"]) if fields.get("leader_id") is not None else None
        ),
        description=_clean_text(fields.get("description"), MAX_DESCRIPTION),
        document_id=(
            int(fields["document_id"])
            if fields.get("document_id") is not None
            else None
        ),
        color=_clean_color(fields.get("color")),
        order_index=(
            _clean_order(fields["order_index"])
            if fields.get("order_index") is not None
            else _next_order(session, project_id)
        ),
        created_at=now,
        updated_at=now,
    )
    session.add(org)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(CODE_PARAM_INVALID, f"组织「{org.name}」已存在") from exc
    return org


def update_organization(session: Session, org_id: int, **fields: Any) -> Organization:
    """§6.2 #75（PATCH）：改父级会校验成环。"""
    org = require_organization(session, org_id)
    project_id = org.project_id

    if fields.get("name") is not None:
        clean_name = _clean_name(fields["name"])
        _ensure_name_free(session, project_id, clean_name, exclude_id=org_id)
        org.name = clean_name
    if fields.get("kind") is not None:
        org.kind = _clean_enum(fields["kind"], ORG_KINDS, "组织类型")
    if "parent_id" in fields:
        parent_id = (
            int(fields["parent_id"]) if fields["parent_id"] is not None else None
        )
        _validate_parent(session, project_id, parent_id)
        _assert_no_cycle(session, project_id, org_id, parent_id)
        org.parent_id = parent_id
    if "faction_id" in fields:
        faction_id = (
            int(fields["faction_id"]) if fields["faction_id"] is not None else None
        )
        _validate_faction(session, project_id, faction_id)
        org.faction_id = faction_id
    if "leader_id" in fields:
        leader_id = (
            int(fields["leader_id"]) if fields["leader_id"] is not None else None
        )
        _validate_leader(session, project_id, leader_id)
        org.leader_id = leader_id
    if "document_id" in fields:
        document_id = (
            int(fields["document_id"]) if fields["document_id"] is not None else None
        )
        _validate_document(session, project_id, document_id)
        org.document_id = document_id
    if "description" in fields:
        org.description = _clean_text(fields["description"], MAX_DESCRIPTION)
    if "color" in fields:
        org.color = _clean_color(fields["color"])
    if fields.get("order_index") is not None:
        org.order_index = _clean_order(fields["order_index"])

    org.updated_at = utc_now()
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(CODE_PARAM_INVALID, "同名组织已存在") from exc
    return org


def delete_organization(
    session: Session, org_id: int, *, strategy: str = "cascade"
) -> dict[str, Any]:
    """§6.2 #75（DELETE）：``cascade`` 一并删 / ``promote`` 上移一级。"""
    org = require_organization(session, org_id)
    mode = (strategy or "cascade").strip()
    if mode not in DELETE_STRATEGIES:
        raise ApiError(
            CODE_PARAM_INVALID, f"删除策略必须是 {'/'.join(DELETE_STRATEGIES)} 之一"
        )

    project_id = org.project_id
    subtree = collect_subtree_ids(session, project_id, org_id)
    member_rows = (
        session.execute(
            select(OrgMember).where(
                OrgMember.org_id.in_(subtree), OrgMember.is_deleted == 0
            )
        )
        .scalars()
        .all()
    )
    child_count = int(
        session.execute(
            select(func.count(Organization.id)).where(
                Organization.parent_id == org.id,
                Organization.is_deleted == 0,
            )
        ).scalar_one()
    )
    # 上移只动「本组织的直属成员」；子树里的成员跟着各自的子组织走
    direct_members = [row for row in member_rows if int(row.org_id) == int(org_id)]

    now = utc_now()
    if mode == "promote":
        if org.parent_id is None:
            raise ApiError(
                CODE_PARAM_INVALID,
                "这是顶层组织，没有上级可挂；请选择「一并删除」或先设一个上级",
            )
        parent_id = int(org.parent_id)
        # 成员上移：与父组织已有身份冲突时整体拒绝，避免静默丢人
        existing = {
            int(cid)
            for (cid,) in session.execute(
                select(OrgMember.character_id).where(
                    OrgMember.org_id == parent_id, OrgMember.is_deleted == 0
                )
            ).all()
        }
        conflicts = [row for row in direct_members if int(row.character_id) in existing]
        if conflicts:
            raise ApiError(
                CODE_PARAM_INVALID,
                f"有 {len(conflicts)} 位成员在上级组织已有身份，请先处理后重试",
            )
        session.execute(
            Organization.__table__.update()
            .where(Organization.parent_id == org.id, Organization.is_deleted == 0)
            .values(parent_id=parent_id)
        )
        session.execute(
            OrgMember.__table__.update()
            .where(OrgMember.org_id == org.id, OrgMember.is_deleted == 0)
            .values(org_id=parent_id)
        )
        org.is_deleted = 1
        org.deleted_at = now
        org.updated_at = now
        session.flush()
        return {
            "id": org_id,
            "deleted": True,
            "strategy": mode,
            "children_moved": child_count,
            "members_moved": len(direct_members),
        }

    session.execute(
        Organization.__table__.update()
        .where(Organization.id.in_(subtree), Organization.is_deleted == 0)
        .values(is_deleted=1, deleted_at=now, updated_at=now)
    )
    if subtree:
        # 主组织被删只降级（C-17）；同时记 updated_at 作为「本批次删除」的
        # 标记，恢复时只复活同一批次的成员，不会把用户早先移除的成员带回来。
        session.execute(
            OrgMember.__table__.update()
            .where(OrgMember.org_id.in_(subtree), OrgMember.is_deleted == 0)
            .values(is_deleted=1, is_primary=0, updated_at=now)
        )
    session.flush()
    return {
        "id": org_id,
        "deleted": True,
        "strategy": mode,
        "organizations_deleted": len(subtree),
        "members_deleted": len(member_rows),
    }


def restore_organization(session: Session, org_id: int) -> dict[str, Any]:
    """回收站恢复：递归还原子树与成员。

    · **同批次语义**：只恢复 ``deleted_at`` 与目标组织相同的子组织；更早单独
      删除的子组织留在回收站，等用户自己恢复（与卷/章恢复一致）
    · 名称被新组织占用时返回 1001，而不是把 UNIQUE 约束异常冒成 500
    · 成员只复活同批次的（``updated_at`` 与删除时间相同）；用户早先手动移除的
      成员不会被带回；若恢复出的角色在别处已有主组织，则降级为普通成员
    · 组织原本归属的阵营已被删除时，清空 ``faction_id`` 避免指针悬空
    """
    org = session.get(Organization, org_id)
    if org is None:
        raise ApiError(CODE_NOT_FOUND, "组织不存在")
    if not org.is_deleted:
        raise ApiError(CODE_PARAM_INVALID, "组织未被删除，无法恢复")
    stamp = org.deleted_at

    rows = session.execute(
        select(Organization.id, Organization.parent_id, Organization.name).where(
            Organization.project_id == org.project_id
        )
    ).all()
    children: dict[int, list[int]] = defaultdict(list)
    for oid, parent_id, _ in rows:
        if parent_id is not None:
            children[int(parent_id)].append(int(oid))
    subtree: list[int] = []
    stack = [int(org_id)]
    while stack:
        current = stack.pop()
        if current in subtree:
            continue
        subtree.append(current)
        stack.extend(children.get(current, []))

    deleted_rows = (
        session.execute(
            select(Organization).where(Organization.id.in_(subtree))
        )
        .scalars()
        .all()
    )
    # 目标自身一定恢复；子组织只恢复与目标同批次的
    restore_ids = {
        int(row.id)
        for row in deleted_rows
        if int(row.id) == int(org_id) or row.deleted_at == stamp
    }
    names = [row.name for row in deleted_rows if int(row.id) in restore_ids]

    conflicts = session.execute(
        select(Organization.name).where(
            Organization.project_id == org.project_id,
            Organization.is_deleted == 0,
            Organization.name.in_(names),
        )
    ).scalars()
    conflict_list = sorted(set(conflicts))
    if conflict_list:
        raise ApiError(
            CODE_PARAM_INVALID,
            "名称已被现存组织占用，请先重命名或删除：" + "、".join(conflict_list),
        )

    now = utc_now()
    session.execute(
        Organization.__table__.update()
        .where(Organization.id.in_(restore_ids), Organization.is_deleted == 1)
        .values(is_deleted=0, deleted_at=None, updated_at=now)
    )

    # 旧版本删除组织时没有给成员打 updated_at 标记；这种情况下没有一条成员
    # 的 updated_at 会等于组织的 deleted_at，退回「全部恢复」以兼容旧回收站数据。
    batch_mode = bool(
        session.execute(
            select(OrgMember.id)
            .where(
                OrgMember.org_id.in_(restore_ids),
                OrgMember.is_deleted == 1,
                OrgMember.updated_at == stamp,
            )
            .limit(1)
        ).scalar()
    )

    restored_members = 0
    skipped: list[int] = []
    primary_demoted = 0
    for oid in restore_ids:
        taken = {
            int(cid)
            for (cid,) in session.execute(
                select(OrgMember.character_id).where(
                    OrgMember.org_id == oid, OrgMember.is_deleted == 0
                )
            ).all()
        }
        inactive = (
            session.execute(
                select(OrgMember).where(
                    OrgMember.org_id == oid, OrgMember.is_deleted == 1
                )
            )
            .scalars()
            .all()
        )
        for member in inactive:
            if batch_mode and member.updated_at != stamp:
                continue  # 用户更早手动移除的成员，不随组织恢复复活
            if int(member.character_id) in taken:
                skipped.append(int(member.id))
                continue
            if member.is_primary:
                has_primary = session.execute(
                    select(OrgMember.id).where(
                        OrgMember.character_id == member.character_id,
                        OrgMember.is_deleted == 0,
                        OrgMember.is_primary == 1,
                    )
                ).scalar()
                if has_primary is not None:
                    member.is_primary = 0
                    primary_demoted += 1
            member.is_deleted = 0
            taken.add(int(member.character_id))
            restored_members += 1

    session.flush()
    # 本函数用 Core UPDATE 批量改状态；同 session 里可能还缓存着恢复前的
    # 组织对象（调用方 trash_service 就持有），必须过期让后续读取回库。
    session.expire_all()
    faction_cleared = _clear_dead_factions(session, restore_ids)
    session.flush()
    return {
        "id": org_id,
        "restored": True,
        "organizations_restored": len(restore_ids),
        "members_restored": restored_members,
        "members_skipped": skipped,
        "primary_demoted": primary_demoted,
        "faction_cleared": faction_cleared,
    }


def _clear_dead_factions(session: Session, org_ids: set[int]) -> list[int]:
    """恢复后的组织若指向已删除的阵营，清空指针（避免悬空引用）。"""
    from ..models import Faction

    cleared: list[int] = []
    for oid in org_ids:
        org = session.get(Organization, oid)
        if org is None or org.faction_id is None or org.is_deleted:
            continue
        faction = session.get(Faction, int(org.faction_id))
        if faction is None or faction.is_deleted:
            org.faction_id = None
            cleared.append(int(oid))
    return cleared


# --------------------------------------------------------------------------
# 成员（#76 / #77）
# --------------------------------------------------------------------------


def _chapter_position(
    session: Session, chapter_id: int, project_id: int
) -> tuple[int, int]:
    row = session.execute(
        select(Volume.order_index, Chapter.order_index)
        .join(Chapter, Chapter.volume_id == Volume.id)
        .where(
            Chapter.id == int(chapter_id),
            Volume.project_id == project_id,
        )
    ).first()
    if row is None:
        # 回收站里的章节仍保留位置：允许既有关系继续引用，恢复后语义不变
        raise ApiError(CODE_PARAM_INVALID, "章节不存在或不属于这本书")
    return (int(row[0]), int(row[1]))


def validate_chapter_range(
    session: Session,
    project_id: int,
    from_chapter_id: int | None,
    to_chapter_id: int | None,
) -> None:
    """生效章区间校验：两章必须属于本书，且起始不晚于结束。

    成员身份与角色关系共用（也是唯一一处「章节先后」口径）。
    只给一端时也要校验（否则会存下别书的章节 id 或悬空 id → 外键 500）。
    """
    positions: list[tuple[int, int]] = []
    for chapter_id in (from_chapter_id, to_chapter_id):
        if chapter_id is not None:
            positions.append(_chapter_position(session, int(chapter_id), project_id))
    if len(positions) == 2 and positions[0] > positions[1]:
        raise ApiError(CODE_PARAM_INVALID, "起始章不能晚于结束章")


def require_member(session: Session, member_id: int) -> OrgMember:
    member = session.get(OrgMember, member_id)
    if member is None:
        raise ApiError(CODE_NOT_FOUND, "成员身份不存在")
    if member.is_deleted:
        raise ApiError(CODE_DELETED, "成员身份已移除")
    return member


def list_members(session: Session, org_id: int) -> dict[str, Any]:
    """§6.2 #76（GET）。"""
    require_organization(session, org_id)
    rows = session.execute(
        select(OrgMember, Character)
        .join(Character, Character.id == OrgMember.character_id)
        .where(
            OrgMember.org_id == org_id,
            OrgMember.is_deleted == 0,
            Character.is_deleted == 0,
        )
        .order_by(OrgMember.is_primary.desc(), OrgMember.id)
    ).all()
    items = [
        {
            "id": member.id,
            "character_id": character.id,
            "character_name": character.name,
            "character_role": character.role,
            "position": member.position,
            "is_primary": bool(member.is_primary),
            "is_secret": bool(member.is_secret),
            "from_chapter_id": member.from_chapter_id,
            "to_chapter_id": member.to_chapter_id,
        }
        for member, character in rows
    ]
    return {"org_id": org_id, "items": items, "total": len(items)}


def _clear_primary(session: Session, character_id: int, keep_id: int | None) -> None:
    statement = OrgMember.__table__.update().where(
        OrgMember.character_id == character_id,
        OrgMember.is_deleted == 0,
        OrgMember.is_primary == 1,
    )
    if keep_id is not None:
        statement = statement.where(OrgMember.id != keep_id)
    session.execute(statement.values(is_primary=0))


def add_member(
    session: Session,
    org_id: int,
    *,
    character_id: int,
    position: str | None = None,
    is_primary: bool = False,
    is_secret: bool = False,
    from_chapter_id: int | None = None,
    to_chapter_id: int | None = None,
) -> OrgMember:
    """§6.2 #76（POST）：加成员；一个角色最多一个主组织。"""
    org = require_organization(session, org_id)
    character = session.get(Character, int(character_id))
    if character is None or character.is_deleted:
        raise ApiError(CODE_NOT_FOUND, "角色不存在")
    if character.project_id != org.project_id:
        raise ApiError(CODE_PARAM_INVALID, "角色必须属于同一本书")
    exists = session.execute(
        select(OrgMember.id).where(
            OrgMember.character_id == int(character_id),
            OrgMember.org_id == org_id,
            OrgMember.is_deleted == 0,
        )
    ).scalar()
    if exists is not None:
        raise ApiError(CODE_PARAM_INVALID, "该角色已在此组织中")

    validate_chapter_range(
        session,
        org.project_id,
        int(from_chapter_id) if from_chapter_id is not None else None,
        int(to_chapter_id) if to_chapter_id is not None else None,
    )

    now = utc_now()
    member = OrgMember(
        character_id=int(character_id),
        org_id=org_id,
        position=_clean_text(position, MAX_POSITION),
        is_primary=_clean_bool(is_primary),
        is_secret=_clean_bool(is_secret),
        from_chapter_id=(int(from_chapter_id) if from_chapter_id is not None else None),
        to_chapter_id=int(to_chapter_id) if to_chapter_id is not None else None,
        created_at=now,
        updated_at=now,
    )
    session.add(member)
    session.flush()
    if member.is_primary:
        _clear_primary(session, member.character_id, member.id)
    return member


def update_member(session: Session, member_id: int, **fields: Any) -> OrgMember:
    """§6.2 #77（PATCH）：职位 / 主组织 / 隐蔽 / 生效段。"""
    member = require_member(session, member_id)
    org = require_organization(session, member.org_id)
    if "position" in fields:
        member.position = _clean_text(fields["position"], MAX_POSITION)
    if "is_secret" in fields and fields["is_secret"] is not None:
        member.is_secret = _clean_bool(fields["is_secret"])
    if "from_chapter_id" in fields or "to_chapter_id" in fields:
        from_id = fields.get("from_chapter_id", member.from_chapter_id)
        to_id = fields.get("to_chapter_id", member.to_chapter_id)
        validate_chapter_range(
            session,
            org.project_id,
            int(from_id) if from_id is not None else None,
            int(to_id) if to_id is not None else None,
        )
        member.from_chapter_id = int(from_id) if from_id is not None else None
        member.to_chapter_id = int(to_id) if to_id is not None else None
    if "is_primary" in fields and fields["is_primary"] is not None:
        member.is_primary = _clean_bool(fields["is_primary"])
        if member.is_primary:
            session.flush()
            _clear_primary(session, member.character_id, member.id)
    member.updated_at = utc_now()
    session.flush()
    return member


def remove_member(session: Session, member_id: int) -> dict[str, Any]:
    """§6.2 #77（DELETE）：软删成员身份（可重新加入）。"""
    member = require_member(session, member_id)
    member.is_deleted = 1
    member.updated_at = utc_now()
    session.flush()
    return {"id": member_id, "deleted": True}


# --------------------------------------------------------------------------
# 组织间关系（#78 / #79）
# --------------------------------------------------------------------------


def require_org_relation(session: Session, relation_id: int) -> OrgRelation:
    row = session.get(OrgRelation, relation_id)
    if row is None:
        raise ApiError(CODE_NOT_FOUND, "组织关系不存在")
    if row.is_deleted:
        raise ApiError(CODE_DELETED, "组织关系已删除")
    return row


def organization_name_map(session: Session, project_id: int) -> dict[int, str]:
    """组织 id → 名称（关系序列化用）。"""
    rows = session.execute(
        select(Organization.id, Organization.name).where(
            Organization.project_id == project_id
        )
    ).all()
    return {int(oid): name for oid, name in rows}


def serialize_org_relation(row: OrgRelation, names: dict[int, str]) -> dict[str, Any]:
    return {
        "id": row.id,
        "from_id": row.from_id,
        "to_id": row.to_id,
        "from_name": names.get(row.from_id),
        "to_name": names.get(row.to_id),
        "relation_type": row.relation_type,
        "relation_label": ORG_RELATION_LABELS.get(row.relation_type, row.relation_type),
        "description": row.description,
        "is_bidirectional": bool(row.is_bidirectional),
        "from_chapter_id": row.from_chapter_id,
        "to_chapter_id": row.to_chapter_id,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def list_org_relations(session: Session, project_id: int) -> dict[str, Any]:
    """§6.2 #78（GET）。"""
    project_service.require_project(session, project_id)
    rows = (
        session.execute(
            select(OrgRelation)
            .where(
                OrgRelation.project_id == project_id,
                OrgRelation.is_deleted == 0,
            )
            .order_by(OrgRelation.id)
        )
        .scalars()
        .all()
    )
    names = organization_name_map(session, project_id)
    return {
        "project_id": project_id,
        "items": [serialize_org_relation(row, names) for row in rows],
        "total": len(rows),
        "types": [
            {"value": value, "label": ORG_RELATION_LABELS[value]}
            for value in ORG_RELATION_TYPES
        ],
    }


def create_org_relation(
    session: Session,
    project_id: int,
    *,
    from_id: int,
    to_id: int,
    relation_type: str = "neutral",
    description: str | None = None,
    is_bidirectional: bool = False,
    from_chapter_id: int | None = None,
    to_chapter_id: int | None = None,
) -> OrgRelation:
    """§6.2 #78（POST）。"""
    project_service.require_project(session, project_id)
    if int(from_id) == int(to_id):
        raise ApiError(CODE_PARAM_INVALID, "组织之间不能自己指向自己")
    for oid in (from_id, to_id):
        org = require_organization(session, int(oid))
        if org.project_id != project_id:
            raise ApiError(CODE_PARAM_INVALID, "两个组织必须属于同一本书")
    kind = _clean_enum(relation_type or "neutral", ORG_RELATION_TYPES, "关系类型")
    duplicate = session.execute(
        select(OrgRelation.id).where(
            OrgRelation.from_id == int(from_id),
            OrgRelation.to_id == int(to_id),
            OrgRelation.relation_type == kind,
            OrgRelation.is_deleted == 0,
        )
    ).scalar()
    if duplicate is not None:
        raise ApiError(CODE_PARAM_INVALID, "这两个组织之间已有同类型关系")
    validate_chapter_range(
        session,
        project_id,
        int(from_chapter_id) if from_chapter_id is not None else None,
        int(to_chapter_id) if to_chapter_id is not None else None,
    )
    now = utc_now()
    row = OrgRelation(
        project_id=project_id,
        from_id=int(from_id),
        to_id=int(to_id),
        relation_type=kind,
        description=_clean_text(description, MAX_DESCRIPTION),
        is_bidirectional=_clean_bool(is_bidirectional),
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
        raise ApiError(CODE_PARAM_INVALID, "这两个组织之间已有同类型关系") from exc
    return row


def update_org_relation(
    session: Session, relation_id: int, **fields: Any
) -> OrgRelation:
    row = require_org_relation(session, relation_id)
    if fields.get("relation_type") is not None:
        kind = _clean_enum(fields["relation_type"], ORG_RELATION_TYPES, "关系类型")
        duplicate = session.execute(
            select(OrgRelation.id).where(
                OrgRelation.from_id == row.from_id,
                OrgRelation.to_id == row.to_id,
                OrgRelation.relation_type == kind,
                OrgRelation.is_deleted == 0,
                OrgRelation.id != relation_id,
            )
        ).scalar()
        if duplicate is not None:
            raise ApiError(CODE_PARAM_INVALID, "同类型关系已存在")
        row.relation_type = kind
    if "description" in fields:
        row.description = _clean_text(fields["description"], MAX_DESCRIPTION)
    if "is_bidirectional" in fields and fields["is_bidirectional"] is not None:
        row.is_bidirectional = _clean_bool(fields["is_bidirectional"])
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
        raise ApiError(CODE_PARAM_INVALID, "同类型关系已存在") from exc
    return row


def delete_org_relation(session: Session, relation_id: int) -> dict[str, Any]:
    row = require_org_relation(session, relation_id)
    row.is_deleted = 1
    row.deleted_at = utc_now()
    row.updated_at = row.deleted_at
    session.flush()
    return {"id": relation_id, "deleted": True}
