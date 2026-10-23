"""字数统计（任务 2.5 / BR-1）。

BR-1 口径：
    · 去标签纯文本后统计
    · **CJK 逐字计**（含扩展 A/B、兼容区）
    · **西文按词计**（连续字母/数字/连字符视为一个词）
    · **标点 / emoji / 符号默认计入**，可开关（``count_punctuation=False`` 时不计）

纯函数、无 I/O，便于 2.3 的实时字数与 2.6 的快照 diff 复用（NFR-M1）。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# CJK 统一表意文字：基本区、扩展 A、兼容区、扩展 B 及之后
_CJK_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2FA1F),
)

# 西文「词」：字母/数字开头，允许内部出现连字符、下划线、撇号（don't / well-known）
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[._'’\-][A-Za-z0-9]+)*")

# 提取纯文本时需要换行的块级标签
_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "div",
    "dl",
    "dt",
    "dd",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tr",
    "td",
    "th",
    "ul",
}

_SKIP_TAGS = {"script", "style", "template"}


def is_cjk(char: str) -> bool:
    """是否为 CJK 表意文字（逐字计数对象）。"""
    code = ord(char)
    return any(start <= code <= end for start, end in _CJK_RANGES)


class _TextExtractor(HTMLParser):
    """把富文本 HTML 还原为纯文本；块级标签转换为换行。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        # 连续空行压缩为两行，去掉首尾空白（不改变可见文字）
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def extract_text(html: str | None) -> str:
    """去掉 HTML 标签，得到纯文本（保留段落换行）。"""
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


def count_words(text: str | None, *, count_punctuation: bool = True) -> int:
    """按 BR-1 统计字数（CJK 逐字 + 西文按词 + 可选标点）。"""
    if not text:
        return 0

    cjk_count = 0
    buffer: list[str] = []
    for char in text:
        if is_cjk(char):
            cjk_count += 1
            # 用空格隔开，避免「中文abc」被拼成一个西文词
            buffer.append(" ")
        else:
            buffer.append(char)

    remainder = "".join(buffer)
    word_count = len(_WORD_RE.findall(remainder))
    if not count_punctuation:
        return cjk_count + word_count

    punctuation = 0
    for char in _WORD_RE.sub("", remainder):
        if char.isspace() or char.isalnum():
            continue
        punctuation += 1
    return cjk_count + word_count + punctuation


def count_html(
    html: str | None,
    *,
    count_punctuation: bool = True,
) -> tuple[str, int]:
    """统计富文本：返回 ``(纯文本, 字数)``，便于同时维护 ``content_text``。"""
    plain = extract_text(html)
    return plain, count_words(plain, count_punctuation=count_punctuation)
