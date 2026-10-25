"""立场 / 组织 / 成员测试（V2.0 / 5.2 / 回归 33~34）。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.models import Organization, OrgMember, session_scope
from backend.schemas import CODE_DELETED, CODE_PARAM_INVALID, ApiError
from backend.services import character_service, faction_service, organization_service


def _expect(exc_info, code: int) -> None:
    assert exc_info.value.code == code, exc_info.value.message


def _faction(database, project_id: int, name: str = "正道", **fields) -> int:
    with session_scope(database.engine) as session:
        row = faction_service.create_faction(session, project_id, name=name, **fields)
        return int(row.id)


def _org(database, project_id: int, name: str, **fields) -> int:
    with session_scope(database.engine) as session:
        row = organization_service.create_organization(
            session, project_id, name=name, **fields
        )
        return int(row.id)


# --------------------------------------------------------------------------
# 立场
# --------------------------------------------------------------------------


def test_faction_crud_and_org_count(database, project_id) -> None:
    fid = _faction(database, project_id, "正道", color="#3B6EA5")
    _org(database, project_id, "青云宗", faction_id=fid)

    with session_scope(database.engine) as session:
        payload = faction_service.list_factions(session, project_id)
        assert payload["total"] == 1
        assert payload["items"][0]["organization_count"] == 1
        assert payload["items"][0]["color"] == "#3b6ea5"

    with session_scope(database.engine) as session:
        updated = faction_service.update_faction(session, fid, name="正道盟")
        assert updated.name == "正道盟"


def test_faction_count_includes_inherited_orgs(database, project_id) -> None:
    """阵营卡片的组织数按「继承后的有效立场」统计，与按阵营筛选结果一致。"""
    fid = _faction(database, project_id, "正道")
    root = _org(database, project_id, "青云宗", faction_id=fid)
    _org(database, project_id, "剑峰", parent_id=root)
    _org(database, project_id, "药庐", parent_id=root)

    with session_scope(database.engine) as session:
        payload = faction_service.list_factions(session, project_id)
        assert payload["items"][0]["organization_count"] == 3


def test_faction_delete_guard(database, project_id) -> None:
    fid = _faction(database, project_id)
    _org(database, project_id, "青云宗", faction_id=fid)
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            faction_service.delete_faction(session, fid)
        _expect(exc, CODE_PARAM_INVALID)
        assert "请先迁移" in exc.value.message


def test_faction_restore(database, project_id) -> None:
    fid = _faction(database, project_id)
    with session_scope(database.engine) as session:
        faction_service.delete_faction(session, fid)
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            faction_service.require_faction(session, fid)
        _expect(exc, CODE_DELETED)
    with session_scope(database.engine) as session:
        assert faction_service.restore_faction(session, fid)["restored"] is True


def test_faction_relation_crud(database, project_id) -> None:
    right = _faction(database, project_id, "正道")
    evil = _faction(database, project_id, "魔道")

    with session_scope(database.engine) as session:
        row = faction_service.create_faction_relation(
            session,
            project_id,
            from_id=right,
            to_id=evil,
            relation_type="enemy",
        )
        rid = int(row.id)
        assert row.is_bidirectional == 1
        with pytest.raises(ApiError) as exc:
            faction_service.create_faction_relation(
                session,
                project_id,
                from_id=right,
                to_id=evil,
                relation_type="enemy",
            )
        _expect(exc, CODE_PARAM_INVALID)
        with pytest.raises(ApiError) as exc:
            faction_service.create_faction_relation(
                session,
                project_id,
                from_id=right,
                to_id=right,
            )
        _expect(exc, CODE_PARAM_INVALID)

    with session_scope(database.engine) as session:
        payload = faction_service.list_faction_relations(session, project_id)
        assert payload["total"] == 1
        assert payload["items"][0]["relation_label"] == "敌对"
        faction_service.delete_faction_relation(session, rid)


# --------------------------------------------------------------------------
# 组织树与立场继承
# --------------------------------------------------------------------------


def test_organization_tree_and_inherited_faction(database, project_id) -> None:
    fid = _faction(database, project_id, "正道")
    root = _org(database, project_id, "青云宗", faction_id=fid)
    peak = _org(database, project_id, "剑峰", parent_id=root)
    hall = _org(database, project_id, "剑堂", parent_id=peak)

    with session_scope(database.engine) as session:
        payload = organization_service.list_organizations(
            session, project_id, tree=True
        )
        assert payload["total"] == 3
        assert len(payload["items"]) == 1
        assert payload["items"][0]["name"] == "青云宗"
        child = payload["items"][0]["children"][0]
        assert child["name"] == "剑峰"
        assert child["children"][0]["name"] == "剑堂"
        # 立场继承：剑堂自己没有 faction_id，向上取到青云宗的正道
        assert child["children"][0]["effective_faction_id"] == fid

    with session_scope(database.engine) as session:
        filtered = organization_service.list_organizations(
            session, project_id, faction_id=fid
        )
        assert filtered["total"] == 3
        subtree = organization_service.collect_subtree_ids(session, project_id, root)
        assert set(subtree) == {root, peak, hall}


def test_cycle_rejected(database, project_id) -> None:
    root = _org(database, project_id, "青云宗")
    peak = _org(database, project_id, "剑峰", parent_id=root)

    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            organization_service.update_organization(session, root, parent_id=peak)
        _expect(exc, CODE_PARAM_INVALID)
        assert "子孙" in exc.value.message

    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            organization_service.update_organization(session, peak, parent_id=peak)
        _expect(exc, CODE_PARAM_INVALID)


# --------------------------------------------------------------------------
# 成员
# --------------------------------------------------------------------------


def test_member_primary_unique(database, project_id, character_factory) -> None:
    cid = character_factory("林昭")
    first = _org(database, project_id, "青云宗")
    second = _org(database, project_id, "血月教")

    with session_scope(database.engine) as session:
        organization_service.add_member(
            session, first, character_id=cid, position="弟子", is_primary=True
        )
        organization_service.add_member(
            session, second, character_id=cid, position="卧底", is_secret=True
        )
        rows = (
            session.execute(select(OrgMember).where(OrgMember.character_id == cid))
            .scalars()
            .all()
        )
        assert len(rows) == 2
        assert sum(row.is_primary for row in rows) == 1

    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            organization_service.add_member(session, first, character_id=cid)
        _expect(exc, CODE_PARAM_INVALID)
        assert "已在" in exc.value.message


def test_member_chapter_range(
    database, project_id, chapter_factory, character_factory
) -> None:
    cid = character_factory("林昭")
    org = _org(database, project_id, "青云宗")
    _, early = chapter_factory(volume_order=1000, chapter_order=1000)
    _, late = chapter_factory(volume_order=1000, chapter_order=2000)

    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            organization_service.add_member(
                session,
                org,
                character_id=cid,
                from_chapter_id=late,
                to_chapter_id=early,
            )
        _expect(exc, CODE_PARAM_INVALID)

    with session_scope(database.engine) as session:
        member = organization_service.add_member(
            session,
            org,
            character_id=cid,
            from_chapter_id=early,
            to_chapter_id=late,
        )
        assert member.from_chapter_id == early
        assert member.to_chapter_id == late


# --------------------------------------------------------------------------
# 删除策略
# --------------------------------------------------------------------------


def test_member_single_ended_chapter_must_exist_in_project(
    database, project_id, chapter_factory, character_factory
) -> None:
    """只给一端时也要校验：别书章节 / 悬空 id 都必须是 1001。"""
    cid = character_factory("林昭")
    org = _org(database, project_id, "青云宗")
    _, own = chapter_factory(volume_order=1000, chapter_order=1000)

    with session_scope(database.engine) as session:
        member = organization_service.add_member(
            session, org, character_id=cid, from_chapter_id=own
        )
        assert member.from_chapter_id == own

    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            organization_service.add_member(
                session, org, character_id=cid, from_chapter_id=999999
            )
        _expect(exc, CODE_PARAM_INVALID)

    # 另一本书的章节 id 同样不允许
    from backend.services import chapter_service, project_service

    with session_scope(database.engine) as session:
        other = project_service.create_project(session, title="别书")
        session.flush()
        foreign_volume = chapter_service.list_volume_tree(session, other.id)[
            "default_volume"
        ]["id"]
        foreign = int(
            chapter_service.create_chapter(
                session, foreign_volume, title="别章"
            ).id
        )
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            organization_service.add_member(
                session, org, character_id=cid, from_chapter_id=foreign
            )
        _expect(exc, CODE_PARAM_INVALID)


def test_delete_cascade(database, project_id, character_factory) -> None:
    cid = character_factory("林昭")
    root = _org(database, project_id, "青云宗")
    peak = _org(database, project_id, "剑峰", parent_id=root)
    with session_scope(database.engine) as session:
        organization_service.add_member(session, peak, character_id=cid)

    with session_scope(database.engine) as session:
        result = organization_service.delete_organization(
            session, root, strategy="cascade"
        )
        assert result["organizations_deleted"] == 2
        assert result["members_deleted"] == 1

    with session_scope(database.engine) as session:
        assert (
            organization_service.list_organizations(session, project_id)["total"] == 0
        )
        rows = session.execute(select(OrgMember)).scalars().all()
        assert all(row.is_deleted == 1 for row in rows)


def test_delete_promote_moves_children_and_members(
    database, project_id, character_factory
) -> None:
    cid = character_factory("林昭")
    root = _org(database, project_id, "青云宗")
    peak = _org(database, project_id, "剑峰", parent_id=root)
    with session_scope(database.engine) as session:
        organization_service.add_member(session, peak, character_id=cid)

    with session_scope(database.engine) as session:
        result = organization_service.delete_organization(
            session, peak, strategy="promote"
        )
        assert result["members_moved"] == 1

    with session_scope(database.engine) as session:
        member = session.execute(select(OrgMember)).scalars().one()
        assert member.org_id == root
        assert member.is_deleted == 0
        assert session.get(Organization, peak).is_deleted == 1


def test_delete_root_promote_rejected(database, project_id) -> None:
    root = _org(database, project_id, "青云宗")
    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            organization_service.delete_organization(session, root, strategy="promote")
        _expect(exc, CODE_PARAM_INVALID)
        assert "顶层组织" in exc.value.message


def test_promote_rejects_member_conflict(
    database, project_id, character_factory
) -> None:
    cid = character_factory("林昭")
    root = _org(database, project_id, "青云宗")
    peak = _org(database, project_id, "剑峰", parent_id=root)
    with session_scope(database.engine) as session:
        organization_service.add_member(session, root, character_id=cid)
        organization_service.add_member(session, peak, character_id=cid)

    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            organization_service.delete_organization(session, peak, strategy="promote")
        _expect(exc, CODE_PARAM_INVALID)
        assert "已有身份" in exc.value.message


def test_promote_ignores_grandchild_members(
    database, project_id, character_factory
) -> None:
    """回归：上移只检查**直属成员**，孙子组织里的人不算冲突。

    曾经的 bug：``member_rows`` 取的是整棵子树，导致「孙组织成员同时也在父组织」
    时被误判为冲突、整次删除失败。
    """
    cid = character_factory("林昭")
    root = _org(database, project_id, "青云宗")
    peak = _org(database, project_id, "剑峰", parent_id=root)
    hall = _org(database, project_id, "剑堂", parent_id=peak)
    with session_scope(database.engine) as session:
        organization_service.add_member(session, root, character_id=cid)
        organization_service.add_member(session, hall, character_id=cid)

    with session_scope(database.engine) as session:
        result = organization_service.delete_organization(
            session, peak, strategy="promote"
        )
        assert result["members_moved"] == 0

    with session_scope(database.engine) as session:
        hall_row = session.get(Organization, hall)
        assert hall_row.parent_id == root
        assert hall_row.is_deleted == 0


def test_restore_recursive(database, project_id, character_factory) -> None:
    cid = character_factory("林昭")
    root = _org(database, project_id, "青云宗")
    peak = _org(database, project_id, "剑峰", parent_id=root)
    with session_scope(database.engine) as session:
        organization_service.add_member(session, peak, character_id=cid)
        organization_service.delete_organization(session, root)

    with session_scope(database.engine) as session:
        result = organization_service.restore_organization(session, root)
        assert result["organizations_restored"] == 2
        assert result["members_restored"] == 1

    with session_scope(database.engine) as session:
        payload = organization_service.list_organizations(
            session, project_id, tree=True
        )
        assert payload["total"] == 2
        assert payload["items"][0]["children"][0]["name"] == "剑峰"


def test_restore_empty_organization_does_not_revive_old_removed_member(
    database, project_id, character_factory
) -> None:
    """组织删除时若已没有在职成员，恢复也不能把更早手动移除的人带回来。"""
    cid = character_factory("顾长庚")
    org_id = _org(database, project_id, "归雁门")
    with session_scope(database.engine) as session:
        member = organization_service.add_member(session, org_id, character_id=cid)
        member_id = int(member.id)
        organization_service.remove_member(session, member_id)
        manually_removed_at = member.deleted_at

    with session_scope(database.engine) as session:
        organization_service.delete_organization(session, org_id, strategy="cascade")

    with session_scope(database.engine) as session:
        restored = organization_service.restore_organization(session, org_id)
        member = session.get(OrgMember, member_id)
        assert restored["members_restored"] == 0
        assert member.is_deleted == 1
        assert member.deleted_at == manually_removed_at


# --------------------------------------------------------------------------
# 组织关系
# --------------------------------------------------------------------------


def test_org_relation_crud(database, project_id) -> None:
    first = _org(database, project_id, "青云宗")
    second = _org(database, project_id, "血月教")

    with session_scope(database.engine) as session:
        with pytest.raises(ApiError) as exc:
            organization_service.create_org_relation(
                session, project_id, from_id=first, to_id=first
            )
        _expect(exc, CODE_PARAM_INVALID)

        row = organization_service.create_org_relation(
            session,
            project_id,
            from_id=first,
            to_id=second,
            relation_type="war",
        )
        rid = int(row.id)
        with pytest.raises(ApiError) as exc:
            organization_service.create_org_relation(
                session,
                project_id,
                from_id=first,
                to_id=second,
                relation_type="war",
            )
        _expect(exc, CODE_PARAM_INVALID)

    with session_scope(database.engine) as session:
        payload = organization_service.list_org_relations(session, project_id)
        assert payload["items"][0]["relation_label"] == "战争"
        organization_service.delete_org_relation(session, rid)
    with session_scope(database.engine) as session:
        assert (
            organization_service.list_org_relations(session, project_id)["total"] == 0
        )


def test_org_list_reports_member_count(database, project_id, character_factory) -> None:
    first = character_factory("林昭")
    second = character_factory("沈砚")
    org = _org(database, project_id, "青云宗")
    with session_scope(database.engine) as session:
        organization_service.add_member(session, org, character_id=first)
        organization_service.add_member(session, org, character_id=second)
        payload = organization_service.list_organizations(session, project_id)
    assert payload["items"][0]["member_count"] == 2


def test_character_org_filter_uses_subtree(
    database, project_id, character_factory
) -> None:
    cid = character_factory("林昭")
    root = _org(database, project_id, "青云宗")
    peak = _org(database, project_id, "剑峰", parent_id=root)
    with session_scope(database.engine) as session:
        organization_service.add_member(session, peak, character_id=cid)
        payload = character_service.list_characters(session, project_id, org_id=root)
        assert [item["id"] for item in payload["items"]] == [cid]


def test_get_organization_detail(database, project_id, character_factory) -> None:
    fid = _faction(database, project_id, "正道")
    cid = character_factory("沈砚")
    root = _org(database, project_id, "青云宗", faction_id=fid, leader_id=cid)
    _org(database, project_id, "剑峰", parent_id=root)
    with session_scope(database.engine) as session:
        organization_service.add_member(
            session, root, character_id=cid, position="宗主"
        )
        payload = organization_service.get_organization(session, root)
    assert payload["member_count"] == 1
    assert payload["child_count"] == 1
    assert payload["effective_faction_id"] == fid
    assert payload["leader_id"] == cid


def test_member_update_and_remove(database, project_id, character_factory) -> None:
    cid = character_factory("林昭")
    org = _org(database, project_id, "青云宗")
    with session_scope(database.engine) as session:
        member = organization_service.add_member(
            session, org, character_id=cid, position="弟子", is_primary=True
        )
        mid = int(member.id)

    with session_scope(database.engine) as session:
        updated = organization_service.update_member(
            session, mid, position="长老", is_secret=True, is_primary=False
        )
        assert updated.position == "长老"
        assert updated.is_secret == 1
        assert updated.is_primary == 0

    with session_scope(database.engine) as session:
        organization_service.remove_member(session, mid)
    with session_scope(database.engine) as session:
        assert organization_service.list_members(session, org)["total"] == 0

    # 退出后可重新加入（部分唯一索引只看活跃行）
    with session_scope(database.engine) as session:
        again = organization_service.add_member(
            session, org, character_id=cid, position="客卿"
        )
        assert int(again.id) != mid
