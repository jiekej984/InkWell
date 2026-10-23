"""项目业务逻辑（任务 2.1 / FR-1）。

对应 FR-1.1~1.8、BR-4（项目级联软删）、BR-6（默认卷）、§6.2 #3~#9。

设计约定：
    · 本模块为**纯业务函数**，接收 ``Session``、不自己开事务，便于单测（NFR-M1）
    · 时间统一走 :func:`backend.timeutil.utc_now`（BR-8：持久化用 UTC）
    · 错误一律抛 :class:`backend.schemas.ApiError`，由统一异常处理器转成响应
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import (
    Chapter,
    Document,
    Project,
    ProjectTag,
    Tag,
    Volume,
    active,
)
from ..schemas import (
    CODE_DELETED,
    CODE_NOT_FOUND,
    CODE_PARAM_INVALID,
    ApiError,
)
from ..timeutil import iso, utc_now

# BR-6：新建项目自动创建默认卷；order_index 固定 0；不可删、不可重命名
DEFAULT_VOLUME_TITLE = "默认卷"
DEFAULT_VOLUME_ORDER_INDEX = 0

PROJECT_STATUSES = ("writing", "paused", "finished")
MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5000


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------


def _clean_title(title: str | None) -> str:
    value = (title or "").strip()
    if not value:
        raise ApiError(CODE_PARAM_INVALID, "书名不能为空")
    if len(value) > MAX_TITLE_LENGTH:
        raise ApiError(
            CODE_PARAM_INVALID, f"书名长度不能超过 {MAX_TITLE_LENGTH} 个字符"
        )
    # FR-1.7：项目名允许重复，这里**故意不做**唯一性校验
    return value


def _clean_description(description: str | None) -> str | None:
    if description is None:
        return None
    value = description.strip()
    if len(value) > MAX_DESCRIPTION_LENGTH:
        raise ApiError(
            CODE_PARAM_INVALID, f"简介长度不能超过 {MAX_DESCRIPTION_LENGTH} 个字符"
        )
    return value or None


def _clean_status(status: str | None) -> str:
    value = (status or "writing").strip()
    if value not in PROJECT_STATUSES:
        raise ApiError(
            CODE_PARAM_INVALID,
            f"项目状态必须是 {'/'.join(PROJECT_STATUSES)} 之一",
        )
    return value


def _clean_target(value: int | None) -> int:
    if value is None:
        return 0
    if value < 0:
        raise ApiError(CODE_PARAM_INVALID, "目标字数不能为负数")
    return int(value)


def _clean_tag_names(names: Iterable[str] | None) -> list[str]:
    """清洗标签名：去空、去重、保序。"""
    if names is None:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = (raw or "").strip()
        if not name or name in seen:
            continue
        if len(name) > 50:
            raise ApiError(CODE_PARAM_INVALID, "单个标签名不能超过 50 个字符")
        seen.add(name)
        result.append(name)
    return result


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------


def require_project(session: Session, project_id: int) -> Project:
    """按 id 取活跃项目；不存在 → 2001，已删除 → 2002。"""
    project = session.execute(
        select(Project).where(Project.id == project_id)
    ).scalar_one_or_none()
    if project is None:
        raise ApiError(CODE_NOT_FOUND, "项目不存在")
    if project.is_deleted:
        raise ApiError(CODE_DELETED, "项目已删除，可在回收站恢复")
    return project


def list_projects(session: Session) -> Sequence[Project]:
    """活跃项目列表：按 ``updated_at`` 倒序（走 ``idx_project_updated``）。"""
    return (
        session.execute(
            active(Project).order_by(Project.updated_at.desc(), Project.id.desc())
        )
        .scalars()
        .all()
    )


def tags_of(session: Session, project_ids: Sequence[int]) -> dict[int, list[Tag]]:
    """批量取项目的标签（避免 N+1）。"""
    if not project_ids:
        return {}
    rows = session.execute(
        select(ProjectTag.project_id, Tag)
        .join(Tag, Tag.id == ProjectTag.tag_id)
        .where(ProjectTag.project_id.in_(project_ids))
        .order_by(ProjectTag.project_id, Tag.name)
    ).all()
    result: dict[int, list[Tag]] = {}
    for project_id, tag in rows:
        result.setdefault(project_id, []).append(tag)
    return result


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------


def _sync_tags(session: Session, project: Project, names: Iterable[str]) -> None:
    """全量替换项目的标签关联；标签按名称复用（``tag.name`` 唯一）。"""
    cleaned = _clean_tag_names(names)
    tags: list[Tag] = []
    for name in cleaned:
        tag = session.execute(select(Tag).where(Tag.name == name)).scalar_one_or_none()
        if tag is None:
            tag = Tag(name=name)
            session.add(tag)
            session.flush()
        tags.append(tag)

    session.execute(delete(ProjectTag).where(ProjectTag.project_id == project.id))
    for tag in tags:
        session.add(ProjectTag(project_id=project.id, tag_id=tag.id))


def create_project(
    session: Session,
    *,
    title: str,
    description: str | None = None,
    status: str | None = None,
    target_word_count: int | None = None,
    tag_names: Iterable[str] | None = None,
) -> Project:
    """新建项目，并**自动创建默认卷**（BR-6）。"""
    now = utc_now()
    project = Project(
        title=_clean_title(title),
        description=_clean_description(description),
        status=_clean_status(status),
        target_word_count=_clean_target(target_word_count),
        total_word_count=0,
        created_at=now,
        updated_at=now,
    )
    session.add(project)
    session.flush()  # 需要 project.id 才能建卷

    session.add(
        Volume(
            project_id=project.id,
            title=DEFAULT_VOLUME_TITLE,
            order_index=DEFAULT_VOLUME_ORDER_INDEX,
            is_default=1,
            created_at=now,
            updated_at=now,
        )
    )
    _sync_tags(session, project, tag_names or [])
    return project


def update_project(
    session: Session,
    project_id: int,
    **fields: Any,
) -> Project:
    """局部更新（§6.2 #6 PATCH）。只处理显式传入的字段。"""
    project = require_project(session, project_id)

    if "title" in fields and fields["title"] is not None:
        project.title = _clean_title(fields["title"])
    if "description" in fields:
        project.description = _clean_description(fields["description"])
    if "status" in fields and fields["status"] is not None:
        project.status = _clean_status(fields["status"])
    if "target_word_count" in fields and fields["target_word_count"] is not None:
        project.target_word_count = _clean_target(fields["target_word_count"])
    if "last_chapter_id" in fields:
        # FR-1.5：记住上次打开的章节；None 表示清除
        project.last_chapter_id = fields["last_chapter_id"]
    if "tag_names" in fields:
        _sync_tags(session, project, fields["tag_names"])

    project.updated_at = utc_now()
    return project


def set_cover(
    session: Session, project_id: int, relpath: str
) -> tuple[Project, str | None]:
    """设置封面相对路径，返回 ``(project, 旧封面相对路径)``。

    旧路径交给调用方决定是否删除文件（本模块不碰磁盘）。
    """
    project = require_project(session, project_id)
    previous = project.cover_path
    project.cover_path = relpath
    project.updated_at = utc_now()
    return project, previous


def touch_opened(session: Session, project_id: int) -> None:
    """更新「最近打开」时间（#2 最近项目 / FR-1.5）。"""
    project = require_project(session, project_id)
    project.last_opened_at = utc_now()


def soft_delete_project(session: Session, project_id: int) -> dict[str, int]:
    """软删除项目并**级联**其卷 / 章 / 设定文档（BR-4）。

    注意：快照表（``chapter_version`` / ``document_version``）**不设软删除字段**
    （勘误 E-03）—— 它们随父资源进入回收站，父被清空时才物理删除。
    """
    project = require_project(session, project_id)
    now = utc_now()

    counts = {"volumes": 0, "chapters": 0, "documents": 0}

    volumes = (
        session.execute(
            select(Volume).where(
                Volume.project_id == project_id, Volume.is_deleted == 0
            )
        )
        .scalars()
        .all()
    )
    for volume in volumes:
        volume.is_deleted = 1
        volume.deleted_at = now
        volume.updated_at = now
        counts["volumes"] += 1

        chapters = (
            session.execute(
                select(Chapter).where(
                    Chapter.volume_id == volume.id, Chapter.is_deleted == 0
                )
            )
            .scalars()
            .all()
        )
        for chapter in chapters:
            chapter.is_deleted = 1
            chapter.deleted_at = now
            chapter.updated_at = now
            counts["chapters"] += 1

    documents = (
        session.execute(
            select(Document).where(
                Document.project_id == project_id, Document.is_deleted == 0
            )
        )
        .scalars()
        .all()
    )
    for document in documents:
        document.is_deleted = 1
        document.deleted_at = now
        document.updated_at = now
        counts["documents"] += 1

    project.is_deleted = 1
    project.deleted_at = now
    project.updated_at = now
    return counts


# --------------------------------------------------------------------------
# 统计与序列化
# --------------------------------------------------------------------------


def project_stats(session: Session, project_id: int) -> dict[str, Any]:
    """§6.2 #9：项目统计。

    字数用 ``SUM(chapter.word_count)`` 实时汇总并把结果同步回
    ``project.total_word_count``，避免与字段值漂移（2.5 会改成增量维护）。
    """
    project = require_project(session, project_id)

    volume_count = int(
        session.execute(
            select(func.count(Volume.id)).where(
                Volume.project_id == project_id, Volume.is_deleted == 0
            )
        ).scalar()
        or 0
    )
    chapter_count = int(
        session.execute(
            select(func.count(Chapter.id))
            .join(Volume, Volume.id == Chapter.volume_id)
            .where(
                Volume.project_id == project_id,
                Volume.is_deleted == 0,
                Chapter.is_deleted == 0,
            )
        ).scalar()
        or 0
    )
    word_count = int(
        session.execute(
            select(func.coalesce(func.sum(Chapter.word_count), 0))
            .join(Volume, Volume.id == Chapter.volume_id)
            .where(
                Volume.project_id == project_id,
                Volume.is_deleted == 0,
                Chapter.is_deleted == 0,
            )
        ).scalar()
        or 0
    )
    document_count = int(
        session.execute(
            select(func.count(Document.id)).where(
                Document.project_id == project_id, Document.is_deleted == 0
            )
        ).scalar()
        or 0
    )

    if project.total_word_count != word_count:
        project.total_word_count = word_count

    target = project.target_word_count or 0
    return {
        "project_id": project.id,
        "volume_count": volume_count,
        "chapter_count": chapter_count,
        "document_count": document_count,
        "word_count": word_count,
        "target_word_count": target,
        # FR-1.3：未设目标则不显示进度
        "progress": (word_count / target) if target > 0 else None,
        "updated_at": iso(project.updated_at),
    }


def serialize_project(
    project: Project,
    tags: Sequence[Tag] | None = None,
) -> dict[str, Any]:
    """项目详情序列化（时间统一 ISO 8601 / UTC）。"""
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "cover_path": project.cover_path,
        "status": project.status,
        "target_word_count": project.target_word_count,
        "total_word_count": project.total_word_count,
        "last_chapter_id": project.last_chapter_id,
        "last_opened_at": iso(project.last_opened_at),
        "created_at": iso(project.created_at),
        "updated_at": iso(project.updated_at),
        "tags": [
            {"id": tag.id, "name": tag.name, "color": tag.color} for tag in tags or ()
        ],
    }
