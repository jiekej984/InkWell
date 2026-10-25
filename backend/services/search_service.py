"""全文检索（任务 2.11 / FR-7 / §6.2 #31）。

实现要点（S2-02 / S2-15）：
    · 章节与设定文档分别查 ``chapter_fts`` / ``document_fts``，在 service 层**合并**
      （不用 UNION，便于「仅章节 / 仅文档 / 全部」范围切换）
    · FTS5 trigram 查询串 **至少 3 个字符**；不足 3 个字符降级为 LIKE 并返回
      ``hint`` 提示（trigram 的已知限制）
    · 查询串整体作为短语（双引号包裹，内部引号翻倍），避免 FTS 语法注入
    · 摘要（snippet）由 Python 生成并做 **HTML 转义**，仅 ``<mark>`` 为受信标签，
      防止正文里的 ``<b>`` 等被当作 HTML 注入
    · 分页：两侧各取 ``page*page_size`` 条（单侧上限 ``MAX_PER_SIDE``）后合并排序再切片；
      ``total`` 为两侧命中数之和。窗口超出上限时返回 ``page_limited=True`` 与提示，
      不静默给出不完整的分页（根治方案为游标分页，见阶段三）
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from sqlalchemy import text

from ..database import Database
from ..models import session_scope
from ..schemas import CODE_PARAM_INVALID, ApiError
from ..services import project_service
from ..timeutil import iso

SCOPES = ("all", "chapters", "documents")
MIN_FTS_CHARS = 3
MAX_PAGE_SIZE = 100
# 单侧取数上限：合并分页的正确性要求「每侧都覆盖到本页之前的所有名次」，
# 因此窗口随 page*page_size 增长；此上限只挡住极深翻页，超出时如实告知（page_limited）。
MAX_PER_SIDE = 1000
SNIPPET_RADIUS = 60
CATEGORY_LABELS = {
    "world": "世界观",
    "timeline": "时间线",
    "faction": "势力",
    "glossary": "名词表",
    "other": "其他",
}

_WHITESPACE = re.compile(r"\s+")


def _fts_query(query: str) -> str:
    """短语查询：引号包裹、内部引号翻倍。"""
    return '"' + query.replace('"', '""') + '"'


def _like_pattern(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def make_snippet(content_text: str | None, query: str) -> str:
    """生成带 ``<mark>`` 的摘要；正文先做 HTML 转义。"""
    plain = _WHITESPACE.sub(" ", content_text or "").strip()
    if not plain:
        return ""
    lower = plain.lower()
    needle = query.lower()
    position = lower.find(needle)
    if position < 0:
        return html.escape(plain[: SNIPPET_RADIUS * 2])

    start = max(0, position - SNIPPET_RADIUS)
    end = min(len(plain), position + len(needle) + SNIPPET_RADIUS)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(plain) else ""
    return (
        f"{prefix}"
        f"{html.escape(plain[start:position])}"
        f"<mark>{html.escape(plain[position:position + len(needle)])}</mark>"
        f"{html.escape(plain[position + len(needle):end])}"
        f"{suffix}"
    )


def _chapter_rows_fts(
    session: Any, query: str, project_id: int | None, limit: int
) -> tuple[list[dict[str, Any]], int]:
    project_filter = "AND v.project_id = :pid" if project_id is not None else ""
    params: dict[str, Any] = {"q": _fts_query(query), "limit": limit}
    if project_id is not None:
        params["pid"] = project_id

    sql = text(f"""
        SELECT c.id, c.title, c.content_text, c.volume_id, c.updated_at,
               v.title AS volume_title, v.project_id,
               p.title AS project_title,
               bm25(chapter_fts) AS rank
        FROM chapter_fts
        JOIN chapter c ON c.id = chapter_fts.rowid
        JOIN volume v ON v.id = c.volume_id
        JOIN project p ON p.id = v.project_id
        WHERE chapter_fts MATCH :q
          AND c.is_deleted = 0 AND v.is_deleted = 0 AND p.is_deleted = 0
          {project_filter}
        ORDER BY rank
        LIMIT :limit
        """)
    rows = session.execute(sql, params).mappings().all()

    count_sql = text(f"""
        SELECT count(*)
        FROM chapter_fts
        JOIN chapter c ON c.id = chapter_fts.rowid
        JOIN volume v ON v.id = c.volume_id
        JOIN project p ON p.id = v.project_id
        WHERE chapter_fts MATCH :q
          AND c.is_deleted = 0 AND v.is_deleted = 0 AND p.is_deleted = 0
          {project_filter}
        """)
    count_params = {"q": _fts_query(query)}
    if project_id is not None:
        count_params["pid"] = project_id
    total = int(session.execute(count_sql, count_params).scalar() or 0)

    items = [_chapter_item(row, query) for row in rows]
    return items, total


def _chapter_rows_like(
    session: Any, query: str, project_id: int | None, limit: int
) -> tuple[list[dict[str, Any]], int]:
    project_filter = "AND v.project_id = :pid" if project_id is not None else ""
    params: dict[str, Any] = {"like": _like_pattern(query), "limit": limit}
    if project_id is not None:
        params["pid"] = project_id

    where = "(c.title LIKE :like ESCAPE '\\' OR c.content_text LIKE :like ESCAPE '\\')"
    sql = text(f"""
        SELECT c.id, c.title, c.content_text, c.volume_id, c.updated_at,
               v.title AS volume_title, v.project_id,
               p.title AS project_title
        FROM chapter c
        JOIN volume v ON v.id = c.volume_id
        JOIN project p ON p.id = v.project_id
        WHERE {where}
          AND c.is_deleted = 0 AND v.is_deleted = 0 AND p.is_deleted = 0
          {project_filter}
        ORDER BY c.updated_at DESC
        LIMIT :limit
        """)
    rows = session.execute(sql, params).mappings().all()

    count_sql = text(f"""
        SELECT count(*)
        FROM chapter c
        JOIN volume v ON v.id = c.volume_id
        JOIN project p ON p.id = v.project_id
        WHERE {where}
          AND c.is_deleted = 0 AND v.is_deleted = 0 AND p.is_deleted = 0
          {project_filter}
        """)
    count_params = {"like": _like_pattern(query)}
    if project_id is not None:
        count_params["pid"] = project_id
    total = int(session.execute(count_sql, count_params).scalar() or 0)
    return [_chapter_item(row, query) for row in rows], total


def _as_datetime(value: Any) -> datetime | None:
    """原生 SQL 读出的 DATETIME 是字符串，统一转回 naive datetime。"""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:  # pragma: no cover - 异常格式
        return None


def _chapter_item(row: Any, query: str) -> dict[str, Any]:
    updated = _as_datetime(row["updated_at"])
    return {
        "type": "chapter",
        "id": int(row["id"]),
        "title": row["title"],
        "project_id": int(row["project_id"]),
        "project_title": row["project_title"],
        "volume_id": int(row["volume_id"]),
        "volume_title": row["volume_title"],
        "snippet": make_snippet(row["content_text"], query),
        "updated_at": iso(updated),
        "_rank": float(row.get("rank") or 0.0),
        "_updated": updated.timestamp() if updated else 0.0,
    }


def _document_rows_fts(
    session: Any, query: str, project_id: int | None, limit: int
) -> tuple[list[dict[str, Any]], int]:
    project_filter = "AND d.project_id = :pid" if project_id is not None else ""
    params: dict[str, Any] = {"q": _fts_query(query), "limit": limit}
    if project_id is not None:
        params["pid"] = project_id

    sql = text(f"""
        SELECT d.id, d.title, d.content_text, d.category, d.updated_at,
               d.project_id, p.title AS project_title,
               bm25(document_fts) AS rank
        FROM document_fts
        JOIN document d ON d.id = document_fts.rowid
        JOIN project p ON p.id = d.project_id
        WHERE document_fts MATCH :q
          AND d.is_deleted = 0 AND p.is_deleted = 0
          {project_filter}
        ORDER BY rank
        LIMIT :limit
        """)
    rows = session.execute(sql, params).mappings().all()

    count_sql = text(f"""
        SELECT count(*)
        FROM document_fts
        JOIN document d ON d.id = document_fts.rowid
        JOIN project p ON p.id = d.project_id
        WHERE document_fts MATCH :q
          AND d.is_deleted = 0 AND p.is_deleted = 0
          {project_filter}
        """)
    count_params = {"q": _fts_query(query)}
    if project_id is not None:
        count_params["pid"] = project_id
    total = int(session.execute(count_sql, count_params).scalar() or 0)
    return [_document_item(row, query) for row in rows], total


def _document_rows_like(
    session: Any, query: str, project_id: int | None, limit: int
) -> tuple[list[dict[str, Any]], int]:
    project_filter = "AND d.project_id = :pid" if project_id is not None else ""
    params: dict[str, Any] = {"like": _like_pattern(query), "limit": limit}
    if project_id is not None:
        params["pid"] = project_id

    where = "(d.title LIKE :like ESCAPE '\\' OR d.content_text LIKE :like ESCAPE '\\')"
    sql = text(f"""
        SELECT d.id, d.title, d.content_text, d.category, d.updated_at,
               d.project_id, p.title AS project_title
        FROM document d
        JOIN project p ON p.id = d.project_id
        WHERE {where}
          AND d.is_deleted = 0 AND p.is_deleted = 0
          {project_filter}
        ORDER BY d.updated_at DESC
        LIMIT :limit
        """)
    rows = session.execute(sql, params).mappings().all()

    count_sql = text(f"""
        SELECT count(*)
        FROM document d
        JOIN project p ON p.id = d.project_id
        WHERE {where}
          AND d.is_deleted = 0 AND p.is_deleted = 0
          {project_filter}
        """)
    count_params = {"like": _like_pattern(query)}
    if project_id is not None:
        count_params["pid"] = project_id
    total = int(session.execute(count_sql, count_params).scalar() or 0)
    return [_document_item(row, query) for row in rows], total


def _document_item(row: Any, query: str) -> dict[str, Any]:
    updated = _as_datetime(row["updated_at"])
    return {
        "type": "document",
        "id": int(row["id"]),
        "title": row["title"],
        "project_id": int(row["project_id"]),
        "project_title": row["project_title"],
        "category": row["category"],
        "category_label": CATEGORY_LABELS.get(row["category"], row["category"]),
        "snippet": make_snippet(row["content_text"], query),
        "updated_at": iso(updated),
        "_rank": float(row.get("rank") or 0.0),
        "_updated": updated.timestamp() if updated else 0.0,
    }


def search(
    database: Database,
    *,
    query: str,
    project_id: int | None = None,
    scope: str = "all",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """#31：全文检索（章节 + 设定文档，范围与项目可选）。"""
    query = _WHITESPACE.sub(" ", (query or "").strip())
    if not query:
        raise ApiError(CODE_PARAM_INVALID, "搜索词不能为空")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in query):
        # FTS5 的查询串不接受 NUL 等控制字符（sqlite3 会抛 unterminated string）
        raise ApiError(CODE_PARAM_INVALID, "搜索词不能包含控制字符")
    if scope not in SCOPES:
        raise ApiError(CODE_PARAM_INVALID, "搜索范围只能是 all/chapters/documents")
    if page < 1:
        raise ApiError(CODE_PARAM_INVALID, "page 必须 ≥ 1")
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ApiError(CODE_PARAM_INVALID, f"page_size 必须在 1~{MAX_PAGE_SIZE} 之间")

    use_fts = len(query) >= MIN_FTS_CHARS
    window = page * page_size
    per_side = min(MAX_PER_SIDE, window)
    page_limited = window > MAX_PER_SIDE

    with session_scope(database.engine) as session:
        if project_id is not None:
            project_service.require_project(session, project_id)

        chapter_items: list[dict[str, Any]] = []
        chapter_total = 0
        if scope in ("all", "chapters"):
            chapter_items, chapter_total = (
                _chapter_rows_fts(session, query, project_id, per_side)
                if use_fts
                else _chapter_rows_like(session, query, project_id, per_side)
            )

        document_items: list[dict[str, Any]] = []
        document_total = 0
        if scope in ("all", "documents"):
            document_items, document_total = (
                _document_rows_fts(session, query, project_id, per_side)
                if use_fts
                else _document_rows_like(session, query, project_id, per_side)
            )

    merged = sorted(
        chapter_items + document_items,
        key=lambda item: (item["_rank"], -item["_updated"]),
    )
    start = (page - 1) * page_size
    page_items = merged[start : start + page_size]
    for item in page_items:
        item.pop("_rank", None)
        item.pop("_updated", None)

    hints: list[str] = []
    if not use_fts:
        hints.append("搜索词少于 3 个字符，已使用模糊匹配（全文索引至少需要 3 个字符）")
    if page_limited:
        hints.append(f"结果过多，仅支持前 {MAX_PER_SIDE} 条以内分页；请加长搜索词")

    return {
        "query": query,
        "scope": scope,
        "project_id": project_id,
        "page": page,
        "page_size": page_size,
        "total": chapter_total + document_total,
        "items": page_items,
        "fuzzy": not use_fts,
        "page_limited": page_limited,
        "hint": "；".join(hints),
    }
