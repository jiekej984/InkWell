"""角色库接口（V2.0 / 任务 5.3；§6.2 #54~#67、#80~#81）。

GET    /projects/{pid}/characters/meta          枚举与中文标签
GET    /projects/{pid}/characters               列表（搜索/筛选/分页）
POST   /projects/{pid}/characters               新建
GET    /characters/{cid}                        详情（别名/字段/关系/组织身份）
PATCH  /characters/{cid}                        局部更新
DELETE /characters/{cid}?force=                 软删 / 彻底删除
PUT    /characters/{cid}/aliases                整体替换别名
GET/POST /characters/{cid}/fields               自定义字段
PATCH/DELETE /fields/{fid}                      自定义字段改删
POST   /characters/{cid}/avatar                 立绘上传（转 512px webp）
GET/POST /characters/{cid}/relations            角色关系
PATCH/DELETE /relations/{rid}                   关系改删
GET    /projects/{pid}/graph                    三模式统一图数据
GET/PUT /projects/{pid}/graph/layout            画布布局
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Query, Request, UploadFile
from pydantic import BaseModel, Field

from ..config import AppConfig
from ..database import Database
from ..models import session_scope
from ..schemas import CODE_NOT_FOUND, ApiError, ok
from ..services import (
    appearance_service,
    character_meta,
    character_service,
    graph_service,
    media,
    relation_service,
)
from ..storage import sign

router = APIRouter(tags=["characters"])


# --------------------------------------------------------------------------
# 入参
# --------------------------------------------------------------------------


class CharacterCreate(BaseModel):
    """新建角色（除姓名外都可空，便于「先建人、后补档」）。"""

    name: str = Field(min_length=1, max_length=100)
    role: str | None = None
    status: str | None = None
    gender: str | None = None
    age: str | None = None
    height: str | None = None
    appearance: str | None = None
    personality: str | None = None
    background: str | None = None
    abilities: str | None = None
    catchphrase: str | None = None
    motivation: str | None = None
    note: str | None = None
    tags: list[str] | None = None
    avatar_path: str | None = None
    order_index: int | None = None


class CharacterUpdate(BaseModel):
    """局部更新；字段未出现 = 不修改。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    role: str | None = None
    status: str | None = None
    gender: str | None = None
    age: str | None = None
    height: str | None = None
    appearance: str | None = None
    personality: str | None = None
    background: str | None = None
    abilities: str | None = None
    catchphrase: str | None = None
    motivation: str | None = None
    note: str | None = None
    tags: list[str] | None = None
    avatar_path: str | None = None
    order_index: int | None = None


class AliasesPayload(BaseModel):
    """整体替换别名；``force`` 仅用于跳过「与别的角色姓名冲突」。"""

    aliases: list[str] = Field(default_factory=list, max_length=30)
    force: bool = False


class FieldCreate(BaseModel):
    key: str = Field(min_length=1, max_length=50)
    value: Any = None
    field_type: str = "text"
    order_index: int | None = None


class FieldUpdate(BaseModel):
    key: str | None = Field(default=None, min_length=1, max_length=50)
    value: Any = None
    field_type: str | None = None
    order_index: int | None = None


class RelationCreate(BaseModel):
    to_id: int
    relation_type: str = "other"
    custom_label: str | None = None
    description: str | None = None
    is_bidirectional: bool | None = None
    is_secret: bool = False
    from_chapter_id: int | None = None
    to_chapter_id: int | None = None


class RelationUpdate(BaseModel):
    relation_type: str | None = None
    custom_label: str | None = None
    description: str | None = None
    is_bidirectional: bool | None = None
    is_secret: bool | None = None
    from_chapter_id: int | None = None
    to_chapter_id: int | None = None


class LayoutPayload(BaseModel):
    payload: dict[str, Any]
    expected_updated_at: str | None = None


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


def _config(request: Request) -> AppConfig:
    return request.app.state.config


# --------------------------------------------------------------------------
# #54~#60
# --------------------------------------------------------------------------


@router.get("/projects/{pid}/characters/meta")
def character_meta_payload() -> dict:
    """§6.2 #54：定位 / 状态 / 关系 20 类 / 组织类型 / 字段类型等全部枚举。"""
    return ok(character_meta.meta_payload())


@router.get("/projects/{pid}/characters")
def list_characters(
    request: Request,
    pid: int,
    keyword: str | None = Query(default=None),
    role: str | None = Query(default=None),
    org_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    sort: str = Query(default="order"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    """§6.2 #55：角色列表。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = character_service.list_characters(
            session,
            pid,
            keyword=keyword,
            role=role,
            org_id=org_id,
            status=status,
            sort=sort,
            page=page,
            page_size=page_size,
        )
    return ok(data)


@router.post("/projects/{pid}/characters")
def create_character(request: Request, pid: int, payload: CharacterCreate) -> dict:
    """§6.2 #56：新建角色。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    fields.pop("name", None)
    with session_scope(database.engine) as session:
        character = character_service.create_character(
            session, pid, name=payload.name, **fields
        )
        data = character_service.serialize_character(character)
    return ok(data)


@router.get("/characters/{cid}")
def get_character(request: Request, cid: int) -> dict:
    """§6.2 #57：角色详情（别名 / 字段 / 关系 / 组织身份）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = character_service.get_character_detail(session, cid)
    return ok(data)


@router.get("/characters/{cid}/appearances")
def get_character_appearances(request: Request, cid: int) -> dict:
    """FR-8.23：按章聚合角色姓名与别名在正文中的出场位置。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = appearance_service.search_appearances(session, cid)
    return ok(data)


@router.patch("/characters/{cid}")
def update_character(request: Request, cid: int, payload: CharacterUpdate) -> dict:
    """§6.2 #58：局部更新（字段级保存）。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    with session_scope(database.engine) as session:
        character_service.update_character(session, cid, **fields)
        data = character_service.get_character_detail(session, cid)
    return ok(data)


@router.delete("/characters/{cid}")
def delete_character(
    request: Request,
    cid: int,
    force: bool = Query(default=False, description="true 时彻底删除"),
) -> dict:
    """§6.2 #59：软删除（进回收站）或彻底删除。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = character_service.delete_character(session, cid, force=force)
    return ok(data)


@router.put("/characters/{cid}/aliases")
def set_aliases(request: Request, cid: int, payload: AliasesPayload) -> dict:
    """§6.2 #60：整体替换别名。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        aliases = character_service.set_aliases(
            session, cid, payload.aliases, force=payload.force
        )
    return ok({"character_id": cid, "aliases": aliases})


# --------------------------------------------------------------------------
# #61~#63 自定义字段与立绘
# --------------------------------------------------------------------------


@router.get("/characters/{cid}/fields")
def list_fields(request: Request, cid: int) -> dict:
    """§6.2 #61（GET）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        detail = character_service.get_character_detail(session, cid)
    return ok({"character_id": cid, "items": detail["fields"]})


@router.post("/characters/{cid}/fields")
def add_field(request: Request, cid: int, payload: FieldCreate) -> dict:
    """§6.2 #61（POST）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        field = character_service.add_field(
            session,
            cid,
            key=payload.key,
            value=payload.value,
            field_type=payload.field_type,
            order_index=payload.order_index,
        )
        data = {
            "id": field.id,
            "key": field.key,
            "value": field.value,
            "field_type": field.field_type,
            "order_index": field.order_index,
        }
    return ok(data)


@router.patch("/fields/{fid}")
def update_field(request: Request, fid: int, payload: FieldUpdate) -> dict:
    """§6.2 #62（PATCH）。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    with session_scope(database.engine) as session:
        field = character_service.update_field(session, fid, **fields)
        data = {
            "id": field.id,
            "key": field.key,
            "value": field.value,
            "field_type": field.field_type,
            "order_index": field.order_index,
        }
    return ok(data)


@router.delete("/fields/{fid}")
def delete_field(request: Request, fid: int) -> dict:
    """§6.2 #62（DELETE）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = character_service.delete_field(session, fid)
    return ok(data)


@router.post("/characters/{cid}/avatar")
def upload_avatar(request: Request, cid: int, file: UploadFile = File(...)) -> dict:
    """§6.2 #63：立绘上传（居中裁方形 → 512px webp）。"""
    config = _config(request)
    database = _database(request)
    with session_scope(database.engine) as session:
        character_service.require_character(session, cid)

    payload = file.file.read()
    relpath = media.save_avatar(config.data_dir, cid, payload, file.filename)

    with session_scope(database.engine) as session:
        character_service.update_character(session, cid, avatar_path=relpath)

    signature = sign(relpath)
    if signature is None:  # pragma: no cover - relpath 由服务端生成
        raise ApiError(CODE_NOT_FOUND, "图片路径非法")
    return ok(
        {
            "path": relpath,
            "url": f"/files/{relpath}?sig={signature}",
            "size": len(payload),
        }
    )


# --------------------------------------------------------------------------
# #65~#67 关系
# --------------------------------------------------------------------------


@router.get("/characters/{cid}/relations")
def list_relations(
    request: Request,
    cid: int,
    include_expired: bool = Query(default=True),
) -> dict:
    """§6.2 #67：某角色的关系列表。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = relation_service.list_character_relations(
            session, cid, include_expired=include_expired
        )
    return ok(data)


@router.post("/characters/{cid}/relations")
def create_relation(request: Request, cid: int, payload: RelationCreate) -> dict:
    """§6.2 #65：新建角色关系。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        row = relation_service.create_character_relation(
            session,
            cid,
            to_id=payload.to_id,
            relation_type=payload.relation_type,
            custom_label=payload.custom_label,
            description=payload.description,
            is_bidirectional=payload.is_bidirectional,
            is_secret=payload.is_secret,
            from_chapter_id=payload.from_chapter_id,
            to_chapter_id=payload.to_chapter_id,
        )
        data = relation_service.serialize_relation(row)
    return ok(data)


@router.patch("/relations/{rid}")
def update_relation(request: Request, rid: int, payload: RelationUpdate) -> dict:
    """§6.2 #66（PATCH）。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    with session_scope(database.engine) as session:
        row = relation_service.update_character_relation(session, rid, **fields)
        data = relation_service.serialize_relation(row)
    return ok(data)


@router.delete("/relations/{rid}")
def delete_relation(request: Request, rid: int) -> dict:
    """§6.2 #66（DELETE）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = relation_service.delete_character_relation(session, rid)
    return ok(data)


# --------------------------------------------------------------------------
# #64 图数据 / #80~#81 布局
# --------------------------------------------------------------------------


@router.get("/projects/{pid}/graph")
def get_graph(
    request: Request,
    pid: int,
    mode: str = Query(default="character"),
    faction_id: int | None = Query(default=None),
    org_id: int | None = Query(default=None),
    center_id: int | None = Query(default=None),
    depth: int = Query(default=2, ge=1, le=3),
    chapter_id: int | None = Query(default=None),
    include_expired: bool = Query(default=False),
    limit: int = Query(default=80, ge=1, le=80),
) -> dict:
    """§6.2 #64：三模式统一图数据。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = graph_service.build_graph(
            session,
            pid,
            mode=mode,
            faction_id=faction_id,
            org_id=org_id,
            center_id=center_id,
            depth=depth,
            chapter_id=chapter_id,
            include_expired=include_expired,
            limit=limit,
        )
    return ok(data)


@router.get("/projects/{pid}/graph/layout")
def get_layout(request: Request, pid: int) -> dict:
    """§6.2 #80：读布局。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = graph_service.get_layout(session, pid)
    return ok(data)


@router.put("/projects/{pid}/graph/layout")
def save_layout(request: Request, pid: int, payload: LayoutPayload) -> dict:
    """§6.2 #81：保存布局（按模式合并；``updated_at`` 不一致返回 3002）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = graph_service.save_layout(
            session,
            pid,
            payload.payload,
            expected_updated_at=payload.expected_updated_at,
        )
    return ok(data)
