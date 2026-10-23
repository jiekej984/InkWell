"""设定文档业务逻辑（任务 2.7 / FR-4）。

对应 FR-4.1~4.4、§6.2 #28~#30：
    · 项目级；五类分类（world / timeline / faction / glossary / other）
    · **不参与全书字数**（``project.total_word_count`` 不会被改动）
    · 复用章节编辑器的消毒 / 图片 / 字数能力
    · 软删除（BR-4）；版本历史按 D-05 不做（`document_version` 表 V1 建）
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Document, active
from ..schemas import CODE_DELETED, CODE_NOT_FOUND, CODE_PARAM_INVALID, ApiError
from ..timeutil import iso, utc_now
from . import media, project_service, sanitize, wordcount

CATEGORIES = ("world", "timeline", "faction", "glossary", "other")
CATEGORY_LABELS = {
    "world": "世界观",
    "timeline": "时间线",
    "faction": "势力",
    "glossary": "名词表",
    "other": "其他",
}
MAX_TITLE_LENGTH = 200
ORDER_STEP = 1000


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------


def _clean_title(title: str | None) -> str:
    value = (title or "").strip()
    if not value:
        raise ApiError(CODE_PARAM_INVALID, "文档标题不能为空")
    if len(value) > MAX_TITLE_LENGTH:
        raise ApiError(
            CODE_PARAM_INVALID, f"文档标题不能超过 {MAX_TITLE_LENGTH} 个字符"
        )
    return value


def _clean_category(category: str | None) -> str:
    value = (category or "other").strip()
    if value not in CATEGORIES:
        raise ApiError(
            CODE_PARAM_INVALID,
            f"文档分类必须是 {'/'.join(CATEGORIES)} 之一",
        )
    return value


def _clean_order(value: int | None) -> int:
    if value is None:
        raise ApiError(CODE_PARAM_INVALID, "排序值不能为空")
    if value < 0:
        raise ApiError(CODE_PARAM_INVALID, "排序值不能为负数")
    return int(value)


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------


def require_document(session: Session, document_id: int) -> Document:
    """按 id 取活跃文档；不存在 → 2001，已删除 → 2002。"""
    document = session.get(Document, document_id)
    if document is None:
        raise ApiError(CODE_NOT_FOUND, "设定文档不存在")
    if document.is_deleted:
        raise ApiError(CODE_DELETED, "设定文档已删除，可在回收站恢复")
    return document


def _touch_project(session: Session, project_id: int) -> None:
    project = project_service.require_project(session, project_id)
    project.updated_at = utc_now()


def serialize_document_meta(document: Document) -> dict[str, Any]:
    """列表项（不含正文，§6.1「大列表接口」约定）。"""
    return {
        "id": document.id,
        "project_id": document.project_id,
        "title": document.title,
        "category": document.category,
        "category_label": CATEGORY_LABELS.get(document.category, document.category),
        "order_index": document.order_index,
        "word_count": document.word_count,
        "created_at": iso(document.created_at),
        "updated_at": iso(document.updated_at),
    }


def list_documents(
    session: Session,
    project_id: int,
    category: str | None = None,
) -> dict[str, Any]:
    """§6.2 #28：文档列表（可按分类筛选）。"""
    project_service.require_project(session, project_id)
    statement = active(Document).where(Document.project_id == project_id)
    if category is not None:
        statement = statement.where(Document.category == _clean_category(category))
    rows = (
        session.execute(statement.order_by(Document.order_index, Document.id))
        .scalars()
        .all()
    )
    return {
        "project_id": project_id,
        "items": [serialize_document_meta(row) for row in rows],
        "total": len(rows),
        "categories": [
            {"value": value, "label": CATEGORY_LABELS[value]} for value in CATEGORIES
        ],
    }


def get_document_detail(session: Session, document_id: int) -> dict[str, Any]:
    """§6.2 #30（GET）：文档详情（正文图片临时签名）。"""
    document = require_document(session, document_id)
    project = project_service.require_project(session, document.project_id)
    return {
        **serialize_document_meta(document),
        "project_title": project.title,
        "content": media.sign_content_images(document.content or ""),
        "content_text": document.content_text,
    }


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------


def _apply_content(document: Document, content_html: str | None) -> None:
    """消毒 + 图片路径还原 + 重算字数（与章节正文同一套规则）。"""
    normalized = media.normalize_content_images(content_html)
    clean = sanitize.sanitize_html(normalized)
    plain, words = wordcount.count_html(clean)
    document.content = clean
    document.content_text = plain
    document.word_count = words


def create_document(
    session: Session,
    project_id: int,
    *,
    title: str,
    category: str | None = "other",
    content_html: str | None = "",
) -> Document:
    """§6.2 #29：新建文档，序号排在项目末尾。"""
    project_service.require_project(session, project_id)
    max_index = session.execute(
        select(func.max(Document.order_index)).where(
            Document.project_id == project_id, Document.is_deleted == 0
        )
    ).scalar()
    order_index = (int(max_index) + ORDER_STEP) if max_index is not None else ORDER_STEP

    now = utc_now()
    document = Document(
        project_id=project_id,
        title=_clean_title(title),
        content=None,
        content_text=None,
        category=_clean_category(category),
        order_index=order_index,
        word_count=0,
        created_at=now,
        updated_at=now,
    )
    _apply_content(document, content_html)
    session.add(document)
    session.flush()
    _touch_project(session, project_id)
    return document


def update_document(
    session: Session,
    document_id: int,
    **fields: Any,
) -> Document:
    """§6.2 #30（PATCH）：改标题/分类/正文/排序。"""
    document = require_document(session, document_id)

    if "title" in fields and fields["title"] is not None:
        document.title = _clean_title(fields["title"])
    if "category" in fields and fields["category"] is not None:
        document.category = _clean_category(fields["category"])
    if "content_html" in fields and fields["content_html"] is not None:
        _apply_content(document, fields["content_html"])
    if "order_index" in fields and fields["order_index"] is not None:
        document.order_index = _clean_order(fields["order_index"])

    document.updated_at = utc_now()
    _touch_project(session, document.project_id)
    return document


def delete_document(session: Session, document_id: int) -> dict[str, Any]:
    """§6.2 #30（DELETE）：软删除（BR-4，回收站可恢复）。"""
    document = require_document(session, document_id)
    now = utc_now()
    document.is_deleted = 1
    document.deleted_at = now
    document.updated_at = now
    _touch_project(session, document.project_id)
    return {"id": document.id, "deleted": True}


def categories_payload() -> list[dict[str, str]]:
    return [{"value": value, "label": CATEGORY_LABELS[value]} for value in CATEGORIES]


def list_document_titles(
    session: Session, project_id: int
) -> Sequence[tuple[int, str]]:
    """供回收站/检索复用的轻量查询。"""
    rows = session.execute(
        select(Document.id, Document.title)
        .where(Document.project_id == project_id, Document.is_deleted == 0)
        .order_by(Document.order_index, Document.id)
    ).all()
    return [(int(row[0]), row[1]) for row in rows]
