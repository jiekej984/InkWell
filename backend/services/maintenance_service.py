"""维护任务（任务 2.5 / #43；2.11 的 #42 也归本模块）。

长任务约定（S2-03）：任务函数签名 ``func(report)``，``report(progress, message)``。
本模块只做数据库维护，不关心 HTTP；由 ``backend/api/maintenance.py`` 提交到
``app.state.tasks``（互斥、500ms 轮询、成功后可 DELETE）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..database import Database
from ..models import Chapter, Document, Project, Volume, session_scope
from .wordcount import count_words, extract_text

ProgressReporter = Callable[..., None]

# 每批处理章节数：控制大项目重算时的内存占用（NFR-P6）
BATCH_SIZE = 100


def recompute_project_totals(session: Session) -> int:
    """按「活跃卷 → 活跃章」重新汇总 ``project.total_word_count``。

    返回被更新的项目数。设定文档不计入全书字数（FR-4.1）。
    """
    volume_rows = session.execute(
        select(Volume.id, Volume.project_id).where(Volume.is_deleted == 0)
    ).all()
    sum_rows = session.execute(
        select(
            Chapter.volume_id,
            func.coalesce(func.sum(Chapter.word_count), 0),
        )
        .where(Chapter.is_deleted == 0)
        .group_by(Chapter.volume_id)
    ).all()
    sums = {int(vid): int(total) for vid, total in sum_rows}

    totals: dict[int, int] = {}
    for volume_id, project_id in volume_rows:
        totals[int(project_id)] = totals.get(int(project_id), 0) + sums.get(
            int(volume_id), 0
        )

    updated = 0
    for project in session.execute(select(Project)).scalars().all():
        expected = totals.get(int(project.id), 0)
        if project.total_word_count != expected:
            project.total_word_count = expected
            updated += 1
    return updated


def rebuild_wordcount(
    database: Database,
    report: ProgressReporter | None = None,
) -> dict[str, Any]:
    """#43：重算全部活跃章节的 ``content_text`` / ``word_count``。

    · 按 ``id`` 分批（BATCH_SIZE），避免一次性载入整库正文（NFR-P6）
    · 只处理未删除章节；软删除的章节保留原值，恢复后由下次重算修正
    · 结束后统一重算项目总字数
    """
    if report:
        report(0, "统计章节总数")

    processed = 0
    changed = 0
    last_id = 0

    with session_scope(database.engine) as session:
        total = int(
            session.execute(
                select(func.count(Chapter.id)).where(Chapter.is_deleted == 0)
            ).scalar()
            or 0
        )
        if report:
            report(0, f"共 {total} 章待重算")

        while True:
            batch = (
                session.execute(
                    select(Chapter)
                    .where(Chapter.is_deleted == 0, Chapter.id > last_id)
                    .order_by(Chapter.id)
                    .limit(BATCH_SIZE)
                )
                .scalars()
                .all()
            )
            if not batch:
                break

            for chapter in batch:
                plain = extract_text(chapter.content or "")
                words = count_words(plain)
                if chapter.content_text != plain or chapter.word_count != words:
                    chapter.content_text = plain
                    chapter.word_count = words
                    changed += 1

            last_id = batch[-1].id
            processed += len(batch)
            session.flush()
            if report:
                percent = int(processed * 100 / total) if total else 100
                report(percent, f"已处理 {processed}/{total} 章")

        updated_projects = recompute_project_totals(session)
        if report:
            report(100, "字数重算完成")

    return {
        "chapters": processed,
        "changed": changed,
        "projects": updated_projects,
    }


def rebuild_fts(
    database: Database,
    report: ProgressReporter | None = None,
) -> dict[str, Any]:
    """#42：重建全文索引（FTS5 external content 的 ``rebuild`` 命令）。

    external content 表不存正文副本，``rebuild`` 会按 content 表重新扫描生成索引；
    触发器在此过程中仍然有效，重建后查询结果应与重建前一致。
    """
    if report:
        report(5, "重建章节索引")
    with session_scope(database.engine) as session:
        session.execute(text("INSERT INTO chapter_fts(chapter_fts) VALUES('rebuild')"))
        if report:
            report(55, "重建设定文档索引")
        session.execute(
            text("INSERT INTO document_fts(document_fts) VALUES('rebuild')")
        )
        chapter_count = int(
            session.execute(
                select(func.count(Chapter.id)).where(Chapter.is_deleted == 0)
            ).scalar()
            or 0
        )
        document_count = int(
            session.execute(
                select(func.count(Document.id)).where(Document.is_deleted == 0)
            ).scalar()
            or 0
        )

    if report:
        report(100, "全文索引重建完成")
    return {
        "rebuilt": ["chapter_fts", "document_fts"],
        "chapters": chapter_count,
        "documents": document_count,
    }
