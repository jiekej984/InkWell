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
from backend.models import (
    Chapter,
    Character,
    Document,
    Faction,
    Organization,
    OrgMember,
    Project,
    Volume,
    session_scope,
)
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


# --------------------------------------------------------------------------
# V2.0 5.10：角色 / 组织 / 阵营回收站
# --------------------------------------------------------------------------


def _create_character(
    client, config, pid: int, name: str, role: str = "supporting"
) -> int:
    body = client.post(
        f"/api/projects/{pid}/characters",
        json={"name": name, "role": role},
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body
    return body["data"]["id"]


def test_trash_character_restore_with_aliases(client, config, project_id) -> None:
    character_id = _create_character(client, config, project_id, "林昭", "protagonist")
    alias_body = client.put(
        f"/api/characters/{character_id}/aliases",
        json={"aliases": ["小昭"]},
        headers=_headers(config),
    ).json()
    assert alias_body["code"] == 0, alias_body

    deleted = client.delete(
        f"/api/characters/{character_id}", headers=_headers(config)
    ).json()
    assert deleted["code"] == 0, deleted

    trash = client.get("/api/trash", headers=_headers(config)).json()["data"]
    assert len(trash["characters"]) == 1
    item = trash["characters"][0]
    assert item["title"] == "林昭"
    assert item["project_title"] == "回收站测试"
    assert item["days_left"] in (29, 30)

    restored = client.post(
        f"/api/trash/character/{character_id}/restore", headers=_headers(config)
    ).json()
    assert restored["code"] == 0, restored
    assert restored["data"]["restored"] is True
    assert "小昭" in restored["data"]["aliases_restored"]

    detail = client.get(
        f"/api/characters/{character_id}", headers=_headers(config)
    ).json()["data"]
    assert detail["name"] == "林昭"
    assert "小昭" in detail["aliases"]


def test_trash_organization_recursive_restore(client, config, database, project_id) -> None:
    character_id = _create_character(client, config, project_id, "沈砚")
    parent = client.post(
        f"/api/projects/{project_id}/organizations",
        json={"name": "青云宗", "kind": "sect"},
        headers=_headers(config),
    ).json()["data"]
    child = client.post(
        f"/api/projects/{project_id}/organizations",
        json={"name": "剑峰", "kind": "sect", "parent_id": parent["id"]},
        headers=_headers(config),
    ).json()["data"]
    member = client.post(
        f"/api/organizations/{parent['id']}/members",
        json={"character_id": character_id, "position": "宗主"},
        headers=_headers(config),
    ).json()
    assert member["code"] == 0, member

    deleted = client.delete(
        f"/api/organizations/{parent['id']}?strategy=cascade",
        headers=_headers(config),
    ).json()
    assert deleted["code"] == 0, deleted

    trash = client.get("/api/trash", headers=_headers(config)).json()["data"]
    titles = {item["title"] for item in trash["organizations"]}
    assert titles == {"青云宗", "剑峰"}
    child_item = next(item for item in trash["organizations"] if item["title"] == "剑峰")
    assert child_item["parent_title"] == "青云宗"

    restored = client.post(
        f"/api/trash/organization/{parent['id']}/restore", headers=_headers(config)
    ).json()
    assert restored["code"] == 0, restored
    assert restored["data"]["restored"] is True

    with session_scope(database.engine) as session:
        assert session.get(Organization, parent["id"]).is_deleted == 0
        assert session.get(Organization, child["id"]).is_deleted == 0
        members = (
            session.query(OrgMember).filter(OrgMember.org_id == parent["id"]).all()
        )
        assert members and members[0].is_deleted == 0


def test_restore_faction_name_conflict_returns_1001(
    client, config, project_id
) -> None:
    """删除期间同名立场可能被新建；恢复应返回 1001，而不是 500。"""
    faction = client.post(
        f"/api/projects/{project_id}/factions",
        json={"name": "正道"},
        headers=_headers(config),
    ).json()["data"]
    client.delete(f"/api/factions/{faction['id']}", headers=_headers(config))
    client.post(
        f"/api/projects/{project_id}/factions",
        json={"name": "正道"},
        headers=_headers(config),
    )

    body = client.post(
        f"/api/trash/faction/{faction['id']}/restore", headers=_headers(config)
    ).json()
    assert body["code"] == 1001, body
    assert "占用" in body["message"]


def test_restore_org_name_conflict_returns_1001(client, config, project_id) -> None:
    org = client.post(
        f"/api/projects/{project_id}/organizations",
        json={"name": "青云宗"},
        headers=_headers(config),
    ).json()["data"]
    client.delete(f"/api/organizations/{org['id']}", headers=_headers(config))
    client.post(
        f"/api/projects/{project_id}/organizations",
        json={"name": "青云宗"},
        headers=_headers(config),
    )

    body = client.post(
        f"/api/trash/organization/{org['id']}/restore", headers=_headers(config)
    ).json()
    assert body["code"] == 1001, body
    assert "占用" in body["message"]


def test_restore_org_only_same_batch_children(client, config, project_id) -> None:
    """更早单独删除的子组织不在父组织的恢复批次里。"""
    parent = client.post(
        f"/api/projects/{project_id}/organizations",
        json={"name": "父宗"},
        headers=_headers(config),
    ).json()["data"]
    child = client.post(
        f"/api/projects/{project_id}/organizations",
        json={"name": "子峰", "parent_id": parent["id"]},
        headers=_headers(config),
    ).json()["data"]
    client.delete(f"/api/organizations/{child['id']}", headers=_headers(config))
    client.delete(
        f"/api/organizations/{parent['id']}?strategy=cascade", headers=_headers(config)
    )

    body = client.post(
        f"/api/trash/organization/{parent['id']}/restore", headers=_headers(config)
    ).json()
    assert body["code"] == 0, body
    assert body["data"]["organizations_restored"] == 1

    listing = client.get(
        f"/api/projects/{project_id}/organizations", headers=_headers(config)
    ).json()["data"]
    names = {item["name"] for item in listing["items"]}
    assert "父宗" in names
    assert "子峰" not in names


def test_restore_volume_with_parent_restores_item_deleted_earlier(
    client, config, project_id, database
) -> None:
    """卷先于项目删除时，项目批次恢复不到它；显式恢复必须真的恢复该卷。"""
    volume = client.post(
        f"/api/projects/{project_id}/volumes",
        json={"title": "旧卷"},
        headers=_headers(config),
    ).json()["data"]
    client.delete(
        f"/api/volumes/{volume['id']}?mode=cascade", headers=_headers(config)
    )
    client.delete(f"/api/projects/{project_id}", headers=_headers(config))

    body = client.post(
        f"/api/trash/volume/{volume['id']}/restore?with_parent=true",
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body
    with session_scope(database.engine) as session:
        assert session.get(Volume, volume["id"]).is_deleted == 0
        assert session.get(Project, project_id).is_deleted == 0


def test_restore_org_with_parent_returns_target(client, config, project_id) -> None:
    """with_parent 时返回的 id / title 必须是用户点的那一项，而不是父组织。"""
    parent = client.post(
        f"/api/projects/{project_id}/organizations",
        json={"name": "青云宗"},
        headers=_headers(config),
    ).json()["data"]
    child = client.post(
        f"/api/projects/{project_id}/organizations",
        json={"name": "剑峰", "parent_id": parent["id"]},
        headers=_headers(config),
    ).json()["data"]

    client.delete(
        f"/api/organizations/{parent['id']}?strategy=cascade",
        headers=_headers(config),
    )
    restored = client.post(
        f"/api/trash/organization/{child['id']}/restore?with_parent=true",
        headers=_headers(config),
    ).json()
    assert restored["code"] == 0, restored
    data = restored["data"]
    assert data["id"] == child["id"]
    assert data["title"] == "剑峰"
    assert data["restored_parent"] == {"type": "organization", "id": parent["id"]}


def test_trash_faction_restore(client, config, database, project_id) -> None:
    faction = client.post(
        f"/api/projects/{project_id}/factions",
        json={"name": "正道"},
        headers=_headers(config),
    ).json()["data"]
    deleted = client.delete(
        f"/api/factions/{faction['id']}", headers=_headers(config)
    ).json()
    assert deleted["code"] == 0, deleted

    trash = client.get("/api/trash", headers=_headers(config)).json()["data"]
    assert [item["title"] for item in trash["factions"]] == ["正道"]

    restored = client.post(
        f"/api/trash/faction/{faction['id']}/restore", headers=_headers(config)
    ).json()
    assert restored["code"] == 0, restored
    with session_scope(database.engine) as session:
        assert session.get(Faction, faction["id"]).is_deleted == 0


def test_trash_character_requires_project_parent(client, config, database) -> None:
    project = client.post(
        "/api/projects", json={"title": "父链项目"}, headers=_headers(config)
    ).json()["data"]
    character_id = _create_character(client, config, project["id"], "顾长庚")
    client.delete(f"/api/characters/{character_id}", headers=_headers(config))
    client.delete(f"/api/projects/{project['id']}", headers=_headers(config))

    pending = client.post(
        f"/api/trash/character/{character_id}/restore", headers=_headers(config)
    ).json()
    assert pending["code"] == 0, pending
    assert pending["data"]["requires_parent"] is True
    assert pending["data"]["parent"]["type"] == "project"

    restored = client.post(
        f"/api/trash/character/{character_id}/restore?with_parent=true",
        headers=_headers(config),
    ).json()
    assert restored["code"] == 0, restored
    assert restored["data"]["restored"] is True

    with session_scope(database.engine) as session:
        assert session.get(Character, character_id).is_deleted == 0


def test_empty_trash_counts_new_types(client, config, project_id) -> None:
    character_id = _create_character(client, config, project_id, "阿棠")
    faction = client.post(
        f"/api/projects/{project_id}/factions",
        json={"name": "青帮"},
        headers=_headers(config),
    ).json()["data"]
    org = client.post(
        f"/api/projects/{project_id}/organizations",
        json={"name": "堂口", "kind": "guild"},
        headers=_headers(config),
    ).json()["data"]

    client.delete(f"/api/characters/{character_id}", headers=_headers(config))
    client.delete(f"/api/factions/{faction['id']}", headers=_headers(config))
    client.delete(
        f"/api/organizations/{org['id']}?strategy=cascade", headers=_headers(config)
    )

    body = client.delete("/api/trash/empty", headers=_headers(config)).json()
    assert body["code"] == 0, body
    counts = body["data"]
    assert counts["characters"] == 1
    assert counts["organizations"] == 1
    assert counts["factions"] == 1


