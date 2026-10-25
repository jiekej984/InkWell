"""按角色姓名与别名反查正文出场位置（FR-8.23）。"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from . import character_service
from .search_service import _fts_query, make_snippet


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _unique_variants(name: str, aliases: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in [name, *aliases]:
        value = value.strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def search_appearances(session: Session, character_id: int) -> dict[str, Any]:
    """按书中顺序聚合出场章节，并统计姓名/别名的不重叠出现次数。

    三个字符及以上的称呼走现有 trigram FTS；更短的称呼走转义 LIKE。
    只检索活跃章节和活跃卷，不把回收站内容计入出场。
    """
    character = character_service.require_character(session, character_id)
    aliases = session.execute(
        text(
            "SELECT alias FROM character_alias "
            "WHERE character_id = :cid AND is_deleted = 0 ORDER BY id"
        ),
        {"cid": character_id},
    ).scalars().all()
    variants = _unique_variants(character.name, [str(alias) for alias in aliases])

    base_select = """
        SELECT DISTINCT c.id AS chapter_id, c.title AS chapter_title,
               c.content_text, c.order_index AS chapter_order,
               v.id AS volume_id, v.title AS volume_title,
               v.order_index AS volume_order
        FROM chapter c
        JOIN volume v ON v.id = c.volume_id
        JOIN project p ON p.id = v.project_id
        WHERE c.is_deleted = 0 AND v.is_deleted = 0 AND p.is_deleted = 0
          AND v.project_id = :pid
    """
    candidates: dict[int, Any] = {}
    long_variants = [value for value in variants if len(value) >= 3]
    if long_variants:
        fts_query = " OR ".join(_fts_query(value) for value in long_variants)
        rows = session.execute(
            text(
                "SELECT c.id AS chapter_id, c.title AS chapter_title, "
                "c.content_text, c.order_index AS chapter_order, "
                "v.id AS volume_id, v.title AS volume_title, "
                "v.order_index AS volume_order "
                "FROM chapter_fts "
                "JOIN chapter c ON c.id = chapter_fts.rowid "
                "JOIN volume v ON v.id = c.volume_id "
                "JOIN project p ON p.id = v.project_id "
                "WHERE chapter_fts MATCH :q AND c.is_deleted = 0 "
                "AND v.is_deleted = 0 AND p.is_deleted = 0 "
                "AND v.project_id = :pid"
            ),
            {"q": fts_query, "pid": character.project_id},
        ).mappings()
        candidates.update({int(row["chapter_id"]): row for row in rows})

    short_variants = [value for value in variants if len(value) < 3]
    if short_variants:
        params: dict[str, Any] = {"pid": character.project_id}
        conditions: list[str] = []
        for index, value in enumerate(short_variants):
            key = f"like_{index}"
            conditions.append(f"c.content_text LIKE :{key} ESCAPE '\\'")
            params[key] = _like_pattern(value)
        rows = session.execute(
            text(base_select + " AND (" + " OR ".join(conditions) + ")"), params
        ).mappings()
        candidates.update({int(row["chapter_id"]): row for row in rows})

    pattern = re.compile(
        "(?:" + "|".join(re.escape(value) for value in sorted(variants, key=len, reverse=True)) + ")",
        re.IGNORECASE,
    )
    items: list[dict[str, Any]] = []
    for row in candidates.values():
        content = str(row["content_text"] or "")
        matches = list(pattern.finditer(content))
        if not matches:
            continue
        first = matches[0]
        first_term = first.group(0)
        items.append(
            {
                "chapter_id": int(row["chapter_id"]),
                "chapter_title": row["chapter_title"],
                "volume_id": int(row["volume_id"]),
                "volume_title": row["volume_title"],
                "occurrences": len(matches),
                "snippet": make_snippet(content, first_term),
                "_volume_order": int(row["volume_order"] or 0),
                "_chapter_order": int(row["chapter_order"] or 0),
            }
        )
    items.sort(key=lambda item: (item["_volume_order"], item["_chapter_order"], item["chapter_id"]))
    for item in items:
        item.pop("_volume_order")
        item.pop("_chapter_order")

    first_appearance = items[0] if items else None
    return {
        "character_id": int(character.id),
        "character_name": character.name,
        "variants": variants,
        "chapter_count": len(items),
        "total_occurrences": sum(item["occurrences"] for item in items),
        "first_appearance": first_appearance,
        "items": items,
    }

