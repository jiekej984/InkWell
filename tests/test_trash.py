"""任务 2.8 测试：回收站列表、父链恢复（BR-4）、清空与过期清理。"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER
from backend.models import Chapter, Document, Volume, session_scope
from backend.services import trash_service
from backend.timeutil import utc_now


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


@pytest.fixture
def project_id(client, config) -> int:
    body = client.post(
        "/api/projects", json={"title": "回收站测试"}, headers=_headers(config)
    ).json()
    assert body["code"] == 0
    return body["data"]["id"]


def _default_volume(client, config, pid: int) -> int:
    return client.get(f"/api/projects/{pid}/volumes", headers=_headers(config)).json()[
        "data"
    ]["default_volume"]["id"]


def _create_chapter(
    client, config, vid: int, title: str, text: str = "正文四字"
) -> int:
    chapter = client.post(
        f"/api/volumes/{vid}/chapters",
        json={"title": title},
        headers=_headers(config),
    ).json()["data"]
    client.put(
        f"/api/chapters/{chapter['id']}/content",
        json={"content_html": f"<p>{text}</p>"},
        headers=_headers(config),
    )
    return chapter["id"]


def _create_document(client, config, pid: int, title: str) -> int:
    return client.post(
        f"/api/projects/{pid}/documents",
        json={"title": title},
        headers=_headers(config),
    ).json()["data"]["id"]


def test_trash_list_and_restore_chapter(client, config, project_id) -> None:
    vid = _default_volume(client, config, project_id)
    chapter_id = _create_chapter(client, config, vid, "第一章")
    document_id = _create_document(client, config, project_id, "设定")

    client.delete(f"/api/chapters/{chapter_id}", headers=_headers(config))
    client.delete(f"/api/documents/{document_id}", headers=_headers(config))

    trash = client.get("/api/trash", headers=_headers(config)).json()["data"]
    assert trash["total"] == 2
    assert trash["retention_days"] == 30
    chapter_item = trash["chapters"][0]
    assert chapter_item["title"] == "第一章"
    assert chapter_item["project_title"] == "回收站测试"
    assert chapter_item["volume_title"] == "默认卷"
    assert chapter_item["days_left"] in (29, 30)

    restored = client.post(
        f"/api/trash/chapter/{chapter_id}/restore", headers=_headers(config)
    ).json()
    assert restored["code"] == 0, restored
    assert restored["data"]["restored"] is True

    detail = client.get(f"/api/chapters/{chapter_id}", headers=_headers(config)).json()
    assert detail["code"] == 0

    # 项目总字数恢复
    stats = client.get(
        f"/api/projects/{project_id}/stats", headers=_headers(config)
    ).json()["data"]
    assert stats["word_count"] == 4

    restored_doc = client.post(
        f"/api/trash/document/{document_id}/restore", headers=_headers(config)
    ).json()
    assert restored_doc["code"] == 0
    assert (
        client.get(f"/api/documents/{document_id}", headers=_headers(config)).json()[
            "code"
        ]
        == 0
    )


def test_project_cascade_trash_and_parent_restore(client, config, project_id) -> None:
    vid = _default_volume(client, config, project_id)
    chapter_id = _create_chapter(client, config, vid, "第一章")
    document_id = _create_document(client, config, project_id, "设定")

    client.delete(f"/api/projects/{project_id}", headers=_headers(config))
    trash = client.get("/api/trash", headers=_headers(config)).json()["data"]
    assert len(trash["projects"]) == 1
    assert len(trash["volumes"]) == 1
    assert len(trash["chapters"]) == 1
    assert len(trash["documents"]) == 1

    # 父项目在回收站：不恢复，返回提示
    response = client.post(
        f"/api/trash/chapter/{chapter_id}/restore", headers=_headers(config)
    ).json()
    assert response["code"] == 0
    assert response["data"]["restored"] is False
    assert response["data"]["requires_parent"] is True
    assert response["data"]["parent"]["type"] == "project"

    # 一并恢复
    restored = client.post(
        f"/api/trash/chapter/{chapter_id}/restore?with_parent=true",
        headers=_headers(config),
    ).json()
    assert restored["code"] == 0, restored
    assert restored["data"]["restored"] is True

    assert (
        client.get(f"/api/projects/{project_id}", headers=_headers(config)).json()[
            "code"
        ]
        == 0
    )
    assert (
        client.get(f"/api/chapters/{chapter_id}", headers=_headers(config)).json()[
            "code"
        ]
        == 0
    )
    assert (
        client.get(f"/api/documents/{document_id}", headers=_headers(config)).json()[
            "code"
        ]
        == 0
    )
    stats = client.get(
        f"/api/projects/{project_id}/stats", headers=_headers(config)
    ).json()["data"]
    assert stats["word_count"] == 4


def test_volume_cascade_restore_with_parent(
    client, config, database, project_id
) -> None:
    volume = client.post(
        f"/api/projects/{project_id}/volumes",
        json={"title": "第一卷"},
        headers=_headers(config),
    ).json()["data"]
    chapter_id = _create_chapter(client, config, volume["id"], "第一章")

    client.delete(f"/api/volumes/{volume['id']}?mode=cascade", headers=_headers(config))

    # 章节的父卷在回收站
    response = client.post(
        f"/api/trash/chapter/{chapter_id}/restore", headers=_headers(config)
    ).json()
    assert response["data"]["requires_parent"] is True
    assert response["data"]["parent"]["type"] == "volume"

    restored = client.post(
        f"/api/trash/chapter/{chapter_id}/restore?with_parent=true",
        headers=_headers(config),
    ).json()
    assert restored["code"] == 0, restored
    assert restored["data"]["restored"] is True

    with session_scope(database.engine) as session:
        volume_row = session.get(Volume, volume["id"])
        chapter_row = session.get(Chapter, chapter_id)
        assert volume_row is not None
        assert volume_row.is_deleted == 0
        assert chapter_row is not None
        assert chapter_row.is_deleted == 0


def test_empty_trash_physically_deletes(client, config, database, project_id) -> None:
    vid = _default_volume(client, config, project_id)
    chapter_id = _create_chapter(client, config, vid, "第一章")
    document_id = _create_document(client, config, project_id, "设定")
    client.delete(f"/api/chapters/{chapter_id}", headers=_headers(config))
    client.delete(f"/api/documents/{document_id}", headers=_headers(config))

    body = client.delete("/api/trash/empty", headers=_headers(config)).json()
    assert body["code"] == 0, body
    assert body["data"]["emptied"] is True

    with session_scope(database.engine) as session:
        assert session.get(Chapter, chapter_id) is None
        assert session.get(Document, document_id) is None

    trash = client.get("/api/trash", headers=_headers(config)).json()["data"]
    assert trash["total"] == 0


def test_purge_expired_trash(database, client, config, project_id) -> None:
    vid = _default_volume(client, config, project_id)
    old_id = _create_chapter(client, config, vid, "旧章")
    recent_id = _create_chapter(client, config, vid, "新章")
    client.delete(f"/api/chapters/{old_id}", headers=_headers(config))
    client.delete(f"/api/chapters/{recent_id}", headers=_headers(config))

    with session_scope(database.engine) as session:
        session.get(Chapter, old_id).deleted_at = utc_now() - timedelta(days=31)
        session.get(Chapter, recent_id).deleted_at = utc_now() - timedelta(days=29)

    with session_scope(database.engine) as session:
        result = trash_service.purge_expired_trash(session)
    assert result["purged"] >= 1

    with session_scope(database.engine) as session:
        assert session.get(Chapter, old_id) is None
        assert session.get(Chapter, recent_id) is not None


def test_restore_invalid_cases(client, config, project_id) -> None:
    vid = _default_volume(client, config, project_id)
    chapter_id = _create_chapter(client, config, vid, "在架的章")

    unknown = client.post(
        "/api/trash/unknown/1/restore", headers=_headers(config)
    ).json()
    assert unknown["code"] == 1001

    missing = client.post(
        "/api/trash/chapter/99999/restore", headers=_headers(config)
    ).json()
    assert missing["code"] == 2001

    not_deleted = client.post(
        f"/api/trash/chapter/{chapter_id}/restore", headers=_headers(config)
    ).json()
    assert not_deleted["code"] == 1001


def test_trash_requires_token(client) -> None:
    response = client.get("/api/trash")
    assert response.status_code == 401
    assert response.json()["code"] == 1002
