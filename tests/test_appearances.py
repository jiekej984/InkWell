"""FR-8.23：角色姓名/别名出场检索。"""

from __future__ import annotations

from backend.models import Chapter, session_scope
from backend.services import appearance_service, character_service


def test_appearance_search_groups_name_and_alias_matches_by_story_order(
    database, project_id, character_factory, chapter_factory
) -> None:
    character_id = character_factory("林昭")
    early_volume, early_chapter = chapter_factory(
        title="初遇", volume_order=10, chapter_order=10
    )
    late_volume, late_chapter = chapter_factory(
        title="重逢", volume_order=20, chapter_order=10
    )
    _, deleted_chapter = chapter_factory(
        title="回收站章节", volume_order=30, chapter_order=10
    )
    with session_scope(database.engine) as session:
        character_service.set_aliases(session, character_id, ["小昭", "云中客"])
        session.get(Chapter, early_chapter).content_text = (
            "林昭遇到云中客，小昭转身后林昭离开。"
        )
        session.get(Chapter, late_chapter).content_text = "云中客后来又出现。"
        deleted = session.get(Chapter, deleted_chapter)
        deleted.content_text = "林昭在这章出现，但章节已删除。"
        deleted.is_deleted = 1

    with session_scope(database.engine) as session:
        data = appearance_service.search_appearances(session, character_id)

    assert data["character_name"] == "林昭"
    assert data["variants"] == ["林昭", "小昭", "云中客"]
    assert data["chapter_count"] == 2
    assert data["total_occurrences"] == 5
    assert data["first_appearance"]["chapter_id"] == early_chapter
    assert [item["chapter_id"] for item in data["items"]] == [
        early_chapter,
        late_chapter,
    ]
    assert [item["occurrences"] for item in data["items"]] == [4, 1]
    assert "<mark>林昭</mark>" in data["items"][0]["snippet"]


def test_appearance_search_returns_empty_for_character_without_mentions(
    database, character_factory
) -> None:
    character_id = character_factory("无名客")
    with session_scope(database.engine) as session:
        data = appearance_service.search_appearances(session, character_id)
    assert data["chapter_count"] == 0
    assert data["total_occurrences"] == 0
    assert data["first_appearance"] is None
    assert data["items"] == []

