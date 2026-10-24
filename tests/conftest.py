"""阶段一测试夹具。

提供相互隔离的数据目录、已迁移的数据库，以及 TestClient。
每个测试自动清除代理环境变量，避免本机 R-17 影响测试客户端。
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import (
    clear_proxy_env,
    ensure_data_dirs,
    load_config,
    pick_free_port,
)
from backend.database import Database
from backend.migrate import apply_migrations
from backend.server import create_app


@pytest.fixture(autouse=True)
def _clean_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """清除代理环境变量（R-17 缓解措施 ①②）。"""
    clear_proxy_env()
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """临时数据目录（通过 INKWELL_DATA_DIR 指定）。"""
    target = tmp_path / "InkwellData"
    monkeypatch.setenv("INKWELL_DATA_DIR", str(target))
    return target


@pytest.fixture
def config(data_dir: Path):
    """测试用配置：独立数据目录 + 独立端口。"""
    cfg = replace(load_config(), port=pick_free_port())
    ensure_data_dirs(cfg)
    return cfg


@pytest.fixture
def database(config) -> Database:
    """已完成迁移的数据库实例。"""
    db = Database(config.db_path)
    apply_migrations(db, config.data_dir)
    return db


@pytest.fixture
def app(config, database):
    """FastAPI 应用，schema_version 与 database 已注入。"""
    application = create_app(config, database)
    application.state.schema_version = config.schema_version
    return application


@pytest.fixture
def client(app):
    """TestClient。

    base_url 必须是 127.0.0.1 / localhost，否则会被 Host 校验拦截（NFR-S5）。
    """
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        yield test_client


# --------------------------------------------------------------------------
# V2.0 角色库测试夹具
# --------------------------------------------------------------------------


@pytest.fixture
def project_id(database) -> int:
    """一本书（直接落库，不经过 service，避免测试依赖被测代码）。"""
    from sqlalchemy import select

    from backend.models import Project, session_scope
    from backend.timeutil import utc_now

    now = utc_now()
    with session_scope(database.engine) as session:
        existing = session.execute(select(Project)).scalars().first()
        if existing is not None:
            return int(existing.id)
        project = Project(
            title="测试书", created_at=now, updated_at=now, status="writing"
        )
        session.add(project)
        session.flush()
        return int(project.id)


@pytest.fixture
def chapter_factory(database, project_id):
    """按（卷序, 章序）造章节；同卷序复用同一个卷。返回 (volume_id, chapter_id)。"""
    from sqlalchemy import select

    from backend.models import Chapter, Volume, session_scope
    from backend.timeutil import utc_now

    def make(
        *,
        title: str = "章",
        volume_order: int = 1000,
        chapter_order: int = 1000,
    ) -> tuple[int, int]:
        now = utc_now()
        with session_scope(database.engine) as session:
            volume = (
                session.execute(
                    select(Volume).where(
                        Volume.project_id == project_id,
                        Volume.order_index == volume_order,
                        Volume.is_deleted == 0,
                    )
                )
                .scalars()
                .first()
            )
            if volume is None:
                volume = Volume(
                    project_id=project_id,
                    title=f"卷 {volume_order}",
                    order_index=volume_order,
                    created_at=now,
                    updated_at=now,
                )
                session.add(volume)
                session.flush()
            chapter = Chapter(
                volume_id=int(volume.id),
                title=title,
                content="",
                content_text="",
                word_count=0,
                order_index=chapter_order,
                created_at=now,
                updated_at=now,
            )
            session.add(chapter)
            session.flush()
            return (int(volume.id), int(chapter.id))

    return make


@pytest.fixture
def character_factory(database, project_id):
    """快速造角色（走 service，保证默认值/顺序与线上一致）。"""
    from backend.models import session_scope
    from backend.services import character_service

    def make(name: str, **fields) -> int:
        with session_scope(database.engine) as session:
            row = character_service.create_character(
                session, project_id, name=name, **fields
            )
            return int(row.id)

    return make
