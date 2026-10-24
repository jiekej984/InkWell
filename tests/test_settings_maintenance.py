"""阶段三 3.6 测试：#51 快照清理、#52 数据库自检、P9 打开数据目录桥接。

对应报告 §6.2 #51 / #52、§7.3 P9、C-07；回归 27（P9 各动作）。
"""

from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER
from backend.models import ChapterVersion, session_scope
from backend.timeutil import utc_now
from main import WindowApi


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


def _chapter(client, config, title: str = "第一章") -> int:
    project = client.post(
        "/api/projects", json={"title": "P9 测试"}, headers=_headers(config)
    ).json()["data"]
    tree = client.get(
        f"/api/projects/{project['id']}/volumes", headers=_headers(config)
    ).json()["data"]
    chapter = client.post(
        f"/api/volumes/{tree['default_volume']['id']}/chapters",
        json={"title": title},
        headers=_headers(config),
    ).json()["data"]
    return int(chapter["id"])


def _seed_auto_versions(database, chapter_id: int, count: int = 40) -> None:
    """直接落 ``count`` 条 auto 快照（全部当天，逐分钟递减）。"""
    now = utc_now()
    with session_scope(database.engine) as session:
        for index in range(count):
            session.add(
                ChapterVersion(
                    chapter_id=chapter_id,
                    version_no=1000 + index,
                    title="第一章",
                    content="<p>旧正文</p>",
                    word_count=3,
                    diff_word_count=0,
                    change_type="auto",
                    created_at=now - timedelta(minutes=index),
                )
            )


def _count_versions(database, chapter_id: int, change_type: str) -> int:
    from sqlalchemy import func, select

    with session_scope(database.engine) as session:
        return int(
            session.execute(
                select(func.count(ChapterVersion.id)).where(
                    ChapterVersion.chapter_id == chapter_id,
                    ChapterVersion.change_type == change_type,
                )
            ).scalar()
            or 0
        )


# --------------------------------------------------------------------------
# #51 清理过期自动快照
# --------------------------------------------------------------------------


def test_cleanup_snapshots_applies_retention(client, config, database) -> None:
    chapter_id = _chapter(client, config)
    _seed_auto_versions(database, chapter_id, count=40)
    manual = client.post(
        f"/api/chapters/{chapter_id}/versions",
        json={"change_type": "manual"},
        headers=_headers(config),
    ).json()
    assert manual["code"] == 0, manual

    body = client.post(
        "/api/maintenance/cleanup-snapshots", headers=_headers(config)
    ).json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["chapters"] == 1
    # 40 条 auto：保留最近 30 条 + 当天最早一条 → 删 9 条
    assert data["deleted"] == 9
    assert _count_versions(database, chapter_id, "auto") == 31
    # manual 永久保留，不受清理影响
    assert _count_versions(database, chapter_id, "manual") == 1

    # 再跑一次是幂等的：没什么可删
    again = client.post(
        "/api/maintenance/cleanup-snapshots", headers=_headers(config)
    ).json()["data"]
    assert again["deleted"] == 0


def test_cleanup_snapshots_requires_token(client) -> None:
    response = client.post("/api/maintenance/cleanup-snapshots")
    assert response.status_code == 401
    assert response.json()["code"] == 1002


# --------------------------------------------------------------------------
# #52 数据库自检
# --------------------------------------------------------------------------


def test_integrity_reports_counts_and_disk(client, config, database) -> None:
    chapter_id = _chapter(client, config)
    client.put(
        f"/api/chapters/{chapter_id}/content",
        json={"content_html": "<p>海风与灯塔</p>"},
        headers=_headers(config),
    )
    client.post("/api/projects", json={"title": "第二本"}, headers=_headers(config))

    body = client.get("/api/system/integrity", headers=_headers(config)).json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["ok"] is True
    assert data["mode"] == "quick"
    assert data["quick_check"] == "ok"
    assert data["schema_version"] == config.schema_version
    assert data["expected_schema_version"] == config.schema_version
    assert Path(data["data_dir"]) == config.data_dir
    assert data["counts"]["projects"] == 2
    assert data["counts"]["chapters"] == 1
    assert data["counts"]["drafts"] == 0
    assert data["db_size"] > 0
    assert data["wal_size"] >= 0
    assert data["disk"]["free"] > 0
    assert data["disk"]["total"] >= data["disk"]["free"]
    assert data["checked_at"].endswith("Z")

    full = client.get("/api/system/integrity?full=1", headers=_headers(config)).json()[
        "data"
    ]
    assert full["mode"] == "full"
    assert full["ok"] is True


def test_integrity_requires_token(client) -> None:
    response = client.get("/api/system/integrity")
    assert response.status_code == 401
    assert response.json()["code"] == 1002


# --------------------------------------------------------------------------
# P9 打开数据目录（桥接）
# --------------------------------------------------------------------------


def test_open_data_dir_opens_config_directory(monkeypatch, config) -> None:
    calls: list[str] = []

    def fake_startfile(path) -> None:
        calls.append(str(path))

    monkeypatch.setattr(os, "startfile", fake_startfile, raising=False)
    result = WindowApi(config).open_data_dir()

    assert result == {"ok": True, "path": str(config.data_dir)}
    assert calls == [str(config.data_dir)]


def test_open_data_dir_reports_os_error(monkeypatch, config) -> None:
    def fake_startfile(path) -> None:
        raise OSError("explorer 不可用")

    monkeypatch.setattr(os, "startfile", fake_startfile, raising=False)
    result = WindowApi(config).open_data_dir()

    assert result["ok"] is False
    assert result["path"] == str(config.data_dir)
    assert "explorer 不可用" in result["error"]
