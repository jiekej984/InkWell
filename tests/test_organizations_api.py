"""组织与大立场接口测试（V2.0 / 5.3；#68~#79）。"""

from __future__ import annotations

import pytest

from backend.config import TOKEN_HEADER


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


@pytest.fixture
def project_id(client, config) -> int:
    body = client.post(
        "/api/projects", json={"title": "组织接口"}, headers=_headers(config)
    ).json()
    assert body["code"] == 0, body
    return body["data"]["id"]


def _faction(client, config, pid: int, name: str, **fields) -> dict:
    body = client.post(
        f"/api/projects/{pid}/factions",
        json={"name": name, **fields},
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body
    return body["data"]


def _org(client, config, pid: int, name: str, **fields) -> dict:
    body = client.post(
        f"/api/projects/{pid}/organizations",
        json={"name": name, **fields},
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body
    return body["data"]


def _character(client, config, pid: int, name: str) -> dict:
    body = client.post(
        f"/api/projects/{pid}/characters",
        json={"name": name},
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body
    return body["data"]


def test_faction_crud_and_delete_guard(client, config, project_id) -> None:
    faction = _faction(client, config, project_id, "正道", color="#3B6EA5")
    assert faction["color"] == "#3b6ea5"
    org = _org(client, config, project_id, "青云宗", faction_id=faction["id"])
    assert org["effective_faction_id"] == faction["id"]

    listing = client.get(
        f"/api/projects/{project_id}/factions", headers=_headers(config)
    ).json()
    assert listing["data"]["total"] == 1
    assert listing["data"]["items"][0]["organization_count"] == 1

    blocked = client.delete(
        f"/api/factions/{faction['id']}", headers=_headers(config)
    ).json()
    assert blocked["code"] == 1001

    patched = client.patch(
        f"/api/factions/{faction['id']}",
        json={"name": "正道盟"},
        headers=_headers(config),
    ).json()
    assert patched["data"]["name"] == "正道盟"


def test_faction_relation_over_http(client, config, project_id) -> None:
    right = _faction(client, config, project_id, "正道")
    evil = _faction(client, config, project_id, "魔道")

    created = client.post(
        f"/api/projects/{project_id}/faction-relations",
        json={"from_id": right["id"], "to_id": evil["id"], "relation_type": "enemy"},
        headers=_headers(config),
    ).json()
    assert created["code"] == 0
    assert created["data"]["relation_label"] == "敌对"
    assert created["data"]["from_name"] == "正道"
    rid = created["data"]["id"]

    duplicate = client.post(
        f"/api/projects/{project_id}/faction-relations",
        json={"from_id": right["id"], "to_id": evil["id"], "relation_type": "enemy"},
        headers=_headers(config),
    ).json()
    assert duplicate["code"] == 1001

    listing = client.get(
        f"/api/projects/{project_id}/faction-relations", headers=_headers(config)
    ).json()
    assert listing["data"]["total"] == 1

    assert (
        client.delete(f"/api/faction-relations/{rid}", headers=_headers(config)).json()[
            "code"
        ]
        == 0
    )


def test_organization_tree_and_cycle(client, config, project_id) -> None:
    root = _org(client, config, project_id, "青云宗")
    peak = _org(client, config, project_id, "剑峰", parent_id=root["id"])

    tree = client.get(
        f"/api/projects/{project_id}/organizations",
        params={"tree": 1},
        headers=_headers(config),
    ).json()
    assert tree["data"]["total"] == 2
    assert tree["data"]["items"][0]["name"] == "青云宗"
    assert tree["data"]["items"][0]["children"][0]["name"] == "剑峰"

    cycle = client.patch(
        f"/api/organizations/{root['id']}",
        json={"parent_id": peak["id"]},
        headers=_headers(config),
    ).json()
    assert cycle["code"] == 1001


def test_organization_delete_strategies(client, config, project_id) -> None:
    root = _org(client, config, project_id, "青云宗")
    child = _org(client, config, project_id, "剑峰", parent_id=root["id"])

    root_promote = client.delete(
        f"/api/organizations/{root['id']}",
        params={"strategy": "promote"},
        headers=_headers(config),
    ).json()
    assert root_promote["code"] == 1001

    promoted = client.delete(
        f"/api/organizations/{child['id']}",
        params={"strategy": "promote"},
        headers=_headers(config),
    ).json()
    assert promoted["code"] == 0
    assert promoted["data"]["members_moved"] == 0

    cascaded = client.delete(
        f"/api/organizations/{root['id']}", headers=_headers(config)
    ).json()
    assert cascaded["code"] == 0
    assert cascaded["data"]["organizations_deleted"] == 1


def test_member_crud_over_http(client, config, project_id) -> None:
    org = _org(client, config, project_id, "青云宗")
    cid = _character(client, config, project_id, "林昭")["id"]

    created = client.post(
        f"/api/organizations/{org['id']}/members",
        json={"character_id": cid, "position": "弟子", "is_primary": True},
        headers=_headers(config),
    ).json()
    assert created["code"] == 0
    assert created["data"]["is_primary"] is True
    mid = created["data"]["id"]

    duplicate = client.post(
        f"/api/organizations/{org['id']}/members",
        json={"character_id": cid},
        headers=_headers(config),
    ).json()
    assert duplicate["code"] == 1001

    listing = client.get(
        f"/api/organizations/{org['id']}/members", headers=_headers(config)
    ).json()
    assert listing["data"]["total"] == 1
    assert listing["data"]["items"][0]["character_name"] == "林昭"

    patched = client.patch(
        f"/api/org-members/{mid}",
        json={"position": "长老", "is_secret": True},
        headers=_headers(config),
    ).json()
    assert patched["data"]["position"] == "长老"
    assert patched["data"]["is_secret"] is True

    assert (
        client.delete(f"/api/org-members/{mid}", headers=_headers(config)).json()[
            "code"
        ]
        == 0
    )


def test_org_relation_over_http(client, config, project_id) -> None:
    first = _org(client, config, project_id, "青云宗")
    second = _org(client, config, project_id, "血月教")

    created = client.post(
        f"/api/projects/{project_id}/org-relations",
        json={"from_id": first["id"], "to_id": second["id"], "relation_type": "war"},
        headers=_headers(config),
    ).json()
    assert created["code"] == 0
    assert created["data"]["from_name"] == "青云宗"
    rid = created["data"]["id"]

    self_link = client.post(
        f"/api/projects/{project_id}/org-relations",
        json={"from_id": first["id"], "to_id": first["id"]},
        headers=_headers(config),
    ).json()
    assert self_link["code"] == 1001

    listing = client.get(
        f"/api/projects/{project_id}/org-relations", headers=_headers(config)
    ).json()
    assert listing["data"]["items"][0]["relation_label"] == "战争"

    assert (
        client.delete(f"/api/org-relations/{rid}", headers=_headers(config)).json()[
            "code"
        ]
        == 0
    )
