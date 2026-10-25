"""任务 2.2 测试：卷章 CRUD + BR-3 排序 + 默认卷 + 非空卷删除。

覆盖 FR-2.1~2.2、BR-3、BR-6、BR-4（软删除），以及 §6.2 #10~#17 / #22。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER
from backend.models import Chapter, Volume, session_scope
from backend.services import chapter_service


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


@pytest.fixture
def project_id(client, config) -> int:
    response = client.post(
        "/api/projects", json={"title": "卷章测试"}, headers=_headers(config)
    )
    assert response.json()["code"] == 0
    return response.json()["data"]["id"]


def _create_volume(client, config, pid: int, title: str) -> int:
    response = client.post(
        f"/api/projects/{pid}/volumes",
        json={"title": title},
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]["id"]


def _create_chapter(client, config, vid: int, title: str) -> int:
    response = client.post(
        f"/api/volumes/{vid}/chapters",
        json={"title": title},
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    return body["data"]["id"]


def _volume_order(database, pid: int) -> list[tuple[int, int]]:
    """返回 ``[(id, order_index), ...]``（按 order_index 排序，仅非默认卷）。"""
    with session_scope(database.engine) as session:
        rows = session.execute(
            select(Volume.id, Volume.order_index)
            .where(
                Volume.project_id == pid,
                Volume.is_default == 0,
                Volume.is_deleted == 0,
            )
            .order_by(Volume.order_index, Volume.id)
        ).all()
    return [(int(row[0]), int(row[1])) for row in rows]


def _chapter_order(database, vid: int) -> list[tuple[int, int]]:
    with session_scope(database.engine) as session:
        rows = session.execute(
            select(Chapter.id, Chapter.order_index)
            .where(Chapter.volume_id == vid, Chapter.is_deleted == 0)
            .order_by(Chapter.order_index, Chapter.id)
        ).all()
    return [(int(row[0]), int(row[1])) for row in rows]


# --------------------------------------------------------------------------
# 卷：列表 / 新建 / 默认卷
# --------------------------------------------------------------------------


def test_volume_tree_default_only(client, config, project_id, database) -> None:
    """BR-6：新项目只有默认卷；默认卷单列，不出现在 volumes 中。"""
    response = client.get(
        f"/api/projects/{project_id}/volumes", headers=_headers(config)
    )
    body = response.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["volumes"] == []
    default = data["default_volume"]
    assert default["is_default"] is True
    assert default["title"] == chapter_service.DEFAULT_VOLUME_TITLE
    assert default["order_index"] == 0
    assert default["chapters"] == []


def test_create_volume_appends_order(client, config, project_id, database) -> None:
    first = _create_volume(client, config, project_id, "第一卷")
    second = _create_volume(client, config, project_id, "第二卷")
    order = _volume_order(database, project_id)
    assert order == [(first, 1000), (second, 2000)]


def test_create_volume_requires_title(client, config, project_id) -> None:
    response = client.post(
        f"/api/projects/{project_id}/volumes",
        json={"title": "   "},
        headers=_headers(config),
    )
    assert response.json()["code"] == 1001


def test_default_volume_cannot_be_renamed_or_deleted(
    client, config, project_id
) -> None:
    response = client.get(
        f"/api/projects/{project_id}/volumes", headers=_headers(config)
    )
    default_id = response.json()["data"]["default_volume"]["id"]

    renamed = client.patch(
        f"/api/volumes/{default_id}",
        json={"title": "改名"},
        headers=_headers(config),
    )
    assert renamed.json()["code"] == 1001

    deleted = client.delete(f"/api/volumes/{default_id}", headers=_headers(config))
    assert deleted.json()["code"] == 1001


def test_update_volume_partial(client, config, project_id) -> None:
    vid = _create_volume(client, config, project_id, "旧名")
    response = client.patch(
        f"/api/volumes/{vid}",
        json={"summary": "新梗概"},
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["title"] == "旧名"
    assert body["data"]["summary"] == "新梗概"


# --------------------------------------------------------------------------
# 章节：新建 / 列表 / 重名
# --------------------------------------------------------------------------


def test_create_chapter_appends_and_metadata(
    client, config, project_id, database
) -> None:
    vid = _create_volume(client, config, project_id, "第一卷")
    first = _create_chapter(client, config, vid, "第一章")
    second = _create_chapter(client, config, vid, "第二章")
    assert _chapter_order(database, vid) == [(first, 1000), (second, 2000)]

    response = client.get(f"/api/volumes/{vid}/chapters", headers=_headers(config))
    body = response.json()
    assert body["code"] == 0
    items = body["data"]["items"]
    assert [item["title"] for item in items] == ["第一章", "第二章"]
    # §6.1：大列表接口仅返回元数据，不含正文
    assert "content" not in items[0]
    assert items[0]["version_no"] == 0
    assert items[0]["word_count"] == 0


def test_chapter_title_may_duplicate(client, config, project_id) -> None:
    vid = _create_volume(client, config, project_id, "第一卷")
    _create_chapter(client, config, vid, "同名")
    _create_chapter(client, config, vid, "同名")
    response = client.get(f"/api/volumes/{vid}/chapters", headers=_headers(config))
    assert [item["title"] for item in response.json()["data"]["items"]] == [
        "同名",
        "同名",
    ]


def test_create_chapter_in_missing_volume_returns_2001(client, config) -> None:
    response = client.post(
        "/api/volumes/99999/chapters",
        json={"title": "无主章节"},
        headers=_headers(config),
    )
    assert response.json()["code"] == 2001


# --------------------------------------------------------------------------
# BR-3 排序
# --------------------------------------------------------------------------


def test_reorder_volume_head_tail_middle(client, config, project_id, database) -> None:
    a = _create_volume(client, config, project_id, "A")
    b = _create_volume(client, config, project_id, "B")
    c = _create_volume(client, config, project_id, "C")

    # 头部：C 移到 A 之前 → 现状 A=1000 会落到 ≤0，触发整体重整
    response = client.post(
        f"/api/projects/{project_id}/volumes/reorder",
        json={"volume_id": c, "next_id": a},
        headers=_headers(config),
    )
    assert response.json()["code"] == 0, response.json()
    assert _volume_order(database, project_id) == [(c, 1000), (a, 2000), (b, 3000)]

    # 尾部：C 移到 B 之后 → 尾部 = max + 1000 = 4000
    response = client.post(
        f"/api/projects/{project_id}/volumes/reorder",
        json={"volume_id": c, "prev_id": b},
        headers=_headers(config),
    )
    assert response.json()["code"] == 0, response.json()
    assert _volume_order(database, project_id) == [(a, 2000), (b, 3000), (c, 4000)]

    # 中间：C 夹到 A 与 B 之间 → floor((2000+3000)/2)=2500
    response = client.post(
        f"/api/projects/{project_id}/volumes/reorder",
        json={"volume_id": c, "prev_id": a, "next_id": b},
        headers=_headers(config),
    )
    assert response.json()["code"] == 0, response.json()
    assert _volume_order(database, project_id) == [(a, 2000), (c, 2500), (b, 3000)]


def test_reorder_adjacent_gap_triggers_rebalance(
    client, config, project_id, database
) -> None:
    """相邻差 ≤1 时按 BR-3 局部重整为 1000/2000/3000。"""
    a = _create_volume(client, config, project_id, "A")
    b = _create_volume(client, config, project_id, "B")
    c = _create_volume(client, config, project_id, "C")

    with session_scope(database.engine) as session:
        volume_b = session.get(Volume, b)
        volume_b.order_index = 1001  # 人为制造 1000 / 1001 的相邻差

    response = client.post(
        f"/api/projects/{project_id}/volumes/reorder",
        json={"volume_id": c, "prev_id": a, "next_id": b},
        headers=_headers(config),
    )
    assert response.json()["code"] == 0, response.json()
    assert _volume_order(database, project_id) == [(a, 1000), (c, 2000), (b, 3000)]


def test_reorder_rejects_foreign_neighbor(client, config, project_id) -> None:
    _create_volume(client, config, project_id, "A")
    other = client.post(
        "/api/projects", json={"title": "另一本"}, headers=_headers(config)
    ).json()["data"]["id"]
    foreign = _create_volume(client, config, other, "别家的卷")

    response = client.post(
        f"/api/projects/{project_id}/volumes/reorder",
        json={"volume_id": foreign, "next_id": 1},
        headers=_headers(config),
    )
    assert response.json()["code"] == 1001


def test_reorder_chapter_append(client, config, project_id, database) -> None:
    vid = _create_volume(client, config, project_id, "第一卷")
    a = _create_chapter(client, config, vid, "A")
    b = _create_chapter(client, config, vid, "B")
    c = _create_chapter(client, config, vid, "C")

    # 省略 prev/next = 追加到末尾（尾部 = max + 1000，BR-3）
    response = client.post(
        f"/api/volumes/{vid}/chapters/reorder",
        json={"chapter_id": a},
        headers=_headers(config),
    )
    assert response.json()["code"] == 0, response.json()
    assert _chapter_order(database, vid) == [(b, 2000), (c, 3000), (a, 4000)]


def test_reorder_chapter_cross_volume(client, config, project_id, database) -> None:
    v1 = _create_volume(client, config, project_id, "来源卷")
    v2 = _create_volume(client, config, project_id, "目标卷")
    a = _create_chapter(client, config, v1, "A")
    b = _create_chapter(client, config, v1, "B")
    target_first = _create_chapter(client, config, v2, "目标一")

    response = client.post(
        f"/api/volumes/{v1}/chapters/reorder",
        json={
            "chapter_id": b,
            "target_volume_id": v2,
            "next_id": target_first,
        },
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["volume_id"] == v2
    assert _chapter_order(database, v1) == [(a, 1000)]
    assert _chapter_order(database, v2) == [(b, 1000), (target_first, 2000)]


def test_reorder_chapter_rejects_foreign_target_volume(
    client, config, project_id, database
) -> None:
    """target_volume_id 属于另一本书时必须拒绝，否则章节会被搬进别人的书里。"""
    v1 = _create_volume(client, config, project_id, "来源卷")
    a = _create_chapter(client, config, v1, "A")
    other = client.post(
        "/api/projects", json={"title": "另一本"}, headers=_headers(config)
    ).json()["data"]["id"]
    foreign = _create_volume(client, config, other, "别家的卷")

    response = client.post(
        f"/api/volumes/{v1}/chapters/reorder",
        json={"chapter_id": a, "target_volume_id": foreign},
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 1001, body
    assert _chapter_order(database, v1) == [(a, 1000)]


# --------------------------------------------------------------------------
# 非空卷删除（BR-4 / FR-2.1）
# --------------------------------------------------------------------------


def test_delete_nonempty_volume_requires_mode(
    client, config, project_id, database
) -> None:
    vid = _create_volume(client, config, project_id, "有章节的卷")
    _create_chapter(client, config, vid, "第一章")

    response = client.delete(f"/api/volumes/{vid}", headers=_headers(config))
    assert response.json()["code"] == 1001
    # 卷与章节都还在
    assert _volume_order(database, project_id) == [(vid, 1000)]
    assert len(_chapter_order(database, vid)) == 1


def test_delete_volume_move_chapters_to_default(
    client, config, project_id, database
) -> None:
    tree = client.get(
        f"/api/projects/{project_id}/volumes", headers=_headers(config)
    ).json()["data"]
    default_id = tree["default_volume"]["id"]
    existing = _create_chapter(client, config, default_id, "默认卷已有章节")

    vid = _create_volume(client, config, project_id, "待删卷")
    first = _create_chapter(client, config, vid, "第一章")
    second = _create_chapter(client, config, vid, "第二章")

    response = client.delete(f"/api/volumes/{vid}?mode=move", headers=_headers(config))
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["moved_chapters"] == 2

    assert _volume_order(database, project_id) == []
    assert _chapter_order(database, default_id) == [
        (existing, 1000),
        (first, 2000),
        (second, 3000),
    ]

    with session_scope(database.engine) as session:
        volume = session.get(Volume, vid)
        assert volume.is_deleted == 1
        assert volume.deleted_at is not None


def test_delete_volume_cascade_soft_deletes_chapters(
    client, config, project_id, database
) -> None:
    vid = _create_volume(client, config, project_id, "待删卷")
    _create_chapter(client, config, vid, "第一章")
    _create_chapter(client, config, vid, "第二章")

    response = client.delete(
        f"/api/volumes/{vid}?mode=cascade", headers=_headers(config)
    )
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["deleted_chapters"] == 2

    with session_scope(database.engine) as session:
        chapters = (
            session.execute(select(Chapter).where(Chapter.volume_id == vid))
            .scalars()
            .all()
        )
        assert len(chapters) == 2
        assert all(chapter.is_deleted == 1 for chapter in chapters)


def test_delete_empty_volume_without_mode(client, config, project_id) -> None:
    vid = _create_volume(client, config, project_id, "空卷")
    response = client.delete(f"/api/volumes/{vid}", headers=_headers(config))
    assert response.json()["code"] == 0


def test_delete_missing_volume_returns_2001(client, config) -> None:
    response = client.delete("/api/volumes/99999", headers=_headers(config))
    assert response.json()["code"] == 2001


# --------------------------------------------------------------------------
# 统计 / 服务层预留
# --------------------------------------------------------------------------


def test_volume_word_counts(client, config, project_id, database) -> None:
    vid = _create_volume(client, config, project_id, "第一卷")
    first = _create_chapter(client, config, vid, "第一章")
    second = _create_chapter(client, config, vid, "第二章")

    with session_scope(database.engine) as session:
        session.get(Chapter, first).word_count = 120
        session.get(Chapter, second).word_count = 80

    body = client.get(
        f"/api/projects/{project_id}/volumes", headers=_headers(config)
    ).json()
    item = body["data"]["volumes"][0]
    assert item["chapter_count"] == 2
    assert item["word_count"] == 200


def test_move_chapters_to_volume_reserved_helper(database, project_id) -> None:
    """C-03：数据层预留「章节移入目标卷末尾」，V1.1 合并卷直接复用。"""
    with session_scope(database.engine) as session:
        from backend.services import project_service

        project = project_service.require_project(session, project_id)
        source = chapter_service.create_volume(session, project.id, title="源卷")
        target = chapter_service.create_volume(session, project.id, title="目标卷")
        for index in range(2):
            chapter_service.create_chapter(
                session, source.id, title=f"迁移章节 {index}"
            )
        moved = chapter_service.move_chapters_to_volume(session, source.id, target.id)
        chapters = chapter_service.list_chapters(session, target.id)["items"]
        assert moved == 2
        assert [chapter["title"] for chapter in chapters] == [
            "迁移章节 0",
            "迁移章节 1",
        ]
        assert [chapter["order_index"] for chapter in chapters] == [1000, 2000]


def _default_volume_id(client, config, pid: int) -> int:
    tree = client.get(f"/api/projects/{pid}/volumes", headers=_headers(config)).json()[
        "data"
    ]
    return tree["default_volume"]["id"]


def test_adopt_default_chapters_into_first_volume(client, config, project_id) -> None:
    """C-04：首个命名卷创建后，默认卷章节一次性迁入。"""
    default_vid = _default_volume_id(client, config, project_id)
    _create_chapter(client, config, default_vid, "楔子一")
    _create_chapter(client, config, default_vid, "楔子二")
    vid = _create_volume(client, config, project_id, "第一卷")

    body = client.post(
        f"/api/volumes/{vid}/adopt-default", headers=_headers(config)
    ).json()
    assert body["code"] == 0, body
    assert body["data"]["moved"] == 2

    tree = client.get(
        f"/api/projects/{project_id}/volumes", headers=_headers(config)
    ).json()["data"]
    assert tree["default_volume"]["chapters"] == []
    assert [item["title"] for item in tree["volumes"][0]["chapters"]] == [
        "楔子一",
        "楔子二",
    ]

    again = client.post(
        f"/api/volumes/{vid}/adopt-default", headers=_headers(config)
    ).json()
    assert again["code"] == 0
    assert again["data"]["moved"] == 0


def test_adopt_default_only_first_named_volume(client, config, project_id) -> None:
    default_vid = _default_volume_id(client, config, project_id)
    _create_chapter(client, config, default_vid, "楔子")
    _create_volume(client, config, project_id, "第一卷")
    second = _create_volume(client, config, project_id, "第二卷")

    not_first = client.post(
        f"/api/volumes/{second}/adopt-default", headers=_headers(config)
    ).json()
    assert not_first["code"] == 1001

    as_target = client.post(
        f"/api/volumes/{default_vid}/adopt-default", headers=_headers(config)
    ).json()
    assert as_target["code"] == 1001
