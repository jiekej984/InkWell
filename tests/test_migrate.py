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
