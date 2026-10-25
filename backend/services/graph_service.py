"""图数据与画布布局（V2.0 / FR-8.16~8.21）。

对应接口 **#64（三模式统一图数据）**、**#80 / #81（布局读写）**。

三种模式的节点与边：

    · ``character``：节点=角色，边=角色关系；可选「以某人为中心 N 跳」
    · ``organization``：节点=组织，边=父子从属 + 组织关系
    · ``faction``：节点=大立场 + 组织，边=立场关系 + 组织关系

落库与截断规则（报告 §7.4）：超过 ``MAX_NODES`` 时按「自定义顺序 + id」取前 N 个，
返回 ``truncated=true`` 与真实 ``total_nodes``，由前端提示用户筛选。
"""

from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Chapter,
    Character,
    CharacterRelation,
    Faction,
    FactionRelation,
    GraphLayout,
    Organization,
    OrgMember,
    OrgRelation,
    Volume,
    active,
)
from ..schemas import (
    CODE_PARAM_INVALID,
    CODE_VERSION_CONFLICT,
    ApiError,
)
from ..timeutil import iso, utc_now
from . import project_service

MODES: tuple[str, ...] = ("character", "organization", "faction")
MAX_NODES = 80
MAX_DEPTH = 3
MAX_LAYOUT_BYTES = 1024 * 1024

# 阵营模式的节点 id 统一加偏移：阵营与组织的自增 id 都从 1 开始，直接混用会撞号。
# 前端按 node.key 区分实体，边只带 id，因此必须在服务层就消歧。
FACTION_GRAPH_OFFSET = 1_000_000


def _faction_node_id(faction_id: int) -> int:
    return int(faction_id) + FACTION_GRAPH_OFFSET
LAYOUT_NODE_FIELDS = ("x", "y", "pinned")


# --------------------------------------------------------------------------
# 公共
# --------------------------------------------------------------------------


def _clean_mode(mode: str | None) -> str:
    value = (mode or "character").strip()
    if value not in MODES:
        raise ApiError(CODE_PARAM_INVALID, f"图模式必须是 {'/'.join(MODES)} 之一")
    return value


def _chapter_positions(session: Session, project_id: int) -> dict[int, tuple[int, int]]:
    # 回收站里的章节仍然保留位置：关系/成员的生效段引用它时，不能因为章节
    # 进了回收站就把边界当作「无界」，否则已失效的关系会在图上复活。
    rows = session.execute(
        select(Chapter.id, Volume.order_index, Chapter.order_index)
        .join(Volume, Volume.id == Chapter.volume_id)
        .where(Volume.project_id == project_id)
    ).all()
    return {
        int(cid): (int(volume_order), int(chapter_order))
        for cid, volume_order, chapter_order in rows
    }


def _active_at(
    positions: dict[int, tuple[int, int]],
    chapter_pos: tuple[int, int] | None,
    from_id: int | None,
    to_id: int | None,
) -> bool:
    """关系/成员身份在给定章节是否有效；章节已被删则视为无界。"""
    if chapter_pos is None:
        return True
    if from_id is not None:
        start = positions.get(int(from_id))
        if start is not None and start > chapter_pos:
            return False
    if to_id is not None:
        end = positions.get(int(to_id))
        if end is not None and end < chapter_pos:
            return False
    return True


def _org_maps(
    session: Session, project_id: int
) -> tuple[dict[int, Organization], dict[int, int | None]]:
    rows = (
        session.execute(
            active(Organization).where(Organization.project_id == project_id)
        )
        .scalars()
        .all()
    )
    by_id = {int(row.id): row for row in rows}

    def resolve(org_id: int) -> int | None:
        seen: set[int] = set()
        current = by_id.get(org_id)
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

    return by_id, {oid: resolve(oid) for oid in by_id}


def _character_orgs(
    session: Session, project_id: int
) -> dict[int, list[tuple[int, int, str | None]]]:
    """角色 → [(org_id, is_primary, org_color)]（只含活跃成员与活跃组织）。"""
    rows = session.execute(
        select(
            OrgMember.character_id,
            OrgMember.org_id,
            OrgMember.is_primary,
            Organization.color,
        )
        .join(Organization, Organization.id == OrgMember.org_id)
        .join(Character, Character.id == OrgMember.character_id)
        .where(
            Organization.project_id == project_id,
            Organization.is_deleted == 0,
            OrgMember.is_deleted == 0,
            Character.is_deleted == 0,
        )
        .order_by(OrgMember.is_primary.desc(), OrgMember.id)
    ).all()
    result: dict[int, list[tuple[int, int, str | None]]] = defaultdict(list)
    for character_id, org_id, is_primary, color in rows:
        result[int(character_id)].append((int(org_id), int(is_primary), color))
    return result


def _faction_names(session: Session, project_id: int) -> dict[int, Faction]:
    rows = (
        session.execute(active(Faction).where(Faction.project_id == project_id))
        .scalars()
        .all()
    )
    return {int(row.id): row for row in rows}


def _truncate(
    nodes: list[dict[str, Any]], limit: int
) -> tuple[list[dict[str, Any]], bool, int]:
    total = len(nodes)
    ordered = sorted(nodes, key=lambda n: (n.get("order", 0), n["id"]))
    return ordered[:limit], total > limit, total


# --------------------------------------------------------------------------
# 人物模式
# --------------------------------------------------------------------------


def _character_graph(
    session: Session,
    project_id: int,
    *,
    faction_id: int | None,
    org_id: int | None,
    center_id: int | None,
    depth: int,
    chapter_id: int | None,
    include_expired: bool,
    limit: int,
) -> dict[str, Any]:
    from . import organization_service

    characters = (
        session.execute(
            active(Character)
            .where(Character.project_id == project_id)
            .order_by(Character.order_index, Character.id)
        )
        .scalars()
        .all()
    )
    by_id = {int(row.id): row for row in characters}

    allowed: set[int] | None = None
    if org_id is not None:
        subtree = set(
            organization_service.collect_subtree_ids(session, project_id, int(org_id))
        )
        rows = session.execute(
            select(OrgMember.character_id).where(
                OrgMember.org_id.in_(subtree), OrgMember.is_deleted == 0
            )
        ).all()
        allowed = {int(cid) for (cid,) in rows}
    if faction_id is not None:
        _, org_faction = _org_maps(session, project_id)
        rows = session.execute(
            select(OrgMember.character_id, OrgMember.org_id).where(
                OrgMember.is_deleted == 0
            )
        ).all()
        in_faction = {
            int(cid)
            for cid, oid in rows
            if org_faction.get(int(oid)) == int(faction_id)
        }
        allowed = in_faction if allowed is None else (allowed & in_faction)

    positions = _chapter_positions(session, project_id) if chapter_id else {}
    chapter_pos = positions.get(int(chapter_id)) if chapter_id else None

    relations = (
        session.execute(
            select(CharacterRelation)
            .where(
                CharacterRelation.project_id == project_id,
                CharacterRelation.is_deleted == 0,
            )
            .order_by(CharacterRelation.id)
        )
        .scalars()
        .all()
    )
    kept_relations = []
    for row in relations:
        if allowed is not None and (
            int(row.from_id) not in allowed or int(row.to_id) not in allowed
        ):
            continue
        if int(row.from_id) not in by_id or int(row.to_id) not in by_id:
            continue
        if chapter_id is not None and not _active_at(
            positions, chapter_pos, row.from_chapter_id, row.to_chapter_id
        ):
            continue
        if chapter_id is None and not include_expired and row.to_chapter_id is not None:
            continue
        kept_relations.append(row)

    # 组织 / 阵营筛选的成员来自 org_member（软删角色仍保留成员身份），
    # 必须与「本项目活跃角色」取交集，否则 by_id[cid] 会 KeyError → 500。
    selected = set(by_id) if allowed is None else (set(allowed) & set(by_id))
    if center_id is not None:
        center = int(center_id)
        if center not in by_id:
            raise ApiError(CODE_PARAM_INVALID, "中心角色不存在")
        neighbours: dict[int, set[int]] = defaultdict(set)
        for row in kept_relations:
            a, b = int(row.from_id), int(row.to_id)
            neighbours[a].add(b)
            neighbours[b].add(a)
        reach = {center}
        queue = deque([(center, 0)])
        while queue:
            current, level = queue.popleft()
            if level >= depth:
                continue
            for other in neighbours.get(current, ()):  # type: ignore[arg-type]
                if other not in reach:
                    reach.add(other)
                    queue.append((other, level + 1))
        selected &= reach

    char_orgs = _character_orgs(session, project_id)
    nodes = []
    for cid in selected:
        row = by_id[cid]
        orgs = char_orgs.get(cid, [])
        first = orgs[0] if orgs else None
        nodes.append(
            {
                "id": cid,
                "key": f"character:{cid}",
                "kind": "character",
                "name": row.name,
                "role": row.role,
                "status": row.status,
                "order": row.order_index,
                "org_id": first[0] if first else None,
                "org_color": first[2] if first else None,
                "primary": bool(first[1]) if first else False,
            }
        )

    nodes, truncated, total = _truncate(nodes, limit)
    kept_ids = {node["id"] for node in nodes}
    edges: list[dict[str, Any]] = []
    edge_index: dict[tuple[int, int, str, str], dict[str, Any]] = {}
    for row in kept_relations:
        if int(row.from_id) not in kept_ids or int(row.to_id) not in kept_ids:
            continue
        a, b = int(row.from_id), int(row.to_id)
        # 报告 §6.7：A→B 与 B→A 的同类型关系按「端点对 + 类型」去重，
        # 只返回一条并标记 is_bidirectional；自定义标签不同视为两条关系。
        key = (min(a, b), max(a, b), row.relation_type, row.custom_label or "")
        edge = edge_index.get(key)
        if edge is not None:
            if edge["from"] != a:
                edge["bidirectional"] = True
            continue
        edge = {
            "id": row.id,
            "kind": "character_relation",
            "from": a,
            "to": b,
            "type": row.relation_type,
            "label": row.custom_label or None,
            "bidirectional": bool(row.is_bidirectional),
            "secret": bool(row.is_secret),
            "active": True if chapter_id is not None else row.to_chapter_id is None,
        }
        edge_index[key] = edge
        edges.append(edge)

    factions = _faction_names(session, project_id)
    _, org_faction = _org_maps(session, project_id)
    member_ids: dict[int, list[int]] = defaultdict(list)
    for cid in kept_ids:
        orgs = char_orgs.get(cid, [])
        if not orgs:
            continue
        fid = org_faction.get(orgs[0][0])
        if fid is not None:
            member_ids[fid].append(cid)
    groups = [
        {
            "id": fid,
            "kind": "faction",
            "name": row.name,
            "color": row.color,
            "member_ids": member_ids.get(fid, []),
        }
        for fid, row in factions.items()
    ]
    return {
        "mode": "character",
        "nodes": nodes,
        "edges": edges,
        "groups": groups,
        "total_nodes": total,
        "truncated": truncated,
    }


# --------------------------------------------------------------------------
# 组织模式 / 阵营模式
# --------------------------------------------------------------------------


def _member_counts(session: Session, project_id: int) -> dict[int, int]:
    """组织 → 在职成员数（只统计本项目、未删除的角色）。"""
    return {
        int(oid): int(count)
        for oid, count in session.execute(
            select(OrgMember.org_id, func.count(OrgMember.id))
            .join(Character, Character.id == OrgMember.character_id)
            .where(
                OrgMember.is_deleted == 0,
                Character.project_id == project_id,
                Character.is_deleted == 0,
            )
            .group_by(OrgMember.org_id)
        ).all()
    }


def _organization_graph(
    session: Session,
    project_id: int,
    *,
    faction_id: int | None,
    org_id: int | None,
    limit: int,
) -> dict[str, Any]:
    from . import organization_service

    by_id, org_faction = _org_maps(session, project_id)
    selected = set(by_id)
    if org_id is not None:
        selected = set(
            organization_service.collect_subtree_ids(session, project_id, int(org_id))
        )
    if faction_id is not None:
        selected = {oid for oid in selected if org_faction.get(oid) == int(faction_id)}

    factions = _faction_names(session, project_id)
    member_counts = _member_counts(session, project_id)
    nodes = [
        {
            "id": oid,
            "key": f"organization:{oid}",
            "kind": "organization",
            "name": by_id[oid].name,
            "kind_label": by_id[oid].kind,
            "order": by_id[oid].order_index,
            "faction_id": org_faction.get(oid),
            "color": by_id[oid].color,
            "parent_id": by_id[oid].parent_id,
            "member_count": member_counts.get(oid, 0),
        }
        for oid in selected
    ]
    nodes, truncated, total = _truncate(nodes, limit)
    kept = {node["id"] for node in nodes}

    edges: list[dict[str, Any]] = []
    for oid in kept:
        parent_id = by_id[oid].parent_id
        if parent_id is not None and int(parent_id) in kept:
            edges.append(
                {
                    "id": f"parent:{oid}",
                    "kind": "org_parent",
                    "from": int(parent_id),
                    "to": oid,
                    "type": "parent",
                    "bidirectional": False,
                    "secret": False,
                    "active": True,
                }
            )
    relation_rows = (
        session.execute(
            select(OrgRelation).where(
                OrgRelation.project_id == project_id,
                OrgRelation.is_deleted == 0,
            )
        )
        .scalars()
        .all()
    )
    for row in relation_rows:
        if int(row.from_id) not in kept or int(row.to_id) not in kept:
            continue
        edges.append(
            {
                "id": row.id,
                "kind": "org_relation",
                "from": int(row.from_id),
                "to": int(row.to_id),
                "type": row.relation_type,
                "label": None,
                "bidirectional": bool(row.is_bidirectional),
                "secret": False,
                "active": row.to_chapter_id is None,
            }
        )
    member_ids: dict[int, list[int]] = defaultdict(list)
    for oid in kept:
        fid = org_faction.get(oid)
        if fid is not None:
            member_ids[fid].append(oid)
    groups = [
        {
            "id": fid,
            "kind": "faction",
            "name": row.name,
            "color": row.color,
            "member_ids": member_ids.get(fid, []),
        }
        for fid, row in factions.items()
    ]
    return {
        "mode": "organization",
        "nodes": nodes,
        "edges": edges,
        "groups": groups,
        "total_nodes": total,
        "truncated": truncated,
    }


def _faction_graph(
    session: Session,
    project_id: int,
    *,
    faction_id: int | None,
    limit: int,
) -> dict[str, Any]:
    factions = _faction_names(session, project_id)
    by_id, org_faction = _org_maps(session, project_id)
    member_counts = _member_counts(session, project_id)

    included_factions = set(factions)
    if faction_id is not None:
        if int(faction_id) not in factions:
            raise ApiError(CODE_PARAM_INVALID, "立场不存在")
        included_factions = {int(faction_id)}

    nodes: list[dict[str, Any]] = [
        {
            "id": _faction_node_id(fid),
            "key": f"faction:{fid}",
            "kind": "faction",
            "name": factions[fid].name,
            "color": factions[fid].color,
            "order": factions[fid].order_index,
        }
        for fid in included_factions
    ]
    org_ids = {oid for oid in by_id if org_faction.get(oid) in included_factions}
    nodes.extend(
        {
            "id": oid,
            "key": f"organization:{oid}",
            "kind": "organization",
            "name": by_id[oid].name,
            "kind_label": by_id[oid].kind,
            "color": by_id[oid].color,
            "faction_id": org_faction.get(oid),
            "order": by_id[oid].order_index,
            "parent_id": by_id[oid].parent_id,
            "member_count": member_counts.get(oid, 0),
        }
        for oid in org_ids
    )
    nodes, truncated, total = _truncate(nodes, limit)
    kept_faction_ids = {node["id"] for node in nodes if node["kind"] == "faction"}
    kept_org_ids = {node["id"] for node in nodes if node["kind"] == "organization"}

    edges: list[dict[str, Any]] = []
    faction_rows = (
        session.execute(
            select(FactionRelation).where(
                FactionRelation.project_id == project_id,
                FactionRelation.is_deleted == 0,
            )
        )
        .scalars()
        .all()
    )
    for row in faction_rows:
        from_id = _faction_node_id(row.from_id)
        to_id = _faction_node_id(row.to_id)
        if from_id in kept_faction_ids and to_id in kept_faction_ids:
            edges.append(
                {
                    "id": row.id,
                    "kind": "faction_relation",
                    "from": from_id,
                    "to": to_id,
                    "type": row.relation_type,
                    "bidirectional": bool(row.is_bidirectional),
                    "secret": False,
                    "active": True,
                }
            )
    for oid in kept_org_ids:
        parent_id = by_id[oid].parent_id
        if parent_id is not None and int(parent_id) in kept_org_ids:
            edges.append(
                {
                    "id": f"parent:{oid}",
                    "kind": "org_parent",
                    "from": int(parent_id),
                    "to": oid,
                    "type": "parent",
                    "bidirectional": False,
                    "secret": False,
                    "active": True,
                }
            )
        elif org_faction.get(oid) is not None:
            fid = org_faction[oid]
            if _faction_node_id(fid) not in kept_faction_ids:
                continue
            edges.append(
                {
                    "id": f"belongs:{oid}",
                    "kind": "membership",
                    "from": _faction_node_id(fid),
                    "to": oid,
                    "type": "belongs",
                    "bidirectional": False,
                    "secret": False,
                    "active": True,
                }
            )
    relation_rows = (
        session.execute(
            select(OrgRelation).where(
                OrgRelation.project_id == project_id,
                OrgRelation.is_deleted == 0,
            )
        )
        .scalars()
        .all()
    )
    for row in relation_rows:
        if int(row.from_id) in kept_org_ids and int(row.to_id) in kept_org_ids:
            edges.append(
                {
                    "id": row.id,
                    "kind": "org_relation",
                    "from": int(row.from_id),
                    "to": int(row.to_id),
                    "type": row.relation_type,
                    "bidirectional": bool(row.is_bidirectional),
                    "secret": False,
                    "active": row.to_chapter_id is None,
                }
            )
    groups = [
        {
            "id": fid,
            "kind": "faction",
            "name": factions[fid].name,
            "color": factions[fid].color,
            "member_ids": [oid for oid in kept_org_ids if org_faction.get(oid) == fid],
        }
        for fid in included_factions
        if fid in factions
    ]
    return {
        "mode": "faction",
        "nodes": nodes,
        "edges": edges,
        "groups": groups,
        "total_nodes": total,
        "truncated": truncated,
    }


# --------------------------------------------------------------------------
# 对外
# --------------------------------------------------------------------------


def build_graph(
    session: Session,
    project_id: int,
    *,
    mode: str = "character",
    faction_id: int | None = None,
    org_id: int | None = None,
    center_id: int | None = None,
    depth: int = 2,
    chapter_id: int | None = None,
    include_expired: bool = False,
    limit: int = MAX_NODES,
) -> dict[str, Any]:
    """§6.2 #64：三模式统一图数据。"""
    project_service.require_project(session, project_id)
    clean_mode = _clean_mode(mode)
    if depth < 1 or depth > MAX_DEPTH:
        raise ApiError(CODE_PARAM_INVALID, f"展开层数必须在 1~{MAX_DEPTH}")
    if limit < 1 or limit > MAX_NODES:
        raise ApiError(CODE_PARAM_INVALID, f"节点上限必须在 1~{MAX_NODES}")
    if chapter_id is not None:
        exists = session.execute(
            select(Chapter.id)
            .join(Volume, Volume.id == Chapter.volume_id)
            .where(
                Chapter.id == int(chapter_id),
                Volume.project_id == project_id,
            )
        ).scalar()
        if exists is None:
            raise ApiError(CODE_PARAM_INVALID, "章节不存在或不属于这本书")

    if clean_mode == "character":
        payload = _character_graph(
            session,
            project_id,
            faction_id=faction_id,
            org_id=org_id,
            center_id=center_id,
            depth=depth,
            chapter_id=chapter_id,
            include_expired=include_expired,
            limit=limit,
        )
    elif clean_mode == "organization":
        payload = _organization_graph(
            session,
            project_id,
            faction_id=faction_id,
            org_id=org_id,
            limit=limit,
        )
    else:
        payload = _faction_graph(
            session,
            project_id,
            faction_id=faction_id,
            limit=limit,
        )
    return {
        "project_id": project_id,
        **payload,
        "chapter_id": chapter_id,
        "limit": limit,
    }


# --------------------------------------------------------------------------
# 布局（#80 / #81）
# --------------------------------------------------------------------------


def get_layout(session: Session, project_id: int) -> dict[str, Any]:
    """§6.2 #80：读布局（无记录返回空对象）。"""
    project_service.require_project(session, project_id)
    row = session.get(GraphLayout, project_id)
    if row is None:
        return {"project_id": project_id, "payload": {}, "updated_at": None}
    try:
        payload = json.loads(row.payload)
    except ValueError:
        payload = {}
    return {
        "project_id": project_id,
        "payload": payload if isinstance(payload, dict) else {},
        "updated_at": iso(row.updated_at),
    }


def _clean_positions(block: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(block, dict):
        raise ApiError(CODE_PARAM_INVALID, "布局必须是「节点 → 坐标」的对象")
    cleaned: dict[str, dict[str, Any]] = {}
    for key, value in block.items():
        if not isinstance(value, dict):
            raise ApiError(CODE_PARAM_INVALID, f"节点 {key} 的坐标格式不合法")
        try:
            x = float(value.get("x"))
            y = float(value.get("y"))
        except (TypeError, ValueError) as exc:
            raise ApiError(CODE_PARAM_INVALID, f"节点 {key} 的坐标必须是数字") from exc
        if not (math.isfinite(x) and math.isfinite(y)):
            # NaN / Infinity 不是合法 JSON 坐标，一旦落库会让后续读取与画布计算失效
            raise ApiError(CODE_PARAM_INVALID, f"节点 {key} 的坐标必须是有限数字")
        cleaned[str(key)] = {
            "x": round(x, 2),
            "y": round(y, 2),
            "pinned": bool(value.get("pinned", True)),
        }
    return cleaned


def save_layout(
    session: Session,
    project_id: int,
    payload: dict[str, Any],
    *,
    expected_updated_at: str | None = None,
) -> dict[str, Any]:
    """§6.2 #81：保存布局。

    · 按模式分命名空间，**只覆盖传入的模式**，不清掉另外两个
    · ``expected_updated_at`` 不一致 → 3002（多窗口/并发）
    · 序列化后体积上限 1 MB
    """
    project_service.require_project(session, project_id)
    if not isinstance(payload, dict):
        raise ApiError(CODE_PARAM_INVALID, "布局必须是对象")
    unknown = set(payload) - set(MODES)
    if unknown:
        raise ApiError(
            CODE_PARAM_INVALID, f"未知的布局模式：{'、'.join(sorted(unknown))}"
        )

    incoming = {
        mode: _clean_positions(payload[mode]) for mode in MODES if mode in payload
    }

    row = session.get(GraphLayout, project_id)
    current: dict[str, Any] = {}
    current_updated = None
    if row is not None:
        current_updated = iso(row.updated_at)
        try:
            loaded = json.loads(row.payload)
            current = loaded if isinstance(loaded, dict) else {}
        except ValueError:
            current = {}

    if expected_updated_at is not None and expected_updated_at != current_updated:
        raise ApiError(CODE_VERSION_CONFLICT, "布局已在别处更新，请刷新后再保存")

    merged = {**current, **incoming}
    text = json.dumps(merged, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > MAX_LAYOUT_BYTES:
        raise ApiError(CODE_PARAM_INVALID, "布局过大（超过 1MB），请先筛选再保存")

    now = utc_now()
    if row is None:
        session.add(GraphLayout(project_id=project_id, payload=text, updated_at=now))
    else:
        row.payload = text
        row.updated_at = now
    session.flush()
    return {
        "project_id": project_id,
        "payload": merged,
        "updated_at": iso(now),
    }
