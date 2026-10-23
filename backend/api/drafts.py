"""暂存接口（任务 2.4 / BR-2；§6.2 未列，按 S2-09 补入）。

POST   /drafts              保存/覆盖某章节暂存
GET    /drafts              暂存列表（摘要，按时间倒序）
GET    /drafts/{cid}        暂存详情（含正文 HTML）
DELETE /drafts/{cid}        删除暂存

章节正文保存成功后，`PUT /chapters/{cid}/content` 会自动清理该章节暂存。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..config import AppConfig
from ..database import Database
from ..models import Chapter, Project, Volume, session_scope
from ..schemas import CODE_NOT_FOUND, ApiError, ok
from ..services import chapter_service, drafts

router = APIRouter(tags=["drafts"])


class DraftSave(BaseModel):
    """保存暂存入参。"""

    chapter_id: int
    content_html: str = ""
    client_saved_at: str | None = None
    reason: str | None = Field(default=None, max_length=200)


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


def _config(request: Request) -> AppConfig:
    return request.app.state.config


@router.post("/drafts")
def save_draft(request: Request, payload: DraftSave) -> dict:
    """保存（覆盖）暂存；章节必须存在。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        chapter = chapter_service.require_chapter(session, payload.chapter_id)
        title = chapter.title
    data = drafts.save_draft(
        _config(request).data_dir,
        chapter_id=payload.chapter_id,
        title=title,
        content_html=payload.content_html,
        client_saved_at=payload.client_saved_at,
        reason=payload.reason,
    )
    return ok(data)


@router.get("/drafts")
def list_drafts(request: Request) -> dict:
    """暂存列表：返回摘要，不回传正文。

    额外带上 ``project_id`` / ``project_title``（阶段三 3.3）：项目列表的暂存横幅
    需要能一键直达对应作品。归属链为 章节 → 卷 → 项目，任一环节已软删除或不存在
    时不填这两个字段，前端据此把该条标为「不可直达」。
    """
    config = _config(request)
    database = _database(request)
    items = drafts.list_drafts(config.data_dir)

    # 标题以数据库为准（暂存里的标题只是快照），章节被删则保留快照标题
    with session_scope(database.engine) as session:
        for item in items:
            chapter = session.get(Chapter, int(item["chapter_id"]))
            if chapter is None or chapter.is_deleted:
                continue
            item["title"] = chapter.title
            volume = session.get(Volume, chapter.volume_id)
            if volume is None or volume.is_deleted:
                continue
            project = session.get(Project, volume.project_id)
            if project is None or project.is_deleted:
                continue
            item["project_id"] = project.id
            item["project_title"] = project.title
    return ok({"items": items, "total": len(items)})


@router.get("/drafts/{cid}")
def get_draft(request: Request, cid: int) -> dict:
    """暂存详情（含正文 HTML）；不存在 → 2001。"""
    data = drafts.get_draft(_config(request).data_dir, cid)
    if data is None:
        raise ApiError(CODE_NOT_FOUND, "暂存不存在")
    return ok(data)


@router.delete("/drafts/{cid}")
def delete_draft(request: Request, cid: int) -> dict:
    """删除暂存；不存在 → 2001。"""
    if not drafts.delete_draft(_config(request).data_dir, cid):
        raise ApiError(CODE_NOT_FOUND, "暂存不存在")
    return ok({"chapter_id": cid, "deleted": True})
