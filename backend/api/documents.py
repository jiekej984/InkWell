"""设定文档接口（§6.2 #28~#30，任务 2.7）。

GET    /projects/{pid}/documents        文档列表（可按 category 筛选）
POST   /projects/{pid}/documents        新建文档
GET    /documents/{did}                 文档详情（正文图片签名）
PATCH  /documents/{did}                 改标题/分类/正文/排序
DELETE /documents/{did}                 软删除
POST   /documents/{did}/images          文档图片上传（§6.2 未列，见 S2-11）
"""

from __future__ import annotations

from fastapi import APIRouter, File, Query, Request, UploadFile
from pydantic import BaseModel, Field

from ..config import AppConfig
from ..database import Database
from ..models import session_scope
from ..schemas import CODE_NOT_FOUND, ApiError, ok
from ..services import document_service, media
from ..storage import sign

router = APIRouter(tags=["documents"])


class DocumentCreate(BaseModel):
    """新建文档入参。"""

    title: str = Field(min_length=1, max_length=200)
    category: str = "other"
    content_html: str = ""


class DocumentUpdate(BaseModel):
    """局部更新文档；``None`` 表示不修改。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = None
    content_html: str | None = None
    order_index: int | None = None


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


def _config(request: Request) -> AppConfig:
    return request.app.state.config


@router.get("/projects/{pid}/documents")
def list_documents(
    request: Request,
    pid: int,
    category: str | None = Query(default=None, description="按分类筛选"),
) -> dict:
    """§6.2 #28：文档列表（仅元数据，可按分类筛选）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = document_service.list_documents(session, pid, category)
    return ok(data)


@router.post("/projects/{pid}/documents")
def create_document(request: Request, pid: int, payload: DocumentCreate) -> dict:
    """§6.2 #29：新建设定文档。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        document = document_service.create_document(
            session,
            pid,
            title=payload.title,
            category=payload.category,
            content_html=payload.content_html,
        )
        data = document_service.serialize_document_meta(document)
    return ok(data)


@router.get("/documents/{did}")
def get_document(request: Request, did: int) -> dict:
    """§6.2 #30（GET）：文档详情。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = document_service.get_document_detail(session, did)
    return ok(data)


@router.patch("/documents/{did}")
def update_document(request: Request, did: int, payload: DocumentUpdate) -> dict:
    """§6.2 #30（PATCH）：改标题/分类/正文/排序。"""
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    with session_scope(database.engine) as session:
        document = document_service.update_document(session, did, **fields)
        data = document_service.get_document_detail(session, document.id)
    return ok(data)


@router.delete("/documents/{did}")
def delete_document(request: Request, did: int) -> dict:
    """§6.2 #30（DELETE）：软删除（BR-4）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = document_service.delete_document(session, did)
    return ok(data)


@router.post("/documents/{did}/images")
def upload_document_image(
    request: Request, did: int, file: UploadFile = File(...)
) -> dict:
    """文档图片上传（§6.2 未列，决策 S2-11）：落 ``media/documents/{did}/``。"""
    config = _config(request)
    database = _database(request)

    with session_scope(database.engine) as session:
        document_service.require_document(session, did)

    payload = file.file.read()
    relpath = media.save_document_image(config.data_dir, did, payload, file.filename)
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
