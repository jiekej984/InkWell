"""章节接口（§6.2 #18~#21，任务 2.3）。

GET    /chapters/{cid}            章节详情（正文图片返回签名 URL）
PATCH  /chapters/{cid}            改标题/状态/梗概/目标字数
PUT    /chapters/{cid}/content    正文保存（消毒 + 字数 + 乐观锁）
DELETE /chapters/{cid}            软删除
POST   /chapters/{cid}/images     正文图片上传（§6.2 未列，见 S2-08）
"""

from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel, Field

from ..config import AppConfig
from ..database import Database
from ..models import session_scope
from ..schemas import CODE_NOT_FOUND, ApiError, ok
from ..services import chapter_service, drafts, media
from ..storage import sign

router = APIRouter(tags=["chapters"])


class ChapterUpdate(BaseModel):
    """局部更新章节；``None`` 表示不修改。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: str | None = None
    summary: str | None = Field(default=None, max_length=5000)
    target_word_count: int | None = None


class ChapterContent(BaseModel):
    """正文保存入参（§6.3）。"""

    content_html: str = ""
    client_saved_at: str | None = None
    expect_version: int | None = None


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


def _config(request: Request) -> AppConfig:
    return request.app.state.config


@router.get("/chapters/{cid}")
def get_chapter(request: Request, cid: int) -> dict:
    """§6.2 #18：章节详情。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = chapter_service.get_chapter_detail(session, cid)
    return ok(data)


@router.patch("/chapters/{cid}")
def update_chapter(request: Request, cid: int, payload: ChapterUpdate) -> dict:
    """§6.2 #19：改标题/状态/梗概/目标字数。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    with session_scope(database.engine) as session:
        chapter = chapter_service.update_chapter(session, cid, **fields)
        data = chapter_service.serialize_chapter_meta(chapter)
    return ok(data)


@router.put("/chapters/{cid}/content")
def save_chapter_content(request: Request, cid: int, payload: ChapterContent) -> dict:
    """§6.2 #20：正文保存（消毒 + 乐观锁 + 字数）。

    冲突 → **3002**；前端须先把内容落到本地暂存再提示刷新（BR-2）。
    """
    database = _database(request)
    with session_scope(database.engine) as session:
        data = chapter_service.save_chapter_content(
            session,
            cid,
            content_html=payload.content_html,
            expect_version=payload.expect_version,
            client_saved_at=payload.client_saved_at,
        )
    # 保存成功后清理该章节暂存（BR-2：暂存只在失败/冲突时存在）
    drafts.delete_draft(_config(request).data_dir, cid)
    return ok(data)


@router.delete("/chapters/{cid}")
def delete_chapter(request: Request, cid: int) -> dict:
    """§6.2 #21：软删除章节（BR-4）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = chapter_service.delete_chapter(session, cid)
    return ok(data)


@router.post("/chapters/{cid}/images")
def upload_chapter_image(
    request: Request, cid: int, file: UploadFile = File(...)
) -> dict:
    """正文图片上传（§6.2 未列接口，决策 S2-08）。

    · 白名单 jpg/png/webp、≤10MB、Pillow 校验真实格式（BR-5）
    · 落 ``media/{cid}/{uuid}.{ext}``，返回相对路径与 30 分钟签名 URL
    """
    config = _config(request)
    database = _database(request)

    with session_scope(database.engine) as session:
        chapter_service.require_chapter(session, cid)  # 先校验章节存在

    payload = file.file.read()
    relpath = media.save_chapter_image(config.data_dir, cid, payload, file.filename)
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
