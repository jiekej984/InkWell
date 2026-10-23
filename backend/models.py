"""SQLAlchemy 同步 ORM 模型与会话管理（任务 2.0 / 决策 S2-04）。

**DDL 的权威定义在** :mod:`backend.migrate`（原始 SQL）；本文件只是它的 ORM 映射，
两者由 ``tests/test_models_ddl.py`` 的一致性测试兜底（真跑：建库 → PRAGMA 比对）。

约定（C-06 定稿 + 两项微调）：

    · **同步** ORM（``sessionmaker``）：与 FastAPI 同步路由配套，不引入 async ORM
      增加复杂度；原生 SQL（FTS MATCH / 快照 / 备份）走 ``session.execute(text(...))``
    · 软删除**显式过滤**：活跃查询走 :func:`active`，回收站查询**裸查**不过滤
      —— 不用全局 ``before_compile`` 隐式改写（2.8 回收站必须反查已删除数据）
    · ``active()`` 是查询辅助而非隐式钩子：调用处一眼可辨「活跃 / 回收站」

未建模的表（有意）：

    · ``app_meta`` —— 迁移基础设施，由 :mod:`backend.migrate` 自行维护
    · ``chapter_fts`` / ``document_fts`` —— FTS5 虚拟表，只能用原生 SQL 查询
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Select,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

ModelT = TypeVar("ModelT", bound="Base")


class Base(DeclarativeBase):
    """声明式基类。"""


# --------------------------------------------------------------------------
# 业务表
# --------------------------------------------------------------------------


class Tag(Base):
    """标签。V1 无软删除字段（0001 DDL）。"""

    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    color: Mapped[str | None] = mapped_column(Text)


class Project(Base):
    """项目。"""

    __tablename__ = "project"
    __table_args__ = (Index("idx_project_updated", text("updated_at DESC")),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    cover_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'writing'")
    )
    target_word_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    total_word_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_chapter_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("chapter.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_deleted: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class Volume(Base):
    """卷（含默认卷，见 BR-6）。"""

    __tablename__ = "volume"
    __table_args__ = (Index("idx_volume_project", "project_id", "order_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1000")
    )
    is_default: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_deleted: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class Chapter(Base):
    """章节。"""

    __tablename__ = "chapter"
    __table_args__ = (Index("idx_chapter_volume", "volume_id", "order_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    volume_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("volume.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'draft'")
    )
    summary: Mapped[str | None] = mapped_column(Text)
    target_word_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    order_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1000")
    )
    version_no: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_deleted: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class ChapterVersion(Base):
    """章节快照：**不可变**记录（S1-08：无 ``updated_at``）。"""

    __tablename__ = "chapter_version"
    __table_args__ = (
        UniqueConstraint("chapter_id", "version_no", name="uq_chapter_version"),
        Index("idx_version_chapter", "chapter_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chapter.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    diff_word_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    change_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Document(Base):
    """设定文档（不参与全书字数，FR-4.1）。"""

    __tablename__ = "document"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    content_text: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'other'")
    )
    order_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1000")
    )
    word_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_deleted: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


class DocumentVersion(Base):
    """设定文档快照：**不可变**记录（表 V1 建，功能 V1.1 —— D-05）。"""

    __tablename__ = "document_version"
    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_document_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("document.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    diff_word_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    change_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ProjectTag(Base):
    """项目与标签的多对多关联。"""

    __tablename__ = "project_tag"

    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True
    )


# --------------------------------------------------------------------------
# 查询辅助（C-06 微调 ①：显式 ≠ 手抄）
# --------------------------------------------------------------------------

ACTIVE_MODELS: tuple[type[Base], ...] = (
    Project,
    Volume,
    Chapter,
    Document,
)


def active(model: type[ModelT], *criteria: Any) -> Select[tuple[ModelT]]:
    """活跃查询：自动带 ``is_deleted = 0``。

    回收站（2.8）需要读取已删除数据时**不要用本函数**，直接裸查
    ``select(Chapter).where(Chapter.is_deleted == 1)`` 即可。

    Raises:
        TypeError: 模型没有 ``is_deleted`` 字段（如快照表），调用方应裸查。
    """
    if not hasattr(model, "is_deleted"):
        raise TypeError(
            f"{model.__name__} 没有 is_deleted 字段，不支持 active() 查询；"
            f"请直接使用 select({model.__name__})"
        )
    statement = select(model).where(model.is_deleted == 0)  # type: ignore[attr-defined]
    for criterion in criteria:
        statement = statement.where(criterion)
    return statement


# --------------------------------------------------------------------------
# 会话管理（同步）
# --------------------------------------------------------------------------


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """按 SQLite 语义构造同步 sessionmaker。

    不启用 ``expire_on_commit=False``：默认行为（提交后过期）能避免读到陈旧对象。
    """
    return sessionmaker(bind=engine, future=True)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """事务作用域：正常退出提交，异常回滚，退出即关闭。

    SQLite 写串行化（NFR-R2）由 ``busy_timeout=5000`` 与单写者保证。
    """
    session = create_session_factory(engine)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
