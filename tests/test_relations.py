"""角色关系测试（V2.0 / 5.2 / 回归 32）。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.models import CharacterRelation, session_scope
from backend.schemas import CODE_DELETED, CODE_PARAM_INVALID, ApiError
from backend.services import relation_service


def _expect(exc_info, code: int) -> None:
    assert exc_info.value.code == code, exc_info.value.message


def _connect(database, first: int, second: int, **fields) -> int:
    with session_scope(database.engine) as session:
        row = relation_service.create_character_relation(
            session, first, to_id=second, **fields
        )
        return int(row.id)


def test_default_direction_and_labels(database, project_id, character_factory) -> None:
    first = character_factory("林昭")
    second = character_factory("沈砚")
    with session_scope(database.engine) as session:
        row = relation_service.create_character_relation(
            session, first, to_id=second, relation_type="master"
        )
        assert row.is_bidirectional == 0
        assert row.custom_label == ""

    third = character_factory("阿蛮")
    with session_scope(database.engine) as session:
        friend = relation_service.create_character_relation(
            session, first, to_id=third, relation_type="friend"
        )
        assert friend.is_bidirectional == 1

    with session_scope(database.engine) as session:
        payload = relation_service.list_character_relations(session, first)
        assert payload["total"] == 2
        labels = {item["relation_label"] for item in payload["items"]}
        assert labels == {"师徒", "朋友"}
        assert all(item["other_name"] in {"沈砚", "阿蛮"} for item in payload["items"])


def test_same_pair_multiple_types_and_labels(
    database, project_id, character_factory
) -> None:
    first = character_factory("林昭")
    second = character_factory("沈砚")
    _connect(database, first, second, relation_type="master")
    _connect(database, first, second, relation_type="enemy")

    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            relation_service.create_character_relation(
                session, first, to_id=second, relation_type="master"
            )
        _expect(exc, CODE_PARAM_INVALID)

    # 同类型 + 不同自定义标签可共存
    _connect(database, first, second, relation_type="other", custom_label="青梅竹马")
    _connect(database, first, second, relation_type="other", custom_label="指腹为婚")
    with session_scope(database.engine) as session:
        assert relation_service.list_character_relations(session, first)["total"] == 4


def test_self_relation_rejected(database, project_id, character_factory) -> None:
    cid = character_factory("林昭")
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            relation_service.create_character_relation(session, cid, to_id=cid)
        _expect(exc, CODE_PARAM_INVALID)


def test_chapter_range(
    database, project_id, chapter_factory, character_factory
) -> None:
    first = character_factory("林昭")
    second = character_factory("沈砚")
    _, early = chapter_factory(volume_order=1000, chapter_order=1000)
    _, late = chapter_factory(volume_order=1000, chapter_order=2000)

    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            relation_service.create_character_relation(
                session,
                first,
                to_id=second,
                from_chapter_id=late,
                to_chapter_id=early,
            )
        _expect(exc, CODE_PARAM_INVALID)

    with session_scope(database.engine) as session:
        row = relation_service.create_character_relation(
            session,
            first,
            to_id=second,
            relation_type="master",
            from_chapter_id=early,
            to_chapter_id=late,
        )
        assert row.from_chapter_id == early
        assert row.to_chapter_id == late

    with session_scope(database.engine) as session:
        payload = relation_service.list_character_relations(
            session, first, include_expired=False
        )
        # to_chapter_id 有值 → 视为已失效，不返回
        assert payload["total"] == 0
        payload_all = relation_service.list_character_relations(session, first)
        assert payload_all["items"][0]["active"] is False


def test_soft_delete_then_rebuild(database, project_id, character_factory) -> None:
    first = character_factory("林昭")
    second = character_factory("沈砚")
    rid = _connect(database, first, second, relation_type="master")

    with session_scope(database.engine) as session:
        relation_service.delete_character_relation(session, rid)
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            relation_service.delete_character_relation(session, rid)
        _expect(exc, CODE_DELETED)

    rebuilt = _connect(database, first, second, relation_type="master")
    assert rebuilt != rid
    with session_scope(database.engine) as session:
        rows = (
            session.execute(
                select(CharacterRelation).where(
                    CharacterRelation.from_id == first,
                    CharacterRelation.relation_type == "master",
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2
        assert sum(row.is_deleted for row in rows) == 1


def test_update_type_resets_default_direction(
    database, project_id, character_factory
) -> None:
    first = character_factory("林昭")
    second = character_factory("沈砚")
    rid = _connect(database, first, second, relation_type="master")

    with session_scope(database.engine) as session:
        updated = relation_service.update_character_relation(
            session, rid, relation_type="spouse"
        )
        assert updated.relation_type == "spouse"
        assert updated.is_bidirectional == 1

    with session_scope(database.engine) as session:
        updated = relation_service.update_character_relation(
            session, rid, is_secret=True, description="暗中结盟"
        )
        assert updated.is_secret == 1
        assert updated.description == "暗中结盟"


def test_update_to_conflicting_pair_rejected(
    database, project_id, character_factory
) -> None:
    first = character_factory("林昭")
    second = character_factory("沈砚")
    master = _connect(database, first, second, relation_type="master")
    enemy = _connect(database, first, second, relation_type="enemy")
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            relation_service.update_character_relation(
                session, enemy, relation_type="master"
            )
        _expect(exc, CODE_PARAM_INVALID)
    with session_scope(database.engine) as session:
        row = session.get(CharacterRelation, master)
        assert row.relation_type == "master"
