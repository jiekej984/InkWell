"""图数据与布局测试（V2.0 / 5.2 / 回归 35~37）。"""

from __future__ import annotations

import pytest

from backend.models import session_scope
from backend.schemas import CODE_PARAM_INVALID, CODE_VERSION_CONFLICT, ApiError
from backend.services import (
    faction_service,
    graph_service,
    organization_service,
    relation_service,
)


def _expect(exc_info, code: int) -> None:
    assert exc_info.value.code == code, exc_info.value.message


def _org(database, project_id: int, name: str, **fields) -> int:
    with session_scope(database.engine) as session:
        row = organization_service.create_organization(
            session, project_id, name=name, **fields
        )
        return int(row.id)


def _faction(database, project_id: int, name: str, **fields) -> int:
    with session_scope(database.engine) as session:
        row = faction_service.create_faction(session, project_id, name=name, **fields)
        return int(row.id)


def _link(database, first: int, second: int, **fields) -> None:
    with session_scope(database.engine) as session:
        relation_service.create_character_relation(
            session, first, to_id=second, **fields
        )


def _graph(database, project_id: int, **kwargs):
    with session_scope(database.engine) as session:
        return graph_service.build_graph(session, project_id, **kwargs)


# --------------------------------------------------------------------------
# 人物模式
# --------------------------------------------------------------------------


def test_character_graph_basic(database, project_id, character_factory) -> None:
    first = character_factory("林昭", role="protagonist")
    second = character_factory("沈砚")
    third = character_factory("阿蛮")
    _link(database, first, second, relation_type="master")
    _link(database, second, third, relation_type="friend")

    payload = _graph(database, project_id)
    assert payload["mode"] == "character"
    assert len(payload["nodes"]) == 3
    assert len(payload["edges"]) == 2
    assert payload["truncated"] is False
    assert {node["name"] for node in payload["nodes"]} == {"林昭", "沈砚", "阿蛮"}
    assert all(node["key"].startswith("character:") for node in payload["nodes"])


def test_center_depth(database, project_id, character_factory) -> None:
    first = character_factory("林昭")
    second = character_factory("沈砚")
    third = character_factory("阿蛮")
    _link(database, first, second, relation_type="master")
    _link(database, second, third, relation_type="friend")

    one_hop = _graph(database, project_id, center_id=first, depth=1)
    assert {node["name"] for node in one_hop["nodes"]} == {"林昭", "沈砚"}

    two_hop = _graph(database, project_id, center_id=first, depth=2)
    assert {node["name"] for node in two_hop["nodes"]} == {
        "林昭",
        "沈砚",
        "阿蛮",
    }


def test_org_and_faction_filters(database, project_id, character_factory) -> None:
    faction = _faction(database, project_id, "正道")
    root = _org(database, project_id, "青云宗", faction_id=faction)
    peak = _org(database, project_id, "剑峰", parent_id=root)
    first = character_factory("林昭")
    second = character_factory("散人")
    with session_scope(database.engine) as session:
        organization_service.add_member(session, peak, character_id=first)

    by_org = _graph(database, project_id, org_id=root)
    assert {node["name"] for node in by_org["nodes"]} == {"林昭"}

    by_faction = _graph(database, project_id, faction_id=faction)
    assert {node["name"] for node in by_faction["nodes"]} == {"林昭"}
    assert second not in {node["id"] for node in by_faction["nodes"]}


def test_chapter_filter_drops_expired_edges(
    database, project_id, chapter_factory, character_factory
) -> None:
    first = character_factory("林昭")
    second = character_factory("沈砚")
    _, ch_start = chapter_factory(volume_order=1000, chapter_order=1000)
    _, ch_end = chapter_factory(volume_order=1000, chapter_order=2000)
    _, ch_late = chapter_factory(volume_order=1000, chapter_order=3000)
    _link(
        database,
        first,
        second,
        relation_type="master",
        from_chapter_id=ch_start,
        to_chapter_id=ch_end,
    )

    at_start = _graph(database, project_id, chapter_id=ch_start)
    assert len(at_start["edges"]) == 1
    assert at_start["nodes"][0]["name"] in {"林昭", "沈砚"}

    at_late = _graph(database, project_id, chapter_id=ch_late)
    assert len(at_late["edges"]) == 0

    default = _graph(database, project_id)
    assert len(default["edges"]) == 0

    with_expired = _graph(database, project_id, include_expired=True)
    assert len(with_expired["edges"]) == 1


def test_truncation(database, project_id, character_factory) -> None:
    for index in range(3):
        first = character_factory(f"角色{index}")
        if index:
            _link(database, 1, first, relation_type="friend")

    payload = _graph(database, project_id, limit=2)
    assert payload["truncated"] is True
    assert payload["total_nodes"] == 3
    assert len(payload["nodes"]) == 2
    assert all(
        edge["from"] in {n["id"] for n in payload["nodes"]} for edge in payload["edges"]
    )


def test_invalid_args(database, project_id) -> None:
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            graph_service.build_graph(session, project_id, mode="nope")
        _expect(exc, CODE_PARAM_INVALID)
        with pytest.raises(ApiError) as exc:
            graph_service.build_graph(session, project_id, depth=9)
        _expect(exc, CODE_PARAM_INVALID)


# --------------------------------------------------------------------------
# 组织 / 阵营模式
# --------------------------------------------------------------------------


def test_organization_mode(database, project_id, character_factory) -> None:
    root = _org(database, project_id, "青云宗")
    peak = _org(database, project_id, "剑峰", parent_id=root)
    other = _org(database, project_id, "血月教")
    first = character_factory("林昭")
    with session_scope(database.engine) as session:
        organization_service.add_member(session, peak, character_id=first)
    with session_scope(database.engine) as session:
        organization_service.create_org_relation(
            session,
            project_id,
            from_id=root,
            to_id=other,
            relation_type="war",
        )

    payload = _graph(database, project_id, mode="organization")
    assert payload["mode"] == "organization"
    assert len(payload["nodes"]) == 3
    counts = {node["name"]: node["member_count"] for node in payload["nodes"]}
    assert counts == {"青云宗": 0, "剑峰": 1, "血月教": 0}
    kinds = {edge["kind"] for edge in payload["edges"]}
    assert "org_parent" in kinds
    assert "org_relation" in kinds
    assert any(edge["from"] == root and edge["to"] == peak for edge in payload["edges"])

    subtree = _graph(database, project_id, mode="organization", org_id=root)
    assert {node["name"] for node in subtree["nodes"]} == {"青云宗", "剑峰"}


def test_faction_mode(database, project_id) -> None:
    right = _faction(database, project_id, "正道")
    evil = _faction(database, project_id, "魔道")
    _org(database, project_id, "青云宗", faction_id=right)
    with session_scope(database.engine) as session:
        faction_service.create_faction_relation(
            session,
            project_id,
            from_id=right,
            to_id=evil,
            relation_type="enemy",
        )

    payload = _graph(database, project_id, mode="faction")
    assert payload["mode"] == "faction"
    factions = [node for node in payload["nodes"] if node["kind"] == "faction"]
    orgs = [node for node in payload["nodes"] if node["kind"] == "organization"]
    assert len(factions) == 2
    assert len(orgs) == 1
    assert all(
        node["id"] >= graph_service.FACTION_GRAPH_OFFSET for node in factions
    )
    assert all(node["id"] < graph_service.FACTION_GRAPH_OFFSET for node in orgs)
    kinds = {edge["kind"] for edge in payload["edges"]}
    assert "faction_relation" in kinds
    assert "membership" in kinds
    membership = next(
        edge for edge in payload["edges"] if edge["kind"] == "membership"
    )
    assert membership["from"] >= graph_service.FACTION_GRAPH_OFFSET


# --------------------------------------------------------------------------
# 布局
# --------------------------------------------------------------------------


def test_layout_roundtrip_and_merge(database, project_id) -> None:
    with session_scope(database.engine) as session:
        empty = graph_service.get_layout(session, project_id)
        assert empty["payload"] == {}

        saved = graph_service.save_layout(
            session,
            project_id,
            {"character": {"character:1": {"x": 10, "y": 20}}},
        )
        assert saved["payload"]["character"]["character:1"]["x"] == 10.0
        stamp = saved["updated_at"]

        merged = graph_service.save_layout(
            session,
            project_id,
            {"organization": {"organization:2": {"x": 5, "y": 6, "pinned": False}}},
            expected_updated_at=stamp,
        )
    assert set(merged["payload"]) == {"character", "organization"}
    assert merged["payload"]["organization"]["organization:2"]["pinned"] is False


def test_layout_conflict_and_validation(database, project_id) -> None:
    with session_scope(database.engine) as session:
        graph_service.save_layout(session, project_id, {"character": {}})
        with pytest.raises(ApiError) as exc:
            graph_service.save_layout(
                session,
                project_id,
                {"character": {}},
                expected_updated_at="2020-01-01T00:00:00Z",
            )
        _expect(exc, CODE_VERSION_CONFLICT)

        with pytest.raises(ApiError) as exc:
            graph_service.save_layout(session, project_id, {"nope": {}})
        _expect(exc, CODE_PARAM_INVALID)

        with pytest.raises(ApiError) as exc:
            graph_service.save_layout(
                session, project_id, {"character": {"x": {"x": "a", "y": 0}}}
            )
        _expect(exc, CODE_PARAM_INVALID)


def test_layout_size_limit(database, project_id, monkeypatch) -> None:
    monkeypatch.setattr(graph_service, "MAX_LAYOUT_BYTES", 8)
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            graph_service.save_layout(
                session, project_id, {"character": {"a": {"x": 1, "y": 2}}}
            )
        _expect(exc, CODE_PARAM_INVALID)
        assert "1MB" in exc.value.message
