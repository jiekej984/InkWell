"""任务 2.5 测试：字数统计（BR-1）与 #43 重算字数长任务。

覆盖：CJK 逐字 / 西文按词 / 标点与 emoji 开关、HTML 去标签、重算任务提交与轮询、
项目总字数汇总、长任务互斥（409 + 3004）。
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER
from backend.models import Chapter, Project, Volume, session_scope
from backend.services.wordcount import count_html, count_words, extract_text


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


@pytest.fixture
def project_id(client, config) -> int:
    response = client.post(
        "/api/projects", json={"title": "字数测试"}, headers=_headers(config)
    )
    assert response.json()["code"] == 0
    return response.json()["data"]["id"]


def _default_volume(client, config, pid: int) -> int:
    body = client.get(f"/api/projects/{pid}/volumes", headers=_headers(config)).json()
    return body["data"]["default_volume"]["id"]


def _create_chapter(client, config, vid: int, title: str) -> int:
    body = client.post(
        f"/api/volumes/{vid}/chapters",
        json={"title": title},
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body
    return body["data"]["id"]


def _wait_task(client, config, tid: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/tasks/{tid}", headers=_headers(config)).json()
        data = body["data"]
        if data["state"] in ("success", "failed"):
            return data
        time.sleep(0.02)
    raise AssertionError("长任务未在超时内结束")


# --------------------------------------------------------------------------
# 纯函数（BR-1）
# --------------------------------------------------------------------------


def test_cjk_counted_per_character() -> None:
    assert count_words("这是一段中文") == 6
    assert count_words("𠀀") == 1  # CJK 扩展 B


def test_western_counted_per_word() -> None:
    assert count_words("hello world") == 2
    assert count_words("don't stop well-known") == 3
    assert count_words("第2026章") == 3  # 两个 CJK + 一个数字词


def test_mixed_counts_cjk_words_and_punctuation() -> None:
    assert count_words("中文 hello，世界！") == 7
    assert count_words("中文 hello，世界！", count_punctuation=False) == 5


def test_emoji_counted_as_symbol() -> None:
    assert count_words("😀") == 1
    assert count_words("你好😀！") == 4
    assert count_words("你好😀！", count_punctuation=False) == 2


def test_whitespace_not_counted() -> None:
    assert count_words("   \n\t  ") == 0


def test_empty_inputs() -> None:
    assert count_words("") == 0
    assert count_words(None) == 0
    assert extract_text(None) == ""
    assert extract_text("") == ""


# --------------------------------------------------------------------------
# HTML → 纯文本
# --------------------------------------------------------------------------


def test_extract_text_keeps_paragraphs() -> None:
    text = extract_text("<p>第一段</p><p>第二段</p>")
    assert text == "第一段\n\n第二段"
    assert count_words(text) == 6


def test_extract_text_skips_script_and_style() -> None:
    html = "<p>正文</p><script>alert(1)</script><style>.a{color:red}</style>"
    assert extract_text(html) == "正文"


def test_extract_text_handles_entities_and_br() -> None:
    assert extract_text("a&amp;b<br>c") == "a&b\nc"


def test_count_html_returns_plain_and_count() -> None:
    plain, count = count_html("<p>你好 world</p>")
    assert plain == "你好 world"
    assert count == 3  # 2 个 CJK + 1 个西文词


def test_quill_like_html() -> None:
    html = (
        "<h1>第一章</h1><p><strong>加粗</strong>与<em>斜体</em></p>"
        "<ul><li>列表项</li></ul><blockquote>引用</blockquote>"
    )
    plain = extract_text(html)
    assert "第一章" in plain
    assert "加粗" in plain
    assert "<" not in plain
    assert (
        count_words(plain) == 13
    )  # 第一章 3 + 加粗 2 + 与 1 + 斜体 2 + 列表项 3 + 引用 2


# --------------------------------------------------------------------------
# #43 重算字数
# --------------------------------------------------------------------------


def test_rebuild_wordcount_updates_chapters_and_project(
    client, config, database, project_id
) -> None:
    vid = _default_volume(client, config, project_id)
    chapter_id = _create_chapter(client, config, vid, "第一章")

    with session_scope(database.engine) as session:
        chapter = session.get(Chapter, chapter_id)
        chapter.content = "<p>你好世界</p><p>hello world</p>"
        chapter.word_count = 0
        chapter.content_text = None

    response = client.post(
        "/api/maintenance/rebuild-wordcount", headers=_headers(config)
    )
    body = response.json()
    assert body["code"] == 0, body
    task = _wait_task(client, config, body["data"]["tid"])
    assert task["state"] == "success", task
    assert task["result"]["chapters"] == 1
    assert task["result"]["changed"] == 1

    with session_scope(database.engine) as session:
        chapter = session.get(Chapter, chapter_id)
        assert chapter.content_text == "你好世界\n\nhello world"
        assert chapter.word_count == 6
        project = session.get(Project, project_id)
        assert project.total_word_count == 6


def test_rebuild_wordcount_requires_token(client) -> None:
    response = client.post("/api/maintenance/rebuild-wordcount")
    assert response.status_code == 401
    assert response.json()["code"] == 1002


def test_rebuild_wordcount_returns_409_when_task_running(client, config) -> None:
    """S2-03：互斥，第二个长任务立即 409 + 3004（不排队）。"""
    tasks = client.app.state.tasks
    gate = threading.Event()
    tasks.submit("blocking", lambda report: gate.wait(5))
    try:
        response = client.post(
            "/api/maintenance/rebuild-wordcount", headers=_headers(config)
        )
        assert response.status_code == 409
        assert response.json()["code"] == 3004
    finally:
        gate.set()


def test_rebuild_wordcount_ignores_soft_deleted_chapters(
    client, config, database, project_id
) -> None:
    vid = _default_volume(client, config, project_id)
    kept = _create_chapter(client, config, vid, "保留")
    removed = _create_chapter(client, config, vid, "已删除")

    with session_scope(database.engine) as session:
        session.get(Chapter, kept).content = "<p>保留章节</p>"
        deleted = session.get(Chapter, removed)
        deleted.content = "<p>已删除章节</p>"
        deleted.is_deleted = 1

    body = client.post(
        "/api/maintenance/rebuild-wordcount", headers=_headers(config)
    ).json()
    task = _wait_task(client, config, body["data"]["tid"])
    assert task["state"] == "success", task

    with session_scope(database.engine) as session:
        assert session.get(Chapter, kept).word_count == 4
        # 软删除章节保留原值（0），恢复后由下一次重算修正
        assert session.get(Chapter, removed).word_count == 0
        assert session.get(Project, project_id).total_word_count == 4
        # 卷统计同样只计活跃章节
        assert session.get(Volume, vid).is_deleted == 0
        assert (
            len(
                session.execute(select(Chapter).where(Chapter.volume_id == vid))
                .scalars()
                .all()
            )
            == 2
        )
