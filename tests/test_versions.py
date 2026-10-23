"""任务 2.6 测试：分级快照（D-04）、版本列表/详情、回滚（BR-9）与物理删除。"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER
from backend.models import Chapter, ChapterVersion, Project, Volume, session_scope
from backend.services import version_service
from backend.timeutil import utc_now


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


@pytest.fixture
def chapter_id(client, config) -> int:
    project = client.post(
        "/api/projects", json={"title": "版本测试"}, headers=_headers(config)
    ).json()["data"]
    tree = client.get(
        f"/api/projects/{project['id']}/volumes", headers=_headers(config)
    ).json()["data"]
    chapter = client.post(
        f"/api/volumes/{tree['default_volume']['id']}/chapters",
        json={"title": "第一章"},
        headers=_headers(config),
    ).json()["data"]
    return chapter["id"]


def _save(client, config, cid: int, text: str, expect: int | None = None):
    body = {"content_html": f"<p>{text}</p>"}
    if expect is not None:
        body["expect_version"] = expect
    return client.put(
        f"/api/chapters/{cid}/content", json=body, headers=_headers(config)
    ).json()


def _set_latest_snapshot_created_at(database, cid: int, offset: timedelta) -> None:
    with session_scope(database.engine) as session:
        row = version_service.latest_snapshot(session, cid)
        row.created_at = utc_now() - offset


def _mark_manual(client, config, cid: int, change_type: str = "manual") -> dict:
    body = client.post(
        f"/api/chapters/{cid}/versions",
        json={"change_type": change_type},
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body
    return body["data"]


# --------------------------------------------------------------------------
# auto 快照（D-04）
# --------------------------------------------------------------------------


def test_auto_snapshot_on_first_long_save(client, config, database, chapter_id) -> None:
    data = _save(client, config, chapter_id, "字" * 250, expect=0)["data"]
    assert data["version_no"] == 1
    assert data["snapshot_created"] is True
    assert data["snapshot_version_no"] == 1

    listing = client.get(
        f"/api/chapters/{chapter_id}/versions", headers=_headers(config)
    ).json()["data"]
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["change_type"] == "auto"
    assert item["version_no"] == 1
    assert item["word_count"] == 250
    assert item["diff_word_count"] == 250


def test_no_auto_snapshot_for_short_content(client, config, chapter_id) -> None:
    data = _save(client, config, chapter_id, "短内容")["data"]
    assert data["snapshot_created"] is False
    listing = client.get(
        f"/api/chapters/{chapter_id}/versions", headers=_headers(config)
    ).json()["data"]
    assert listing["total"] == 0


def test_auto_snapshot_requires_interval_and_word_delta(
    client, config, database, chapter_id
) -> None:
    first = _save(client, config, chapter_id, "字" * 250)["data"]
    assert first["snapshot_created"] is True

    # 快照刚创建：即使字数差 ≥200 也不应再建（<5 分钟）
    _set_latest_snapshot_created_at(database, chapter_id, timedelta(seconds=5))
    second = _save(client, config, chapter_id, "字" * 500)["data"]
    assert second["snapshot_created"] is False

    # 把快照时间拨回 10 分钟前 → 满足间隔 + 字数差
    _set_latest_snapshot_created_at(database, chapter_id, timedelta(minutes=10))
    third = _save(client, config, chapter_id, "字" * 800)["data"]
    assert third["snapshot_created"] is True
    assert third["snapshot_version_no"] == third["version_no"]

    with session_scope(database.engine) as session:
        count = session.execute(
            select(func.count(ChapterVersion.id)).where(
                ChapterVersion.chapter_id == chapter_id
            )
        ).scalar()
    assert count == 2


def test_auto_snapshot_word_delta_threshold(
    client, config, database, chapter_id
) -> None:
    _save(client, config, chapter_id, "字" * 250)
    _set_latest_snapshot_created_at(database, chapter_id, timedelta(minutes=10))
    # 只增加 100 字：不满足 ≥200
    data = _save(client, config, chapter_id, "字" * 350)["data"]
    assert data["snapshot_created"] is False


# --------------------------------------------------------------------------
# manual / milestone
# --------------------------------------------------------------------------


def test_manual_snapshot(client, config, chapter_id) -> None:
    _save(client, config, chapter_id, "短内容")
    item = _mark_manual(client, config, chapter_id)
    assert item["change_type"] == "manual"
    assert item["version_no"] == 2  # 保存到 #1，手动快照递增到 #2
    assert item["word_count"] == 3

    detail = client.get(f"/api/chapters/{chapter_id}", headers=_headers(config)).json()[
        "data"
    ]
    assert detail["version_no"] == 2

    listing = client.get(
        f"/api/chapters/{chapter_id}/versions", headers=_headers(config)
    ).json()["data"]
    assert [row["version_no"] for row in listing["items"]] == [2]


def test_milestone_snapshot(client, config, chapter_id) -> None:
    _save(client, config, chapter_id, "定稿内容")
    item = _mark_manual(client, config, chapter_id, "milestone")
    assert item["change_type"] == "milestone"


def test_invalid_snapshot_type_rejected(client, config, chapter_id) -> None:
    body = client.post(
        f"/api/chapters/{chapter_id}/versions",
        json={"change_type": "auto"},
        headers=_headers(config),
    ).json()
    assert body["code"] == 1001


# --------------------------------------------------------------------------
# 回滚（BR-9 / S2-10）
# --------------------------------------------------------------------------


def test_restore_version_creates_restore_snapshot(
    client, config, database, chapter_id
) -> None:
    # #1：300 字 auto 快照
    _save(client, config, chapter_id, "字" * 300)
    manual = _mark_manual(client, config, chapter_id)  # #2，内容 300 字
    # 改成 400 字（#3，因间隔不足不会自动快照）
    _save(client, config, chapter_id, "改" * 400)

    response = client.post(
        f"/api/chapters/{chapter_id}/versions/{manual['id']}/restore",
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["restored_from"] == 2
    assert data["version_no"] == 4
    assert data["snapshot_version_no"] == 4
    assert data["word_count"] == 300

    detail = client.get(f"/api/chapters/{chapter_id}", headers=_headers(config)).json()[
        "data"
    ]
    assert detail["version_no"] == 4
    assert detail["word_count"] == 300
    assert "字" * 10 in detail["content"]
    assert "改" * 10 not in detail["content"]

    # 回滚前内容已存为 #4 restore 快照（永久）
    versions = client.get(
        f"/api/chapters/{chapter_id}/versions", headers=_headers(config)
    ).json()["data"]["items"]
    restore_rows = [row for row in versions if row["change_type"] == "restore"]
    assert len(restore_rows) == 1
    assert restore_rows[0]["version_no"] == 4
    pre_restore = client.get(
        f"/api/versions/{restore_rows[0]['id']}", headers=_headers(config)
    ).json()["data"]
    assert "改" * 10 in pre_restore["content"]

    with session_scope(database.engine) as session:
        chapter = session.get(Chapter, chapter_id)
        project_id = session.execute(
            select(Volume.project_id).where(Volume.id == chapter.volume_id)
        ).scalar_one()
        project = session.get(Project, project_id)
        assert chapter.word_count == 300
        assert project.total_word_count == 300


def test_restore_foreign_version_returns_2001(client, config, chapter_id) -> None:
    _save(client, config, chapter_id, "第一章内容")
    other = _mark_manual(client, config, chapter_id)

    # 新建第二章与其版本
    project = client.get(
        f"/api/chapters/{chapter_id}", headers=_headers(config)
    ).json()["data"]["project_id"]
    tree = client.get(
        f"/api/projects/{project}/volumes", headers=_headers(config)
    ).json()["data"]
    second = client.post(
        f"/api/volumes/{tree['default_volume']['id']}/chapters",
        json={"title": "第二章"},
        headers=_headers(config),
    ).json()["data"]
    client.put(
        f"/api/chapters/{second['id']}/content",
        json={"content_html": "<p>第二章内容</p>"},
        headers=_headers(config),
    )
    second_version = client.post(
        f"/api/chapters/{second['id']}/versions",
        json={"change_type": "manual"},
        headers=_headers(config),
    ).json()["data"]

    response = client.post(
        f"/api/chapters/{second['id']}/versions/{other['id']}/restore",
        headers=_headers(config),
    ).json()
    assert response["code"] == 2001
    # 正例：第二章自己的版本可以回滚
    ok = client.post(
        f"/api/chapters/{second['id']}/versions/{second_version['id']}/restore",
        headers=_headers(config),
    ).json()
    assert ok["code"] == 0


# --------------------------------------------------------------------------
# 物理删除 / 清理 / 鉴权
# --------------------------------------------------------------------------


def test_delete_version_is_physical(client, config, chapter_id) -> None:
    _save(client, config, chapter_id, "内容")
    item = _mark_manual(client, config, chapter_id)
    response = client.delete(
        f"/api/versions/{item['id']}", headers=_headers(config)
    ).json()
    assert response["code"] == 0
    assert response["data"]["deleted"] is True

    missing = client.get(f"/api/versions/{item['id']}", headers=_headers(config)).json()
    assert missing["code"] == 2001


def test_prune_auto_snapshots_keeps_30_plus_daily_first(database, chapter_id) -> None:
    """45 条 auto（3 条/天 × 15 天）：保留最近 30 条 + 更早各天首条（30 天内）。"""
    now = utc_now()
    with session_scope(database.engine) as session:
        for index in range(45):
            day = index // 3
            slot = index % 3
            session.add(
                ChapterVersion(
                    chapter_id=chapter_id,
                    version_no=index + 1,
                    title="快照",
                    content="内容",
                    word_count=10,
                    diff_word_count=0,
                    change_type="auto",
                    created_at=now - timedelta(days=day, minutes=slot + 1),
                )
            )

    with session_scope(database.engine) as session:
        removed = version_service.prune_auto_snapshots(session, chapter_id)
    assert removed == 10

    with session_scope(database.engine) as session:
        rows = (
            session.execute(
                select(ChapterVersion)
                .where(ChapterVersion.chapter_id == chapter_id)
                .order_by(ChapterVersion.version_no)
            )
            .scalars()
            .all()
        )
        # 会话关闭后属性会过期（expire_on_commit），因此在会话内取值
        by_day: dict[int, int] = {}
        for row in rows:
            age = (now - row.created_at).days
            by_day[age] = by_day.get(age, 0) + 1
        total = len(rows)
    assert total == 35
    assert by_day[0] == 3  # 最近一天保留全部
    assert by_day[14] == 1  # 更早的天只保留当日首条


def test_version_endpoints_require_token(client, chapter_id) -> None:
    response = client.get(f"/api/chapters/{chapter_id}/versions")
    assert response.status_code == 401
    assert response.json()["code"] == 1002
