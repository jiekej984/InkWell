"""卷章接口（§6.2 #10~#17 / #22，任务 2.2）。

GET    /projects/{pid}/volumes            卷列表 + 章节树（默认卷单列）
POST   /projects/{pid}/volumes            新建卷
POST   /projects/{pid}/volumes/reorder    卷排序（BR-3）
PATCH  /volumes/{vid}                     改卷名/梗概（默认卷拒绝）
DELETE /volumes/{vid}?mode=move|cascade   删卷（非空卷必须二选一）
GET    /volumes/{vid}/chapters            章节列表
POST   /volumes/{vid}/chapters            新建章节
POST   /volumes/{vid}/chapters/reorder    章节排序 / 跨卷移动（BR-3）
POST   /volumes/{vid}/adopt-default       把默认卷章节迁入首个命名卷（C-04）
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from ..database import Database
from ..models import session_scope
from ..schemas import CODE_NOT_FOUND, ApiError, ok
from ..services import chapter_service
from ..timeutil import iso

router = APIRouter(tags=["volumes"])


class VolumeCreate(BaseModel):
    """新建卷入参。"""

    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=5000)


class VolumeUpdate(BaseModel):
    """局部更新卷；``None`` 表示不修改。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=5000)


class VolumeReorder(BaseModel):
    """卷排序：拖拽到 ``prev_id`` 与 ``next_id`` 之间（都为空 = 末尾）。"""

    volume_id: int
    prev_id: int | None = None
    next_id: int | None = None


class ChapterCreate(BaseModel):
    """新建章节入参。"""

    title: str = Field(min_length=1, max_length=200)
    status: str | None = "draft"
    summary: str | None = Field(default=None, max_length=5000)
    target_word_count: int | None = 0


class ChapterReorder(BaseModel):
    """章节排序 / 跨卷移动。"""

    chapter_id: int
    prev_id: int | None = None
    next_id: int | None = None
    target_volume_id: int | None = None


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


# --------------------------------------------------------------------------
# 卷
# --------------------------------------------------------------------------


@router.get("/projects/{pid}/volumes")
def list_volumes(request: Request, pid: int) -> dict:
    """§6.2 #10：卷列表 + 章节树（仅元数据；默认卷单列，BR-6）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        tree = chapter_service.list_volume_tree(session, pid)
    return ok(tree)


@router.post("/projects/{pid}/volumes")
def create_volume(request: Request, pid: int, payload: VolumeCreate) -> dict:
    """§6.2 #11：新建卷，自动排在现有卷之后。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        volume = chapter_service.create_volume(
            session, pid, title=payload.title, summary=payload.summary
        )
        data = chapter_service.serialize_volume(volume, ())
    return ok(data)


@router.post("/projects/{pid}/volumes/reorder")
def reorder_volumes(request: Request, pid: int, payload: VolumeReorder) -> dict:
    """§6.2 #14：卷排序（BR-3）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        volume = chapter_service.reorder_volume(
            session,
            pid,
            payload.volume_id,
            prev_id=payload.prev_id,
            next_id=payload.next_id,
        )
        data = {
            "id": volume.id,
            "order_index": volume.order_index,
            "updated_at": iso(volume.updated_at),
        }
    return ok(data)


@router.patch("/volumes/{vid}")
def update_volume(request: Request, vid: int, payload: VolumeUpdate) -> dict:
    """§6.2 #12：改卷名/梗概；默认卷拒绝（BR-6）。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    with session_scope(database.engine) as session:
        volume = chapter_service.update_volume(session, vid, **fields)
        tree = chapter_service.list_volume_tree(session, volume.project_id)
        data = next(
            (item for item in tree["volumes"] if item["id"] == vid),
            tree["default_volume"],
        )
    return ok(data)


@router.delete("/volumes/{vid}")
def delete_volume(
    request: Request,
    vid: int,
    mode: str | None = Query(
        default=None,
        description="非空卷删除方式：move=章节移入默认卷，cascade=章节一并删除",
    ),
) -> dict:
    """§6.2 #13：删卷（BR-4 / FR-2.1）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        result = chapter_service.delete_volume(session, vid, mode)
    return ok(result)


# --------------------------------------------------------------------------
# 章节
# --------------------------------------------------------------------------


@router.get("/volumes/{vid}/chapters")
def list_chapters(request: Request, vid: int) -> dict:
    """§6.2 #16：章节列表（仅元数据）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = chapter_service.list_chapters(session, vid)
    return ok(data)


@router.post("/volumes/{vid}/chapters")
def create_chapter(request: Request, vid: int, payload: ChapterCreate) -> dict:
    """§6.2 #17：新建章节。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        chapter = chapter_service.create_chapter(
            session,
            vid,
            title=payload.title,
            status=payload.status,
            summary=payload.summary,
            target_word_count=payload.target_word_count,
        )
        data = chapter_service.serialize_chapter_meta(chapter)
    return ok(data)


@router.post("/volumes/{vid}/chapters/reorder")
def reorder_chapters(request: Request, vid: int, payload: ChapterReorder) -> dict:
    """§6.2 #22：章节排序 / 跨卷移动（BR-3）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        chapter = chapter_service.reorder_chapter(
            session,
            vid,
            payload.chapter_id,
            prev_id=payload.prev_id,
            next_id=payload.next_id,
            target_volume_id=payload.target_volume_id,
        )
        data = chapter_service.serialize_chapter_meta(chapter)
    return ok(data)


@router.post("/volumes/{vid}/adopt-default")
def adopt_default_chapters(request: Request, vid: int) -> dict:
    """C-04（§6.2 未列）：首个命名卷创建后，把默认卷章节一次性迁入。

    仅当目标卷是该项目唯一命名卷时允许；否则返回 1001。
    """
    database = _database(request)
    with session_scope(database.engine) as session:
        data = chapter_service.adopt_default_chapters(session, vid)
    return ok(data)
