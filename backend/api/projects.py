"""项目接口（§6.2 #3~#9，任务 2.1）。

GET    /projects              项目列表
POST   /projects              新建项目（自动建默认卷，BR-6）
GET    /projects/{pid}        详情
PATCH  /projects/{pid}        改信息与状态
DELETE /projects/{pid}        软删除（级联卷/章/文档，BR-4）
POST   /projects/{pid}/cover  上传/换封面
GET    /projects/{pid}/stats  统计
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Request, UploadFile
from pydantic import BaseModel, Field

from ..config import AppConfig
from ..database import Database
from ..models import session_scope
from ..schemas import CODE_FILE_INVALID, CODE_NOT_FOUND, ApiError, ok
from ..services import project_service
from ..storage import atomic_write_bytes, resolve_path

router = APIRouter(tags=["projects"])

# BR-5：图片白名单与单张上限（封面复用同一约束）
ALLOWED_COVER_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
MAX_COVER_BYTES = 10 * 1024 * 1024
_PIL_FORMATS = {"JPEG", "PNG", "WEBP"}
_PIL_EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


class ProjectCreate(BaseModel):
    """新建项目入参。"""

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: str | None = "writing"
    target_word_count: int | None = 0
    tags: list[str] | None = None


class ProjectUpdate(BaseModel):
    """局部更新入参；``None`` 表示不修改该字段。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: str | None = None
    target_word_count: int | None = None
    last_chapter_id: int | None = None
    tags: list[str] | None = None


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


def _config(request: Request) -> AppConfig:
    return request.app.state.config


# --------------------------------------------------------------------------
# #3 / #4 / #5 / #6 / #7
# --------------------------------------------------------------------------


@router.get("/projects")
def list_projects(request: Request) -> dict:
    """项目列表（活跃，按更新时间倒序）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        projects = project_service.list_projects(session)
        tag_map = project_service.tags_of(session, [p.id for p in projects])
        items = [
            project_service.serialize_project(p, tag_map.get(p.id, ()))
            for p in projects
        ]
    return ok({"items": items, "total": len(items)})


@router.post("/projects")
def create_project(request: Request, payload: ProjectCreate) -> dict:
    """新建项目；自动创建默认卷（BR-6），项目名允许重复（FR-1.7）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        project = project_service.create_project(
            session,
            title=payload.title,
            description=payload.description,
            status=payload.status,
            target_word_count=payload.target_word_count,
            tag_names=payload.tags,
        )
        session.flush()
        tags = project_service.tags_of(session, [project.id]).get(project.id, ())
        data = project_service.serialize_project(project, tags)
    return ok(data)


@router.get("/projects/{pid}")
def get_project(request: Request, pid: int) -> dict:
    """项目详情；同时记录「最近打开时间」（FR-1.3 卡片展示 / FR-1.5 定位）。

    详情接口是前端「打开项目」的唯一入口（写作页 `openWriter` 先取详情），
    因此最近打开时间的更新点放在这里，不额外增加接口。只写
    ``last_opened_at``，不触碰 ``updated_at``，避免影响列表的更新时间序。
    """
    database = _database(request)
    with session_scope(database.engine) as session:
        project = project_service.require_project(session, pid)
        project_service.touch_opened(session, pid)
        tags = project_service.tags_of(session, [pid]).get(pid, ())
        data = project_service.serialize_project(project, tags)
    return ok(data)


@router.patch("/projects/{pid}")
def update_project(request: Request, pid: int, payload: ProjectUpdate) -> dict:
    database = _database(request)
    fields = payload.model_dump(exclude_unset=True)
    if "tags" in fields:
        fields["tag_names"] = fields.pop("tags")

    with session_scope(database.engine) as session:
        project = project_service.update_project(session, pid, **fields)
        session.flush()
        tags = project_service.tags_of(session, [pid]).get(pid, ())
        data = project_service.serialize_project(project, tags)
    return ok(data)


@router.delete("/projects/{pid}")
def delete_project(request: Request, pid: int) -> dict:
    """软删除（BR-4）：级联卷 / 章 / 设定文档，可在回收站恢复（2.8）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        counts = project_service.soft_delete_project(session, pid)
    return ok({"id": pid, "deleted": True, "cascaded": counts})


# --------------------------------------------------------------------------
# #8 封面
# --------------------------------------------------------------------------


def _validate_cover(payload: bytes, filename: str | None) -> str:
    """校验封面，返回规范化扩展名（不含点）；非法抛 4002。"""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_COVER_EXTENSIONS:
        raise ApiError(
            CODE_FILE_INVALID,
            f"封面格式必须是 {'/'.join(ALLOWED_COVER_EXTENSIONS)} 之一",
        )
    if not payload:
        raise ApiError(CODE_FILE_INVALID, "封面文件为空")
    if len(payload) > MAX_COVER_BYTES:
        raise ApiError(CODE_FILE_INVALID, "封面文件不能超过 10MB")

    # 用 Pillow 校验真实格式，防止扩展名伪装；落盘扩展名取**真实格式**，
    # 避免 JPEG 内容存成 .png 后以错误的 Content-Type 提供
    try:
        from PIL import Image

        with Image.open(BytesIO(payload)) as image:
            if image.format not in _PIL_FORMATS:
                raise ApiError(CODE_FILE_INVALID, "封面文件内容与扩展名不符")
            return _PIL_EXTENSIONS[image.format]
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(CODE_FILE_INVALID, "封面文件无法解析") from exc


@router.post("/projects/{pid}/cover")
def upload_cover(request: Request, pid: int, file: UploadFile = File(...)) -> dict:
    """上传/换封面：存 ``covers/``，库内只存**相对路径**（BR-5）。"""
    config = _config(request)
    database = _database(request)

    payload = file.file.read()
    extension = _validate_cover(payload, file.filename)
    # 用随机串而非时间戳：同一秒内连续换封面会产生同名文件，导致旧文件被覆盖
    relpath = f"covers/cover_{pid}_{uuid4().hex[:12]}.{extension}"

    with session_scope(database.engine) as session:
        project_service.require_project(session, pid)  # 提前校验存在性
    target = resolve_path(config.data_dir, relpath)
    if target is None:  # pragma: no cover - relpath 由本函数生成
        raise ApiError(CODE_FILE_INVALID, "封面路径非法")
    atomic_write_bytes(target, payload)

    with session_scope(database.engine) as session:
        _, previous = project_service.set_cover(session, pid, relpath)

    # 删除被替换掉的旧封面（限于 covers/ 内，避免越界删除）
    if previous and previous != relpath:
        old_path = resolve_path(config.data_dir, previous)
        if old_path is not None and old_path != target and old_path.exists():
            old_path.unlink()

    return ok({"cover_path": relpath, "size": len(payload)})


# --------------------------------------------------------------------------
# #9 统计
# --------------------------------------------------------------------------


@router.get("/projects/{pid}/stats")
def project_stats(request: Request, pid: int) -> dict:
    database = _database(request)
    with session_scope(database.engine) as session:
        stats = project_service.project_stats(session, pid)
    return ok(stats)
