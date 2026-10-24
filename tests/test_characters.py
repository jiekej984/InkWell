"""角色服务测试（V2.0 / 5.2 / 回归 29~31）。"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from backend.models import (
    Character,
    CharacterAlias,
    CharacterField,
    CharacterRelation,
    session_scope,
)
from backend.schemas import CODE_DELETED, CODE_NOT_FOUND, CODE_PARAM_INVALID, ApiError
from backend.services import character_service, relation_service


def _expect(exc_info, code: int) -> None:
    assert exc_info.value.code == code, exc_info.value.message


# --------------------------------------------------------------------------
# 建档与编辑
# --------------------------------------------------------------------------


def test_create_defaults(database, project_id) -> None:
    with session_scope(database.engine) as session:
        row = character_service.create_character(
            session, project_id, name="  林昭  ", gender="女"
        )
        assert row.name == "林昭"
        assert row.role == "supporting"
        assert row.status == "alive"
        assert row.source == "manual"
        assert row.order_index == 1000
        assert row.gender == "女"

    with session_scope(database.engine) as session:
        second = character_service.create_character(session, project_id, name="沈砚")
        assert second.order_index == 2000


def test_create_rejects_invalid_enum(database, project_id) -> None:
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            character_service.create_character(
                session, project_id, name="甲", role="boss"
            )
        _expect(exc, CODE_PARAM_INVALID)


def test_create_rejects_blank_name(database, project_id) -> None:
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            character_service.create_character(session, project_id, name="   ")
        _expect(exc, CODE_PARAM_INVALID)


def test_update_fields_and_tags(database, project_id, character_factory) -> None:
    cid = character_factory("林昭")
    with session_scope(database.engine) as session:
        row = character_service.update_character(
            session,
            cid,
            age="十六七岁",
            height="一六五",
            personality="冷峻，护短",
            tags=["剑修", "复仇线", "剑修"],
            avatar_path="media/characters/1/x.webp",
        )
        assert row.age == "十六七岁"
        assert row.height == "一六五"
        assert json.loads(row.tags) == ["剑修", "复仇线"]
        assert row.avatar_path.endswith("x.webp")

    with session_scope(database.engine) as session:
        detail = character_service.get_character_detail(session, cid)
        assert detail["tags"] == ["剑修", "复仇线"]
        assert detail["status_label"] == "存活"
        assert detail["role_label"] == "重要配角"


def test_list_filters_and_pagination(database, project_id, character_factory) -> None:
    lin = character_factory("林昭", role="protagonist")
    shen = character_factory("沈砚", role="supporting")
    gu = character_factory("顾长陵", role="antagonist", status="dead")

    with session_scope(database.engine) as session:
        character_service.set_aliases(session, lin, ["小昭", "昭儿"])

    with session_scope(database.engine) as session:
        assert character_service.list_characters(session, project_id)["total"] == 3
        assert [
            item["name"]
            for item in character_service.list_characters(
                session, project_id, role="protagonist"
            )["items"]
        ] == ["林昭"]
        assert [
            item["name"]
            for item in character_service.list_characters(
                session, project_id, status="dead"
            )["items"]
        ] == ["顾长陵"]
        # 别名命中
        assert [
            item["id"]
            for item in character_service.list_characters(
                session, project_id, keyword="昭儿"
            )["items"]
        ] == [lin]
        # 分页 + 排序（SQLite 对中文按 UTF-8 字节序：林 < 沈 < 顾）
        page = character_service.list_characters(
            session, project_id, sort="name", page=1, page_size=2
        )
        assert page["total"] == 3
        assert [item["name"] for item in page["items"]] == ["林昭", "沈砚"]
        assert {item["id"] for item in page["items"]} == {lin, shen}
        assert gu not in {item["id"] for item in page["items"]}


def test_list_rejects_bad_sort(database, project_id) -> None:
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            character_service.list_characters(session, project_id, sort="rand")
        _expect(exc, CODE_PARAM_INVALID)


def test_list_rejects_unknown_org(database, project_id) -> None:
    """组织筛选传了不存在的 id：报 2001，而不是静默返回空列表。"""
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            character_service.list_characters(session, project_id, org_id=9999)
        _expect(exc, CODE_NOT_FOUND)


# --------------------------------------------------------------------------
# 别名
# --------------------------------------------------------------------------


def test_aliases_basic(database, project_id, character_factory) -> None:
    cid = character_factory("林昭")
    with session_scope(database.engine) as session:
        saved = character_service.set_aliases(
            session, cid, ["小昭", "  ", "小昭", "林昭", "昭儿"]
        )
    assert saved == ["小昭", "昭儿"]


def test_alias_conflict_with_other_name_needs_force(
    database, project_id, character_factory
) -> None:
    character_factory("沈砚")
    cid = character_factory("林昭")
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            character_service.set_aliases(session, cid, ["沈砚"])
        _expect(exc, CODE_PARAM_INVALID)
        assert "沈砚" in exc.value.message
    with session_scope(database.engine) as session:
        assert character_service.set_aliases(session, cid, ["沈砚"], force=True) == [
            "沈砚"
        ]


def test_alias_conflict_with_other_alias_always_fails(
    database, project_id, character_factory
) -> None:
    first = character_factory("林昭")
    second = character_factory("沈砚")
    with session_scope(database.engine) as session:
        character_service.set_aliases(session, first, ["小昭"])
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            character_service.set_aliases(session, second, ["小昭"], force=True)
        _expect(exc, CODE_PARAM_INVALID)
        assert "小昭" in exc.value.message


def test_alias_replacement_takes_effect(
    database, project_id, character_factory
) -> None:
    cid = character_factory("林昭")
    with session_scope(database.engine) as session:
        character_service.set_aliases(session, cid, ["小昭", "昭儿"])
    with session_scope(database.engine) as session:
        character_service.set_aliases(session, cid, ["昭儿"])
    with session_scope(database.engine) as session:
        detail = character_service.get_character_detail(session, cid)
        assert detail["aliases"] == ["昭儿"]


# --------------------------------------------------------------------------
# 删除 / 恢复 / 彻底删除
# --------------------------------------------------------------------------


def test_soft_delete_and_restore(database, project_id, character_factory) -> None:
    cid = character_factory("林昭")
    with session_scope(database.engine) as session:
        character_service.set_aliases(session, cid, ["小昭", "昭儿"])
        character_service.delete_character(session, cid)

    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            character_service.require_character(session, cid)
        _expect(exc, CODE_DELETED)
        # 别名一并标记，不再占用唯一键
        aliases = (
            session.execute(
                select(CharacterAlias).where(CharacterAlias.character_id == cid)
            )
            .scalars()
            .all()
        )
        assert aliases and all(row.is_deleted == 1 for row in aliases)

    with session_scope(database.engine) as session:
        result = character_service.restore_character(session, cid)
        assert result["restored"] is True
        assert sorted(result["aliases_restored"]) == ["小昭", "昭儿"]

    with session_scope(database.engine) as session:
        detail = character_service.get_character_detail(session, cid)
        assert sorted(detail["aliases"]) == ["小昭", "昭儿"]


def test_restore_skips_occupied_alias(database, project_id, character_factory) -> None:
    first = character_factory("林昭")
    with session_scope(database.engine) as session:
        character_service.set_aliases(session, first, ["小昭"])
        character_service.delete_character(session, first)

    second = character_factory("沈砚")
    with session_scope(database.engine) as session:
        character_service.set_aliases(session, second, ["小昭"])

    with session_scope(database.engine) as session:
        result = character_service.restore_character(session, first)
    assert result["aliases_restored"] == []
    assert result["aliases_skipped"] == ["小昭"]


def test_force_delete_cascades_children(
    database, project_id, character_factory
) -> None:
    first = character_factory("林昭")
    second = character_factory("沈砚")
    with session_scope(database.engine) as session:
        character_service.set_aliases(session, first, ["小昭"])
        character_service.add_field(session, first, key="灵根", value="水")
        relation_service.create_character_relation(
            session, first, to_id=second, relation_type="master"
        )
        character_service.delete_character(session, first, force=True)

    with session_scope(database.engine) as session:
        assert session.get(Character, first) is None
        assert (
            session.execute(
                select(CharacterAlias).where(CharacterAlias.character_id == first)
            ).all()
            == []
        )
        assert (
            session.execute(
                select(CharacterField).where(CharacterField.character_id == first)
            ).all()
            == []
        )
        assert (
            session.execute(
                select(CharacterRelation).where(CharacterRelation.from_id == first)
            ).all()
            == []
        )


def test_require_character_states(database, project_id, character_factory) -> None:
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            character_service.require_character(session, 9999)
        _expect(exc, CODE_NOT_FOUND)

    cid = character_factory("林昭")
    with session_scope(database.engine) as session:
        character_service.delete_character(session, cid)
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            character_service.require_character(session, cid)
        _expect(exc, CODE_DELETED)
        character_service.restore_character(session, cid)
        with pytest.raises(ApiError) as exc:
            character_service.restore_character(session, cid)
        _expect(exc, CODE_PARAM_INVALID)


# --------------------------------------------------------------------------
# 自定义字段
# --------------------------------------------------------------------------


def test_field_crud_and_validation(database, project_id, character_factory) -> None:
    cid = character_factory("林昭")
    with session_scope(database.engine) as session:
        field = character_service.add_field(
            session, cid, key="灵根", value="单系水灵根", field_type="text"
        )
        fid = int(field.id)
        with pytest.raises(ApiError) as exc:
            character_service.add_field(session, cid, key="灵根")
        _expect(exc, CODE_PARAM_INVALID)

    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            character_service.add_field(
                session, cid, key="年龄", value="十六", field_type="number"
            )
        _expect(exc, CODE_PARAM_INVALID)

    with session_scope(database.engine) as session:
        updated = character_service.update_field(
            session, fid, value="12", field_type="number"
        )
        assert updated.field_type == "number"
        assert updated.value == "12"

    with session_scope(database.engine) as session:
        character_service.delete_field(session, fid)
    with session_scope(database.engine) as session:
        detail = character_service.get_character_detail(session, cid)
        assert detail["fields"] == []


def test_field_date_type(database, project_id, character_factory) -> None:
    cid = character_factory("林昭")
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            character_service.add_field(
                session, cid, key="生日", value="不是日期", field_type="date"
            )
        _expect(exc, CODE_PARAM_INVALID)
    with session_scope(database.engine) as session:
        field = character_service.add_field(
            session, cid, key="生日", value="2026-01-01", field_type="date"
        )
        assert field.value == "2026-01-01"


def test_detail_contains_relations_and_memberships(
    database, project_id, character_factory
) -> None:
    first = character_factory("林昭")
    second = character_factory("沈砚")
    with session_scope(database.engine) as session:
        relation_service.create_character_relation(
            session, first, to_id=second, relation_type="master"
        )
        detail = character_service.get_character_detail(session, first)
    assert detail["relations"][0]["other_name"] == "沈砚"
    assert detail["relations"][0]["relation_label"] == "师徒"
    assert detail["memberships"] == []


def test_meta_payload_covers_all_enums() -> None:
    """#54 元数据：枚举数量与字段契约（V3.0 的 AI 输出依赖这些 key）。"""
    from backend.services import character_meta

    payload = character_meta.meta_payload()
    assert len(payload["roles"]) == 6
    assert len(payload["statuses"]) == 4
    assert len(payload["relation_types"]) == 20
    assert len(payload["field_types"]) == 4
    assert len(payload["organization_kinds"]) == 6
    assert len(payload["organization_relation_types"]) == 5
    assert len(payload["faction_relation_types"]) == 4
    assert payload["character_field_labels"]["note"] == "备注"
    assert payload["character_field_labels"]["height"] == "身高"
    master = next(
        item for item in payload["relation_types"] if item["value"] == "master"
    )
    assert master["label"] == "师徒"
    assert master["default_bidirectional"] == 0
