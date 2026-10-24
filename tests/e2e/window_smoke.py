"""真实窗口冒烟（pywebview + WebView2）—— 补足 pytest 覆盖不到的窗口层。

覆盖链路：临时数据目录 → 起后端 → 造样例数据（含 9 万字超长章节）→ 开真实窗口 → 驱动页面
（项目列表 → 写作页排版实测 → 输入 → 3s 自动保存 → 超长章节提示不阻断 → 检索）→
回查 HTTP 侧结果 → 关窗退出。

运行（推荐用项目 venv）：

    D:\\小说辅助\\.venv\\Scripts\\python.exe tests\\e2e\\window_smoke.py
    ... --json          # 仅输出 JSON（ASCII 转义，便于脚本/CI 解析）
    ... --keep-data     # 保留临时数据目录，便于排查失败现场
    ... --timeout 30    # 单步等待上限（秒）

退出码：0 全部通过；1 任一步失败（失败原因在输出里）。

注意：会短暂弹出一个真实窗口（约 20 秒），跑完自动关闭；不读写项目 ``data/``。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER, clear_proxy_env, ensure_data_dirs, load_config
from backend.database import Database
from backend.migrate import apply_migrations
from backend.server import create_app

STARTUP_TIMEOUT = 10.0
# 章节正文 = 阶段三 3.4 的排版样本：标题 / 正文 / 引用 / 列表 / 代码块 /
# 中英混排 / emoji。冒烟据此实测「首行缩进 / 不缩进豁免 / 行高稳定」。
CHAPTER_HTML = (
    "<h2>潮汐与灯塔</h2>"
    "<p>深夜的码头，海风带着咸味。她低声说：“走吧。”</p>"
    "<blockquote>潮水退去，露出半截旧船。</blockquote>"
    "<ol><li>灯笼</li><li>缆绳</li></ol>"
    "<pre><code>if (tide &gt; 0) light();</code></pre>"
    "<p>She whispered, “走吧”，海风 3.5 级，第 2 次。</p>"
    "<p>潮水退了 🌊🌙，她笑了 😀。</p>"
)
DOCUMENT_HTML = "<p>海风来自黑水河。</p>"
SECOND_DOCUMENT_TITLE = "人物 · 守塔人"
TYPED_TEXT = "冒烟输入"

# 阶段三 3.4 / 回归 20：8 万字以上的超长章节（不含「海风」，避免干扰检索断言）
LONG_CHAPTER_TITLE = "超长章"
LONG_SENTENCE = "潮声漫过礁石，灯塔在雨里转了一圈又一圈。"
LONG_PARAGRAPH_COUNT = 300  # 300 段 × 300 字 ≈ 9 万字
LONG_REPEAT = 15

# T1（真机验收缺口补齐）：5 万～8 万之间的 warn 档，之前只有一次性手测
WARN_CHAPTER_TITLE = "五万章"
WARN_PARAGRAPH_COUNT = 100
WARN_REPEAT = 26  # 100 段 × 520 字 = 5.2 万字

# 阶段三 3.4：把运行时排版实测值一次性取回（字号 / 行高 / 行宽 / 缩进豁免 / 行高稳定）
TYPOGRAPHY_PROBE = """
(function () {
  const editor = document.querySelector('.ql-editor');
  const style = getComputedStyle(editor);
  const indentOf = (node) => (node ? getComputedStyle(node).textIndent : 'missing');
  const samples = Array.from(editor.querySelectorAll('p')).slice(-3);
  return JSON.stringify({
    fontSize: style.fontSize,
    lineHeight: style.lineHeight,
    maxWidth: style.maxWidth,
    paddingLeft: style.paddingLeft,
    caretColor: style.caretColor,
    spellcheck: editor.getAttribute('spellcheck'),
    indents: {
      p: indentOf(editor.querySelector('p')),
      h2: indentOf(editor.querySelector('h2')),
      blockquote: indentOf(editor.querySelector('blockquote')),
      li: indentOf(editor.querySelector('li')),
      code: indentOf(
        editor.querySelector('.ql-code-block-container') ||
          editor.querySelector('pre')
      )
    },
    lineHeights: samples.map((node) => node.getBoundingClientRect().height)
  });
})()
"""

# 阶段三 3.4：空文档占位的渲染位置（与首行正文左对齐）
PLACEHOLDER_PROBE = """
(function () {
  const editor = document.querySelector('.ql-editor');
  const style = getComputedStyle(editor, '::before');
  return JSON.stringify({
    blank: editor.classList.contains('ql-blank'),
    content: style.content,
    indent: style.textIndent,
    left: style.left,
    fontStyle: style.fontStyle
  });
})()
"""

# 把光标放到正文末尾：模态对话框开关后 DOM 选区会丢，直接 execCommand 会返回 false，
# 所以每次「模拟打字」前显式重建选区（仅测试驱动需要，真实用户点一下正文即可）。
CARET_TO_END = """
(function () {
  const editor = document.querySelector('.ql-editor');
  const range = document.createRange();
  range.selectNodeContents(editor);
  range.collapse(false);
  const selection = getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  editor.focus();
  return true;
})()
"""


class SmokeError(RuntimeError):
    """冒烟失败（消息里带步骤名）。"""


class UvicornThread(threading.Thread):
    """在子线程运行 uvicorn（与 main.py 的启动方式一致）。"""

    def __init__(self, app: Any, host: str, port: int) -> None:
        super().__init__(daemon=True, name="inkwell-e2e-uvicorn")
        import uvicorn

        self.server = uvicorn.Server(
            uvicorn.Config(
                app=app,
                host=host,
                port=port,
                log_level="warning",
                access_log=False,
            )
        )

    def run(self) -> None:
        self.server.run()

    def stop(self) -> None:
        self.server.should_exit = True

    def wait_started(self, timeout: float = STARTUP_TIMEOUT) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.server.started:
                return
            if not self.is_alive():
                break
            time.sleep(0.02)
        raise SmokeError("后端启动超时")


class TokenApi:
    """窗口桥接：把本次进程的 token 交给前端（与 main.py 的 WindowApi 等价）。"""

    def __init__(self, token: str) -> None:
        self._token = token

    def get_token(self) -> str:
        return self._token

    def is_dev(self) -> bool:
        return True


def seed(client: httpx.Client) -> dict[str, int]:
    """造最小样例：1 个项目、3 章正文（9 万字超长章 / 5.2 万字 warn 章）、2 份设定文档。"""
    project = client.post("/api/projects", json={"title": "冒烟之书"}).json()["data"]
    tree = client.get(f"/api/projects/{project['id']}/volumes").json()["data"]
    default_volume_id = tree["default_volume"]["id"]
    chapter = client.post(
        f"/api/volumes/{default_volume_id}/chapters",
        json={"title": "第一章"},
    ).json()["data"]
    saved = client.put(
        f"/api/chapters/{chapter['id']}/content",
        json={"content_html": CHAPTER_HTML},
    ).json()
    if saved["code"] != 0:
        raise SmokeError(f"造章节正文失败：{saved}")

    # 3.4 / 回归 20：8 万字超长章节（合计约 9 万字）
    long_chapter = client.post(
        f"/api/volumes/{default_volume_id}/chapters",
        json={"title": LONG_CHAPTER_TITLE},
    ).json()["data"]
    long_html = "".join(
        f"<p>{LONG_SENTENCE * LONG_REPEAT}</p>" for _ in range(LONG_PARAGRAPH_COUNT)
    )
    long_saved = client.put(
        f"/api/chapters/{long_chapter['id']}/content",
        json={"content_html": long_html},
    ).json()
    if long_saved["code"] != 0 or long_saved["data"]["word_count"] < 80000:
        raise SmokeError(f"造超长章节失败：{long_saved}")

    # T1：5 万～8 万的 warn 档章节
    warn_chapter = client.post(
        f"/api/volumes/{default_volume_id}/chapters",
        json={"title": WARN_CHAPTER_TITLE},
    ).json()["data"]
    warn_html = "".join(
        f"<p>{LONG_SENTENCE * WARN_REPEAT}</p>" for _ in range(WARN_PARAGRAPH_COUNT)
    )
    warn_saved = client.put(
        f"/api/chapters/{warn_chapter['id']}/content",
        json={"content_html": warn_html},
    ).json()
    warn_words = warn_saved.get("data", {}).get("word_count", 0)
    if warn_saved["code"] != 0 or not 50000 <= warn_words < 80000:
        raise SmokeError(f"造 warn 档章节失败：{warn_saved}")

    client.post(
        f"/api/projects/{project['id']}/documents",
        json={"title": "世界观", "category": "world", "content_html": DOCUMENT_HTML},
    )
    # B2：第二篇文档用于「删除 + 回退到剩余文档」，正文不含「海风」以免影响检索断言
    second_document = client.post(
        f"/api/projects/{project['id']}/documents",
        json={
            "title": SECOND_DOCUMENT_TITLE,
            "category": "faction",
            "content_html": "<p>守塔人世代居住在北礁。</p>",
        },
    ).json()["data"]
    return {
        "project_id": project["id"],
        "chapter_id": chapter["id"],
        "long_chapter_id": long_chapter["id"],
        "warn_chapter_id": warn_chapter["id"],
        "document_id": second_document["id"],
    }


def make_driver(
    window: Any,
    client: httpx.Client,
    ids: dict[str, int],
    timeout: float,
    result: dict[str, Any],
    quiet: bool,
) -> Any:
    """返回 pywebview 的启动回调：驱动页面并收集断言结果。"""

    def js(code: str) -> Any:
        return window.evaluate_js(code)

    def wait(code: str, label: str) -> None:
        deadline = time.time() + timeout
        last_error = ""
        while time.time() < deadline:
            try:
                if js(code):
                    return
            except Exception as exc:
                last_error = str(exc)
            time.sleep(0.2)
        detail = f"（{last_error}）" if last_error else ""
        raise SmokeError(f"超时未满足：{label}{detail}")

    def step(label: str, condition: Any = True, detail: str = "") -> None:
        if not condition:
            raise SmokeError(f"{label} 不成立" + (f"（{detail}）" if detail else ""))
        result["steps"].append(label)
        if not quiet:
            print(f"[PASS] {label}", flush=True)

    def driver() -> None:
        try:
            js(
                "window.__errs = [];"
                "window.addEventListener('error', e =>"
                " window.__errs.push(String(e.message)));"
                "window.addEventListener('unhandledrejection', e =>"
                " window.__errs.push(String((e.reason && e.reason.message)"
                " || e.reason)));"
            )

            wait("document.querySelectorAll('.card').length > 0", "项目列表渲染")
            step("项目列表渲染")

            # ---- 阶段三 3.3：卡片信息（状态徽标 / 最近打开 / 缺封面回退） ----
            badge = js(
                "document.querySelector('.card[data-id=\"%d\"] .badge').textContent"
                % ids["project_id"]
            )
            step("卡片状态徽标", badge == "连载中", str(badge))
            opened = js(
                'document.querySelector(\'.card[data-id="%d"]'
                ' [data-role="opened"]\').textContent' % ids["project_id"]
            )
            step(
                "卡片最近打开时间",
                "最近打开" in (opened or "") and "未知" not in (opened or ""),
                str(opened),
            )
            cover = js(
                '!!document.querySelector(\'.card[data-id="%d"]'
                " .card__cover-fallback')" % ids["project_id"]
            )
            step("缺封面回退默认封面（FR-1.8）", cover is True)

            bridge = js("document.getElementById('bridge').textContent")
            step("桥接 token 注入", "已就绪" in (bridge or ""), bridge)
            health = js("document.getElementById('health').textContent")
            step("健康检查 200", "200" in (health or ""), health)

            # ---- B1：对话框「取消」必须能关掉（空表单 + 已填表单两种）----
            projects_before = client.get("/api/projects").json()["data"]["total"]
            js("document.getElementById('new-project').click()")
            wait(
                "document.getElementById('project-dialog').open === true", "新建对话框"
            )
            js(
                "document.querySelector('#project-dialog "
                "[data-dialog-cancel]').click()"
            )
            wait(
                "document.getElementById('project-dialog').open === false",
                "未填书名点取消关闭",
            )
            step("未填书名点「取消」也能关闭（B1）")
            js("document.getElementById('new-project').click()")
            wait(
                "document.getElementById('project-dialog').open === true",
                "新建对话框重开",
            )
            js(
                "(function(){document.getElementById('project-title').value="
                "'不该被创建';"
                "document.querySelector('#project-dialog "
                "[data-dialog-cancel]').click();return true;})()"
            )
            wait(
                "document.getElementById('project-dialog').open === false",
                "已填书名点取消关闭",
            )
            projects_after = client.get("/api/projects").json()["data"]["total"]
            step(
                "已填书名点「取消」同样关闭且不建项目（B1）",
                projects_after == projects_before,
                f"{projects_before} → {projects_after}",
            )

            js(
                "document.querySelector('.card[data-id=\"%d\"] .card__actions .btn')"
                ".click()" % ids["project_id"]
            )
            wait(
                "!document.getElementById('view-writer').hidden"
                " && !!document.querySelector('.ql-editor')",
                "写作页与 Quill 初始化",
            )
            step("写作页与 Quill 初始化")
            title = js("document.getElementById('chapter-title').value")
            step("章节标题加载", title == "第一章", title)

            # ---- B1（同类对话框）：askText 的「取消」也要能关掉且不建章 ----
            def chapter_total() -> int:
                tree_data = client.get(
                    f"/api/projects/{ids['project_id']}/volumes"
                ).json()["data"]
                volumes = list(tree_data["volumes"]) + [tree_data["default_volume"]]
                return sum(len(volume["chapters"]) for volume in volumes)

            chapters_before = chapter_total()
            js("document.getElementById('add-chapter').click()")
            wait(
                "document.getElementById('prompt-dialog').open === true", "新建章对话框"
            )
            js(
                "document.querySelector('#prompt-dialog "
                "[data-dialog-cancel]').click()"
            )
            wait(
                "document.getElementById('prompt-dialog').open === false",
                "关闭新建章对话框",
            )
            step(
                "新建章对话框「取消」关闭且不建章（B1 同类）",
                chapter_total() == chapters_before,
                f"{chapters_before} → {chapter_total()}",
            )

            # ---- 阶段三 3.4：编辑器排版（§7.2 / FR-3.4）----
            metrics = json.loads(js(TYPOGRAPHY_PROBE))
            result.setdefault("checks", {})["typography"] = metrics
            step("正文 17px", metrics["fontSize"] == "17px", metrics["fontSize"])
            step(
                "行高 1.9（≈32.3px）",
                abs(float(str(metrics["lineHeight"]).replace("px", "")) - 32.3) < 0.2,
                metrics["lineHeight"],
            )
            step("行宽 ≤760px", metrics["maxWidth"] == "760px", metrics["maxWidth"])
            step(
                "首行缩进 2 字符（34px）",
                metrics["indents"]["p"] == "34px",
                metrics["indents"]["p"],
            )
            step(
                "标题/引用/列表/代码块不缩进",
                all(
                    metrics["indents"][key] == "0px"
                    for key in ("h2", "blockquote", "li", "code")
                ),
                json.dumps(metrics["indents"], ensure_ascii=False),
            )
            step(
                "关闭拼写检查（spellcheck=false）",
                metrics["spellcheck"] == "false",
                str(metrics["spellcheck"]),
            )
            heights = metrics["lineHeights"]
            step(
                "中英混排 / emoji 行高不跳动",
                len(heights) == 3 and max(heights) - min(heights) <= 0.5,
                str(heights),
            )

            js(CARET_TO_END)
            js("document.execCommand('insertText', false, '%s');true" % TYPED_TEXT)
            wait(
                "document.getElementById('save-status').textContent"
                ".includes('已保存')",
                "3s 自动保存",
            )
            saved_at = js("document.getElementById('save-status').textContent")
            step("输入触发 3s 自动保存", saved_at)

            detail = client.get(f"/api/chapters/{ids['chapter_id']}").json()["data"]
            step(
                "正文已写入后端",
                TYPED_TEXT in (detail["content_text"] or ""),
                detail["content_text"][-30:],
            )
            drafts = client.get("/api/drafts").json()["data"]
            step("保存成功后暂存已清理", drafts["total"] == 0, str(drafts["total"]))

            # ---- B3 / D-3.4-1：代码块「保存 → 重开」保形 ----
            # 把首段转成代码块（Quill 首个容器由种子的 <pre> 生成，转换后应为 2 个）
            js(
                "(function(){const ed=document.querySelector('.ql-editor');"
                "const p=ed.querySelector('p');"
                "const range=document.createRange();"
                "range.selectNodeContents(p);range.collapse(true);"
                "const sel=getSelection();sel.removeAllRanges();"
                "sel.addRange(range);ed.focus();return true;})()"
            )
            time.sleep(0.3)  # 等 Quill 的 selectionchange 把 DOM 选区收进内部状态
            version_before_cb = js(
                "document.getElementById('stat-version').textContent"
            )
            js(
                "document.querySelector('.ql-toolbar button.ql-code-block').click();true"
            )
            wait(
                "document.querySelectorAll('.ql-editor .ql-code-block-container')"
                ".length === 2",
                "代码块格式已应用",
            )
            wait(
                "document.getElementById('stat-version').textContent !== %s"
                % json.dumps(version_before_cb),
                "代码块变更已保存",
            )
            stored = client.get(f"/api/chapters/{ids['chapter_id']}").json()["data"][
                "content"
            ]
            step(
                "代码块存档为 <pre><code>（D-3.4-1）",
                (stored or "").count("<pre>") == 2
                and "ql-code-block-container" not in (stored or ""),
                (stored or "")[:80],
            )
            reopened = js(
                "(function(){for (const node of document.querySelectorAll"
                "('.tree__chapter')) {if (node.textContent.includes('第一章'))"
                " {node.click();return true;}}return false;})()"
            )
            step("点树重开第一章", reopened is True)
            wait(
                "document.querySelectorAll('.ql-editor .ql-code-block-container')"
                ".length === 2",
                "重开后代码块还原",
            )
            step("重开章节后代码块格式仍在（D-3.4-1 关闭）")

            # ---- 阶段三 3.4 / 回归 20：8 万字超长章节提示不阻断（FR-3.9）----
            found = js(
                "(function(){for (const node of document.querySelectorAll"
                "('.tree__chapter')) {if (node.textContent.includes('%s'))"
                " {node.click();return true;}}return false;})()" % LONG_CHAPTER_TITLE
            )
            step("大纲树出现超长章节", found is True)
            wait(
                "document.getElementById('chapter-title').value === '%s'"
                % LONG_CHAPTER_TITLE,
                "打开超长章节",
            )
            wait(
                "document.getElementById('chapter-capacity').hidden === false",
                "超长章节容量提示",
            )
            chip = js("document.getElementById('chapter-capacity').innerText")
            step(
                "8 万字给出拆章提示（不弹窗）",
                "拆章" in (chip or "") and "万字" in (chip or ""),
                str(chip),
            )
            chip_class = js("document.getElementById('chapter-capacity').className")
            step(
                "提示为 split 档（描边 + 文案双编码）",
                "is-split" in (chip_class or ""),
                str(chip_class),
            )
            step(
                "超长章节仍可编辑（不阻断）",
                js("document.querySelector('.ql-editor').isContentEditable") is True,
            )
            version_before = js("document.getElementById('stat-version').textContent")
            js(CARET_TO_END)
            js("document.execCommand('insertText', false, '续');true")
            wait(
                "document.getElementById('stat-version').textContent !== %s"
                " && document.getElementById('save-status').textContent"
                ".includes('已保存')" % json.dumps(version_before),
                "超长章节保存",
            )
            step("超长章节保存成功（不阻断）")
            result.setdefault("checks", {})["long_chapter"] = {
                "chip": chip,
                "class": chip_class,
                "words": js("document.getElementById('stat-chapter').textContent"),
                "editable": True,
            }

            # ---- T1：warn 档（5 万～8 万）自动化回归 ----
            js(
                "(function(){for (const node of document.querySelectorAll"
                "('.tree__chapter')) {if (node.textContent.includes('%s'))"
                " {node.click();return true;}}return false;})()" % WARN_CHAPTER_TITLE
            )
            wait(
                "document.getElementById('chapter-title').value === '%s'"
                % WARN_CHAPTER_TITLE,
                "打开 warn 档章节",
            )
            wait(
                "document.getElementById('chapter-capacity').hidden === false",
                "warn 档容量提示",
            )
            warn_chip = js("document.getElementById('chapter-capacity').innerText")
            warn_class = js("document.getElementById('chapter-capacity').className")
            step(
                "5 万字档给出「超上限」提示（T1）",
                "已超" in (warn_chip or "") and "万字" in (warn_chip or ""),
                str(warn_chip),
            )
            step(
                "warn 档样式为 is-warn（不是 is-split）",
                "is-warn" in (warn_class or "")
                and "is-split" not in (warn_class or ""),
                str(warn_class),
            )
            result.setdefault("checks", {})["warn_chapter"] = {
                "chip": warn_chip,
                "class": warn_class,
                "words": js("document.getElementById('stat-chapter').textContent"),
            }

            # ---- B2：设定文档删除入口（列表行删除按钮 + 软删除 + 回退）----
            js("document.getElementById('open-documents').click()")
            wait("document.getElementById('view-documents').hidden === false", "设定页")
            wait(
                "document.querySelectorAll('#document-list .tree__row').length === 2",
                "设定列表两行",
            )
            step(
                "设定列表每行都有删除入口（B2）",
                js("document.querySelectorAll('#document-list .tree__delete').length")
                == 2,
            )
            js("window.__realConfirm = window.confirm;window.confirm = () => true;true")
            clicked = js(
                "(function(){for (const row of document.querySelectorAll"
                "('#document-list .tree__row')) {if (row.textContent.includes('守塔人'))"
                " {row.querySelector('.tree__delete').click();return true;}}"
                "return false;})()"
            )
            step("删除按钮可点（B2）", clicked is True)
            wait(
                "document.querySelectorAll('#document-list .tree__row').length === 1",
                "删除后列表刷新",
            )
            step("删除后列表只剩一篇（B2）")
            deleted = client.get(f"/api/documents/{ids['document_id']}").json()
            step(
                "后端已软删除，回收站可恢复",
                deleted.get("code") == 2002,
                str(deleted.get("code")),
            )
            remaining = js("document.getElementById('document-title').value")
            step("删除后回退到剩余文档", remaining == "世界观", str(remaining))
            js("window.confirm = window.__realConfirm;true")
            js("document.getElementById('back-to-writer').click()")
            wait(
                "document.getElementById('view-writer').hidden === false",
                "返回写作页",
            )
            step("设定页可返回写作页")

            js("document.getElementById('nav-home').click()")
            wait(
                "document.getElementById('view-projects').hidden === false",
                "返回项目列表",
            )
            js("document.getElementById('nav-search').click()")
            wait("document.getElementById('view-search').hidden === false", "检索页")
            js(
                "(function() {const input=document.getElementById('search-input');"
                "input.value='海风';"
                "document.getElementById('search-go').click();return true;})()"
            )
            wait("document.querySelectorAll('.search-hit').length > 0", "检索命中")
            hits = js("document.querySelectorAll('.search-hit').length")
            step("检索命中章节 + 设定文档", hits == 2, str(hits))
            snippet = js("document.querySelector('.search-hit__snippet').innerHTML")
            step("摘要高亮", "<mark>海风</mark>" in (snippet or ""), snippet)
            status = js("document.getElementById('search-status').textContent")
            step("短词降级提示", "（模糊匹配）" in (status or ""), status)

            search = client.get("/api/search", params={"q": "海风"}).json()["data"]
            step("检索响应含 fuzzy 字段", search.get("fuzzy") is True)
            step("首页未触发分页上限", search.get("page_limited") is False)

            # ---- 阶段三 3.3：首启引导（C-09） ----
            js("document.getElementById('nav-home').click()")
            wait(
                "document.getElementById('view-projects').hidden === false",
                "回到项目列表",
            )
            js("document.getElementById('new-project').click()")
            wait(
                "document.getElementById('project-dialog').open === true", "新建对话框"
            )
            js(
                "(function(){"
                "document.getElementById('project-title').value='首启之书';"
                "document.getElementById('project-form')"
                ".requestSubmit(document.getElementById('save-project'));"
                "return true;})()"
            )
            wait(
                "!document.getElementById('view-writer').hidden"
                " && document.querySelector('.ql-editor') !== null",
                "首启直达写作页",
            )
            step("首启引导直达写作页")
            first_title = js("document.getElementById('chapter-title').value")
            step("首启自动创建第一章", first_title == "第一章", str(first_title))
            # 聚焦必须在章节加载完成、编辑器可编辑之后（阶段三_IME验证记录 §二）
            wait(
                "document.activeElement === document.querySelector('.ql-editor')",
                "首启聚焦正文",
            )
            step("首启聚焦正文（章节就绪后）")

            # ---- 阶段三 3.4：空文档占位（与首行正文左对齐）----
            placeholder = json.loads(js(PLACEHOLDER_PROBE))
            step(
                "空章节显示占位提示",
                placeholder["blank"] is True
                and "开始写这一章" in (placeholder["content"] or ""),
                str(placeholder["content"]),
            )
            step(
                "占位沿用 2 字符缩进（与正文左对齐）",
                placeholder["indent"] == "34px" and placeholder["left"] == "24px",
                f"{placeholder['indent']} / {placeholder['left']}",
            )

            # ---- B5：IME 组合期间隐藏占位（真机 V-02 第 1 条）----
            js(
                "document.querySelector('.ql-editor')"
                ".dispatchEvent(new CompositionEvent('compositionstart'));true"
            )
            compose_hidden = js(
                "getComputedStyle(document.querySelector('.ql-editor'),'::before')"
                ".display"
            )
            step(
                "组合输入期间占位隐藏（B5）",
                compose_hidden == "none",
                str(compose_hidden),
            )
            js(
                "document.querySelector('.ql-editor')"
                ".dispatchEvent(new CompositionEvent('compositionend'));true"
            )
            compose_visible = js(
                "getComputedStyle(document.querySelector('.ql-editor'),'::before')"
                ".display"
            )
            step(
                "组合结束后占位恢复（B5）",
                compose_visible != "none",
                str(compose_visible),
            )

            # ---- 阶段三 3.3：空态与出错态 ----
            js("document.getElementById('nav-home').click()")
            wait(
                "document.getElementById('view-projects').hidden === false",
                "回到项目列表",
            )
            for project in client.get("/api/projects").json()["data"]["items"]:
                client.delete(f"/api/projects/{project['id']}")
            js("window.dispatchEvent(new Event('inkwell:projects-refresh'));true")
            wait(
                "document.getElementById('project-empty').hidden === false"
                " && document.querySelectorAll('.card').length === 0",
                "空态",
            )
            step("空态可见")
            js("document.getElementById('empty-new-project').click()")
            wait(
                "document.getElementById('project-dialog').open === true", "空态主 CTA"
            )
            step("空态主 CTA 可用")
            js("document.getElementById('project-dialog').close()")

            # 拦截 fetch 模拟后端不可用 → 出错态 → 恢复后重试
            js(
                "window.__realFetch = window.fetch;"
                "window.fetch = () => Promise.reject(new Error('模拟断网'));"
                "document.getElementById('projects-retry').click();true"
            )
            wait(
                "document.getElementById('projects-error').hidden === false",
                "出错态可见",
            )
            step("出错态可见")
            js(
                "window.fetch = window.__realFetch;"
                "document.getElementById('projects-retry').click();true"
            )
            wait(
                "document.getElementById('projects-error').hidden === true"
                " && document.getElementById('project-empty').hidden === false",
                "重试后恢复",
            )
            step("重试后恢复空态")

            errors = js("window.__errs || []")
            step("页面无 JS 异常", errors == [], json.dumps(errors, ensure_ascii=False))
            result["ok"] = True
        except SmokeError as exc:
            result["errors"].append(str(exc))
            if not quiet:
                print(f"[FAIL] {exc}", flush=True)
        except Exception as exc:
            result["errors"].append(f"{type(exc).__name__}: {exc}")
            if not quiet:
                print(f"[FAIL] 未预期异常：{exc}", flush=True)
        finally:
            try:
                result["page_errors"] = js("window.__errs || []")
            except Exception:
                pass
            window.destroy()

    return driver


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inkwell 真实窗口冒烟")
    parser.add_argument("--json", action="store_true", help="仅输出 JSON 结果")
    parser.add_argument("--keep-data", action="store_true", help="保留临时数据目录")
    parser.add_argument(
        "--timeout", type=float, default=30.0, help="单步等待上限（秒）"
    )
    args = parser.parse_args(argv)

    data_dir = Path(tempfile.mkdtemp(prefix="inkwell-e2e-"))
    os.environ["INKWELL_DATA_DIR"] = str(data_dir)
    clear_proxy_env()

    result: dict[str, Any] = {"ok": False, "steps": [], "errors": [], "data_dir": ""}
    database: Database | None = None
    thread: UvicornThread | None = None

    try:
        config = load_config()
        ensure_data_dirs(config)
        database = Database(config.db_path)
        schema_version = apply_migrations(database, config.data_dir)

        app = create_app(config, database)
        app.state.schema_version = schema_version
        thread = UvicornThread(app, config.host, config.port)
        thread.start()
        thread.wait_started()

        client = httpx.Client(
            base_url=config.base_url,
            trust_env=False,
            timeout=10.0,
            headers={TOKEN_HEADER: config.token},
        )
        try:
            ids = seed(client)
            result["checks"] = {"seed": ids}

            import webview

            window = webview.create_window(
                title="Inkwell 冒烟",
                url=f"{config.base_url}/",
                js_api=TokenApi(config.token),
                width=1100,
                height=760,
                text_select=True,
            )
            webview.start(
                make_driver(
                    window,
                    client,
                    ids,
                    args.timeout,
                    result,
                    quiet=args.json,
                ),
                debug=False,
                private_mode=False,
                storage_path=str(config.webview_storage_dir),
            )
        finally:
            client.close()
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        if not args.json:
            print(f"[FAIL] 启动失败：{exc}", flush=True)
    finally:
        if thread is not None:
            thread.stop()
        if database is not None:
            database.dispose()
        result["data_dir"] = str(data_dir)
        if not args.keep_data:
            shutil.rmtree(data_dir, ignore_errors=True)

    if args.json:
        print(json.dumps(result, ensure_ascii=True), flush=True)
    else:
        print(flush=True)
        print(
            f"结果：{'通过' if result['ok'] else '失败'}"
            f"（{len(result['steps'])} 步）",
            flush=True,
        )
        if result["errors"]:
            for error in result["errors"]:
                print(f"  - {error}", flush=True)
        if args.keep_data:
            print(f"临时数据目录：{data_dir}", flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
