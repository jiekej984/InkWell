"""任务 1.5 迁移骨架测试：版本写入、幂等、迁移前备份、失败回滚。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from backend.config import SCHEMA_VERSION
from backend.database import Database
from backend.migrate import (
    MigrationError,
    apply_migrations,
    available_versions,
    current_schema_version,
)

EXPECTED_TABLES = {
    "project",
    "tag",
    "project_tag",
    "volume",
    "chapter",
    "chapter_version",
    "document",
    "document_version",
    "app_meta",
    # V2.0 角色库（0003）
    "character",
    "character_alias",
    "character_field",
    "faction",
    "organization",
    "org_member",
    "org_relation",
    "faction_relation",
    "character_relation",
    "graph_layout",
}

# 0003 的 7 条部分唯一索引：唯一性只约束活跃行，软删后可重建
PARTIAL_UNIQUE_INDEXES = {
    "uq_alias_active",
    "uq_faction_name",
    "uq_org_name",
    "uq_member_active",
    "uq_org_rel_active",
    "uq_faction_rel_active",
    "uq_char_rel_active",
}


def _tables(database: Database) -> set[str]:
    with database.connect() as conn:
        return {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }


def test_initial_migration_creates_full_schema(config) -> None:
    database = Database(config.db_path)
    version = apply_migrations(database, config.data_dir)
    assert version == SCHEMA_VERSION
    assert EXPECTED_TABLES <= _tables(database)
    database.dispose()


def test_schema_version_is_written(database: Database) -> None:
    with database.connect() as conn:
        row = conn.execute(
            text("SELECT value FROM app_meta WHERE key='schema_version'")
        ).fetchone()
    assert row is not None
    assert int(row[0]) == SCHEMA_VERSION


def test_current_schema_version_reads_persisted_value(database: Database) -> None:
    conn = sqlite3.connect(str(database.db_path))
    try:
        assert current_schema_version(conn) == SCHEMA_VERSION
    finally:
        conn.close()


def test_fts_table_uses_trigram_tokenizer(database: Database) -> None:
    """决策 S1-01：FTS5 采用 trigram，保证中文子串可检索。"""
    conn = sqlite3.connect(str(database.db_path))
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='chapter_fts'"
        ).fetchone()
        assert row is not None
        assert "trigram" in row[0]
        assert "content='chapter'" in row[0]

        conn.execute(
            "INSERT INTO volume (project_id, title, created_at, updated_at) VALUES (1, 'v', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "INSERT INTO chapter (volume_id, title, content, content_text, created_at, updated_at) "
            "VALUES (1, '第一章', '<p>黑水河畔的少年</p>', '黑水河畔的少年', '2026-01-01', '2026-01-01')"
        )
        hits = conn.execute(
            "SELECT count(*) FROM chapter_fts WHERE chapter_fts MATCH '水河畔'"
        ).fetchone()[0]
        assert hits == 1
    finally:
        conn.close()


def test_rerun_is_idempotent(database: Database, config) -> None:
    backups_dir = config.data_dir / "backups"
    before = sorted(path.name for path in backups_dir.glob("*.db"))

    version = apply_migrations(database, config.data_dir)
    after = sorted(path.name for path in backups_dir.glob("*.db"))

    assert version == SCHEMA_VERSION
    assert before == after, "重复执行迁移不应产生新的备份"


def test_premigrate_backup_created(config) -> None:
    """迁移前必须产出原子备份（BR-7 / NFR-R5）。"""
    database = Database(config.db_path)
    apply_migrations(database, config.data_dir)

    backups = sorted((config.data_dir / "backups").glob("inkwell_premigrate_*.db"))
    assert backups, "迁移前未生成备份文件"
    assert list((config.data_dir / "backups").glob("*.tmp")) == []
    database.dispose()


def test_failed_migration_rolls_back(config) -> None:
    """迁移失败必须整体回滚，数据库保持迁移前状态（NFR-M5）。"""
    from backend import migrate as migrate_module

    database = Database(config.db_path)
    apply_migrations(database, config.data_dir)

    @migrate_module.migration(SCHEMA_VERSION + 1)
    def _exploding(_: sqlite3.Connection) -> None:
        _ = None
        raise RuntimeError("模拟迁移失败")

    try:
        with pytest.raises(MigrationError):
            apply_migrations(database, config.data_dir, target=SCHEMA_VERSION + 1)
    finally:
        # 清理测试期间注册的迁移，避免影响其它用例
        migrate_module._MIGRATIONS.pop(SCHEMA_VERSION + 1, None)

    with database.connect() as conn:
        version = conn.execute(
            text("SELECT value FROM app_meta WHERE key='schema_version'")
        ).fetchone()[0]
    assert int(version) == SCHEMA_VERSION, "失败迁移不应改变 schema_version"
    database.dispose()


def test_available_versions_start_at_one() -> None:
    assert available_versions()[0] == 1


# --------------------------------------------------------------------------
# 0003 角色库
# --------------------------------------------------------------------------


def _build_schema_v2(path: Path) -> None:
    """按真实的 0001 / 0002 语句造一个 schema 2 的库（用于升级测试）。

    不复用 ``apply_migrations(target=2)``：该函数只接受「已注册的最高版本」，
    注册 0003 之后无法再迁到 2，这是刻意的单向约束（NFR-M5 不支持降级）。
    """
    from backend import migrate as migrate_module

    conn = sqlite3.connect(str(path))
    conn.isolation_level = None
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO app_meta(key, value) VALUES ('schema_version', '0')")
        for statement in migrate_module._MIGRATION_0001_STATEMENTS:
            conn.execute(statement)
        for statement in migrate_module._MIGRATION_0002_STATEMENTS:
            conn.execute(statement)
        conn.execute("UPDATE app_meta SET value = '2' WHERE key = 'schema_version'")
    finally:
        conn.close()


def test_migration_0003_partial_unique_indexes(database: Database) -> None:
    """唯一性只约束活跃行：7 条部分唯一索引必须带 ``WHERE is_deleted = 0``。"""
    conn = sqlite3.connect(str(database.db_path))
    try:
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='index' AND name LIKE 'uq_%'"
        ).fetchall()
    finally:
        conn.close()

    assert {name for name, _ in rows} == PARTIAL_UNIQUE_INDEXES
    for name, sql in rows:
        assert sql is not None, f"{name} 是自动索引，应为显式创建"
        assert "WHERE is_deleted = 0" in sql, f"{name} 缺少部分索引条件：{sql}"


def test_character_relation_custom_label_defaults_to_empty_string(
    database: Database,
) -> None:
    """NULL 不参与唯一比较，故默认值必须是空串（自审 B1）。"""
    conn = sqlite3.connect(str(database.db_path))
    try:
        columns = {
            row[1]: row[4]
            for row in conn.execute("PRAGMA table_info(character_relation)")
        }
    finally:
        conn.close()
    assert columns["custom_label"] == "''"


def test_upgrade_from_schema_2_preserves_data(config) -> None:
    """2 → 3 升级：新表建齐，旧数据不丢（NFR-M3 / AC-23）。"""
    path = config.data_dir / "upgrade.db"
    _build_schema_v2(path)

    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "INSERT INTO project(title, created_at, updated_at) "
            "VALUES ('旧书', '2026-01-01', '2026-01-01')"
        )
        conn.commit()
        assert current_schema_version(conn) == 2
    finally:
        conn.close()

    database = Database(path)
    try:
        version = apply_migrations(database, config.data_dir)
        assert version == SCHEMA_VERSION
    finally:
        database.dispose()

    conn = sqlite3.connect(str(path))
    try:
        assert current_schema_version(conn) == 3
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert EXPECTED_TABLES <= tables
        assert conn.execute("SELECT title FROM project").fetchone()[0] == "旧书"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        conn.close()
