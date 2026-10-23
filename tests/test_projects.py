"""任务 2.1 测试：项目 CRUD + 封面 + 标签 + 统计（§6.2 #2~#9）。

覆盖 FR-1.1~1.8、BR-4（级联软删）、BR-6（默认卷），以及封面的格式/大小校验。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER
from backend.models import (
    Chapter,
    Document,
    Project,
    ProjectTag,
    Tag,
    Volume,
    session_scope,
)
from backend.services import project_service


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


def _png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color=(12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def project_id(client, config) -> int:
    response = client.post(
        "/api/projects",
        json={"title": "测试之书", "description": "简介", "tags": ["奇幻", "连载"]},
        headers=_headers(config),
    )
    assert response.json()["code"] == 0
    return response.json()["data"]["id"]


# --------------------------------------------------------------------------
# #4 新建
# --------------------------------------------------------------------------


def test_create_project_makes_default_volume(client, config, database) -> None:
    """BR-6：新建项目必须自动创建默认卷（order_index=0、is_default=1）。"""
    response = client.post(
        "/api/projects", json={"title": "新书"}, headers=_headers(config)
    )
    body = response.json()
    assert body["code"] == 0, body
    pid = body["data"]["id"]

    with session_scope(database.engine) as session:
        # 会话提交后对象会过期（expire_on_commit 默认开），属性必须在会话内读取
        volumes = [
            (v.title, v.order_index, v.is_default)
            for v in session.execute(select(Volume).where(Volume.project_id == pid))
            .scalars()
            .all()
        ]
    assert volumes == [(project_service.DEFAULT_VOLUME_TITLE, 0, 1)]


def test_project_title_may_duplicate(client, config) -> None:
    """FR-1.7：项目名允许重复。"""
    for _ in range(2):
        response = client.post(
            "/api/projects", json={"title": "同名书"}, headers=_headers(config)
        )
        assert response.json()["code"] == 0
    listing = client.get("/api/projects", headers=_headers(config)).json()
    assert listing["data"]["total"] == 2


def test_create_with_empty_title_returns_1001(client, config) -> None:
    response = client.post(
        "/api/projects", json={"title": "   "}, headers=_headers(config)
    )
    assert response.json()["code"] == 1001


def test_create_with_bad_status_returns_1001(client, config) -> None:
    response = client.post(
        "/api/projects",
        json={"title": "书", "status": "unknown"},
        headers=_headers(config),
    )
    assert response.json()["code"] == 1001


def test_type_error_is_normalized_to_1001(client, config) -> None:
    """§6.1 统一响应：FastAPI 的 422 必须转成 1001 + data.errors。"""
    response = client.post(
        "/api/projects",
        json={"title": "书", "target_word_count": "很多"},
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 1001
    assert response.status_code == 200
    assert body["data"]["errors"]


def test_projects_require_token(client) -> None:
    assert client.get("/api/projects").status_code == 401


# --------------------------------------------------------------------------
# #3 / #5 列表与详情
# --------------------------------------------------------------------------


def test_list_returns_tags_and_is_ordered_by_updated_desc(
    client, config, project_id
) -> None:
    client.post("/api/projects", json={"title": "第二本"}, headers=_headers(config))
    body = client.get("/api/projects", headers=_headers(config)).json()
    items = body["data"]["items"]
    assert body["data"]["total"] == 2
    # 后建的排在前面（updated_at 倒序）
    assert items[0]["title"] == "第二本"
    first = client.get(f"/api/projects/{project_id}", headers=_headers(config)).json()
    assert [t["name"] for t in first["data"]["tags"]] == ["奇幻", "连载"]


def test_get_missing_project_returns_2001(client, config) -> None:
    response = client.get("/api/projects/9999", headers=_headers(config))
    assert response.json()["code"] == 2001


# --------------------------------------------------------------------------
# #6 更新
# --------------------------------------------------------------------------


def test_patch_updates_fields_and_replaces_tags(client, config, project_id) -> None:
    response = client.patch(
        f"/api/projects/{project_id}",
        json={
            "title": "改名了",
            "status": "paused",
            "target_word_count": 100000,
            "tags": ["科幻"],
        },
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["title"] == "改名了"
    assert body["data"]["status"] == "paused"
    assert body["data"]["target_word_count"] == 100000
    assert [t["name"] for t in body["data"]["tags"]] == ["科幻"]


def test_patch_omitted_fields_are_untouched(client, config, project_id) -> None:
    before = client.get(f"/api/projects/{project_id}", headers=_headers(config)).json()
    client.patch(
        f"/api/projects/{project_id}",
        json={"status": "finished"},
        headers=_headers(config),
    )
    after = client.get(f"/api/projects/{project_id}", headers=_headers(config)).json()
    assert after["data"]["title"] == before["data"]["title"]
    assert after["data"]["description"] == before["data"]["description"]


def test_tags_are_reused_not_duplicated(client, config, database) -> None:
    """tag.name 唯一：同名标签复用，不重复插入。"""
    for index in range(2):
        response = client.post(
            "/api/projects",
            json={"title": f"书{index}", "tags": ["共用标签"]},
            headers=_headers(config),
        )
        assert response.json()["code"] == 0
    with session_scope(database.engine) as session:
        names = session.execute(select(Tag.name)).scalars().all()
        links = session.execute(select(ProjectTag)).scalars().all()
    assert names == ["共用标签"]
    assert len(links) == 2


# --------------------------------------------------------------------------
# #7 软删除级联
# --------------------------------------------------------------------------


def test_soft_delete_cascades_volumes_chapters_documents(
    client, config, database, project_id
) -> None:
    """BR-4：项目软删 → 卷 / 章 / 设定文档级联软删（快照表无软删字段，见 E-03）。"""
    with session_scope(database.engine) as session:
        volume = session.execute(
            select(Volume).where(Volume.project_id == project_id)
        ).scalar_one()
        session.add(
            Chapter(
                volume_id=volume.id,
                title="第一章",
                content="",
                content_text="",
                created_at=project_service.utc_now(),
                updated_at=project_service.utc_now(),
            )
        )
        session.add(
            Chapter(
                volume_id=volume.id,
                title="第二章",
                content="",
                content_text="",
                created_at=project_service.utc_now(),
                updated_at=project_service.utc_now(),
            )
        )
        session.add(
            Document(
                project_id=project_id,
                title="世界观",
                category="world",
                created_at=project_service.utc_now(),
                updated_at=project_service.utc_now(),
            )
        )

    response = client.delete(f"/api/projects/{project_id}", headers=_headers(config))
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["cascaded"] == {
        "volumes": 1,
        "chapters": 2,
        "documents": 1,
    }

    with session_scope(database.engine) as session:
        project = session.get(Project, project_id)
        assert project.is_deleted == 1 and project.deleted_at is not None
        assert all(
            v.is_deleted == 1
            for v in session.execute(
                select(Volume).where(Volume.project_id == project_id)
            ).scalars()
        )
        assert all(
            c.is_deleted == 1 for c in session.execute(select(Chapter)).scalars()
        )
        assert all(
            d.is_deleted == 1 for d in session.execute(select(Document)).scalars()
        )

    # 列表不再包含；详情返回 2002（已删除）
    listing = client.get("/api/projects", headers=_headers(config)).json()
    assert listing["data"]["total"] == 0
    detail = client.get(f"/api/projects/{project_id}", headers=_headers(config)).json()
    assert detail["code"] == 2002


def test_delete_missing_project_returns_2001(client, config) -> None:
    assert (
        client.delete("/api/projects/9999", headers=_headers(config)).json()["code"]
        == 2001
    )


# --------------------------------------------------------------------------
# #8 封面
# --------------------------------------------------------------------------


def test_upload_cover_stores_relative_path(
    client, config, database, project_id
) -> None:
    """BR-5：库内只存相对路径，文件落在 covers/。"""
    payload = _png_bytes()
    response = client.post(
        f"/api/projects/{project_id}/cover",
        files={"file": ("cover.png", payload, "image/png")},
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    relpath = body["data"]["cover_path"]
    assert relpath.startswith("covers/")
    assert not relpath.startswith("/")
    assert (config.data_dir / relpath).exists()

    with session_scope(database.engine) as session:
        assert session.get(Project, project_id).cover_path == relpath


def test_upload_rejects_bad_extension(client, config, project_id) -> None:
    response = client.post(
        f"/api/projects/{project_id}/cover",
        files={"file": ("cover.gif", _png_bytes(), "image/gif")},
        headers=_headers(config),
    )
    assert response.json()["code"] == 4002


def test_upload_rejects_disguised_extension(client, config, project_id) -> None:
    """.png 扩展名但内容不是图片 → 4002（Pillow 校验真实格式）。"""
    response = client.post(
        f"/api/projects/{project_id}/cover",
        files={"file": ("evil.png", b"not an image at all", "image/png")},
        headers=_headers(config),
    )
    assert response.json()["code"] == 4002


def test_replacing_cover_removes_old_file(client, config, database, project_id) -> None:
    first = client.post(
        f"/api/projects/{project_id}/cover",
        files={"file": ("a.png", _png_bytes((4, 4)), "image/png")},
        headers=_headers(config),
    ).json()["data"]["cover_path"]
    second = client.post(
        f"/api/projects/{project_id}/cover",
        files={"file": ("b.png", _png_bytes((6, 6)), "image/png")},
        headers=_headers(config),
    ).json()["data"]["cover_path"]

    assert first != second
    assert not (config.data_dir / first).exists()
    assert (config.data_dir / second).exists()


def test_cover_for_missing_project_returns_2001(client, config) -> None:
    response = client.post(
        "/api/projects/9999/cover",
        files={"file": ("a.png", _png_bytes(), "image/png")},
        headers=_headers(config),
    )
    assert response.json()["code"] == 2001


# --------------------------------------------------------------------------
# #9 统计
# --------------------------------------------------------------------------


def test_stats_counts_and_progress(client, config, database, project_id) -> None:
    with session_scope(database.engine) as session:
        volume = session.execute(
            select(Volume).where(Volume.project_id == project_id)
        ).scalar_one()
        now = project_service.utc_now()
        session.add(
            Chapter(
                volume_id=volume.id,
                title="第一章",
                word_count=1200,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            Chapter(
                volume_id=volume.id,
                title="第二章",
                word_count=800,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            Document(
                project_id=project_id, title="设定", created_at=now, updated_at=now
            )
        )

    body = client.get(
        f"/api/projects/{project_id}/stats", headers=_headers(config)
    ).json()
    stats = body["data"]
    assert stats["volume_count"] == 1
    assert stats["chapter_count"] == 2
    assert stats["document_count"] == 1
    assert stats["word_count"] == 2000
    # FR-1.3：未设目标字数，进度不显示
    assert stats["progress"] is None

    client.patch(
        f"/api/projects/{project_id}",
        json={"target_word_count": 4000},
        headers=_headers(config),
    )
    stats = client.get(
        f"/api/projects/{project_id}/stats", headers=_headers(config)
    ).json()["data"]
    assert stats["progress"] == 0.5

    with session_scope(database.engine) as session:
        assert session.get(Project, project_id).total_word_count == 2000


def test_stats_for_missing_project_returns_2001(client, config) -> None:
    assert (
        client.get("/api/projects/9999/stats", headers=_headers(config)).json()["code"]
        == 2001
    )


# --------------------------------------------------------------------------
# #2 /system/meta
# --------------------------------------------------------------------------


def test_meta_returns_version_dirs_and_recent_project(
    client, config, project_id
) -> None:
    body = client.get("/api/system/meta", headers=_headers(config)).json()
    data = body["data"]
    assert data["version"] == config.version
    assert data["port"] == config.port
    assert data["data_dir"] == str(config.data_dir)
    assert data["recent_project"] is None  # 尚未记录打开时间

    client.patch(
        f"/api/projects/{project_id}",
        json={"last_chapter_id": None},
        headers=_headers(config),
    )
    with session_scope(client.app.state.database.engine) as session:
        project_service.touch_opened(session, project_id)

    data = client.get("/api/system/meta", headers=_headers(config)).json()["data"]
    assert data["recent_project"]["id"] == project_id


# --------------------------------------------------------------------------
# 阶段三 3.3：#3 详情即「打开项目」，顺手记录最近打开时间（FR-1.3 / FR-1.5）
# --------------------------------------------------------------------------


def test_get_detail_records_last_opened(client, config, project_id) -> None:
    """详情会写 last_opened_at，列表与详情读到同一个值。"""
    detail = client.get(f"/api/projects/{project_id}", headers=_headers(config)).json()
    assert detail["code"] == 0
    opened = detail["data"]["last_opened_at"]
    assert opened is not None

    listed = client.get("/api/projects", headers=_headers(config)).json()["data"]
    item = next(p for p in listed["items"] if p["id"] == project_id)
    assert item["last_opened_at"] == opened


def test_touch_opened_does_not_bump_updated_at(client, config, project_id) -> None:
    """最近打开只写 last_opened_at，不能改写 updated_at（否则列表排序会被翻动）。"""
    first = client.get(f"/api/projects/{project_id}", headers=_headers(config)).json()[
        "data"
    ]
    second = client.get(f"/api/projects/{project_id}", headers=_headers(config)).json()[
        "data"
    ]
    assert second["updated_at"] == first["updated_at"]
    # ISO 8601 同格式字符串可直接比较
    assert second["last_opened_at"] >= first["last_opened_at"]
