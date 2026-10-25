"""任务 2.9 测试：备份/恢复（#32~#34）、保留策略、启动后台流程与孤儿媒体。"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER
from backend.models import session_scope
from backend.services import backup_service


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


def _wait_task(client, config, tid: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/tasks/{tid}", headers=_headers(config)).json()
        data = body["data"]
        if data["state"] in ("success", "failed"):
            return data
        time.sleep(0.02)
    raise AssertionError("长任务未在超时内结束")


def _create_project(client, config, title: str) -> int:
    body = client.post(
        "/api/projects", json={"title": title}, headers=_headers(config)
    ).json()
    assert body["code"] == 0, body
    return body["data"]["id"]


def _backup_name(client, config) -> str:
    body = client.post("/api/backup", headers=_headers(config)).json()
    assert body["code"] == 0, body
    task = _wait_task(client, config, body["data"]["tid"])
    assert task["state"] == "success", task
    return task["result"]["name"]


def _write_sqlite(path: Path, schema_version: int) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO app_meta(key, value) VALUES ('schema_version', ?)",
            (str(schema_version),),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# #32 / #33
# --------------------------------------------------------------------------


def test_create_backup_and_list(client, config) -> None:
    name = _backup_name(client, config)
    assert name.startswith("inkwell_backup_")
    assert (config.data_dir / "backups" / name).is_file()

    listing = client.get("/api/backups", headers=_headers(config)).json()
    assert listing["code"] == 0, listing
    data = listing["data"]
    assert any(
        item["name"] == name and item["kind"] == "manual" for item in data["items"]
    )
    assert data["disk_free_bytes"] >= 0
    assert data["last_daily_backup"] is None


def test_list_ignores_non_db_and_tmp(client, config) -> None:
    directory = config.data_dir / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "inkwell_backup_x.db.tmp").write_bytes(b"tmp")
    (directory / "notes.txt").write_text("x", encoding="utf-8")

    items = client.get("/api/backups", headers=_headers(config)).json()["data"]["items"]
    names = {item["name"] for item in items}
    assert "inkwell_backup_x.db.tmp" not in names
    assert "notes.txt" not in names


# --------------------------------------------------------------------------
# #34 恢复
# --------------------------------------------------------------------------


def test_premigrate_v0_backup_is_never_restorable(client, config) -> None:
    """首次建库前的空快照被列出，但恢复必须拒绝（否则整库清空）。"""
    directory = config.data_dir / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    name = "inkwell_premigrate_20260101_000000_v0.db"
    _write_sqlite(directory / name, 0)

    items = client.get("/api/backups", headers=_headers(config)).json()["data"]["items"]
    item = next(entry for entry in items if entry["name"] == name)
    assert item["restorable"] is False
    assert item["warning"]

    body = client.post(
        f"/api/backups/{name}/restore", headers=_headers(config)
    ).json()
    assert body["code"] == 3001, body


def test_restore_backup_recovers_data(client, config, database) -> None:
    _create_project(client, config, "恢复后仍存在")
    name = _backup_name(client, config)
    _create_project(client, config, "恢复后应消失")

    body = client.post(f"/api/backups/{name}/restore", headers=_headers(config)).json()
    assert body["code"] == 0, body
    task = _wait_task(client, config, body["data"]["tid"])
    assert task["state"] == "success", task
    assert task["result"]["schema_version"] == config.schema_version

    projects = client.get("/api/projects", headers=_headers(config)).json()["data"][
        "items"
    ]
    titles = [item["title"] for item in projects]
    assert "恢复后仍存在" in titles
    assert "恢复后应消失" not in titles

    # 恢复前自动备份
    backups = sorted((config.data_dir / "backups").glob("inkwell_prerestore_*.db"))
    assert backups, "缺少恢复前备份"

    # 恢复后引擎仍可用
    health = client.get("/api/system/health", headers=_headers(config)).json()
    assert health["code"] == 0
    assert health["data"]["schema_version"] == config.schema_version


def test_restore_rejects_corrupt_backup(client, config) -> None:
    name = "inkwell_backup_corrupt.db"
    path = config.data_dir / "backups" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("this is not a sqlite database", encoding="utf-8")

    response = client.post(
        f"/api/backups/{name}/restore", headers=_headers(config)
    ).json()
    assert response["code"] == 3001
    assert "校验失败" in response["message"]


def test_restore_rejects_newer_schema(client, config) -> None:
    name = "inkwell_backup_newer.db"
    path = config.data_dir / "backups" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_sqlite(path, schema_version=99)

    response = client.post(
        f"/api/backups/{name}/restore", headers=_headers(config)
    ).json()
    assert response["code"] == 3003


def test_restore_name_and_missing_validation(client, config) -> None:
    illegal = client.post(
        "/api/backups/evil.txt/restore", headers=_headers(config)
    ).json()
    assert illegal["code"] == 4003

    missing = client.post(
        "/api/backups/nope.db/restore", headers=_headers(config)
    ).json()
    assert missing["code"] == 2001


# --------------------------------------------------------------------------
# 保留策略 / 启动后台
# --------------------------------------------------------------------------


def test_prune_daily_backups_keeps_week_window(config) -> None:
    directory = config.data_dir / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 10, 23, 12, 0, 0)
    created = []
    for offset in range(20):
        path = directory / f"inkwell_daily_202601{offset + 1:02d}_120000.db"
        path.write_bytes(b"x")
        stamp = (now - timedelta(days=offset)).timestamp()
        os.utime(path, (stamp, stamp))
        created.append(path)

    removed = backup_service.prune_old_backups(config.data_dir, now=now)
    assert removed, "应删除超出保留窗口的每日备份"

    remaining = sorted(directory.glob("inkwell_daily_*.db"))
    # 最近 7 天 + 最多 4 个周备份
    assert 7 <= len(remaining) <= 11
    # 最新一天必须保留
    assert created[0].exists()


def test_run_startup_tasks_daily_and_rollback(database, config) -> None:
    now = datetime.now().replace(microsecond=0)
    first = backup_service.run_startup_tasks(database, config.data_dir, now=now)
    assert first["daily_backup"] is not None
    daily = list((config.data_dir / "backups").glob("inkwell_daily_*.db"))
    assert len(daily) == 1

    second = backup_service.run_startup_tasks(database, config.data_dir, now=now)
    assert second["daily_backup"] is None
    assert len(list((config.data_dir / "backups").glob("inkwell_daily_*.db"))) == 1

    # 模拟时间回拨：记录日期晚于今天
    tomorrow = (now.date() + timedelta(days=1)).isoformat()
    with session_scope(database.engine) as session:
        session.execute(
            text(
                "INSERT INTO app_meta(key, value) VALUES (:k, :v) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
            ),
            {"k": "last_backup_date", "v": tomorrow},
        )

    third = backup_service.run_startup_tasks(database, config.data_dir, now=now)
    assert third["skipped_rollback"] is True
    assert third["daily_backup"] is None


def test_cleanup_orphan_media_keeps_character_avatars(
    client, config, database
) -> None:
    """V2.0 立绘只由 character.avatar_path 引用，不能被孤儿清理误删。"""
    pid = _create_project(client, config, "立绘测试")
    character = client.post(
        f"/api/projects/{pid}/characters",
        json={"name": "林昭"},
        headers=_headers(config),
    ).json()["data"]
    relpath = f"media/characters/{character['id']}/portrait.webp"
    avatar = config.data_dir / relpath
    avatar.parent.mkdir(parents=True, exist_ok=True)
    avatar.write_bytes(b"avatar")
    patched = client.patch(
        f"/api/characters/{character['id']}",
        json={"avatar_path": relpath},
        headers=_headers(config),
    ).json()
    assert patched["code"] == 0, patched

    orphan = config.data_dir / "media" / "characters" / "orphan.webp"
    orphan.write_bytes(b"orphan")
    old = (datetime.now() - timedelta(days=2)).timestamp()
    os.utime(avatar, (old, old))
    os.utime(orphan, (old, old))

    removed = backup_service.cleanup_orphan_media(
        database, config.data_dir, now=datetime.now()
    )
    assert removed == 1
    assert avatar.exists()
    assert not orphan.exists()


def test_cleanup_orphan_media_keeps_version_snapshot_images(
    client, config, database
) -> None:
    """版本快照是永久数据：正文删掉的图片，只要快照还引用就不能删。"""
    pid = _create_project(client, config, "快照图片")
    tree = client.get(f"/api/projects/{pid}/volumes", headers=_headers(config)).json()[
        "data"
    ]
    chapter = client.post(
        f"/api/volumes/{tree['default_volume']['id']}/chapters",
        json={"title": "第一章"},
        headers=_headers(config),
    ).json()["data"]
    client.put(
        f"/api/chapters/{chapter['id']}/content",
        json={"content_html": '<p><img src="media/1/snap.png"></p>'},
        headers=_headers(config),
    )
    snapshot = client.post(
        f"/api/chapters/{chapter['id']}/versions",
        json={"change_type": "manual"},
        headers=_headers(config),
    ).json()
    assert snapshot["code"] == 0, snapshot
    # 当前正文不再引用这张图
    client.put(
        f"/api/chapters/{chapter['id']}/content",
        json={"content_html": "<p>无图</p>"},
        headers=_headers(config),
    )

    image = config.data_dir / "media" / "1" / "snap.png"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"snap")
    old = (datetime.now() - timedelta(days=2)).timestamp()
    os.utime(image, (old, old))

    removed = backup_service.cleanup_orphan_media(
        database, config.data_dir, now=datetime.now()
    )
    assert removed == 0
    assert image.exists()


def test_cleanup_orphan_media(client, config, database) -> None:
    pid = _create_project(client, config, "图片测试")
    tree = client.get(f"/api/projects/{pid}/volumes", headers=_headers(config)).json()[
        "data"
    ]
    chapter = client.post(
        f"/api/volumes/{tree['default_volume']['id']}/chapters",
        json={"title": "第一章"},
        headers=_headers(config),
    ).json()["data"]
    client.put(
        f"/api/chapters/{chapter['id']}/content",
        json={"content_html": '<p><img src="media/1/keep.png"></p>'},
        headers=_headers(config),
    )

    media_dir = config.data_dir / "media" / "1"
    media_dir.mkdir(parents=True, exist_ok=True)
    keep = media_dir / "keep.png"
    orphan = media_dir / "orphan.png"
    keep.write_bytes(b"keep")
    orphan.write_bytes(b"orphan")
    old = (datetime.now() - timedelta(days=2)).timestamp()
    os.utime(keep, (old, old))
    os.utime(orphan, (old, old))

    removed = backup_service.cleanup_orphan_media(
        database, config.data_dir, now=datetime.now()
    )
    assert removed == 1
    assert keep.exists()
    assert not orphan.exists()
