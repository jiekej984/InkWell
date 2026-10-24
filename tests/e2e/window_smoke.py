"""真实窗口冒烟（pywebview + WebView2）—— 补足 pytest 覆盖不到的窗口层。

覆盖链路：临时数据目录 → 起后端 → 造样例数据（含 9 万字超长章节）→ 开真实窗口 → 驱动页面
（项目列表 → 写作页排版实测 → 输入 → 3s 自动保存 → **3.5 保存三态 / 断网重试 /
#50 导出本章 / 3002 刷新恢复 / BR-2 四条路径** → 超长章节提示不阻断 → **3.7 快捷键
（含 IME 与输入框门禁）/ 3.8 章内查找** → 检索 → P6/P9/P7/P8）→ 回查 HTTP 侧结果 → 关窗退出。

运行（推荐用项目 venv）：

    D:\\小说辅助\\.venv\\Scripts\\python.exe tests\\e2e\\window_smoke.py
    ... --json          # 仅输出 JSON（ASCII 转义，便于脚本/CI 解析）
    ... --keep-data     # 保留临时数据目录，便于排查失败现场
    ... --timeout 30    # 单步等待上限（秒）

退出码：0 全部通过；1 任一步失败（失败原因在输出里）。

注意：会短暂弹出一个真实窗口（约 90~120 秒，含重试阶梯与查找交互），跑完自动关闭；
不读写项目 ``data/``。
"""

from __future__ import annotations

import argparse
import json
import os
import re
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

    def __init__(self, token: str, data_dir: Any = None) -> None:
        self._token = token
        self._data_dir = str(data_dir or "")

    def get_token(self) -> str:
        return self._token

    def is_dev(self) -> bool:
        return True

    def open_data_dir(self) -> dict:
        """P9「打开数据目录」：冒烟不真的拉起资源管理器，只回传路径。"""
        return {"ok": True, "path": self._data_dir}


def seed(client: httpx.Client) -> dict[str, int]:
    """造最小样例：1 个项目、4 章正文（9 万字超长章 / 5.2 万字 warn 章 / 第二章）、2 份设定文档。"""
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

    # 3.5 / BR-2：一个体量很小的第二章，用于「切换章节强制保存」（避免加载 9 万字章节）
    second_chapter = client.post(
        f"/api/volumes/{default_volume_id}/chapters",
        json={"title": "第二章"},
    ).json()["data"]
    client.put(
        f"/api/chapters/{second_chapter['id']}/content",
        json={"content_html": "<p>切换测试的正文，不含关键词。</p>"},
    )

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


def _integrity_failure_detail(
    data_dir: Any, client: Any, status_text: str
) -> dict[str, Any]:
    """完整自检失败时的现场三连（3.9）：UI 文案 / 接口重试 / 全新连接。

    三者不一致时能一眼区分「真损坏」与「连接态误报」：``#42 重建索引`` 之后的
    池内连接会因 FTS5 结构缓存过期误报 malformed inverted index，而独立连接读到的是
    ok —— 结论与验证见 `docs/故障排查.md`。
    """
    import sqlite3

    detail: dict[str, Any] = {"status": status_text}
    try:
        payload = client.get("/api/system/integrity", params={"full": 1}).json()
        data = payload.get("data") or {}
        detail["api_retry"] = {"ok": data.get("ok"), "message": data.get("quick_check")}
    except Exception as exc:
        detail["api_retry"] = f"ERR {type(exc).__name__}: {exc}"
    try:
        conn = sqlite3.connect(str(Path(data_dir) / "inkwell.db"), timeout=5.0)
        try:
            detail["fresh_connection"] = [
                str(row[0]) for row in conn.execute("PRAGMA integrity_check")
            ][:3]
        finally:
            conn.close()
    except Exception as exc:
        detail["fresh_connection"] = f"ERR {type(exc).__name__}: {exc}"
    return detail


def make_driver(
    window: Any,
    client: httpx.Client,
    ids: dict[str, int],
    data_dir: Path,
    timeout: float,
    result: dict[str, Any],
    quiet: bool,
) -> Any:
    """返回 pywebview 的启动回调：驱动页面并收集断言结果。"""

    def js(code: str) -> Any:
        return window.evaluate_js(code)

    def wait(code: str, label: str, limit: float | None = None) -> None:
        deadline = time.time() + (limit or timeout)
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

    def key_event(
        key: str,
        ctrl: bool = False,
        shift: bool = False,
        target: str = "document.activeElement || document.body",
        composing: bool = False,
    ) -> None:
        """在指定元素上派发 keydown（3.7 快捷键 / 3.8 查找驱动用）。"""
        js(
            "(function(){const el=%s;"
            "const e=new KeyboardEvent('keydown',{key:%s,ctrlKey:%s,shiftKey:%s,"
            "bubbles:true,cancelable:true,isComposing:%s});"
            "el.dispatchEvent(e);return true;})()"
            % (
                target,
                json.dumps(key),
                "true" if ctrl else "false",
                "true" if shift else "false",
                "true" if composing else "false",
            )
        )

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

            # ---- 阶段三 3.5 / 回归 23：状态栏三态（§7.4 / BR-2）----
            def save_state() -> str:
                return js("document.getElementById('save-state').dataset.state")

            def save_text() -> str:
                return js("document.getElementById('save-status').textContent")

            def click_chapter(title_text: str) -> Any:
                return js(
                    "(function(){for (const node of document.querySelectorAll"
                    "('.tree__chapter')) {if (node.textContent.includes('%s'))"
                    " {node.click();return true;}}return false;})()" % title_text
                )

            def chapter_detail() -> dict:
                body = client.get(f"/api/chapters/{ids['chapter_id']}").json()
                return body["data"]

            def state_probe() -> dict:
                return json.loads(
                    js(
                        "(function(){const box=document.getElementById('save-state');"
                        "const text=document.getElementById('save-status');"
                        "const icon=document.getElementById('save-state-icon');"
                        "const style=getComputedStyle(box);"
                        "return JSON.stringify({state:box.dataset.state,"
                        "text:text.textContent,icon:icon.textContent,"
                        "role:text.getAttribute('role'),"
                        "live:text.getAttribute('aria-live'),"
                        "border:style.borderColor});})()"
                    )
                )

            # 3.9：绿态描边走 120ms 过渡（--transition-fast），先等描边到位再连无障碍属性
            # 一起断言；旧写法在文案出现后立刻读 computedStyle，可能撞上过渡起点
            # （偶发读到 --border 的 rgb(229, 226, 220)）。
            wait(
                "getComputedStyle(document.getElementById('save-state'))"
                ".borderColor === 'rgb(79, 122, 91)'",
                "已保存态描边到位",
            )
            probe = state_probe()
            step(
                "三态之一：已保存 HH:MM 绿态",
                probe["state"] == "saved"
                and probe["icon"] == "✓"
                and "已保存" in probe["text"]
                and re.search(r"\d{2}:\d{2}", probe["text"]) is not None,
                json.dumps(probe, ensure_ascii=False),
            )
            step(
                "三重编码 + 无障碍：绿色描边 + role/aria-live",
                probe["border"] == "rgb(79, 122, 91)"
                and probe["role"] == "status"
                and probe["live"] == "polite",
                f"{probe['border']} / {probe['role']} / {probe['live']}",
            )

            # 「保存中…」：挂起 PUT，读到 saving 后再放行
            js(
                "window.__realFetch = window.fetch;"
                "window.fetch = (url, opts) => {"
                "  if (String(url).includes('/content')"
                " && opts && opts.method === 'PUT') {"
                "    return new Promise((resolve, reject) => {"
                "      window.__releaseSave = () =>"
                " window.__realFetch(url, opts).then(resolve, reject);"
                "    });"
                "  }"
                "  return window.__realFetch(url, opts);"
                "}; true"
            )
            js(CARET_TO_END)
            js("document.execCommand('insertText', false, '三态保存中');true")
            wait(
                "document.getElementById('save-state').dataset.state === 'saving'",
                "保存中态",
            )
            step(
                "三态之二：保存中…（灰底 + 环形图标）",
                js("document.getElementById('save-state-icon').textContent") == "◌"
                and "保存中" in save_text(),
                save_text(),
            )
            js("window.__releaseSave();true")
            wait(
                "document.getElementById('save-state').dataset.state === 'saved'",
                "保存完成",
            )
            step("保存完成回到已保存绿态")
            js("window.fetch = window.__realFetch;true")

            # 模拟断网：只拦 PUT，暂存 / 导出 / 其他请求照常
            js(
                "window.fetch = (url, opts) => {"
                "  if (String(url).includes('/content')"
                " && opts && opts.method === 'PUT') {"
                "    return Promise.reject(new TypeError('模拟断网'));"
                "  }"
                "  return window.__realFetch(url, opts);"
                "}; true"
            )
            js(CARET_TO_END)
            js("document.execCommand('insertText', false, '断网输入');true")
            wait(
                "document.getElementById('save-state').dataset.state === 'failed'"
                " && getComputedStyle(document.getElementById('save-state'))"
                ".borderColor === 'rgb(184, 79, 54)'",
                "失败态",
            )
            failed = state_probe()
            step(
                "三态之三：保存失败（红描边 #B84F36）",
                failed["icon"] == "⚠"
                and "保存失败" in failed["text"]
                and failed["border"] == "rgb(184, 79, 54)",
                json.dumps(failed, ensure_ascii=False),
            )
            step(
                "失败态附「重试 / 导出本章」",
                js("!document.getElementById('retry-save').hidden") is True
                and js("!document.getElementById('export-chapter').hidden") is True,
            )

            # C-03 / #50：断网时导出编辑器当前正文（库内还是旧正文）
            exports_before = {
                path.name for path in (data_dir / "exports").glob("*.txt")
            }
            js("document.getElementById('export-chapter').click();true")
            wait(
                "document.getElementById('status-note').textContent.includes('已导出')",
                "导出本章完成",
            )
            exported_files = sorted(
                (data_dir / "exports").glob("*.txt"),
                key=lambda path: path.stat().st_mtime,
            )
            exported = exported_files[-1]
            exported_text = exported.read_text(encoding="utf-8")
            step(
                "#50 导出的是未保存的编辑器正文",
                exported.name not in exports_before and "断网输入" in exported_text,
                exported.name,
            )
            step(
                "状态栏提示导出文件名与目录",
                exported.name
                in (js("document.getElementById('status-note').textContent") or ""),
                js("document.getElementById('status-note').textContent"),
            )

            wait(
                "document.getElementById('save-status').textContent"
                ".includes('保存失败，已本地暂存')",
                "三次重试耗尽",
            )
            step("三次重试耗尽后提示「保存失败，已本地暂存」")
            pending_drafts = client.get("/api/drafts").json()["data"]
            step(
                "失败后服务端留有一份暂存（BR-2）",
                pending_drafts["total"] >= 1,
                str(pending_drafts["total"]),
            )

            js("window.fetch = window.__realFetch;true")
            js("document.getElementById('retry-save').click();true")
            wait(
                "document.getElementById('save-state').dataset.state === 'saved'",
                "手动重试成功",
            )
            step("点击「重试」后恢复已保存")
            step(
                "断网期间的输入已补写回服务端",
                "断网输入" in (chapter_detail()["content_text"] or ""),
            )
            step(
                "重试成功后暂存已清空",
                client.get("/api/drafts").json()["data"]["total"] == 0,
            )

            # 3002：外部先写一次，前端版本号过期 → 冲突态 → 刷新并恢复
            external = client.put(
                f"/api/chapters/{ids['chapter_id']}/content",
                json={"content_html": "<p>外部改动</p>"},
            ).json()
            step(
                "外部更新已生效（制造 3002）",
                external["code"] == 0,
                str(external["code"]),
            )
            js(CARET_TO_END)
            js("document.execCommand('insertText', false, '冲突输入');true")
            wait(
                "document.getElementById('save-state').dataset.state === 'conflict'",
                "冲突态",
            )
            conflict = state_probe()
            step(
                "3002 冲突态：已本地暂存 + 刷新并恢复",
                "版本冲突" in conflict["text"]
                and js("!document.getElementById('reload-chapter').hidden") is True
                and js("document.getElementById('retry-save').hidden") is True,
                json.dumps(conflict, ensure_ascii=False),
            )
            js("document.getElementById('reload-chapter').click();true")
            wait(
                "document.getElementById('save-state').dataset.state === 'saved'",
                "刷新并恢复后保存成功",
            )
            step(
                "刷新并恢复后未丢输入（自动补写）",
                "冲突输入" in (chapter_detail()["content_text"] or ""),
            )

            # BR-2：失焦 / 页面隐藏 / 切换章节 三条强制保存路径
            def force_save(dispatch_code: str, marker: str, label: str) -> None:
                js(CARET_TO_END)
                js("document.execCommand('insertText', false, '%s');true" % marker)
                js(dispatch_code)
                wait(
                    "document.getElementById('save-status').textContent"
                    ".includes('已保存')",
                    label,
                )
                step(
                    f"BR-2：{label}", marker in (chapter_detail()["content_text"] or "")
                )

            force_save(
                "window.dispatchEvent(new Event('blur'));true",
                "失焦保存",
                "失焦强制保存",
            )
            force_save(
                "window.dispatchEvent(new Event('pagehide'));true",
                "隐藏保存",
                "pagehide 强制保存",
            )
            js(CARET_TO_END)
            js("document.execCommand('insertText', false, '隐藏态保存');true")
            js(
                "Object.defineProperty(document,'visibilityState',"
                "{value:'hidden',configurable:true});"
                "document.dispatchEvent(new Event('visibilitychange'));true"
            )
            wait(
                "document.getElementById('save-status').textContent.includes('已保存')",
                "visibilitychange 强制保存",
            )
            js("delete document.visibilityState;true")
            step(
                "BR-2：页面隐藏（visibilitychange）强制保存",
                "隐藏态保存" in (chapter_detail()["content_text"] or ""),
            )

            js(CARET_TO_END)
            js("document.execCommand('insertText', false, '切换前输入');true")
            step("大纲树可切到第二章（用于切换保存）", click_chapter("第二章") is True)
            wait(
                "document.getElementById('chapter-title').value === '第二章'",
                "打开第二章",
            )
            step("切回第一章", click_chapter("第一章") is True)
            wait(
                "document.getElementById('chapter-title').value === '第一章'",
                "切回第一章完成",
            )
            step(
                "BR-2：切换章节强制保存",
                "切换前输入" in (chapter_detail()["content_text"] or ""),
            )

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
            # 3.9：等「原生选区真的落在编辑器里」再点工具栏。Quill 的 format 读的是原生
            # 选区；只有在编辑器**未获焦点**时它才会用内部 savedRange 覆盖，所以这里同时
            # 断言 activeElement 与选区锚点。旧写法只 sleep 0.3s，偶发点了个空（format 静默
            # 无效），表现为 30s 超时；改成显式前置条件后要么稳定通过、要么立即报出真因。
            wait(
                "document.activeElement === document.querySelector('.ql-editor')"
                " && (function(){const s=getSelection();"
                "const ed=document.querySelector('.ql-editor');"
                "return !!s.rangeCount && ed.contains(s.anchorNode);})()",
                "代码块选区就绪",
            )
            version_before_cb = js(
                "document.getElementById('stat-version').textContent"
            )
            js(
                "document.querySelector('.ql-toolbar button.ql-code-block').click();true"
            )
            try:
                wait(
                    "document.querySelectorAll('.ql-editor .ql-code-block-container')"
                    ".length === 2",
                    "代码块格式已应用",
                )
            except SmokeError as exc:
                detail = js(
                    "(function(){const ed=document.querySelector('.ql-editor');"
                    "const s=getSelection();"
                    "const p=ed.querySelector('p');"
                    "return JSON.stringify({containers:"
                    "document.querySelectorAll('.ql-editor .ql-code-block-container')"
                    ".length,blocks:ed.children.length,firstTag:"
                    "p?p.parentNode.tagName+'>'+p.tagName:'missing',"
                    "active:(document.activeElement&&"
                    "(document.activeElement.className||document.activeElement.id))"
                    "||'none',anchor:s.rangeCount&&s.anchorNode&&"
                    "(s.anchorNode.nodeType===3?s.anchorNode.parentNode.tagName:"
                    "s.anchorNode.tagName)||'none',toolbar:"
                    "!!document.querySelector('.ql-toolbar button.ql-code-block'),"
                    "errs:window.__errs});})()"
                )
                raise SmokeError(f"代码块格式未应用：{detail}") from exc
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

            # ---- 阶段三 3.6 / FR-5.4：P5 差异对比与回滚确认文案 ----
            js("document.getElementById('manual-snapshot').click()")
            wait(
                "document.getElementById('status-note').textContent"
                ".includes('已存为版本')",
                "手动快照完成",
            )
            step("P5 创建手动快照")
            js(CARET_TO_END)
            js("document.execCommand('insertText', false, '版本差异样本');true")
            js("document.getElementById('open-versions').click()")
            wait(
                "document.getElementById('versions-dialog').open === true"
                " && document.querySelectorAll('#version-list .version').length > 0",
                "版本弹窗与列表",
            )
            js("document.querySelector('#version-list .version__main').click()")
            wait(
                "document.querySelectorAll('#version-content .diff__row').length > 0",
                "差异渲染",
            )
            diff_text = js("document.getElementById('version-content').textContent")
            step(
                "P5 差异对比标出新增行",
                "版本差异样本" in (diff_text or "")
                and js(
                    "document.querySelectorAll('#version-content .diff__row--add')"
                    ".length"
                )
                >= 1,
                str(diff_text)[:80],
            )
            js(
                "document.querySelector('.versions__tab[data-mode=\"preview\"]').click();true"
            )
            wait(
                "document.querySelectorAll('#version-content .versions__preview-body')"
                ".length === 1",
                "切到内容预览",
            )
            step("P5 差异 / 预览可切换")
            js(
                "window.__realConfirm = window.confirm;window.__chat = '';"
                "window.confirm = (message) => {window.__chat = message;return false;};true"
            )
            js("document.getElementById('restore-version').click();true")
            chat = js("window.__chat || ''")
            step(
                "P5 回滚确认文案含「由 #… 回滚至 #…，生成 #…」",
                "回滚至" in (chat or "") and "生成 #" in (chat or ""),
                str(chat),
            )
            js("window.confirm = window.__realConfirm;true")
            js("document.getElementById('close-versions').click();true")

            # ---- 阶段三 3.7 / §7.5 / 回归 24：快捷键注册表 + 键位标注 ----
            step(
                "按钮标注键位（title / aria-keyshortcuts）",
                "Ctrl+S" in (js("document.getElementById('save-chapter').title") or "")
                and js(
                    "document.getElementById('nav-search')"
                    ".getAttribute('aria-keyshortcuts')"
                )
                == "Control+Shift+F"
                and "Ctrl+N"
                in (js("document.getElementById('add-chapter').title") or ""),
            )

            # 焦点在正文里按 Ctrl+F：查找条打开并聚焦输入
            js("document.querySelector('.ql-editor').focus();true")
            text_before_find = js("document.querySelector('.ql-editor').innerText")
            key_event("f", ctrl=True, target="document.querySelector('.ql-editor')")
            wait(
                "document.getElementById('find-bar').hidden === false"
                " && document.activeElement === document.getElementById('find-input')",
                "Ctrl+F 打开查找条",
            )
            step("Ctrl+F 打开章内查找条并聚焦输入")

            # 输入即定位：第一章正文里「海风」出现 2 次
            js(
                "(function(){const i=document.getElementById('find-input');"
                "i.value='海风';i.dispatchEvent(new Event('input',{bubbles:true}));"
                "return true;})()"
            )
            wait(
                "document.getElementById('find-count').textContent === '1/2'",
                "查找命中 2 处",
            )
            step("查找条匹配数 n/N（海风 ×2）")
            uses_highlight = js(
                "typeof CSS !== 'undefined' && !!CSS.highlights"
                " && typeof Highlight === 'function'"
            )
            highlighted = js(
                "CSS.highlights.get('inkwell-find').size"
                if uses_highlight
                else "!getSelection().isCollapsed"
            )
            step(
                "命中高亮（Custom Highlight / Selection 降级）",
                highlighted == 2 if uses_highlight else highlighted is True,
                str(highlighted),
            )

            # Enter / Shift+Enter 在匹配间移动
            key_event("Enter", target="document.getElementById('find-input')")
            wait(
                "document.getElementById('find-count').textContent === '2/2'",
                "查找下一个",
            )
            key_event(
                "Enter",
                shift=True,
                target="document.getElementById('find-input')",
            )
            wait(
                "document.getElementById('find-count').textContent === '1/2'",
                "查找上一个",
            )
            step("Enter / Shift+Enter 切换匹配")

            # Esc 关闭，正文一字未改
            key_event("Escape", target="document.getElementById('find-input')")
            wait(
                "document.getElementById('find-bar').hidden === true",
                "Esc 关闭查找条",
            )
            step("Esc 关闭查找条")
            text_after_find = js("document.querySelector('.ql-editor').innerText")
            step(
                "查找不修改正文（回归 25）",
                text_before_find == text_after_find,
                f"{str(text_before_find)[:40]} → {str(text_after_find)[:40]}",
            )
            result.setdefault("checks", {})["find"] = {
                "highlight_api": uses_highlight,
                "matches": 2,
            }

            # IME 组合期间（isComposing）不误触
            key_event(
                "n",
                ctrl=True,
                target="document.querySelector('.ql-editor')",
                composing=True,
            )
            step(
                "IME 组合期间 Ctrl+N 不误触",
                js("document.getElementById('prompt-dialog').open") is False,
            )

            # 输入框内不触发（Ctrl+N），正文内触发
            js("document.getElementById('chapter-title').focus();true")
            key_event("n", ctrl=True, target="document.getElementById('chapter-title')")
            step(
                "输入框内 Ctrl+N 不误触（C-06）",
                js("document.getElementById('prompt-dialog').open") is False,
            )
            js("document.getElementById('chapter-title').blur();true")
            js("document.querySelector('.ql-editor').focus();true")
            key_event("n", ctrl=True, target="document.querySelector('.ql-editor')")
            wait(
                "document.getElementById('prompt-dialog').open === true",
                "正文内 Ctrl+N 新建章节",
            )
            js("document.querySelector('#prompt-dialog [data-dialog-cancel]').click()")
            wait(
                "document.getElementById('prompt-dialog').open === false",
                "关闭新建章节对话框",
            )
            step("正文内 Ctrl+N 新建章节（对话框可取消）")

            # Ctrl+S：保存 + 手动快照
            key_event("s", ctrl=True, target="document.querySelector('.ql-editor')")
            wait(
                "document.getElementById('status-note').textContent"
                ".includes('已存为版本')",
                "Ctrl+S 手动快照",
            )
            step("Ctrl+S 保存 + 手动快照（FR-5.5）")

            # Ctrl+Shift+V：版本历史
            key_event(
                "v",
                ctrl=True,
                shift=True,
                target="document.querySelector('.ql-editor')",
            )
            wait(
                "document.getElementById('versions-dialog').open === true",
                "Ctrl+Shift+V 版本历史",
            )
            step("Ctrl+Shift+V 打开版本历史")
            js("document.getElementById('close-versions').click();true")
            wait(
                "document.getElementById('versions-dialog').open === false",
                "关闭版本历史",
            )

            # ---- 阶段三 3.9 / 回归 21 + 22：大纲树右键菜单与拖拽排序 ----
            # 本节会改章节标题 / 状态 / 归属卷，所以放在「按标题找章节」的用例之后；
            # 之后的用例只按固定标题（超长章 / 五万章）与 API 断言，不受影响。

            def project_tree() -> dict:
                return client.get(f"/api/projects/{ids['project_id']}/volumes").json()[
                    "data"
                ]

            def chapter_by_title(wanted: str) -> dict | None:
                tree = project_tree()
                for volume in [*tree["volumes"], tree["default_volume"]]:
                    for chapter in volume["chapters"]:
                        if chapter["title"] == wanted:
                            return chapter
                return None

            def open_tree_menu(title_text: str) -> bool:
                """在章节节点上派发右键菜单（回归 22）。"""
                return js(
                    "(function(){const node=[...document.querySelectorAll"
                    "('.tree__chapter')].find(n=>n.textContent.includes('%s'));"
                    "if(!node) return false;"
                    "const r=node.getBoundingClientRect();"
                    "node.dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,"
                    "cancelable:true,clientX:Math.round(r.left+12),"
                    "clientY:Math.round(r.top+6)}));return true;})()" % title_text
                )

            def click_tree_menu(label: str) -> bool:
                return js(
                    "(function(){const item=[...document.querySelectorAll"
                    "('#tree-menu .menu__item')].find(n=>n.textContent.includes"
                    "('%s'));if(!item) return false;item.click();return true;})()"
                    % label
                )

            def drag_chapter(source_title: str, target_title: str) -> bool:
                """卷内拖拽：把 source 拖到 target 之前（回归 21）。"""
                return js(
                    "(function(){const all=[...document.querySelectorAll"
                    "('.tree__chapter')];"
                    "const src=all.find(n=>n.textContent.includes('%s'));"
                    "const dst=all.find(n=>n.textContent.includes('%s'));"
                    "if(!src||!dst) return false;"
                    "const dt=new DataTransfer();"
                    "src.dispatchEvent(new DragEvent('dragstart',{bubbles:true,"
                    "dataTransfer:dt}));"
                    "const r=dst.getBoundingClientRect();"
                    "const x=Math.round(r.left+10);const y=Math.round(r.top+3);"
                    "for (const type of ['dragover','drop']) {"
                    "dst.dispatchEvent(new DragEvent(type,{bubbles:true,"
                    "cancelable:true,dataTransfer:dt,clientX:x,clientY:y}));}"
                    "src.dispatchEvent(new DragEvent('dragend',{bubbles:true,"
                    "dataTransfer:dt}));return true;})()" % (source_title, target_title)
                )

            def drag_chapter_to_volume(source_title: str, volume_title: str) -> bool:
                """跨卷拖拽：把章节拖到目标卷标题上（= 追加到该卷末尾）。"""
                return js(
                    "(function(){const src=[...document.querySelectorAll"
                    "('.tree__chapter')].find(n=>n.textContent.includes('%s'));"
                    "if(!src) return false;"
                    "const sec=[...document.querySelectorAll('.volume')]"
                    ".find(s=>{const t=s.querySelector('.volume__title');"
                    "return t&&t.textContent.includes('%s');});"
                    "if(!sec) return false;"
                    "const header=sec.querySelector('.volume__header');"
                    "const dt=new DataTransfer();"
                    "src.dispatchEvent(new DragEvent('dragstart',{bubbles:true,"
                    "dataTransfer:dt}));"
                    "const r=header.getBoundingClientRect();"
                    "for (const type of ['dragover','drop']) {"
                    "header.dispatchEvent(new DragEvent(type,{bubbles:true,"
                    "cancelable:true,dataTransfer:dt,clientX:Math.round(r.left+6),"
                    "clientY:Math.round(r.top+4)}));}"
                    "src.dispatchEvent(new DragEvent('dragend',{bubbles:true,"
                    "dataTransfer:dt}));return true;})()" % (source_title, volume_title)
                )

            step("右键章节弹出菜单（回归 22）", open_tree_menu("第一章") is True)
            wait(
                "document.getElementById('tree-menu').hidden === false",
                "章节右键菜单可见",
            )
            menu_labels = js(
                "[...document.querySelectorAll('#tree-menu .menu__item')]"
                ".map(n=>n.textContent)"
            )
            step(
                "菜单含 打开 / 重命名 / 章节信息 / 标记定稿 / 删除",
                menu_labels
                == ["打开", "重命名…", "章节信息…", "标记定稿", "删除章节…"],
                json.dumps(menu_labels, ensure_ascii=False),
            )

            step("点菜单「重命名…」", click_tree_menu("重命名") is True)
            wait(
                "document.getElementById('chapter-info-dialog').open === true",
                "章节信息对话框",
            )
            step(
                "重命名时焦点落在标题输入框",
                js(
                    "document.activeElement"
                    " === document.getElementById('chapter-info-name')"
                )
                is True,
            )
            js(
                "(function(){const i=document.getElementById('chapter-info-name');"
                "i.value='第一章 改名';"
                "i.dispatchEvent(new Event('input',{bubbles:true}));"
                "document.getElementById('chapter-info-save').click();"
                "return true;})()"
            )
            wait(
                "document.getElementById('chapter-info-dialog').open === false"
                " && [...document.querySelectorAll('.tree__chapter')].some("
                "n=>n.textContent.includes('第一章 改名'))",
                "重命名生效",
            )
            renamed = client.get(f"/api/chapters/{ids['chapter_id']}").json()["data"]
            step(
                "章节信息保存后标题落库（回归 22）",
                renamed["title"] == "第一章 改名",
                renamed["title"],
            )

            step("右键第二章", open_tree_menu("第二章") is True)
            step("点菜单「标记定稿」（回归 22）", click_tree_menu("标记定稿") is True)
            wait(
                "document.getElementById('status-note').textContent"
                ".includes('已标记定稿')",
                "标记定稿提示",
            )
            finalized = chapter_by_title("第二章")
            step(
                "定稿后状态为 final",
                finalized is not None and finalized["status"] == "final",
                json.dumps(finalized, ensure_ascii=False)[:120],
            )
            version_rows = client.get(
                f"/api/chapters/{finalized['id']}/versions"
            ).json()["data"]["items"]
            step(
                "定稿生成 milestone 版本（回归 22）",
                any(row.get("change_type") == "milestone" for row in version_rows),
                str([row.get("change_type") for row in version_rows]),
            )

            js(
                "window.__realConfirm = window.confirm;"
                "window.confirm = () => true;true"
            )
            step("右键第二章准备删除", open_tree_menu("第二章") is True)
            step("点菜单「删除章节…」", click_tree_menu("删除章节") is True)
            wait(
                "document.getElementById('status-note').textContent"
                ".includes('已移入回收站')"
                " && ![...document.querySelectorAll('.tree__chapter')].some("
                "n=>n.textContent.includes('第二章'))",
                "章节删除进回收站",
            )
            step("删除后树里消失（回归 22）")
            trash = client.get("/api/trash").json()["data"]
            step(
                "回收站可见被删章节（回归 22）",
                any(item["title"] == "第二章" for item in trash["chapters"]),
                json.dumps(trash["chapters"], ensure_ascii=False)[:120],
            )
            js("window.confirm = window.__realConfirm;true")

            js(
                "window.__realConfirm = window.confirm;"
                "window.confirm = () => true;true"
            )
            js("document.getElementById('add-volume').click();true")
            wait(
                "document.getElementById('prompt-dialog').open === true",
                "新建卷对话框",
            )
            js(
                "(function(){const i=document.getElementById('prompt-input');"
                "i.value='第二卷';i.dispatchEvent(new Event('input',{bubbles:true}));"
                "document.querySelector('#prompt-dialog button[type=submit]')"
                ".click();return true;})()"
            )
            wait(
                "document.getElementById('status-note').textContent"
                ".includes('已新建卷并迁入')",
                "默认卷章节迁入新卷（C-04）",
            )
            js("window.confirm = window.__realConfirm;true")
            tree_after_adopt = project_tree()
            step(
                "首个命名卷创建时默认卷章节一次性迁入（C-04 / 回归 21）",
                len(tree_after_adopt["volumes"]) == 1
                and tree_after_adopt["volumes"][0]["title"] == "第二卷"
                and tree_after_adopt["default_volume"]["chapters"] == []
                and len(tree_after_adopt["volumes"][0]["chapters"]) == 3,
                json.dumps(
                    [
                        [volume["title"], [c["title"] for c in volume["chapters"]]]
                        for volume in tree_after_adopt["volumes"]
                    ],
                    ensure_ascii=False,
                ),
            )

            step(
                "卷内拖拽：五万章 → 第一章 改名 之前（回归 21）",
                drag_chapter("五万章", "第一章 改名") is True,
            )
            wait(
                "document.getElementById('status-note').textContent"
                ".includes('已移动')",
                "卷内拖拽生效",
            )
            order = [c["title"] for c in project_tree()["volumes"][0]["chapters"]]
            step(
                "卷内顺序按拖拽落库（回归 21）",
                order == ["五万章", "第一章 改名", "超长章"],
                json.dumps(order, ensure_ascii=False),
            )

            js("document.getElementById('add-volume').click();true")
            wait(
                "document.getElementById('prompt-dialog').open === true",
                "新建第三卷对话框",
            )
            js(
                "(function(){const i=document.getElementById('prompt-input');"
                "i.value='第三卷';i.dispatchEvent(new Event('input',{bubbles:true}));"
                "document.querySelector('#prompt-dialog button[type=submit]')"
                ".click();return true;})()"
            )
            wait(
                "[...document.querySelectorAll('.volume__title')].some("
                "t=>t.textContent === '第三卷')",
                "第三卷出现",
            )
            step("已有命名卷时新建卷不再触发迁入确认（回归 21）")
            step(
                "跨卷拖拽：超长章 → 第三卷（回归 21）",
                drag_chapter_to_volume("超长章", "第三卷") is True,
            )
            wait(
                "document.getElementById('status-note').textContent"
                ".includes('已移动')",
                "跨卷拖拽生效",
            )
            volumes_after_move = {
                volume["title"]: [c["title"] for c in volume["chapters"]]
                for volume in project_tree()["volumes"]
            }
            step(
                "跨卷后归属正确（回归 21）",
                volumes_after_move.get("第三卷") == ["超长章"]
                and volumes_after_move.get("第二卷") == ["五万章", "第一章 改名"],
                json.dumps(volumes_after_move, ensure_ascii=False),
            )

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
            key_event("f", ctrl=True, shift=True, target="document.body")
            wait(
                "document.getElementById('view-search').hidden === false"
                " && document.activeElement === document.getElementById('search-input')",
                "检索页（Ctrl+Shift+F）",
            )
            step("Ctrl+Shift+F 从项目列表直达全局搜索")
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

            # ---- 阶段三 3.6 / FR-7.4 / 回归 26：P6 搜索分页（120 条 → 6 页）----
            page_volume = client.post(
                f"/api/projects/{ids['project_id']}/volumes",
                json={"title": "分页卷"},
            ).json()["data"]
            for index in range(120):
                item = client.post(
                    f"/api/volumes/{page_volume['id']}/chapters",
                    json={"title": f"分页章 {index:03d}"},
                ).json()["data"]
                client.put(
                    f"/api/chapters/{item['id']}/content",
                    json={"content_html": "<p>分页样本</p>"},
                )
            js(
                "(function(){document.getElementById('search-input').value='分页样本';"
                "document.getElementById('search-scope').value='chapters';"
                "document.getElementById('search-go').click();return true;})()"
            )
            wait(
                "document.querySelectorAll('.search-hit').length === 20",
                "搜索首页 20 条",
            )
            step("P6 搜索首页 20 条")
            step(
                "P6「加载更多」可见",
                js("!document.getElementById('search-more').hidden") is True,
            )
            for expected in (40, 60, 80, 100, 120):
                js("document.getElementById('search-more').click();true")
                wait(
                    f"document.querySelectorAll('.search-hit').length === {expected}",
                    f"加载到 {expected} 条",
                )
            step("P6 120 条可翻到第 6 页")
            step(
                "P6 总数与后端一致且按钮隐藏",
                "共 120 条"
                in (js("document.getElementById('search-status').textContent") or "")
                and js("document.getElementById('search-more').hidden") is True,
                js("document.getElementById('search-status').textContent"),
            )

            # ---- 阶段三 3.6 / C-07 / 回归 27：P9 应用设置页 ----
            js("document.getElementById('nav-home').click()")
            wait(
                "document.getElementById('view-projects').hidden === false",
                "返回项目列表",
            )
            js("document.getElementById('open-settings').click()")
            wait(
                "document.getElementById('view-settings').hidden === false"
                " && document.querySelectorAll('#settings-info .settings__row')"
                ".length >= 5",
                "设置页与自检信息",
            )
            step("P9 设置页展示数据 / 磁盘 / schema")
            info = js("document.getElementById('settings-info').innerText")
            step(
                "P9 自检信息含数据目录与内容计数",
                "数据目录" in (info or "") and "章节" in (info or ""),
                str(info)[:80],
            )
            js(
                "window.__realConfirm = window.confirm;"
                "window.confirm = () => true;true"
            )
            wait(
                "document.getElementById('settings-cleanup-snapshots').disabled === false",
                "清理按钮可用",
            )
            js("document.getElementById('settings-cleanup-snapshots').click()")
            wait(
                "document.getElementById('settings-status').textContent"
                ".includes('已清理')",
                "清理过期快照",
            )
            step("P9 清理过期快照（#51）")
            js("window.confirm = window.__realConfirm;true")
            wait(
                "document.getElementById('settings-rebuild-fts').disabled === false",
                "重建按钮可用",
            )
            js("document.getElementById('settings-rebuild-fts').click()")
            wait(
                "document.getElementById('settings-status').textContent"
                ".includes('索引已重建')",
                "重建全文索引",
                45.0,
            )
            step("P9 重建全文索引（#42 长任务）")
            wait(
                "document.getElementById('settings-integrity').disabled === false",
                "自检按钮可用",
            )
            js("document.getElementById('settings-integrity').click()")
            try:
                wait(
                    "document.getElementById('settings-status').textContent"
                    ".includes('自检通过（完整')",
                    "完整自检",
                    45.0,
                )
            except SmokeError as exc:
                detail = js("document.getElementById('settings-status').textContent")
                context = _integrity_failure_detail(data_dir, client, detail)
                raise SmokeError(
                    f"完整自检未完成：{detail}｜现场："
                    f"{json.dumps(context, ensure_ascii=False)}"
                ) from exc
            step("P9 数据库自检（#52）")
            js("document.getElementById('settings-open-dir').click()")
            wait(
                "document.getElementById('settings-status').textContent"
                ".includes('已打开数据目录')",
                "打开数据目录",
            )
            step("P9 打开数据目录（桥接 open_data_dir）")
            step(
                "P9 诊断包入口存在",
                js("!!document.getElementById('settings-diagnostics')") is True,
            )

            # ---- 阶段三 3.6：P7 备份页 列表 / 出错态 / 重试 ----
            js("document.getElementById('close-settings').click()")
            wait(
                "document.getElementById('view-projects').hidden === false",
                "回到项目列表",
            )
            key_event("e", ctrl=True, shift=True, target="document.body")
            wait("document.getElementById('view-backup').hidden === false", "备份页")
            step("Ctrl+Shift+E 直达备份与导出页")
            # 迁移会先落一份 premigrate 备份，所以初始至少 1 条
            wait(
                "document.querySelectorAll('#backup-list .trash__row').length >= 1",
                "备份列表",
            )
            step("P7 备份列表可见（含迁移前备份）")
            before = js("document.querySelectorAll('#backup-list .trash__row').length")
            js("document.getElementById('backup-now').click()")
            wait(
                "document.getElementById('backup-status').textContent"
                ".includes('备份完成')",
                "备份完成",
                45.0,
            )
            wait(
                "document.querySelectorAll('#backup-list .trash__row').length"
                " === %d" % (before + 1),
                "新建备份后列表",
            )
            step("P7 立即备份后新增一条")
            js(
                "window.__realFetch = window.fetch;"
                "window.fetch = () => Promise.reject(new Error('模拟断网'));"
                "document.getElementById('refresh-backups').click();true"
            )
            wait(
                "document.querySelectorAll('#backup-list .list-state--error')"
                ".length === 1",
                "备份出错态",
            )
            step("P7 出错态可见（带重试）")
            js(
                "window.fetch = window.__realFetch;"
                "document.querySelector('#backup-list .list-state button')"
                ".click();true"
            )
            wait(
                "document.querySelectorAll('#backup-list .trash__row').length"
                " === %d" % (before + 1),
                "备份重试恢复",
            )
            step("P7 重试后恢复列表")
            js("document.getElementById('close-backup').click()")
            wait(
                "document.getElementById('view-projects').hidden === false",
                "回到项目列表",
            )

            # ---- 阶段三 3.6：P8 回收站 空态 / 出错态 / 重试 ----
            js("document.getElementById('open-trash').click()")
            wait("document.getElementById('view-trash').hidden === false", "回收站")
            # B2 步骤删掉了一篇设定文档，回收站里至少有一条
            wait(
                "document.querySelectorAll('#trash-list .trash__row').length >= 1",
                "回收站列表",
            )
            step("P8 回收站列表可见（含已删设定文档）")
            js(
                "window.__realFetch = window.fetch;"
                "window.fetch = () => Promise.reject(new Error('模拟断网'));"
                "document.getElementById('close-trash').click();"
                "document.getElementById('open-trash').click();true"
            )
            wait(
                "document.querySelectorAll('#trash-list .list-state--error')"
                ".length === 1",
                "回收站出错态",
            )
            step("P8 出错态可见（带重试）")
            js(
                "window.fetch = window.__realFetch;"
                "document.querySelector('#trash-list .list-state button')"
                ".click();true"
            )
            wait(
                "document.querySelectorAll('#trash-list .trash__row').length >= 1",
                "回收站重试恢复",
            )
            step("P8 重试后恢复列表")
            js("document.getElementById('close-trash').click()")
            wait(
                "document.getElementById('view-projects').hidden === false",
                "回到项目列表",
            )
            js("window.dispatchEvent(new Event('inkwell:projects-refresh'));true")

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

    # 中文 Windows 控制台默认 GBK：✓ / ⚠ 这类符号会让 print 抛 UnicodeEncodeError，
    # 把输出统一改成 UTF-8（不可编码字符替换，不中断冒烟）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
                js_api=TokenApi(config.token, config.data_dir),
                width=1100,
                height=760,
                text_select=True,
            )
            webview.start(
                make_driver(
                    window,
                    client,
                    ids,
                    config.data_dir,
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
