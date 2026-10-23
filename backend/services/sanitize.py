"""富文本服务端白名单消毒（NFR-S6 / 回归 14）。

职责：把编辑器提交的 HTML 清洗为「只含允许标签与属性」的安全片段，落库前调用。
约定：
    · 只允许排版所需标签（加粗/斜体/标题/列表/引用/分割线/链接/图片）
    · ``class`` 仅允许出现在块级标签上（Quill 的对齐/缩进/字号类名）
    · ``img`` 的 ``src`` 只允许库内相对路径 ``media/...``（外链图片直接丢弃）
    · ``style`` 属性一律不允许（颜色/字号内联样式在 V1 不持久化）
    · ``<script>`` / ``<style>`` / ``<iframe>`` 连同内容整段删除，不留残余文本
"""

from __future__ import annotations

import re

import bleach

ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "s",
        "strike",
        "del",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "ol",
        "ul",
        "li",
        "a",
        "img",
        "span",
        "pre",
        "code",
        "hr",
        "sub",
        "sup",
    }
)

# Quill 会在这些标签上挂 ql-align-*/ql-indent-*/ql-size-* 等类名
_CLASS_TAGS = frozenset(
    {
        "p",
        "span",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "ul",
        "ol",
        "blockquote",
        "pre",
        "code",
    }
)

ALLOWED_PROTOCOLS = frozenset({"http", "https", "mailto"})

_BLOCK_TAG_RE = re.compile(
    r"<(script|style|iframe|object|embed)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_ORPHAN_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


def _allow_attribute(tag: str, name: str, value: str) -> bool:
    """bleach 属性回调：按标签决定放行哪些属性。"""
    if name == "class":
        return tag in _CLASS_TAGS
    if tag == "img":
        if name == "src":
            # 只允许库内相对路径；外链、data:、javascript: 一律丢弃
            return value.startswith("media/")
        return name in {"alt", "width", "height"}
    if tag == "a":
        if name == "href":
            return True
        return name in {"title", "target", "rel"}
    return False


def sanitize_html(html: str | None) -> str:
    """清洗 HTML；``None`` / 空串返回空串。"""
    if not html:
        return ""

    # 危险标签连同内容整段删除（bleach 只删标签会留下脚本文本）
    stripped = _BLOCK_TAG_RE.sub("", str(html))
    cleaned = bleach.clean(
        stripped,
        tags=ALLOWED_TAGS,
        attributes=_allow_attribute,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
    # 消毒后仍缺 src 的 img 无意义，删除整个标签（前端统一显示占位）
    return _ORPHAN_IMG_RE.sub(
        lambda match: match.group(0) if "src=" in match.group(0).lower() else "",
        cleaned,
    )
