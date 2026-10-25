"""任务 2.11 测试：全文检索（#31）与 #42 重建索引。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER
from backend.services import search_service


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


def _wait_task(client, config, tid: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/tasks/{tid}", headers=_headers(config)).json()["data"]
        if data["state"] in ("success", "failed"):
            return data
        time.sleep(0.02)
    raise AssertionError("任务未在超时内结束")


def _create_project(client, config, title: str) -> int:
    body = client.post(
        "/api/projects", json={"title": title}, headers=_headers(config)
    ).json()
    assert body["code"] == 0, body
    return body["data"]["id"]


def _default_volume(client, config, pid: int) -> int:
    return client.get(f"/api/projects/{pid}/volumes", headers=_headers(config)).json()[
        "data"
    ]["default_volume"]["id"]


def _create_chapter(client, config, pid: int, title: str, text: str) -> int:
    chapter = client.post(
        f"/api/volumes/{_default_volume(client, config, pid)}/chapters",
        json={"title": title},
        headers=_headers(config),
    ).json()["data"]
    client.put(
        f"/api/chapters/{chapter['id']}/content",
        json={"content_html": f"<p>{text}</p>"},
        headers=_headers(config),
    )
    return chapter["id"]


def _create_document(client, config, pid: int, title: str, text: str) -> int:
    return client.post(
        f"/api/projects/{pid}/documents",
        json={"title": title, "category": "world", "content_html": f"<p>{text}</p>"},
        headers=_headers(config),
    ).json()["data"]["id"]


def _search(client, config, **params) -> dict:
    response = client.get("/api/search", params=params, headers=_headers(config)).json()
    assert response["code"] == 0, response
    return response["data"]


def _bulk_chapters(client, config, pid: int, count: int) -> list[int]:
    """在默认卷批量建章（正文长度递增，避免 bm25 并列导致分页顺序不定）。"""
    volume = _default_volume(client, config, pid)
    ids = []
    for index in range(count):
        chapter = client.post(
            f"/api/volumes/{volume}/chapters",
            json={"title": f"第{index}章"},
            headers=_headers(config),
        ).json()["data"]
        client.put(
            f"/api/chapters/{chapter['id']}/content",
            json={"content_html": f"<p>黑水河{'水' * index}第{index}段</p>"},
            headers=_headers(config),
        )
        ids.append(chapter["id"])
    return ids


@pytest.fixture
def corpus(client, config) -> dict[str, int]:
    a = _create_project(client, config, "项目甲")
    _create_chapter(client, config, a, "黑水河记事", "少年在黑水河畔长大")
    _create_document(client, config, a, "世界观", "黑水河横贯大陆")
    b = _create_project(client, config, "项目乙")
    _create_chapter(client, config, b, "另一章", "这里也写黑水河")
    return {"a": a, "b": b}


def test_search_all_sources(client, config, corpus) -> None:
    data = _search(client, config, q="黑水河")
    assert data["total"] == 3
    types = {item["type"] for item in data["items"]}
    assert types == {"chapter", "document"}
    snippets = " ".join(item["snippet"] for item in data["items"])
    assert "<mark>黑水河</mark>" in snippets
    assert data["hint"] == ""


def test_search_scope_filters(client, config, corpus) -> None:
    chapters = _search(client, config, q="黑水河", scope="chapters")
    assert chapters["total"] == 2
    assert {item["type"] for item in chapters["items"]} == {"chapter"}

    documents = _search(client, config, q="黑水河", scope="documents")
    assert documents["total"] == 1
    assert documents["items"][0]["type"] == "document"
    assert documents["items"][0]["category_label"] == "世界观"


def test_search_project_filter(client, config, corpus) -> None:
    only_a = _search(client, config, q="黑水河", project_id=corpus["a"])
    assert only_a["total"] == 2
    assert all(item["project_id"] == corpus["a"] for item in only_a["items"])

    only_b = _search(client, config, q="黑水河", project_id=corpus["b"])
    assert only_b["total"] == 1
    assert only_b["items"][0]["project_id"] == corpus["b"]


def test_short_query_falls_back_to_like(client, config, corpus) -> None:
    data = _search(client, config, q="黑水")
    assert data["hint"], "少于 3 字符应提示已降级为模糊匹配"
    assert data["total"] == 3
    assert "<mark>黑水</mark>" in " ".join(item["snippet"] for item in data["items"])


def test_search_pagination(client, config, corpus) -> None:
    first = _search(client, config, q="黑水河", page=1, page_size=1)
    second = _search(client, config, q="黑水河", page=2, page_size=1)
    assert first["total"] == 3
    assert len(first["items"]) == 1
    assert len(second["items"]) == 1
    assert first["items"][0]["id"] != second["items"][0]["id"]


def test_search_deep_page_returns_last_window(client, config) -> None:
    """回归：120 条命中时第 6 页（第 101~120 条）不能被窗口截成空页。"""
    pid = _create_project(client, config, "深页")
    _bulk_chapters(client, config, pid, 120)

    first = _search(
        client,
        config,
        q="黑水河",
        project_id=pid,
        scope="chapters",
        page=1,
        page_size=20,
    )
    last = _search(
        client,
        config,
        q="黑水河",
        project_id=pid,
        scope="chapters",
        page=6,
        page_size=20,
    )

    assert first["total"] == 120
    assert last["total"] == 120
    assert last["page_limited"] is False
    assert len(last["items"]) == 20
    first_ids = {item["id"] for item in first["items"]}
    last_ids = {item["id"] for item in last["items"]}
    assert first_ids.isdisjoint(last_ids)


def test_search_page_beyond_window_is_flagged(client, config, monkeypatch) -> None:
    """窗口被单侧上限截断时必须显式告知，而不是静默返回空页。"""
    pid = _create_project(client, config, "窗口上限")
    _bulk_chapters(client, config, pid, 12)
    monkeypatch.setattr(search_service, "MAX_PER_SIDE", 10)

    first = _search(
        client,
        config,
        q="黑水河",
        project_id=pid,
        scope="chapters",
        page=1,
        page_size=10,
    )
    beyond = _search(
        client,
        config,
        q="黑水河",
        project_id=pid,
        scope="chapters",
        page=2,
        page_size=10,
    )

    assert first["page_limited"] is False
    assert len(first["items"]) == 10
    assert beyond["total"] == 12
    assert beyond["page_limited"] is True
    assert "加长搜索词" in beyond["hint"]
    assert beyond["items"] == []


def test_search_excludes_deleted(client, config, corpus) -> None:
    chapters = _search(client, config, q="黑水河", scope="chapters")
    chapter_id = chapters["items"][0]["id"]
    client.delete(f"/api/chapters/{chapter_id}", headers=_headers(config))

    after = _search(client, config, q="黑水河", scope="chapters")
    assert after["total"] == 1
    assert all(item["id"] != chapter_id for item in after["items"])


def test_title_only_match_is_returned(client, config) -> None:
    pid = _create_project(client, config, "标题命中")
    _create_chapter(client, config, pid, "黑水河外传", "内容完全不相关")
    data = _search(client, config, q="黑水河", project_id=pid)
    assert data["total"] == 1
    assert "黑水河" in data["items"][0]["title"]


def test_snippet_escapes_html(client, config) -> None:
    pid = _create_project(client, config, "转义")
    _create_chapter(client, config, pid, "危险内容", "&lt;b&gt;危险&lt;/b&gt;")
    data = _search(client, config, q="危险", project_id=pid)
    snippet = data["items"][0]["snippet"]
    assert "&lt;b&gt;" in snippet
    assert "<b>危险" not in snippet


def test_search_validation(client, config, corpus) -> None:
    empty = client.get("/api/search?q=", headers=_headers(config)).json()
    assert empty["code"] == 1001

    bad_scope = client.get(
        "/api/search?q=黑水河&scope=bad", headers=_headers(config)
    ).json()
    assert bad_scope["code"] == 1001

    missing_project = client.get(
        "/api/search?q=黑水河&project_id=99999", headers=_headers(config)
    ).json()
    assert missing_project["code"] == 2001

    bad_page = client.get(
        "/api/search?q=黑水河&page_size=101", headers=_headers(config)
    ).json()
    assert bad_page["code"] == 1001


def test_rebuild_fts(client, config, corpus) -> None:
    before = _search(client, config, q="黑水河")
    body = client.post("/api/maintenance/rebuild-fts", headers=_headers(config)).json()
    assert body["code"] == 0, body
    task = _wait_task(client, config, body["data"]["tid"])
    assert task["state"] == "success", task
    assert task["result"]["rebuilt"] == ["chapter_fts", "document_fts"]

    after = _search(client, config, q="黑水河")
    assert after["total"] == before["total"]
    assert {item["type"] for item in after["items"]} == {
        item["type"] for item in before["items"]
    }


def test_search_rejects_control_characters(client, config, corpus) -> None:
    body = client.get(
        "/api/search", params={"q": "黑\x00水"}, headers=_headers(config)
    ).json()
    assert body["code"] == 1001, body


def test_search_requires_token(client) -> None:
    response = client.get("/api/search", params={"q": "黑水河"})
    assert response.status_code == 401
    assert response.json()["code"] == 1002
