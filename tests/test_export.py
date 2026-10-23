"""任务 2.10 测试：导出 TXT/Markdown（#35，长任务）。"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER

# AC-6 样本：中文 + 英文 + 数字 + 标点 + HTML 实体 + emoji，覆盖 BR-1 各计数分支
MIXED_SAMPLES = [
    ("第一章", "<p>深夜的码头，海风带着咸味。她低声说：“走吧。”</p>"),
    (
        "Chapter Two",
        "<p>Hello world! This is 2026 年的 first draft——别问为什么。</p>",
    ),
    ("Emoji", "<p>表情 😀🎉 与符号 ©®™ 也算字符；省略号……破折号——</p>"),
    (
        "Mixed",
        "<p>第二段<br>换行之后 <em>斜体</em> 与 <strong>粗体</strong> 都要保留。</p>",
    ),
]


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2FA1F
    )


_WORD_RUN = re.compile(r"[A-Za-z0-9]+(?:[._'’\-][A-Za-z0-9]+)*")


def reference_word_count(text: str) -> int:
    """独立于 ``backend.services.wordcount`` 的参考计数（BR-1 口径）。

    刻意不调用被测实现：CJK 逐字 + 西文按词 + 其余非空白字符（标点/符号/emoji）各计 1。
    """
    cjk = 0
    rest: list[str] = []
    for char in text:
        if _is_cjk(char):
            cjk += 1
            rest.append(" ")
        else:
            rest.append(char)
    remainder = "".join(rest)
    return (
        cjk
        + len(_WORD_RUN.findall(remainder))
        + sum(
            1
            for char in _WORD_RUN.sub("", remainder)
            if not char.isspace() and not char.isalnum()
        )
    )


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


def _wait_task(client, config, tid: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/tasks/{tid}", headers=_headers(config)).json()["data"]
        if data["state"] in ("success", "failed"):
            return data
        time.sleep(0.02)
    raise AssertionError("导出任务未在超时内结束")


def _create_project(client, config, title: str = "导出测试") -> int:
    body = client.post(
        "/api/projects", json={"title": title}, headers=_headers(config)
    ).json()
    assert body["code"] == 0, body
    return body["data"]["id"]


def _default_volume(client, config, pid: int) -> int:
    return client.get(f"/api/projects/{pid}/volumes", headers=_headers(config)).json()[
        "data"
    ]["default_volume"]["id"]


def _create_volume(client, config, pid: int, title: str) -> int:
    return client.post(
        f"/api/projects/{pid}/volumes",
        json={"title": title},
        headers=_headers(config),
    ).json()["data"]["id"]


def _create_chapter(client, config, vid: int, title: str, text: str) -> int:
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


def _export(client, config, pid: int, fmt: str) -> dict:
    body = client.post(
        f"/api/projects/{pid}/export",
        json={"format": fmt},
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body
    task = _wait_task(client, config, body["data"]["tid"])
    assert task["state"] == "success", task
    return task["result"]


def _mixed_project(client, config) -> tuple[int, list[tuple[str, str, int]]]:
    """建含中英混排 / 标点 / emoji 的项目，返回 [(章标题, content_text, 库内字数)]。"""
    pid = _create_project(client, config, "混排之书")
    client.patch(
        f"/api/projects/{pid}",
        json={"description": "AC-6 混排样本"},
        headers=_headers(config),
    )
    volume = _default_volume(client, config, pid)
    chapters: list[tuple[str, str, int]] = []
    for title, html in MIXED_SAMPLES:
        chapter = client.post(
            f"/api/volumes/{volume}/chapters",
            json={"title": title},
            headers=_headers(config),
        ).json()["data"]
        saved = client.put(
            f"/api/chapters/{chapter['id']}/content",
            json={"content_html": html},
            headers=_headers(config),
        ).json()
        assert saved["code"] == 0, saved
        detail = client.get(
            f"/api/chapters/{chapter['id']}", headers=_headers(config)
        ).json()["data"]
        chapters.append((title, detail["content_text"] or "", detail["word_count"]))
    return pid, chapters


def test_export_txt_with_volumes_and_chapters(client, config) -> None:
    pid = _create_project(client, config, "测试之书")
    client.patch(
        f"/api/projects/{pid}",
        json={"description": "这是一本测试书"},
        headers=_headers(config),
    )
    volume = _create_volume(client, config, pid, "第一卷")
    _create_chapter(client, config, volume, "第一章", "阿尔法")
    _create_chapter(client, config, volume, "第二章", "贝塔")

    result = _export(client, config, pid, "txt")
    assert result["format"] == "txt"
    assert result["chapters"] == 2
    assert result["word_count"] == 5
    assert result["exported_chapters"] == 2
    assert result["relpath"].startswith("exports/")

    path = config.data_dir / result["relpath"]
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "测试之书" in text
    assert "这是一本测试书" in text
    assert "第一卷" in text
    assert "第一章" in text and "阿尔法" in text
    assert text.index("阿尔法") < text.index("贝塔")
    # BR-7：不留半截 *.tmp
    assert not list((config.data_dir / "exports").glob("*.tmp"))


def test_export_markdown_structure(client, config) -> None:
    pid = _create_project(client, config, "Markdown 之书")
    client.patch(
        f"/api/projects/{pid}",
        json={"description": "简介一行"},
        headers=_headers(config),
    )
    volume = _create_volume(client, config, pid, "上卷")
    _create_chapter(client, config, volume, "开篇", "正文一段")

    result = _export(client, config, pid, "md")
    text = (config.data_dir / result["relpath"]).read_text(encoding="utf-8")
    assert text.startswith("# Markdown 之书")
    assert "> 简介一行" in text
    assert "## 上卷" in text
    assert "### 开篇" in text
    assert "正文一段" in text


def test_export_empty_project(client, config) -> None:
    pid = _create_project(client, config, "空书")

    txt = _export(client, config, pid, "txt")
    assert txt["empty"] is True
    assert txt["chapters"] == 0
    text = (config.data_dir / txt["relpath"]).read_text(encoding="utf-8")
    assert "空书" in text
    assert "（暂无正文）" in text

    md = _export(client, config, pid, "md")
    md_text = (config.data_dir / md["relpath"]).read_text(encoding="utf-8")
    assert "# 空书" in md_text
    assert "## 目录" in md_text
    assert "（暂无章节）" in md_text


def test_export_default_volume_has_no_heading(client, config) -> None:
    pid = _create_project(client, config, "未分卷")
    _create_chapter(
        client, config, _default_volume(client, config, pid), "第一章", "甲"
    )

    result = _export(client, config, pid, "txt")
    text = (config.data_dir / result["relpath"]).read_text(encoding="utf-8")
    assert "默认卷" not in text
    assert "第一章" in text


def test_export_sanitizes_filename(client, config) -> None:
    pid = _create_project(client, config, "书名/带*非法?字符")
    result = _export(client, config, pid, "txt")
    name = result["filename"]
    for illegal in ("/", "*", "?", "\\", ":", '"', "<", ">", "|"):
        assert illegal not in name
    assert name.endswith(".txt")


def test_export_invalid_format_and_missing_project(client, config) -> None:
    pid = _create_project(client, config, "格式测试")
    bad = client.post(
        f"/api/projects/{pid}/export",
        json={"format": "pdf"},
        headers=_headers(config),
    ).json()
    assert bad["code"] == 1001

    missing = client.post(
        "/api/projects/99999/export",
        json={"format": "txt"},
        headers=_headers(config),
    ).json()
    assert missing["code"] == 2001


def test_export_requires_token(client, config) -> None:
    pid = _create_project(client, config, "鉴权")
    response = client.post(f"/api/projects/{pid}/export", json={"format": "txt"})
    assert response.status_code == 401
    assert response.json()["code"] == 1002


def test_export_txt_body_matches_content_text_and_wordcount(client, config) -> None:
    """AC-6：TXT 正文与库内 ``content_text`` 逐字一致，字数误差 ≤0.5%。"""
    pid, chapters = _mixed_project(client, config)
    # 样本身足够长：1 字误差即 >0.5%，断言才有意义
    assert sum(len(text) for _, text, _ in chapters) >= 80

    result = _export(client, config, pid, "txt")
    exported = (config.data_dir / result["relpath"]).read_text(encoding="utf-8")

    # 每章标题 + 空行 + 正文必须与库内 content_text 逐字一致
    for title, text, _ in chapters:
        assert f"{title}\n\n{text}" in exported, f"导出正文与库内不一致：{title}"

    exported_body = "\n\n".join(text for _, text, _ in chapters)
    measured = reference_word_count(exported_body)
    reported = result["word_count"]
    error = abs(reported - measured) / max(measured, 1)
    assert error <= 0.005, (
        f"AC-6 字数误差 {error:.4%} 超过 0.5%"
        f"（导出正文 {measured} 字 / 统计 {reported} 字）"
    )
    assert reported == sum(words for _, _, words in chapters)

    # 富文本不得泄漏标签；标点与 emoji 必须原样保留
    for tag in ("<p>", "<br>", "<em>", "<strong>"):
        assert tag not in exported
    for sample in ("😀", "©", "——", "“走吧。”"):
        assert sample in exported


def test_export_markdown_keeps_every_paragraph(client, config) -> None:
    """AC-6：Markdown 正文不得丢段、不得泄漏标签，字数与 TXT 同源一致。"""
    pid, chapters = _mixed_project(client, config)
    result = _export(client, config, pid, "md")
    exported = (config.data_dir / result["relpath"]).read_text(encoding="utf-8")

    for _, text, _ in chapters:
        for paragraph in (part.strip() for part in text.split("\n")):
            if paragraph:
                assert paragraph in exported, f"Markdown 丢失段落：{paragraph}"

    assert result["word_count"] == sum(words for _, _, words in chapters)
    assert "### 第一章" in exported
    assert "### Mixed" in exported
    for tag in ("<p>", "<em>", "<strong>"):
        assert tag not in exported
