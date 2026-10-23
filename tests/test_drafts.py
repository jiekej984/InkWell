"""任务 2.4 后端测试：暂存落盘、列表、读取、删除与保存后自动清理（BR-2）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER
from backend.services import drafts as draft_service
from backend.services.drafts import MAX_DRAFT_BYTES


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


@pytest.fixture
def chapter_id(client, config) -> int:
    project = client.post(
        "/api/projects", json={"title": "暂存测试"}, headers=_headers(config)
    ).json()["data"]
    tree = client.get(
        f"/api/projects/{project['id']}/volumes", headers=_headers(config)
    ).json()["data"]
    volume_id = tree["default_volume"]["id"]
    chapter = client.post(
        f"/api/volumes/{volume_id}/chapters",
        json={"title": "第一章"},
        headers=_headers(config),
    ).json()["data"]
    return chapter["id"]


def _save(client, config, chapter_id: int, html: str, reason: str = "save_failed"):
    return client.post(
        "/api/drafts",
        json={
            "chapter_id": chapter_id,
            "content_html": html,
            "client_saved_at": "2026-10-23T08:00:00Z",
            "reason": reason,
        },
        headers=_headers(config),
    ).json()


def test_save_and_get_draft(client, config, chapter_id) -> None:
    body = _save(client, config, chapter_id, "<p>暂存正文</p>")
    assert body["code"] == 0, body
    data = body["data"]
    assert data["chapter_id"] == chapter_id
    assert data["title"] == "第一章"
    assert data["size"] > 0

    path = draft_service.draft_path(config.data_dir, chapter_id)
    assert path.exists()

    listing = client.get("/api/drafts", headers=_headers(config)).json()
    assert listing["code"] == 0
    assert listing["data"]["total"] == 1
    assert "content_html" not in listing["data"]["items"][0]

    detail = client.get(f"/api/drafts/{chapter_id}", headers=_headers(config)).json()
    assert detail["code"] == 0
    assert detail["data"]["content_html"] == "<p>暂存正文</p>"


def test_draft_overwrites_same_chapter(client, config, chapter_id) -> None:
    _save(client, config, chapter_id, "<p>第一版</p>")
    _save(client, config, chapter_id, "<p>第二版</p>")
    listing = client.get("/api/drafts", headers=_headers(config)).json()
    assert listing["data"]["total"] == 1
    detail = client.get(f"/api/drafts/{chapter_id}", headers=_headers(config)).json()
    assert detail["data"]["content_html"] == "<p>第二版</p>"


def test_save_draft_missing_chapter_returns_2001(client, config) -> None:
    body = _save(client, config, 99999, "<p>x</p>")
    assert body["code"] == 2001


def test_draft_requires_token(client, chapter_id) -> None:
    response = client.get(f"/api/drafts/{chapter_id}")
    assert response.status_code == 401
    assert response.json()["code"] == 1002


def test_delete_draft(client, config, chapter_id) -> None:
    _save(client, config, chapter_id, "<p>x</p>")
    response = client.delete(
        f"/api/drafts/{chapter_id}", headers=_headers(config)
    ).json()
    assert response["code"] == 0
    assert response["data"]["deleted"] is True

    missing = client.get(f"/api/drafts/{chapter_id}", headers=_headers(config)).json()
    assert missing["code"] == 2001


def test_successful_content_save_clears_draft(client, config, chapter_id) -> None:
    _save(client, config, chapter_id, "<p>失败时的暂存</p>")
    saved = client.put(
        f"/api/chapters/{chapter_id}/content",
        json={"content_html": "<p>正常保存</p>"},
        headers=_headers(config),
    ).json()
    assert saved["code"] == 0, saved

    cleared = client.get(f"/api/drafts/{chapter_id}", headers=_headers(config)).json()
    assert cleared["code"] == 2001
    assert not draft_service.draft_path(config.data_dir, chapter_id).exists()


def test_oversized_draft_rejected(client, config, chapter_id) -> None:
    body = _save(client, config, chapter_id, "x" * (MAX_DRAFT_BYTES + 10))
    assert body["code"] == 4002


def test_list_ignores_corrupt_draft_files(client, config, chapter_id) -> None:
    _save(client, config, chapter_id, "<p>ok</p>")
    corrupt = config.data_dir / "drafts" / "chapter_999.json"
    corrupt.write_text("not json", encoding="utf-8")

    listing = client.get("/api/drafts", headers=_headers(config)).json()
    assert listing["data"]["total"] == 1
    assert listing["data"]["items"][0]["chapter_id"] == chapter_id
