"""版本快照接口（§6.2 #23~#27，任务 2.6）。

GET    /chapters/{cid}/versions                 版本列表（新→旧）
GET    /versions/{vid}                          版本详情（含正文，图片签名）
POST   /chapters/{cid}/versions                 手动/里程碑快照
POST   /chapters/{cid}/versions/{vid}/restore   回滚（先存 restore 快照，再覆盖正文）
DELETE /versions/{vid}                          删除快照（物理删除）
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..database import Database
from ..models import session_scope
from ..schemas import CODE_NOT_FOUND, ApiError, ok
from ..services import chapter_service, version_service

router = APIRouter(tags=["versions"])


class VersionCreate(BaseModel):
    """手动快照入参；缺省为 manual。"""

    change_type: str = "manual"


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


@router.get("/chapters/{cid}/versions")
def list_versions(request: Request, cid: int) -> dict:
    """§6.2 #23：版本列表（倒序，含字数差异）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        chapter_service.require_chapter(session, cid)
        rows = version_service.list_versions(session, cid)
        items = [version_service.serialize_version(row) for row in rows]
    return ok({"chapter_id": cid, "items": items, "total": len(items)})


@router.get("/versions/{vid}")
def get_version(request: Request, vid: int) -> dict:
    """§6.2 #24：版本详情（含正文，图片临时签名）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        row = version_service.require_version(session, vid)
        data = version_service.serialize_version_detail(row)
    return ok(data)


@router.post("/chapters/{cid}/versions")
def create_version(
    request: Request,
    cid: int,
    payload: VersionCreate | None = None,
) -> dict:
    """§6.2 #25：手动 / 里程碑快照（永久保留）。"""
    database = _database(request)
    change_type = payload.change_type if payload is not None else "manual"
    with session_scope(database.engine) as session:
        chapter = chapter_service.require_chapter(session, cid)
        row = version_service.create_snapshot(session, chapter, change_type)
        data = version_service.serialize_version(row)
    return ok(data)


@router.post("/chapters/{cid}/versions/{vid}/restore")
def restore_version(request: Request, cid: int, vid: int) -> dict:
    """§6.2 #26：回滚到指定版本（版本号递增，回滚前内容永久保留）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        chapter = chapter_service.require_chapter(session, cid)
        data = version_service.restore_version(session, chapter, vid)
    return ok(data)


@router.delete("/versions/{vid}")
def delete_version(request: Request, vid: int) -> dict:
    """§6.2 #27：删除快照（物理删，非回收站语义）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = version_service.delete_version(session, vid)
    return ok({**data, "deleted": True})
