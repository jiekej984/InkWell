"""任务 2.0 验收①：**DDL 一致性测试**（migrate.py ↔ models.py）。

决策 S2-04 微调 ② 要求：这个测试**必须真跑**，不能只写样子。

做法：建两个库 ——

    · **库 A（权威）**：由 ``migrate.py`` 真实迁移产出
    · **库 B（ORM）**：由 ``Base.metadata.create_all()`` 产出

然后对每个表逐字段比对 ``PRAGMA table_info`` / ``index_list`` / ``foreign_key_list``。
类型字符串两边都由 SQLite 报出，格式天然一致，避免字符串解析带来的假阴性。
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import SCHEMA_VERSION
from backend.database import Database
from backend.migrate import apply_migrations
from backend.models import (
    ACTIVE_MODELS,
    Chapter,
    ChapterVersion,
    Character,
    CharacterAlias,
    CharacterRelation,
    Document,
    DocumentVersion,
    Faction,
    FactionRelation,
    Organization,
    OrgMember,
    OrgRelation,
    Project,
    ProjectTag,
    Tag,
    Volume,
    active,
    session_scope,
)

# ORM 未建模的表：迁移基础设施 + FTS5 虚拟表（只能用原生 SQL 访问）
#
# 注意：external content 的 FTS5 表会额外产生 5 张影子表
# ``<name>_data / _idx / _content / _docsize / _config``，同样要排除。
NON_ORM_TABLES = {"app_meta", "chapter_fts", "document_fts"}
FTS_PREFIXES = ("chapter_fts", "document_fts")


def _skip(table: str) -> bool:
    """是否为 ORM 不建模的表。"""
    return table in NON_ORM_TABLES or table.startswith(FTS_PREFIXES)


def _orm_tables(tables: list[str]) -> set[str]:
    return {t for t in tables if not _skip(t)}


def _snapshot(path: Path) -> tuple[list[str], dict, dict, dict]:
    """读取一个库的结构快照。"""
    conn = sqlite3.connect(str(path))
    try:
        tables = sorted(
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        )
        info = {t: conn.execute(f"PRAGMA table_info({t})").fetchall() for t in tables}
        indexes = {
            t: conn.execute(f"PRAGMA index_list({t})").fetchall() for t in tables
        }
        foreign_keys = {
            t: conn.execute(f"PRAGMA foreign_key_list({t})").fetchall() for t in tables
        }
    finally:
        conn.close()
    return tables, info, indexes, foreign_keys


@pytest.fixture
def migrated_db_path(config) -> Path:
    """库 A：由迁移脚本真实产出。"""
    database = Database(config.db_path)
    apply_migrations(database, config.data_dir)
    database.dispose()
    return config.db_path


@pytest.fixture
def orm_db_path(tmp_path: Path) -> Path:
    """库 B：由 ORM 元数据产出。"""
    path = tmp_path / "orm.db"
    engine = create_engine(f"sqlite+pysqlite:///{path.as_posix()}")
    try:
        from backend.models import Base

        Base.metadata.create_all(engine)
    finally:
        engine.dispose()
    return path


def test_schema_version_is_four() -> None:
    """迁移 0004 已登记，SCHEMA_VERSION 应为 4（组织成员删除批次）。"""
    assert SCHEMA_VERSION == 4


def test_table_sets_match(migrated_db_path: Path, orm_db_path: Path) -> None:
    """表集合必须一致（排除 ORM 未建模的 app_meta 与 FTS 虚拟表及其影子表）。"""
    a_tables, _, _, _ = _snapshot(migrated_db_path)
    b_tables, _, _, _ = _snapshot(orm_db_path)

    assert set(NON_ORM_TABLES) <= set(a_tables), "迁移库缺少基础设施/FTS 表"
    assert _orm_tables(a_tables) == _orm_tables(b_tables)


def _normalized_columns(cols: list[tuple]) -> list[tuple]:
    """归一化列定义后比对。

    去掉 ``cid``（列序号）；主键列**不比对 notnull**，因为存在一处已知的、
    语义等价的表述差异：

        · 迁移脚本写 ``id INTEGER PRIMARY KEY AUTOINCREMENT`` → PRAGMA notnull = 0
        · SQLAlchemy 生成 ``id INTEGER NOT NULL, PRIMARY KEY (id)`` → notnull = 1

    主键本身已隐含非空（且 INTEGER 主键即 rowid 别名），两者行为一致。
    """
    result = []
    for col in cols:
        _, name, type_, notnull, default, pk = col
        result.append((name, type_, 0 if pk else notnull, default, pk))
    return result


def test_columns_match_field_by_field(
    migrated_db_path: Path, orm_db_path: Path
) -> None:
    """逐字段比对：列名、类型、非空、默认值、主键位次。"""
    _, a_info, _, _ = _snapshot(migrated_db_path)
    _, b_info, _, _ = _snapshot(orm_db_path)

    for table, a_cols in a_info.items():
        if _skip(table):
            continue
        assert table in b_info, f"ORM 缺少表 {table}"
        assert _normalized_columns(a_cols) == _normalized_columns(
            b_info[table]
        ), f"表 {table} 的列定义不一致"


def test_indexes_match(migrated_db_path: Path, orm_db_path: Path) -> None:
    """索引比对：名称 + 唯一性 + 来源（显式 index / 唯一约束 autoindex）。"""
    _, _, a_idx, _ = _snapshot(migrated_db_path)
    _, _, b_idx, _ = _snapshot(orm_db_path)

    for table, a_rows in a_idx.items():
        if _skip(table):
            continue
        a_set = {(r[1], r[2], r[3]) for r in a_rows}  # (name, unique, origin)
        b_set = {(r[1], r[2], r[3]) for r in b_idx[table]}
        assert a_set == b_set, f"表 {table} 的索引不一致: {a_set ^ b_set}"


def test_foreign_keys_match(migrated_db_path: Path, orm_db_path: Path) -> None:
    """外键比对：(本表列, 目标表, 目标列, on_delete)。"""
    _, _, _, a_fk = _snapshot(migrated_db_path)
    _, _, _, b_fk = _snapshot(orm_db_path)

    for table, a_rows in a_fk.items():
        if _skip(table):
            continue
        a_set = {(r[3], r[2], r[4], r[6]) for r in a_rows}
        b_set = {(r[3], r[2], r[4], r[6]) for r in b_fk[table]}
        assert a_set == b_set, f"表 {table} 的外键不一致: {a_set ^ b_set}"


def test_soft_delete_and_mutable_fields_present(
    migrated_db_path: Path,
) -> None:
    """S1-08：软删除字段与 updated_at 归属必须正确。"""
    _, info, _, _ = _snapshot(migrated_db_path)

    for table in ("project", "volume", "chapter", "document"):
        columns = {c[1] for c in info[table]}
        assert "is_deleted" in columns, f"{table} 缺少 is_deleted"
        assert "deleted_at" in columns, f"{table} 缺少 deleted_at"
        assert "updated_at" in columns, f"{table} 缺少 updated_at"

    # 不可变快照：无 updated_at（S1-08）
    for table in ("chapter_version", "document_version"):
        assert "updated_at" not in {c[1] for c in info[table]}


def test_character_tables_soft_delete_columns(migrated_db_path: Path) -> None:
    """V2.0 新表：软删字段齐全。

    一处**有意的不对称**（不进回收站，随主体级联物理删除）：
        · ``character_alias`` 无 ``updated_at`` / ``deleted_at``
    """
    _, info, _, _ = _snapshot(migrated_db_path)
    expected = {
        "character": {"is_deleted", "deleted_at", "updated_at"},
        "faction": {"is_deleted", "deleted_at", "updated_at"},
        "organization": {"is_deleted", "deleted_at", "updated_at"},
        "character_relation": {"is_deleted", "deleted_at", "updated_at"},
        "org_relation": {"is_deleted", "deleted_at", "updated_at"},
        "faction_relation": {"is_deleted", "deleted_at", "updated_at"},
        "org_member": {"is_deleted", "updated_at", "deleted_at"},
        "character_alias": {"is_deleted"},
    }
    for table, columns in expected.items():
        actual = {c[1] for c in info[table]}
        assert columns <= actual, f"{table} 缺少 {columns - actual}"


def test_check_constraints_present(migrated_db_path: Path) -> None:
    """三条防自环 CHECK：DDL 比对不覆盖 CHECK，单独兜底。"""
    conn = sqlite3.connect(str(migrated_db_path))
    try:
        rows = dict(
            conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table'"
            ).fetchall()
        )
    finally:
        conn.close()

    assert "CHECK (parent_id IS NULL OR parent_id <> id)" in rows["organization"]
    assert "CHECK (from_id <> to_id)" in rows["org_relation"]
    assert "CHECK (from_id <> to_id)" in rows["faction_relation"]
    assert "CHECK (from_id <> to_id)" in rows["character_relation"]


def test_migration_0002_document_fts_is_queryable(database: Database) -> None:
    """S2-02：document_fts 与 chapter_fts 同构，且能命中中文子串。"""
    now = datetime(2026, 1, 1)
    with session_scope(database.engine) as session:
        session.add(
            Project(title="测试书", created_at=now, updated_at=now, status="writing")
        )
        session.flush()
        session.add(
            Document(
                project_id=1,
                title="世界观",
                content_text="黑水河畔的少年",
                category="world",
                created_at=now,
                updated_at=now,
            )
        )

    with database.connect() as conn:
        hits = conn.execute(
            text("SELECT count(*) FROM document_fts WHERE document_fts MATCH '水河畔'")
        ).scalar()
    assert hits == 1

    # 同构性：两张 FTS 表的定义字符串应当一致（除表名与 content 指向）
    raw = sqlite3.connect(str(database.db_path))
    try:
        chapter_sql = raw.execute(
            "SELECT sql FROM sqlite_master WHERE name='chapter_fts'"
        ).fetchone()[0]
        document_sql = raw.execute(
            "SELECT sql FROM sqlite_master WHERE name='document_fts'"
        ).fetchone()[0]
    finally:
        raw.close()
    assert "trigram" in chapter_sql and "trigram" in document_sql
    assert "content='chapter'" in chapter_sql
    assert "content='document'" in document_sql
    assert chapter_sql.replace("chapter_fts", "X").replace(
        "'chapter'", "Y"
    ) == document_sql.replace("document_fts", "X").replace("'document'", "Y")


def test_active_filters_soft_deleted(database: Database) -> None:
    """C-06 微调①：active() 过滤已删除；裸查能读到已删除（回收站 2.8 需要）。"""
    now = datetime(2026, 1, 1)
    with session_scope(database.engine) as session:
        session.add(Project(title="在写的书", created_at=now, updated_at=now))
        session.add(
            Project(
                title="已删除的书",
                created_at=now,
                updated_at=now,
                is_deleted=1,
                deleted_at=now,
            )
        )

    with session_scope(database.engine) as session:
        assert len(session.execute(active(Project)).scalars().all()) == 1
        assert (
            len(
                session.execute(active(Project, Project.title == "在写的书"))
                .scalars()
                .all()
            )
            == 1
        )
        # 裸查：回收站场景必须能读到已删除数据
        from sqlalchemy import select

        assert (
            len(
                session.execute(select(Project).where(Project.is_deleted == 1))
                .scalars()
                .all()
            )
            == 1
        )


def test_active_rejects_immutable_models() -> None:
    """快照表没有 is_deleted，调用 active() 应当明确报错而不是静默返回全部。"""
    with pytest.raises(TypeError):
        active(ChapterVersion)
    with pytest.raises(TypeError):
        active(DocumentVersion)


def test_active_models_registry_is_complete() -> None:
    """所有带软删除的模型都必须登记在 ACTIVE_MODELS，避免漏管。"""
    expected = {
        Project,
        Volume,
        Chapter,
        Document,
        Character,
        CharacterAlias,
        CharacterRelation,
        Faction,
        FactionRelation,
        Organization,
        OrgMember,
        OrgRelation,
    }
    assert set(ACTIVE_MODELS) == expected
    for model in expected:
        assert hasattr(model, "is_deleted"), f"{model.__name__} 缺少 is_deleted"
    for model in (Tag, ChapterVersion, DocumentVersion, ProjectTag):
        assert not hasattr(model, "is_deleted")


def test_session_scope_commits_and_rolls_back(database: Database) -> None:
    """同步会话：正常提交、异常回滚。"""
    now = datetime(2026, 1, 1)

    with session_scope(database.engine) as session:
        session.add(Project(title="会提交", created_at=now, updated_at=now))

    with session_scope(database.engine) as session:
        assert len(session.execute(active(Project)).scalars().all()) == 1

    with pytest.raises(RuntimeError):
        with session_scope(database.engine) as session:
            session.add(Project(title="会回滚", created_at=now, updated_at=now))
            raise RuntimeError("模拟失败")

    with session_scope(database.engine) as session:
        assert len(session.execute(active(Project)).scalars().all()) == 1
