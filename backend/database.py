"""SQLite 连接与运维：PRAGMA、WAL、checkpoint、在线备份（§5.4）。"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

BUSY_TIMEOUT_MS = 5000
WAL_CHECKPOINT_INTERVAL_SECONDS = 300  # 假设值，阶段二调优后固化
WAL_CHECKPOINT_THRESHOLD_BYTES = 32 * 1024 * 1024  # 假设值


class DatabaseError(RuntimeError):
    """数据库层异常。"""


@event.listens_for(Engine, "connect")
def _apply_pragmas(dbapi_connection: object, connection_record: object) -> None:
    """为每个新建连接设置 PRAGMA（§4.5 启动流程第 4 步 / §5.4）。

    决策 S1-05：SQLAlchemy 2.0 官方 SQLite 文档示例在执行
    ``PRAGMA foreign_keys=ON`` 前会先切 ``dbapi_connection.autocommit = True``，
    但 **Python 3.11 的 ``sqlite3.Connection`` 并不存在 ``autocommit`` 属性**
    （该属性自 3.12 起才提供），照抄会抛 ``AttributeError``。
    本项目实测（Python 3.11.9 + SQLAlchemy 2.1.6）：``connect`` 事件触发时
    ``isolation_level == ''``，事务尚未开启，此时直接执行 PRAGMA 即可生效
    （``PRAGMA foreign_keys`` 返回 1）。因此这里不切换 autocommit。
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def _check_file(path: Path) -> tuple[bool, list[str]]:
    """对单个数据库文件执行 quick_check。"""
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute("PRAGMA quick_check").fetchall()
    finally:
        conn.close()
    messages = [str(row[0]) for row in rows]
    return (messages == ["ok"]), messages


class Database:
    """封装 SQLAlchemy Engine 与 SQLite 运维操作。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = self._build_engine()

    def _build_engine(self) -> Engine:
        return create_engine(
            f"sqlite+pysqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
            future=True,
        )

    def reopen(self) -> None:
        """释放连接池并按同一路径重建 Engine（恢复备份后调用）。"""
        self.engine.dispose()
        self.engine = self._build_engine()

    def connect(self):
        """获取一个连接（调用方负责关闭）。"""
        return self.engine.connect()

    def quick_check(self) -> tuple[bool, list[str]]:
        """启动自检（§4.5 第 5 步）。"""
        with self.engine.connect() as conn:
            rows = conn.execute(text("PRAGMA quick_check")).fetchall()
        messages = [str(row[0]) for row in rows]
        return (messages == ["ok"]), messages

    def integrity_check(self) -> tuple[bool, list[str]]:
        """完整完整性检查（每周一次或异常时，后台执行）。"""
        with self.engine.connect() as conn:
            rows = conn.execute(text("PRAGMA integrity_check")).fetchall()
        messages = [str(row[0]) for row in rows]
        return (messages == ["ok"]), messages

    def checkpoint(self, mode: str = "TRUNCATE") -> tuple[int, int, int]:
        """执行 WAL checkpoint，返回 ``(busy, log, checkpointed)``。"""
        with self.engine.connect() as conn:
            row = conn.execute(text(f"PRAGMA wal_checkpoint({mode})")).fetchone()
        if row is None:
            return (1, -1, -1)
        return (int(row[0]), int(row[1]), int(row[2]))

    def backup(self, dest: Path) -> Path:
        """在线热备：使用 ``sqlite3.Connection.backup()``（§5.4）。"""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(str(self.db_path))
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return dest

    def atomic_backup(self, dest: Path) -> Path:
        """原子备份：checkpoint → 备份到 ``.tmp`` → 完整性校验 → ``os.replace``。

        保证目标文件任一时刻要么是旧版本、要么是完整的新版本（BR-7 / NFR-R5）。
        阶段一由迁移流程使用；阶段二 2.9 的备份服务将复用本方法。
        """
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint("TRUNCATE")  # §5.4：备份前强制 checkpoint

        tmp = dest.with_name(dest.name + ".tmp")
        if tmp.exists():
            tmp.unlink()
        try:
            self.backup(tmp)
            healthy, messages = _check_file(tmp)
            if not healthy:
                raise DatabaseError(
                    f"备份文件未通过完整性检查: {dest} ({'; '.join(messages)})"
                )
            os.replace(tmp, dest)
        finally:
            if tmp.exists():
                tmp.unlink()
        return dest

    def dispose(self) -> None:
        """释放连接池。"""
        self.engine.dispose()
