"""任务 2.7 测试：设定文档 CRUD（#28~#30）、分类、字数隔离与图片。"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER
from backend.models import Document, Project, session_scope


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


def _png_bytes(size: tuple[int, int] = (6, 6)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color=(1, 2, 3)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def project_id(client, config) -> int:
    body = client.post(
        "/api/projects", json={"title": "设定测试"}, headers=_headers(config)
    ).json()
    assert body["code"] == 0
    return body["data"]["id"]


def _create(client, config, pid: int, title: str, category: str = "other", html=""):
    body = client.post(
        f"/api/projects/{pid}/documents",
        json={"title": title, "category": category, "content_html": html},
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body
    return body["data"]


def test_create_and_list_documents(client, config, project_id) -> None:
    first = _create(
        client, config, project_id, "世界观总纲", "world", "<p>大陆与海洋</p>"
    )
    second = _create(client, config, project_id, "年表", "timeline")

    assert first["order_index"] == 1000
    assert second["order_index"] == 2000
    assert first["category_label"] == "世界观"

    listing = client.get(
        f"/api/projects/{project_id}/documents", headers=_headers(config)
    ).json()["data"]
    assert listing["total"] == 2
    assert [item["title"] for item in listing["items"]] == ["世界观总纲", "年表"]
    assert "content" not in listing["items"][0]
    # 五类分类随列表返回（页面 P3 筛选按钮用）
    assert [item["value"] for item in listing["categories"]] == [
        "world",
        "timeline",
        "faction",
        "glossary",
        "other",
    ]


def test_list_filter_by_category(client, config, project_id) -> None:
    _create(client, config, project_id, "世界观", "world")
    _create(client, config, project_id, "势力", "faction")
    body = client.get(
        f"/api/projects/{project_id}/documents?category=faction",
        headers=_headers(config),
    ).json()
    assert body["code"] == 0
    assert [item["title"] for item in body["data"]["items"]] == ["势力"]


def test_list_rejects_bad_category(client, config, project_id) -> None:
    response = client.get(
        f"/api/projects/{project_id}/documents?category=unknown",
        headers=_headers(config),
    ).json()
    assert response["code"] == 1001


def test_create_rejects_empty_title_and_bad_category(
    client, config, project_id
) -> None:
    empty = client.post(
        f"/api/projects/{project_id}/documents",
        json={"title": "   "},
        headers=_headers(config),
    ).json()
    assert empty["code"] == 1001

    bad = client.post(
        f"/api/projects/{project_id}/documents",
        json={"title": "x", "category": "unknown"},
        headers=_headers(config),
    ).json()
    assert bad["code"] == 1001


def test_document_content_sanitized_and_counted(client, config, project_id) -> None:
    document = _create(
        client,
        config,
        project_id,
        "设定",
        "world",
        '<p onclick="evil()">你好世界</p><script>alert(1)</script>',
    )
    assert document["word_count"] == 4

    detail = client.get(
        f"/api/documents/{document['id']}", headers=_headers(config)
    ).json()["data"]
    assert "script" not in detail["content"].lower()
    assert "onclick" not in detail["content"]
    assert detail["word_count"] == 4
    assert detail["content_text"] == "你好世界"


def test_document_update_content_and_category(
    client, config, database, project_id
) -> None:
    document = _create(client, config, project_id, "旧标题", "other", "<p>旧内容</p>")

    body = client.patch(
        f"/api/documents/{document['id']}",
        json={
            "title": "新标题",
            "category": "glossary",
            "content_html": "<p>新内容更长了</p>",
        },
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["title"] == "新标题"
    assert data["category"] == "glossary"
    assert data["word_count"] == 6

    with session_scope(database.engine) as session:
        row = session.get(Document, document["id"])
        assert row.title == "新标题"
        assert row.content_text == "新内容更长了"


def test_documents_do_not_change_project_total(
    client, config, database, project_id
) -> None:
    project = client.get(
        f"/api/projects/{project_id}", headers=_headers(config)
    ).json()["data"]
    tree = client.get(
        f"/api/projects/{project_id}/volumes", headers=_headers(config)
    ).json()["data"]
    chapter = client.post(
        f"/api/volumes/{tree['default_volume']['id']}/chapters",
        json={"title": "第一章"},
        headers=_headers(config),
    ).json()["data"]
    client.put(
        f"/api/chapters/{chapter['id']}/content",
        json={"content_html": "<p>正文四字</p>"},
        headers=_headers(config),
    )

    _create(client, config, project_id, "长设定", "world", "<p>" + "设" * 300 + "</p>")

    with session_scope(database.engine) as session:
        total = session.get(Project, project_id).total_word_count
    assert total == 4
    assert project["total_word_count"] == 0


def test_document_soft_delete(client, config, database, project_id) -> None:
    document = _create(client, config, project_id, "待删")
    response = client.delete(
        f"/api/documents/{document['id']}", headers=_headers(config)
    ).json()
    assert response["code"] == 0

    with session_scope(database.engine) as session:
        row = session.get(Document, document["id"])
        assert row.is_deleted == 1
        assert row.deleted_at is not None

    missing = client.get(
        f"/api/documents/{document['id']}", headers=_headers(config)
    ).json()
    assert missing["code"] == 2002
    listing = client.get(
        f"/api/projects/{project_id}/documents", headers=_headers(config)
    ).json()["data"]
    assert listing["total"] == 0


def test_document_missing_returns_2001(client, config, project_id) -> None:
    assert (
        client.get("/api/documents/99999", headers=_headers(config)).json()["code"]
        == 2001
    )
    assert (
        client.post(
            "/api/projects/99999/documents",
            json={"title": "x"},
            headers=_headers(config),
        ).json()["code"]
        == 2001
    )


def test_document_image_upload_and_signature(client, config, project_id) -> None:
    document = _create(client, config, project_id, "带图设定")
    payload = _png_bytes()
    body = client.post(
        f"/api/documents/{document['id']}/images",
        files={"file": ("pic.png", payload, "image/png")},
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body
    relpath = body["data"]["path"]
    assert relpath.startswith(f"media/documents/{document['id']}/")
    assert (config.data_dir / relpath).exists()
    assert client.get(body["data"]["url"]).status_code == 200

    client.patch(
        f"/api/documents/{document['id']}",
        json={"content_html": f'<p><img src="{relpath}"></p>'},
        headers=_headers(config),
    )
    detail = client.get(
        f"/api/documents/{document['id']}", headers=_headers(config)
    ).json()["data"]
    assert f"/files/{relpath}?sig=" in detail["content"]


def test_document_endpoints_require_token(client, project_id) -> None:
    response = client.get(f"/api/projects/{project_id}/documents")
    assert response.status_code == 401
    assert response.json()["code"] == 1002
