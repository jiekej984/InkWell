"""角色库接口测试（V2.0 / 5.3；#54~#67、#80~#81）。"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from backend.config import TOKEN_HEADER


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


def _png_bytes(size: tuple[int, int] = (8, 8)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color=(20, 40, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def project_id(client, config) -> int:
    body = client.post(
        "/api/projects", json={"title": "角色接口"}, headers=_headers(config)
    ).json()
    assert body["code"] == 0, body
    return body["data"]["id"]


def _character(client, config, pid: int, name: str, **fields) -> dict:
    body = client.post(
        f"/api/projects/{pid}/characters",
        json={"name": name, **fields},
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body
    return body["data"]


# --------------------------------------------------------------------------
# #54~#58
# --------------------------------------------------------------------------


def test_huge_id_is_param_error_not_500(client, config) -> None:
    """超出 SQLite INTEGER 的 id 由全局 OverflowError 处理为 1001，不冒 500。"""
    body = client.get(f"/api/characters/{10**30}", headers=_headers(config)).json()
    assert body["code"] == 1001, body


def test_meta_lists_all_enums(client, config, project_id) -> None:
    body = client.get(
        f"/api/projects/{project_id}/characters/meta", headers=_headers(config)
    ).json()
    assert body["code"] == 0
    data = body["data"]
    assert len(data["relation_types"]) == 20
    assert len(data["roles"]) == 6
    assert data["character_field_labels"]["note"] == "备注"


def test_create_get_patch_list(client, config, project_id) -> None:
    created = _character(
        client, config, project_id, "林昭", role="protagonist", age="十六七岁"
    )
    assert created["role"] == "protagonist"
    assert created["role_label"] == "主角"
    assert created["status"] == "alive"
    cid = created["id"]

    detail = client.get(f"/api/characters/{cid}", headers=_headers(config)).json()
    assert detail["code"] == 0
    assert detail["data"]["aliases"] == []
    assert detail["data"]["memberships"] == []

    patched = client.patch(
        f"/api/characters/{cid}",
        json={"personality": "冷峻", "tags": ["剑修"]},
        headers=_headers(config),
    ).json()
    assert patched["code"] == 0
    assert patched["data"]["personality"] == "冷峻"
    assert patched["data"]["tags"] == ["剑修"]

    listing = client.get(
        f"/api/projects/{project_id}/characters",
        params={"keyword": "林", "sort": "order"},
        headers=_headers(config),
    ).json()
    assert listing["code"] == 0
    assert listing["data"]["total"] == 1
    assert listing["data"]["items"][0]["id"] == cid


def test_character_appearances_endpoint(client, config, project_id) -> None:
    character = _character(client, config, project_id, "林昭")
    body = client.get(
        f"/api/characters/{character['id']}/appearances", headers=_headers(config)
    ).json()
    assert body["code"] == 0, body
    assert body["data"]["character_id"] == character["id"]
    assert body["data"]["chapter_count"] == 0


def test_delete_then_get_reports_deleted(client, config, project_id) -> None:
    cid = _character(client, config, project_id, "林昭")["id"]
    assert (
        client.delete(f"/api/characters/{cid}", headers=_headers(config)).json()["code"]
        == 0
    )
    body = client.get(f"/api/characters/{cid}", headers=_headers(config)).json()
    assert body["code"] == 2002


def test_validation_error_maps_to_1001(client, config, project_id) -> None:
    body = client.post(
        f"/api/projects/{project_id}/characters",
        json={"name": "甲", "role": "boss"},
        headers=_headers(config),
    ).json()
    assert body["code"] == 1001


# --------------------------------------------------------------------------
# #60~#62 别名与字段
# --------------------------------------------------------------------------


def test_alias_conflict_and_force(client, config, project_id) -> None:
    _character(client, config, project_id, "沈砚")
    cid = _character(client, config, project_id, "林昭")["id"]

    conflict = client.put(
        f"/api/characters/{cid}/aliases",
        json={"aliases": ["沈砚"]},
        headers=_headers(config),
    ).json()
    assert conflict["code"] == 1001

    forced = client.put(
        f"/api/characters/{cid}/aliases",
        json={"aliases": ["沈砚", "小昭"], "force": True},
        headers=_headers(config),
    ).json()
    assert forced["code"] == 0
    assert sorted(forced["data"]["aliases"]) == ["小昭", "沈砚"]


def test_fields_crud_over_http(client, config, project_id) -> None:
    cid = _character(client, config, project_id, "林昭")["id"]

    created = client.post(
        f"/api/characters/{cid}/fields",
        json={"key": "灵根", "value": "单系水灵根", "field_type": "text"},
        headers=_headers(config),
    ).json()
    assert created["code"] == 0
    fid = created["data"]["id"]

    listing = client.get(
        f"/api/characters/{cid}/fields", headers=_headers(config)
    ).json()
    assert listing["data"]["items"][0]["key"] == "灵根"

    bad = client.post(
        f"/api/characters/{cid}/fields",
        json={"key": "年龄", "value": "十六", "field_type": "number"},
        headers=_headers(config),
    ).json()
    assert bad["code"] == 1001

    updated = client.patch(
        f"/api/fields/{fid}",
        json={"value": "12", "field_type": "number"},
        headers=_headers(config),
    ).json()
    assert updated["data"]["field_type"] == "number"

    assert (
        client.delete(f"/api/fields/{fid}", headers=_headers(config)).json()["code"]
        == 0
    )


# --------------------------------------------------------------------------
# #63 立绘
# --------------------------------------------------------------------------


def test_avatar_is_square_webp(client, config, project_id) -> None:
    cid = _character(client, config, project_id, "林昭")["id"]
    response = client.post(
        f"/api/characters/{cid}/avatar",
        files={"file": ("a.png", _png_bytes((10, 30)), "image/png")},
        headers=_headers(config),
    )
    body = response.json()
    assert body["code"] == 0, body
    assert body["data"]["path"].startswith("media/characters/")
    assert body["data"]["path"].endswith(".webp")
    assert "/files/" in body["data"]["url"]

    target = Path(config.data_dir) / body["data"]["path"]
    assert target.is_file()

    from PIL import Image

    with Image.open(target) as image:
        assert image.format == "WEBP"
        assert image.size == (512, 512)

    detail = client.get(f"/api/characters/{cid}", headers=_headers(config)).json()
    assert detail["data"]["avatar_path"] == body["data"]["path"]


def test_avatar_rejects_non_image(client, config, project_id) -> None:
    cid = _character(client, config, project_id, "林昭")["id"]
    body = client.post(
        f"/api/characters/{cid}/avatar",
        files={"file": ("a.png", b"not an image", "image/png")},
        headers=_headers(config),
    ).json()
    assert body["code"] == 4002


# --------------------------------------------------------------------------
# #65~#67 关系
# --------------------------------------------------------------------------


def test_relation_crud_over_http(client, config, project_id) -> None:
    first = _character(client, config, project_id, "林昭")["id"]
    second = _character(client, config, project_id, "沈砚")["id"]

    created = client.post(
        f"/api/characters/{first}/relations",
        json={"to_id": second, "relation_type": "master"},
        headers=_headers(config),
    ).json()
    assert created["code"] == 0
    assert created["data"]["relation_label"] == "师徒"
    rid = created["data"]["id"]

    duplicate = client.post(
        f"/api/characters/{first}/relations",
        json={"to_id": second, "relation_type": "master"},
        headers=_headers(config),
    ).json()
    assert duplicate["code"] == 1001

    listing = client.get(
        f"/api/characters/{first}/relations", headers=_headers(config)
    ).json()
    assert listing["data"]["total"] == 1
    assert listing["data"]["items"][0]["other_name"] == "沈砚"

    patched = client.patch(
        f"/api/relations/{rid}",
        json={"is_secret": True},
        headers=_headers(config),
    ).json()
    assert patched["data"]["is_secret"] is True

    assert (
        client.delete(f"/api/relations/{rid}", headers=_headers(config)).json()["code"]
        == 0
    )


# --------------------------------------------------------------------------
# #64 / #80 / #81 图与布局
# --------------------------------------------------------------------------


def test_graph_and_layout(client, config, project_id) -> None:
    first = _character(client, config, project_id, "林昭")["id"]
    second = _character(client, config, project_id, "沈砚")["id"]
    client.post(
        f"/api/characters/{first}/relations",
        json={"to_id": second, "relation_type": "friend"},
        headers=_headers(config),
    )

    graph = client.get(
        f"/api/projects/{project_id}/graph",
        params={"mode": "character"},
        headers=_headers(config),
    ).json()
    assert graph["code"] == 0
    assert len(graph["data"]["nodes"]) == 2
    assert len(graph["data"]["edges"]) == 1

    invalid = client.get(
        f"/api/projects/{project_id}/graph",
        params={"mode": "nope"},
        headers=_headers(config),
    ).json()
    assert invalid["code"] == 1001

    empty = client.get(
        f"/api/projects/{project_id}/graph/layout", headers=_headers(config)
    ).json()
    assert empty["data"]["payload"] == {}

    saved = client.put(
        f"/api/projects/{project_id}/graph/layout",
        json={
            "payload": {"character": {f"character:{first}": {"x": 1, "y": 2}}},
        },
        headers=_headers(config),
    ).json()
    assert saved["code"] == 0
    stamp = saved["data"]["updated_at"]

    conflict = client.put(
        f"/api/projects/{project_id}/graph/layout",
        json={
            "payload": {"character": {}},
            "expected_updated_at": "2020-01-01T00:00:00Z",
        },
        headers=_headers(config),
    ).json()
    assert conflict["code"] == 3002

    merged = client.put(
        f"/api/projects/{project_id}/graph/layout",
        json={
            "payload": {"organization": {"organization:1": {"x": 5, "y": 6}}},
            "expected_updated_at": stamp,
        },
        headers=_headers(config),
    ).json()
    assert merged["code"] == 0
    assert set(merged["data"]["payload"]) == {"character", "organization"}
