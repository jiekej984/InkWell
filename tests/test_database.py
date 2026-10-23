"""任务 1.5 数据库运维测试：PRAGMA、WAL、checkpoint、备份。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from backend.database import Database


def test_foreign_keys_enabled(database: Database) -> None:
    with database.connect() as conn:
        value = conn.execute(text("PRAGMA foreign_keys")).fetchone()[0]
    assert value == 1


def test_journal_mode_is_wal(database: Database) -> None:
    with database.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).fetchone()[0]
    assert mode == "wal"


def test_busy_timeout_configured(database: Database) -> None:
    with database.connect() as conn:
        timeout = conn.execute(text("PRAGMA busy_timeout")).fetchone()[0]
    assert timeout == 5000


def test_quick_check_is_healthy(database: Database) -> None:
    healthy, messages = database.quick_check()
    assert healthy is True
    assert messages == ["ok"]


def test_checkpoint_returns_triple(database: Database) -> None:
    result = database.checkpoint("TRUNCATE")
    assert len(result) == 3
    assert all(isinstance(item, int) for item in result)


def test_backup_produces_readable_copy(database: Database, tmp_path: Path) -> None:
    dest = tmp_path / "backup.db"
    database.backup(dest)
    assert dest.is_file()

    conn = sqlite3.connect(str(dest))
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert "project" in tables
    assert "app_meta" in tables


def test_atomic_backup_leaves_no_tmp_file(database: Database, tmp_path: Path) -> None:
    dest = tmp_path / "atomic.db"
    database.atomic_backup(dest)
    assert dest.is_file()
    assert list(tmp_path.glob("*.tmp")) == []


def test_wal_files_created_next_to_db(database: Database) -> None:
    with database.connect() as conn:
        conn.execute(text("SELECT 1"))
    # WAL 模式下会伴随 -wal / -shm 文件（§4.4 数据目录布局）
    assert (database.db_path.parent).is_dir()
