"""schema 迁移骨架。

对应 §5.4「迁移」与 NFR-M5：
    · 迁移前原子备份（BR-7 / NFR-R5）
    · 按 ``schema_version`` 单调递增顺序应用
    · 失败回滚并引导从 backups/ 恢复
    · 不支持降级

**表的权威定义在本文件的迁移脚本中**（原始 SQL）。阶段二新增的 ``models.py``
需与之保持一致，届时由一致性测试兜底。

注意：迁移内**不使用** ``executescript()`` —— 它会先隐式 COMMIT，
破坏「所有迁移 + 版本号更新在同一事务内」的原子性保证。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .config import SCHEMA_VERSION
from .database import BUSY_TIMEOUT_MS

if TYPE_CHECKING:  # pragma: no cover - 仅用于类型标注
    from .database import Database

SCHEMA_VERSION_KEY = "schema_version"

Migration = Callable[[sqlite3.Connection], None]
_MIGRATIONS: dict[int, Migration] = {}


class MigrationError(RuntimeError):
    """迁移失败。"""


def migration(version: int) -> Callable[[Migration], Migration]:
    """注册一个迁移脚本；版本号必须全局唯一且单调递增。"""

    def decorator(func: Migration) -> Migration:
        if version in _MIGRATIONS:
            raise ValueError(f"重复的迁移版本号: {version}")
        _MIGRATIONS[version] = func
        return func

    return decorator


def available_versions() -> list[int]:
    """返回已注册的迁移版本号（升序）。"""
    return sorted(_MIGRATIONS)


def _ensure_app_meta(conn: sqlite3.Connection) -> None:
    """``app_meta`` 属于迁移基础设施，按需创建，不计入业务迁移脚本。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO app_meta (key, value) VALUES (?, ?)",
        (SCHEMA_VERSION_KEY, "0"),
    )


def current_schema_version(conn: sqlite3.Connection) -> int:
    """读取当前库结构版本；尚未初始化时返回 0。"""
    _ensure_app_meta(conn)
    row = conn.execute(
        "SELECT value FROM app_meta WHERE key = ?", (SCHEMA_VERSION_KEY,)
    ).fetchone()
    return int(row[0]) if row else 0


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "UPDATE app_meta SET value = ? WHERE key = ?",
        (str(version), SCHEMA_VERSION_KEY),
    )


def apply_migrations(
    database: Database,
    data_dir: Path,
    *,
    target: int | None = None,
) -> int:
    """把数据库迁移到 ``target``（默认 ``SCHEMA_VERSION``），返回迁移后的版本号。

    所有待执行迁移与 ``schema_version`` 更新位于**同一个事务**内：
    任一迁移抛异常则整体回滚，数据库保持迁移前状态（NFR-M5）。
    """
    target = SCHEMA_VERSION if target is None else target

    known = available_versions()
    if not known or known[-1] != target:
        raise MigrationError(
            f"缺少迁移脚本：无法将 schema 迁移到 {target}（已注册版本: {known}）"
        )

    conn = sqlite3.connect(str(database.db_path))
    conn.isolation_level = None  # 手动管理事务
    # PRAGMA 必须在事务之外设置（journal_mode 在事务内不可更改）
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    try:
        current = current_schema_version(conn)
        if current > target:
            raise MigrationError(
                f"数据库版本 {current} 高于应用支持的 {target}，不支持降级；"
                f"请升级应用或从 backups/ 恢复"
            )

        pending = [version for version in known if version > current]
        if not pending:
            return current

        # 迁移前原子备份（BR-7 / NFR-R5）
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backups_dir = Path(data_dir) / "backups"
        database.atomic_backup(
            backups_dir / f"inkwell_premigrate_{stamp}_v{current}.db"
        )

        conn.execute("BEGIN")
        try:
            for version in pending:
                _MIGRATIONS[version](conn)
            _set_schema_version(conn, target)
        except Exception as exc:
            conn.execute("ROLLBACK")
            raise MigrationError(
                f"迁移到 {target} 失败，已回滚：{exc}。"
                f"数据库仍为迁移前状态，可从 backups/ 核对"
            ) from exc
        conn.execute("COMMIT")
        return target
    finally:
        conn.close()


# --------------------------------------------------------------------------
# 0001 —— 初始 schema（V1）
# --------------------------------------------------------------------------
#
# 与报告 §5.2 的差异（均为小幅补全，已留痕以便复核）：
#   · 所有业务表补充 ``is_deleted`` / ``deleted_at``（依据 §5.2 通用约定）
#   · ``volume`` / ``document`` / ``document_version`` 补充 ``updated_at``
#   · FTS5 分词器采用 **trigram**（决策 S1-01，实测依据见 DECISIONS.md）
#   · ``document`` 表未建索引（§5.2 未规定），阶段二按实测再补
#
# 说明：``app_meta`` 由 ``_ensure_app_meta()`` 在读取版本时按需创建，
# 因此不在此脚本中重复建表。

_MIGRATION_0001_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE tag (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        name    TEXT NOT NULL UNIQUE,
        color   TEXT
    )
    """,
    """
    CREATE TABLE project (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        title             TEXT NOT NULL,
        description       TEXT,
        cover_path        TEXT,
        status            TEXT NOT NULL DEFAULT 'writing',
        target_word_count INTEGER NOT NULL DEFAULT 0,
        total_word_count  INTEGER NOT NULL DEFAULT 0,
        last_opened_at    DATETIME,
        last_chapter_id   INTEGER REFERENCES chapter(id) ON DELETE SET NULL,
        created_at        DATETIME NOT NULL,
        updated_at        DATETIME NOT NULL,
        is_deleted        INTEGER NOT NULL DEFAULT 0,
        deleted_at        DATETIME
    )
    """,
    "CREATE INDEX idx_project_updated ON project(updated_at DESC)",
    """
    CREATE TABLE volume (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        title       TEXT NOT NULL,
        summary     TEXT,
        order_index INTEGER NOT NULL DEFAULT 1000,
        is_default  INTEGER NOT NULL DEFAULT 0,
        created_at  DATETIME NOT NULL,
        updated_at  DATETIME NOT NULL,
        is_deleted  INTEGER NOT NULL DEFAULT 0,
        deleted_at  DATETIME
    )
    """,
    "CREATE INDEX idx_volume_project ON volume(project_id, order_index)",
    """
    CREATE TABLE chapter (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        volume_id         INTEGER NOT NULL REFERENCES volume(id) ON DELETE CASCADE,
        title             TEXT NOT NULL,
        content           TEXT,
        content_text      TEXT,
        word_count        INTEGER NOT NULL DEFAULT 0,
        status            TEXT NOT NULL DEFAULT 'draft',
        summary           TEXT,
        target_word_count INTEGER NOT NULL DEFAULT 0,
        order_index       INTEGER NOT NULL DEFAULT 1000,
        version_no        INTEGER NOT NULL DEFAULT 0,
        created_at        DATETIME NOT NULL,
        updated_at        DATETIME NOT NULL,
        is_deleted        INTEGER NOT NULL DEFAULT 0,
        deleted_at        DATETIME
    )
    """,
    "CREATE INDEX idx_chapter_volume ON chapter(volume_id, order_index)",
    """
    CREATE TABLE chapter_version (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter_id       INTEGER NOT NULL REFERENCES chapter(id) ON DELETE CASCADE,
        version_no       INTEGER NOT NULL,
        title            TEXT,
        content          TEXT NOT NULL,
        word_count       INTEGER NOT NULL DEFAULT 0,
        diff_word_count  INTEGER NOT NULL DEFAULT 0,
        change_type      TEXT NOT NULL,
        created_at       DATETIME NOT NULL,
        UNIQUE (chapter_id, version_no)
    )
    """,
    "CREATE INDEX idx_version_chapter ON chapter_version(chapter_id, created_at DESC)",
    """
    CREATE TABLE document (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id   INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        title        TEXT NOT NULL,
        content      TEXT,
        content_text TEXT,
        category     TEXT NOT NULL DEFAULT 'other',
        order_index  INTEGER NOT NULL DEFAULT 1000,
        word_count   INTEGER NOT NULL DEFAULT 0,
        created_at   DATETIME NOT NULL,
        updated_at   DATETIME NOT NULL,
        is_deleted   INTEGER NOT NULL DEFAULT 0,
        deleted_at   DATETIME
    )
    """,
    """
    CREATE TABLE document_version (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id      INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
        version_no       INTEGER NOT NULL,
        title            TEXT,
        content          TEXT NOT NULL,
        word_count       INTEGER NOT NULL DEFAULT 0,
        diff_word_count  INTEGER NOT NULL DEFAULT 0,
        change_type      TEXT NOT NULL,
        created_at       DATETIME NOT NULL,
        UNIQUE (document_id, version_no)
    )
    """,
    """
    CREATE TABLE project_tag (
        project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        tag_id      INTEGER NOT NULL REFERENCES tag(id) ON DELETE CASCADE,
        PRIMARY KEY (project_id, tag_id)
    )
    """,
    # 全文检索：external content 表，正文只存一份（ADR-008 / §5.2）
    """
    CREATE VIRTUAL TABLE chapter_fts USING fts5(
        title,
        content_text,
        content='chapter',
        content_rowid='id',
        tokenize='trigram'
    )
    """,
    # external content 表不会自动同步，必须由触发器维护（SQLite 官方 FTS5 文档 §4.4.3）
    """
    CREATE TRIGGER chapter_fts_ai AFTER INSERT ON chapter BEGIN
        INSERT INTO chapter_fts(rowid, title, content_text)
        VALUES (new.id, new.title, new.content_text);
    END
    """,
    """
    CREATE TRIGGER chapter_fts_ad AFTER DELETE ON chapter BEGIN
        INSERT INTO chapter_fts(chapter_fts, rowid, title, content_text)
        VALUES ('delete', old.id, old.title, old.content_text);
    END
    """,
    """
    CREATE TRIGGER chapter_fts_au AFTER UPDATE ON chapter BEGIN
        INSERT INTO chapter_fts(chapter_fts, rowid, title, content_text)
        VALUES ('delete', old.id, old.title, old.content_text);
        INSERT INTO chapter_fts(rowid, title, content_text)
        VALUES (new.id, new.title, new.content_text);
    END
    """,
)


@migration(1)
def _0001_initial_schema(conn: sqlite3.Connection) -> None:
    """建立 V1 全量业务表、索引、FTS5 外部内容表与同步触发器。"""
    for statement in _MIGRATION_0001_STATEMENTS:
        conn.execute(statement)


# --------------------------------------------------------------------------
# 0002 —— 设定文档全文检索（决策 S2-02）
# --------------------------------------------------------------------------
#
# 背景：§5.2 只定义了 ``chapter_fts``，而 FR-7.1（Must）要求检索覆盖
# **章节标题 + 章节正文 + 设定文档**，故补建 ``document_fts``。
#
# 约束（发起人 2026-10-23 定稿）：
#   · 与 ``chapter_fts`` **完全同构**：external content + trigram + 三触发器
#   · **不回改 0001**，作为独立迁移版本追加
#   · 阶段一 ``data/inkwell.db`` 为空测试库，**不做数据回填**
#   · 查询侧在 service 层分两次查后合并（不用 UNION），便于范围切换

_MIGRATION_0002_STATEMENTS: tuple[str, ...] = (
    """
    CREATE VIRTUAL TABLE document_fts USING fts5(
        title,
        content_text,
        content='document',
        content_rowid='id',
        tokenize='trigram'
    )
    """,
    """
    CREATE TRIGGER document_fts_ai AFTER INSERT ON document BEGIN
        INSERT INTO document_fts(rowid, title, content_text)
        VALUES (new.id, new.title, new.content_text);
    END
    """,
    """
    CREATE TRIGGER document_fts_ad AFTER DELETE ON document BEGIN
        INSERT INTO document_fts(document_fts, rowid, title, content_text)
        VALUES ('delete', old.id, old.title, old.content_text);
    END
    """,
    """
    CREATE TRIGGER document_fts_au AFTER UPDATE ON document BEGIN
        INSERT INTO document_fts(document_fts, rowid, title, content_text)
        VALUES ('delete', old.id, old.title, old.content_text);
        INSERT INTO document_fts(rowid, title, content_text)
        VALUES (new.id, new.title, new.content_text);
    END
    """,
)


@migration(2)
def _0002_document_fts(conn: sqlite3.Connection) -> None:
    """为设定文档建立 FTS5 外部内容表与同步触发器（FR-7.1 / S2-02）。"""
    for statement in _MIGRATION_0002_STATEMENTS:
        conn.execute(statement)


# --------------------------------------------------------------------------
# 0003 —— 角色库：角色 / 组织 / 大立场 十表（V2.0 任务 5.1）
# --------------------------------------------------------------------------
#
# 与报告 v2.1 §5.2 的 DDL **逐字一致**（含 6 条部分唯一索引），差异仅两处：
#   · 语句不含结尾分号（迁移逐条 ``conn.execute``）
#   · ``graph_layout`` 在本版**改为 ORM 建模**（报告原写「不入 ORM」），
#     目的是让 ``test_models_ddl.py`` 的表集合比对保持严格，不必新增排除项
#
# 关键设计（详见 5.0 走查基线 §三）：
#   · 唯一性一律用**部分唯一索引** ``WHERE is_deleted = 0``，否则删了加不回来
#   · ``custom_label`` 用空串而非 NULL —— SQLite 的 NULL 不参与唯一比较
#   · ``age`` / ``height`` 用 TEXT，容纳「十六七岁」「一丈二」等中文描述

_MIGRATION_0003_STATEMENTS: tuple[str, ...] = (
    # ① 角色
    """
    CREATE TABLE character (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        name        TEXT    NOT NULL,
        role        TEXT    NOT NULL DEFAULT 'supporting',
        gender      TEXT,
        age         TEXT,
        height      TEXT,
        appearance  TEXT,
        personality TEXT,
        background  TEXT,
        abilities   TEXT,
        catchphrase TEXT,
        motivation  TEXT,
        note        TEXT,
        status      TEXT    NOT NULL DEFAULT 'alive',
        avatar_path TEXT,
        tags        TEXT,
        source      TEXT    NOT NULL DEFAULT 'manual',
        meta_json   TEXT,
        order_index INTEGER NOT NULL DEFAULT 1000,
        created_at  DATETIME NOT NULL,
        updated_at  DATETIME NOT NULL,
        is_deleted  INTEGER NOT NULL DEFAULT 0,
        deleted_at  DATETIME
    )
    """,
    "CREATE INDEX idx_character_project ON character(project_id, order_index)",
    "CREATE INDEX idx_character_active  ON character(project_id, is_deleted)",
    # ② 别名
    """
    CREATE TABLE character_alias (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id   INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        character_id INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
        alias        TEXT    NOT NULL,
        created_at   DATETIME NOT NULL,
        is_deleted   INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE UNIQUE INDEX uq_alias_active ON character_alias(project_id, alias) "
    "WHERE is_deleted = 0",
    "CREATE INDEX idx_alias_character ON character_alias(character_id)",
    # ③ 自定义字段
    """
    CREATE TABLE character_field (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        character_id INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
        key          TEXT    NOT NULL,
        value        TEXT,
        field_type   TEXT    NOT NULL DEFAULT 'text',
        order_index  INTEGER NOT NULL DEFAULT 1000,
        created_at   DATETIME NOT NULL,
        updated_at   DATETIME NOT NULL,
        UNIQUE (character_id, key)
    )
    """,
    # ④ 大立场
    """
    CREATE TABLE faction (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        name        TEXT    NOT NULL,
        color       TEXT,
        description TEXT,
        order_index INTEGER NOT NULL DEFAULT 1000,
        created_at  DATETIME NOT NULL,
        updated_at  DATETIME NOT NULL,
        is_deleted  INTEGER NOT NULL DEFAULT 0,
        deleted_at  DATETIME
    )
    """,
    "CREATE UNIQUE INDEX uq_faction_name ON faction(project_id, name) "
    "WHERE is_deleted = 0",
    "CREATE INDEX idx_faction_project ON faction(project_id, order_index)",
    # ⑤ 组织
    """
    CREATE TABLE organization (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        faction_id  INTEGER REFERENCES faction(id) ON DELETE SET NULL,
        parent_id   INTEGER REFERENCES organization(id) ON DELETE CASCADE,
        name        TEXT    NOT NULL,
        kind        TEXT    NOT NULL DEFAULT 'other',
        leader_id   INTEGER REFERENCES character(id) ON DELETE SET NULL,
        description TEXT,
        document_id INTEGER REFERENCES document(id) ON DELETE SET NULL,
        color       TEXT,
        order_index INTEGER NOT NULL DEFAULT 1000,
        created_at  DATETIME NOT NULL,
        updated_at  DATETIME NOT NULL,
        is_deleted  INTEGER NOT NULL DEFAULT 0,
        deleted_at  DATETIME,
        CHECK (parent_id IS NULL OR parent_id <> id)
    )
    """,
    "CREATE UNIQUE INDEX uq_org_name ON organization(project_id, name) "
    "WHERE is_deleted = 0",
    "CREATE INDEX idx_org_project ON organization(project_id, parent_id, order_index)",
    "CREATE INDEX idx_org_faction ON organization(faction_id)",
    # ⑥ 组织成员
    """
    CREATE TABLE org_member (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        character_id    INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
        org_id          INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
        position        TEXT,
        is_primary      INTEGER NOT NULL DEFAULT 0,
        is_secret       INTEGER NOT NULL DEFAULT 0,
        from_chapter_id INTEGER REFERENCES chapter(id) ON DELETE SET NULL,
        to_chapter_id   INTEGER REFERENCES chapter(id) ON DELETE SET NULL,
        created_at      DATETIME NOT NULL,
        updated_at      DATETIME NOT NULL,
        is_deleted      INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE UNIQUE INDEX uq_member_active ON org_member(character_id, org_id) "
    "WHERE is_deleted = 0",
    "CREATE INDEX idx_member_org ON org_member(org_id)",
    "CREATE INDEX idx_member_character ON org_member(character_id)",
    # ⑦ 组织间关系
    """
    CREATE TABLE org_relation (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id       INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        from_id          INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
        to_id            INTEGER NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
        relation_type    TEXT    NOT NULL DEFAULT 'neutral',
        description      TEXT,
        is_bidirectional INTEGER NOT NULL DEFAULT 0,
        from_chapter_id  INTEGER REFERENCES chapter(id) ON DELETE SET NULL,
        to_chapter_id    INTEGER REFERENCES chapter(id) ON DELETE SET NULL,
        created_at       DATETIME NOT NULL,
        updated_at       DATETIME NOT NULL,
        is_deleted       INTEGER NOT NULL DEFAULT 0,
        deleted_at       DATETIME,
        CHECK (from_id <> to_id)
    )
    """,
    "CREATE UNIQUE INDEX uq_org_rel_active "
    "ON org_relation(from_id, to_id, relation_type) WHERE is_deleted = 0",
    "CREATE INDEX idx_org_rel_project ON org_relation(project_id, is_deleted)",
    # ⑧ 大立场间关系
    """
    CREATE TABLE faction_relation (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id       INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        from_id          INTEGER NOT NULL REFERENCES faction(id) ON DELETE CASCADE,
        to_id            INTEGER NOT NULL REFERENCES faction(id) ON DELETE CASCADE,
        relation_type    TEXT    NOT NULL DEFAULT 'neutral',
        description      TEXT,
        is_bidirectional INTEGER NOT NULL DEFAULT 1,
        created_at       DATETIME NOT NULL,
        updated_at       DATETIME NOT NULL,
        is_deleted       INTEGER NOT NULL DEFAULT 0,
        deleted_at       DATETIME,
        CHECK (from_id <> to_id)
    )
    """,
    "CREATE UNIQUE INDEX uq_faction_rel_active "
    "ON faction_relation(from_id, to_id, relation_type) WHERE is_deleted = 0",
    # ⑨ 角色关系
    """
    CREATE TABLE character_relation (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id       INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
        from_id          INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
        to_id            INTEGER NOT NULL REFERENCES character(id) ON DELETE CASCADE,
        relation_type    TEXT    NOT NULL DEFAULT 'other',
        custom_label     TEXT    NOT NULL DEFAULT '',
        description      TEXT,
        is_bidirectional INTEGER NOT NULL DEFAULT 0,
        is_secret        INTEGER NOT NULL DEFAULT 0,
        from_chapter_id  INTEGER REFERENCES chapter(id) ON DELETE SET NULL,
        to_chapter_id    INTEGER REFERENCES chapter(id) ON DELETE SET NULL,
        created_at       DATETIME NOT NULL,
        updated_at       DATETIME NOT NULL,
        is_deleted       INTEGER NOT NULL DEFAULT 0,
        deleted_at       DATETIME,
        CHECK (from_id <> to_id)
    )
    """,
    "CREATE UNIQUE INDEX uq_char_rel_active "
    "ON character_relation(from_id, to_id, relation_type, custom_label) "
    "WHERE is_deleted = 0",
    "CREATE INDEX idx_char_rel_project ON character_relation(project_id, is_deleted)",
    "CREATE INDEX idx_char_rel_from ON character_relation(from_id)",
    "CREATE INDEX idx_char_rel_to ON character_relation(to_id)",
    # ⑩ 画布布局
    """
    CREATE TABLE graph_layout (
        project_id INTEGER PRIMARY KEY REFERENCES project(id) ON DELETE CASCADE,
        payload    TEXT    NOT NULL,
        updated_at DATETIME NOT NULL
    )
    """,
)


@migration(3)
def _0003_character_library(conn: sqlite3.Connection) -> None:
    """角色库十表（V2.0 / FR-8.1~8.24 的存储底座）。"""
    for statement in _MIGRATION_0003_STATEMENTS:
        conn.execute(statement)


@migration(4)
def _0004_org_member_deletion_batch(conn: sqlite3.Connection) -> None:
    """为组织成员增加独立软删批次，避免组织恢复带回旧手动移除成员。"""
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(org_member)").fetchall()
    }
    if "deleted_at" not in columns:
        conn.execute("ALTER TABLE org_member ADD COLUMN deleted_at DATETIME")
    # V2.0 将组织批量删除时间写在成员 updated_at；用它回填旧删除记录，
    # 让旧组织批次恢复保持原行为，同时将更早手动移除的成员排除在外。
    conn.execute(
        "UPDATE org_member SET deleted_at = updated_at "
        "WHERE is_deleted = 1 AND deleted_at IS NULL"
    )
    conn.execute(
        "CREATE INDEX idx_member_restore_batch "
        "ON org_member(org_id, is_deleted, deleted_at)"
    )
