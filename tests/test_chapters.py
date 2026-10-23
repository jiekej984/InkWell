"""任务 2.3 测试：章节接口 #18~#21、图片上传、`/files/` 签名与消毒链路。

覆盖回归 13（路径穿越 → 4003）、回归 14（`<script>` 清除）、回归 18（无/过期签名 → 4004）。
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER
from backend.models import Chapter, Project, session_scope
from backend.storage import sign


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


def _png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color=(10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def project_id(client, config) -> int:
    response = client.post(
        "/api/projects", json={"title": "编辑器测试"}, headers=_headers(config)
    )
    assert response.json()["code"] == 0
    return response.json()["data"]["id"]


@pytest.fixture
def chapter_id(client, config, project_id) -> int:
    tree = client.get(
        f"/api/projects/{project_id}/volumes", headers=_headers(config)
    ).json()["data"]
    volume_id = tree["default_volume"]["id"]
    body = client.post(
        f"/api/volumes/{volume_id}/chapters",
        json={"title": "第一章"},
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body
    return body["data"]["id"]


# --------------------------------------------------------------------------
# #18 / #19 详情与局部更新
# --------------------------------------------------------------------------


def test_get_chapter_detail(client, config, project_id, chapter_id) -> None:
    response = client.get(f"/api/chapters/{chapter_id}", headers=_headers(config))
    body = response.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["title"] == "第一章"
    assert data["project_id"] == project_id
    assert data["content"] == ""
    assert data["version_no"] == 0
    assert data["project_word_count"] == 0


def test_get_missing_chapter_returns_2001(client, config) -> None:
    response = client.get("/api/chapters/99999", headers=_headers(config))
    assert response.json()["code"] == 2001


def test_update_chapter_fields(client, config, database, chapter_id) -> None:
    response = client.patch(
        f"/api/chapters/{chapter_id}",
        json={
            "title": "改名后的章",
            "status": "first",
            "summary": "梗概",
            "target_word_count": 3000,
        },
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["title"] == "改名后的章"
    assert body["data"]["status"] == "first"
    assert body["data"]["target_word_count"] == 3000

    with session_scope(database.engine) as session:
        chapter = session.get(Chapter, chapter_id)
        assert chapter.summary == "梗概"


def test_update_chapter_rejects_bad_status(client, config, chapter_id) -> None:
    response = client.patch(
        f"/api/chapters/{chapter_id}",
        json={"status": "unknown"},
        headers=_headers(config),
    )
    assert response.json()["code"] == 1001


# --------------------------------------------------------------------------
# #20 正文保存：消毒 / 字数 / 乐观锁
# --------------------------------------------------------------------------


def test_save_content_sanitizes_and_counts(
    client, config, database, project_id, chapter_id
) -> None:
    html = (
        '<h1>标题</h1><p onclick="evil()">你好<strong>世界</strong></p>'
        "<script>alert(1)</script>"
    )
    response = client.put(
        f"/api/chapters/{chapter_id}/content",
        json={"content_html": html, "expect_version": 0, "client_saved_at": "x"},
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["word_count"] == 6  # 标题 2 + 你好 2 + 世界 2
    assert data["project_word_count"] == 6
    assert data["version_no"] == 1
    assert data["snapshot_created"] is False

    with session_scope(database.engine) as session:
        chapter = session.get(Chapter, chapter_id)
        assert "script" not in (chapter.content or "").lower()
        assert "onclick" not in (chapter.content or "")
        assert chapter.content_text == "标题\n\n你好世界"
        assert chapter.word_count == 6
        assert session.get(Project, project_id).total_word_count == 6

    detail = client.get(f"/api/chapters/{chapter_id}", headers=_headers(config)).json()[
        "data"
    ]
    assert "script" not in detail["content"].lower()
    assert "标题" in detail["content"]


def test_save_content_conflict_returns_3002(
    client, config, database, chapter_id
) -> None:
    first = client.put(
        f"/api/chapters/{chapter_id}/content",
        json={"content_html": "<p>第一版</p>", "expect_version": 0},
        headers=_headers(config),
    ).json()
    assert first["code"] == 0, first

    conflict = client.put(
        f"/api/chapters/{chapter_id}/content",
        json={"content_html": "<p>冲突版本</p>", "expect_version": 0},
        headers=_headers(config),
    ).json()
    assert conflict["code"] == 3002

    with session_scope(database.engine) as session:
        chapter = session.get(Chapter, chapter_id)
        assert "第一版" in chapter.content
        assert chapter.version_no == 1


def test_save_content_normalizes_signed_image(
    client, config, database, chapter_id
) -> None:
    response = client.put(
        f"/api/chapters/{chapter_id}/content",
        json={
            "content_html": '<p><img src="/files/media/9/x.png?sig=abc"></p>',
            "expect_version": 0,
        },
        headers=_headers(config),
    )
    assert response.json()["code"] == 0, response.json()

    with session_scope(database.engine) as session:
        chapter = session.get(Chapter, chapter_id)
        assert 'src="media/9/x.png"' in chapter.content

    detail = client.get(f"/api/chapters/{chapter_id}", headers=_headers(config)).json()[
        "data"
    ]
    assert "/files/media/9/x.png?sig=" in detail["content"]


def test_save_content_updates_project_total(
    client, config, project_id, chapter_id
) -> None:
    client.put(
        f"/api/chapters/{chapter_id}/content",
        json={"content_html": "<p>你好世界</p>", "expect_version": 0},
        headers=_headers(config),
    )
    response = client.put(
        f"/api/chapters/{chapter_id}/content",
        json={"content_html": "<p>你好世界再见</p>", "expect_version": 1},
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["word_count"] == 6
    assert body["data"]["project_word_count"] == 6


def test_save_empty_content(client, config, chapter_id) -> None:
    response = client.put(
        f"/api/chapters/{chapter_id}/content",
        json={},
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["word_count"] == 0


# --------------------------------------------------------------------------
# #21 删除
# --------------------------------------------------------------------------


def test_delete_chapter_soft_deletes(
    client, config, database, project_id, chapter_id
) -> None:
    client.put(
        f"/api/chapters/{chapter_id}/content",
        json={"content_html": "<p>四字正文</p>"},
        headers=_headers(config),
    )
    response = client.delete(f"/api/chapters/{chapter_id}", headers=_headers(config))
    body = response.json()
    assert body["code"] == 0, body

    with session_scope(database.engine) as session:
        chapter = session.get(Chapter, chapter_id)
        assert chapter.is_deleted == 1
        assert session.get(Project, project_id).total_word_count == 0

    missing = client.get(f"/api/chapters/{chapter_id}", headers=_headers(config))
    assert missing.json()["code"] == 2002


# --------------------------------------------------------------------------
# 图片上传 + #36 / #37
# --------------------------------------------------------------------------


def test_image_upload_and_signed_download(client, config, database, chapter_id) -> None:
    payload = _png_bytes()
    response = client.post(
        f"/api/chapters/{chapter_id}/images",
        files={"file": ("pic.png", payload, "image/png")},
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    relpath = body["data"]["path"]
    assert relpath.startswith(f"media/{chapter_id}/")
    assert (config.data_dir / relpath).exists()

    download = client.get(body["data"]["url"])
    assert download.status_code == 200
    assert download.content == payload

    # 保存正文后，详情返回的签名 URL 仍可下载
    client.put(
        f"/api/chapters/{chapter_id}/content",
        json={"content_html": f'<p><img src="{relpath}"></p>'},
        headers=_headers(config),
    )
    detail = client.get(f"/api/chapters/{chapter_id}", headers=_headers(config)).json()[
        "data"
    ]
    assert f"/files/{relpath}?sig=" in detail["content"]
    signed_url = detail["content"].split('src="', 1)[1].split('"', 1)[0]
    assert client.get(signed_url).status_code == 200


def test_image_upload_rejects_bad_extension(client, config, chapter_id) -> None:
    response = client.post(
        f"/api/chapters/{chapter_id}/images",
        files={"file": ("pic.gif", _png_bytes(), "image/gif")},
        headers=_headers(config),
    )
    assert response.json()["code"] == 4002


def test_image_upload_rejects_non_image(client, config, chapter_id) -> None:
    response = client.post(
        f"/api/chapters/{chapter_id}/images",
        files={"file": ("evil.png", b"not an image", "image/png")},
        headers=_headers(config),
    )
    assert response.json()["code"] == 4002


def test_image_upload_missing_chapter_returns_2001(client, config) -> None:
    response = client.post(
        "/api/chapters/99999/images",
        files={"file": ("pic.png", _png_bytes(), "image/png")},
        headers=_headers(config),
    )
    assert response.json()["code"] == 2001


def test_file_requires_valid_signature(client, config) -> None:
    unsigned = client.get("/files/media/1/none.png")
    assert unsigned.status_code == 401
    assert unsigned.json()["code"] == 4004

    valid_sig = sign("media/1/none.png")
    missing = client.get(f"/files/media/1/none.png?sig={valid_sig}")
    assert missing.status_code == 200
    assert missing.json()["code"] == 2001


def test_expired_signature_returns_4004(client, config) -> None:
    expired = sign("media/1/a.png", ttl=1800, now=time.time() - 7200)
    response = client.get(f"/files/media/1/a.png?sig={expired}")
    assert response.status_code == 401
    assert response.json()["code"] == 4004


def test_path_traversal_returns_4003(client, config) -> None:
    response = client.get("/files/..%2F..%2Finkwell.db")
    assert response.status_code == 400
    assert response.json()["code"] == 4003

    encoded = client.get("/files/%2E%2E%2F%2E%2E%2Finkwell.db")
    assert encoded.json()["code"] == 4003


def test_sign_endpoint_batch(client, config) -> None:
    response = client.post(
        "/api/files/sign",
        json={"paths": ["media/1/a.png", "../etc/passwd", "/abs/x.png"]},
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert len(data["items"]) == 1
    assert data["items"][0]["path"] == "media/1/a.png"
    assert data["items"][0]["url"].startswith("/files/media/1/a.png?sig=")
    assert len(data["invalid"]) == 2
    assert data["ttl"] == 30 * 60


def test_chapter_endpoints_require_token(client, chapter_id) -> None:
    response = client.get(f"/api/chapters/{chapter_id}")
    assert response.status_code == 401
    assert response.json()["code"] == 1002


def test_frontend_editor_assets_are_served(client) -> None:
    """静态资源路径与 index.html 引用一致（V-02 走查前的冒烟检查）。"""
    for path in (
        "/",
        "/js/editor.js",
        "/js/writer.js",
        "/js/view.js",
        "/vendor/quill/quill.js",
        "/vendor/quill/quill.snow.css",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
