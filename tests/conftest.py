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
