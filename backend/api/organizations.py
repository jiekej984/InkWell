"""组织与大立场接口（V2.0 / 任务 5.3；§6.2 #68~#79）。

GET/POST      /projects/{pid}/factions            立场列表 / 新建
PATCH/DELETE  /factions/{fid}                     立场改删（有组织时拒绝）
GET/POST      /projects/{pid}/faction-relations   立场关系
PATCH/DELETE  /faction-relations/{rid}
GET/POST      /projects/{pid}/organizations       组织列表（?tree=1 树形）
PATCH/DELETE  /organizations/{oid}                组织改删（?strategy=cascade|promote）
GET/POST      /organizations/{oid}/members        成员
PATCH/DELETE  /org-members/{mid}
GET/POST      /projects/{pid}/org-relations       组织关系
PATCH/DELETE  /org-relations/{rid}
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from ..database import Database
from ..models import session_scope
from ..schemas import CODE_NOT_FOUND, ApiError, ok
from ..services import faction_service, organization_service

router = APIRouter(tags=["organizations"])


# --------------------------------------------------------------------------
# 入参
# --------------------------------------------------------------------------


class FactionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str | None = None
    description: str | None = None
    order_index: int | None = None


class FactionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = None
    description: str | None = None
    order_index: int | None = None


class FactionRelationCreate(BaseModel):
    from_id: int
    to_id: int
    relation_type: str = "neutral"
    description: str | None = None
    is_bidirectional: bool = True


class FactionRelationUpdate(BaseModel):
    relation_type: str | None = None
    description: str | None = None
    is_bidirectional: bool | None = None


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str | None = None
    parent_id: int | None = None
    faction_id: int | None = None
    leader_id: int | None = None
    description: str | None = None
    document_id: int | None = None
    color: str | None = None
    order_index: int | None = None


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    kind: str | None = None
    parent_id: int | None = None
    faction_id: int | None = None
    leader_id: int | None = None
    description: str | None = None
    document_id: int | None = None
    color: str | None = None
    order_index: int | None = None


class MemberCreate(BaseModel):
    character_id: int
    position: str | None = None
    is_primary: bool = False
    is_secret: bool = False
    from_chapter_id: int | None = None
    to_chapter_id: int | None = None


class MemberUpdate(BaseModel):
    position: str | None = None
    is_primary: bool | None = None
    is_secret: bool | None = None
    from_chapter_id: int | None = None
    to_chapter_id: int | None = None


class OrgRelationCreate(BaseModel):
    from_id: int
    to_id: int
    relation_type: str = "neutral"
    description: str | None = None
    is_bidirectional: bool = False
    from_chapter_id: int | None = None
    to_chapter_id: int | None = None


class OrgRelationUpdate(BaseModel):
    relation_type: str | None = None
    description: str | None = None
    is_bidirectional: bool | None = None
    from_chapter_id: int | None = None
    to_chapter_id: int | None = None


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


def _member_payload(member) -> dict:
    return {
        "id": member.id,
        "character_id": member.character_id,
        "org_id": member.org_id,
        "position": member.position,
        "is_primary": bool(member.is_primary),
        "is_secret": bool(member.is_secret),
        "from_chapter_id": member.from_chapter_id,
        "to_chapter_id": member.to_chapter_id,
    }


# --------------------------------------------------------------------------
# #68~#72 大立场
# --------------------------------------------------------------------------


@router.get("/projects/{pid}/factions")
def list_factions(request: Request, pid: int) -> dict:
    """§6.2 #68。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = faction_service.list_factions(session, pid)
    return ok(data)


@router.post("/projects/{pid}/factions")
def create_faction(request: Request, pid: int, payload: FactionCreate) -> dict:
    """§6.2 #69。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    fields.pop("name", None)
    with session_scope(database.engine) as session:
        faction = faction_service.create_faction(
            session, pid, name=payload.name, **fields
        )
        data = faction_service.serialize_faction(faction)
    return ok(data)


@router.patch("/factions/{fid}")
def update_faction(request: Request, fid: int, payload: FactionUpdate) -> dict:
    """§6.2 #70（PATCH）。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    with session_scope(database.engine) as session:
        faction = faction_service.update_faction(session, fid, **fields)
        data = faction_service.serialize_faction(faction)
    return ok(data)


@router.delete("/factions/{fid}")
def delete_faction(request: Request, fid: int) -> dict:
    """§6.2 #70（DELETE）：仍有组织归属时拒绝。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = faction_service.delete_faction(session, fid)
    return ok(data)


@router.get("/projects/{pid}/faction-relations")
def list_faction_relations(request: Request, pid: int) -> dict:
    """§6.2 #71（GET）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = faction_service.list_faction_relations(session, pid)
    return ok(data)


@router.post("/projects/{pid}/faction-relations")
def create_faction_relation(
    request: Request, pid: int, payload: FactionRelationCreate
) -> dict:
    """§6.2 #71（POST）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        row = faction_service.create_faction_relation(
            session,
            pid,
            from_id=payload.from_id,
            to_id=payload.to_id,
            relation_type=payload.relation_type,
            description=payload.description,
            is_bidirectional=payload.is_bidirectional,
        )
        names = faction_service.faction_name_map(session, pid)
        data = faction_service.serialize_faction_relation(row, names)
    return ok(data)


@router.patch("/faction-relations/{rid}")
def update_faction_relation(
    request: Request, rid: int, payload: FactionRelationUpdate
) -> dict:
    """§6.2 #72（PATCH）。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    with session_scope(database.engine) as session:
        row = faction_service.update_faction_relation(session, rid, **fields)
        names = faction_service.faction_name_map(session, row.project_id)
        data = faction_service.serialize_faction_relation(row, names)
    return ok(data)


@router.delete("/faction-relations/{rid}")
def delete_faction_relation(request: Request, rid: int) -> dict:
    """§6.2 #72（DELETE）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = faction_service.delete_faction_relation(session, rid)
    return ok(data)


# --------------------------------------------------------------------------
# #73~#75 组织
# --------------------------------------------------------------------------


@router.get("/projects/{pid}/organizations")
def list_organizations(
    request: Request,
    pid: int,
    tree: bool = Query(default=False),
    faction_id: int | None = Query(default=None),
    org_id: int | None = Query(default=None),
) -> dict:
    """§6.2 #73：扁平或嵌套树。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = organization_service.list_organizations(
            session, pid, tree=tree, faction_id=faction_id, org_id=org_id
        )
    return ok(data)


@router.post("/projects/{pid}/organizations")
def create_organization(
    request: Request, pid: int, payload: OrganizationCreate
) -> dict:
    """§6.2 #74。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    fields.pop("name", None)
    with session_scope(database.engine) as session:
        org = organization_service.create_organization(
            session, pid, name=payload.name, **fields
        )
        data = organization_service.get_organization(session, org.id)
    return ok(data)


@router.patch("/organizations/{oid}")
def update_organization(
    request: Request, oid: int, payload: OrganizationUpdate
) -> dict:
    """§6.2 #75（PATCH）：改父级会校验成环。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    with session_scope(database.engine) as session:
        org = organization_service.update_organization(session, oid, **fields)
        data = organization_service.get_organization(session, org.id)
    return ok(data)


@router.delete("/organizations/{oid}")
def delete_organization(
    request: Request,
    oid: int,
    strategy: str = Query(default="cascade", description="cascade | promote"),
) -> dict:
    """§6.2 #75（DELETE）：一并删 / 上移一级。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = organization_service.delete_organization(session, oid, strategy=strategy)
    return ok(data)


# --------------------------------------------------------------------------
# #76~#77 成员
# --------------------------------------------------------------------------


@router.get("/organizations/{oid}/members")
def list_members(request: Request, oid: int) -> dict:
    """§6.2 #76（GET）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = organization_service.list_members(session, oid)
    return ok(data)


@router.post("/organizations/{oid}/members")
def add_member(request: Request, oid: int, payload: MemberCreate) -> dict:
    """§6.2 #76（POST）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        member = organization_service.add_member(
            session,
            oid,
            character_id=payload.character_id,
            position=payload.position,
            is_primary=payload.is_primary,
            is_secret=payload.is_secret,
            from_chapter_id=payload.from_chapter_id,
            to_chapter_id=payload.to_chapter_id,
        )
        data = _member_payload(member)
    return ok(data)


@router.patch("/org-members/{mid}")
def update_member(request: Request, mid: int, payload: MemberUpdate) -> dict:
    """§6.2 #77（PATCH）。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    with session_scope(database.engine) as session:
        member = organization_service.update_member(session, mid, **fields)
        data = _member_payload(member)
    return ok(data)


@router.delete("/org-members/{mid}")
def remove_member(request: Request, mid: int) -> dict:
    """§6.2 #77（DELETE）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = organization_service.remove_member(session, mid)
    return ok(data)


# --------------------------------------------------------------------------
# #78~#79 组织关系
# --------------------------------------------------------------------------


@router.get("/projects/{pid}/org-relations")
def list_org_relations(request: Request, pid: int) -> dict:
    """§6.2 #78（GET）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = organization_service.list_org_relations(session, pid)
    return ok(data)


@router.post("/projects/{pid}/org-relations")
def create_org_relation(request: Request, pid: int, payload: OrgRelationCreate) -> dict:
    """§6.2 #78（POST）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        row = organization_service.create_org_relation(
            session,
            pid,
            from_id=payload.from_id,
            to_id=payload.to_id,
            relation_type=payload.relation_type,
            description=payload.description,
            is_bidirectional=payload.is_bidirectional,
            from_chapter_id=payload.from_chapter_id,
            to_chapter_id=payload.to_chapter_id,
        )
        names = organization_service.organization_name_map(session, pid)
        data = organization_service.serialize_org_relation(row, names)
    return ok(data)


@router.patch("/org-relations/{rid}")
def update_org_relation(request: Request, rid: int, payload: OrgRelationUpdate) -> dict:
    """§6.2 #79（PATCH）。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    with session_scope(database.engine) as session:
        row = organization_service.update_org_relation(session, rid, **fields)
        names = organization_service.organization_name_map(session, row.project_id)
        data = organization_service.serialize_org_relation(row, names)
    return ok(data)


@router.delete("/org-relations/{rid}")
def delete_org_relation(request: Request, rid: int) -> dict:
    """§6.2 #79（DELETE）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = organization_service.delete_org_relation(session, rid)
    return ok(data)
