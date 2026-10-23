"""任务 2.3 纯函数测试：服务端消毒（NFR-S6）与图片路径规范化/签名。

回归 14：粘贴 `<script>` 保存后重新打开已清除。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.media import normalize_content_images, sign_content_images
from backend.services.sanitize import sanitize_html
from backend.storage import verify

_SIG_RE = re.compile(r'src="/files/(media/[^"?]+)\?sig=([^"]+)"')


def test_script_removed_with_content() -> None:
    clean = sanitize_html("<p>正文</p><script>alert(1)</script>")
    assert "<script" not in clean.lower()
    assert "alert(1)" not in clean
    assert "正文" in clean


def test_event_handlers_and_javascript_urls_removed() -> None:
    clean = sanitize_html('<p onclick="x()">a</p><a href="javascript:alert(1)">b</a>')
    assert "onclick" not in clean
    assert "javascript" not in clean


def test_external_image_src_removed() -> None:
    clean = sanitize_html(
        '<p><img src="https://evil.example/x.png"><img src="media/1/a.png"></p>'
    )
    assert "evil.example" not in clean
    assert 'src="media/1/a.png"' in clean


def test_class_kept_only_on_block_tags() -> None:
    clean = sanitize_html(
        '<p class="ql-align-center">居中</p>' '<img class="x" src="media/1/a.png">'
    )
    assert 'class="ql-align-center"' in clean
    assert 'class="x"' not in clean


def test_style_attribute_stripped() -> None:
    clean = sanitize_html('<p style="color:red">a</p>')
    assert "style" not in clean


def test_allowed_formatting_tags_kept() -> None:
    html = (
        "<h1>标题</h1><p><strong>粗</strong><em>斜</em><u>下划线</u>"
        "<s>删</s></p><ul><li>项</li></ul><blockquote>引</blockquote>"
        "<hr><pre><code>x</code></pre>"
    )
    clean = sanitize_html(html)
    for token in (
        "<h1>",
        "<strong>",
        "<em>",
        "<u>",
        "<s>",
        "<ul>",
        "<li>",
        "<blockquote>",
        "<hr",
        "<pre>",
        "<code>",
    ):
        assert token in clean


def test_normalize_signed_urls() -> None:
    html = (
        '<img src="/files/media/3/a.png?sig=123">'
        '<img src="http://127.0.0.1:8000/files/media/3/b.png?sig=x">'
        '<img src="media/3/c.png">'
    )
    assert normalize_content_images(html) == (
        '<img src="media/3/a.png">'
        '<img src="media/3/b.png">'
        '<img src="media/3/c.png">'
    )


def test_external_url_not_normalized() -> None:
    html = '<img src="https://evil.example/a.png">'
    assert normalize_content_images(html) == html


def test_sign_content_images_roundtrip() -> None:
    html = '<p><img src="media/3/a.png" alt="图"></p>'
    signed = sign_content_images(html)
    match = _SIG_RE.search(signed)
    assert match is not None, signed
    assert verify(match.group(1), match.group(2)) is True
    assert verify("media/3/other.png", match.group(2)) is False
    assert normalize_content_images(signed) == html
