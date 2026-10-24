"""阶段三 3.9：交互无障碍走查（真实窗口 + WebView2，按键走 CDP 真键位）。

与 `window_smoke.py` 的分工：
    · `window_smoke` 覆盖**功能链路**（写作 / 保存三态 / 检索 / 设置页 / 大纲树拖拽…）
    · 本脚本覆盖**键盘与无障碍**（回归 28）：Tab 顺序、对话框焦点陷阱 / Esc / 焦点归还、
      树节点方向键、`:focus-visible` 描边、真实渲染配色的 WCAG 对比度、100/125/150% 缩放。

**按键为什么走 CDP**：合成 `KeyboardEvent` 不会触发浏览器默认行为（Tab 移动焦点、
Enter 点击、Esc 关对话框都依赖默认行为），只有 `Input.dispatchKeyEvent` 才是真按键。

覆盖清单：
    1. Tab 顺序（项目列表 / 写作页）与「焦点只落在可交互元素上」
    2. 卡片 Enter 打开作品
    3. 对话框：首字段获焦 → Tab 不逃逸（焦点陷阱）→ Esc 关闭 → 焦点归还触发按钮
    4. 大纲树：↑/↓ 移动、← 折叠、→ 展开、Home 回首个
    5. 键盘聚焦时 `:focus-visible` 可见描边
    6. 对比度：正文 / 状态栏 / 树 / 按钮 / 提示文字（AA 4.5，大字 3.0）
    7. 缩放 100% / 125% / 150%：无横向溢出、编辑器行宽仍 ≤760

运行（推荐用项目 venv）：
    D:\\小说辅助\\.venv\\Scripts\\python.exe tests\\e2e\\a11y_walk.py
    ... --json           # 仅输出 JSON
    ... --keep-data      # 保留临时数据目录

退出码：0 全部通过；1 有检查失败（失败项与实测值在输出里）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests" / "e2e") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests" / "e2e"))

import window_smoke as ws

from backend.config import TOKEN_HEADER, clear_proxy_env, ensure_data_dirs, load_config
from backend.database import Database
from backend.migrate import apply_migrations
from backend.server import create_app

# CDP 按键定义：(key, code, windowsVirtualKeyCode)
TAB = ("Tab", "Tab", 9)
ENTER = ("Enter", "Enter", 13)
ESCAPE = ("Escape", "Escape", 27)
ARROW_UP = ("ArrowUp", "ArrowUp", 38)
ARROW_DOWN = ("ArrowDown", "ArrowDown", 40)
ARROW_LEFT = ("ArrowLeft", "ArrowLeft", 37)
ARROW_RIGHT = ("ArrowRight", "ArrowRight", 39)
HOME = ("Home", "Home", 36)

INTERACTIVE_SELECTOR = (
    "button,input,select,textarea,a[href],[role=button],[role=tab],"
    "[contenteditable=true],[tabindex]:not([tabindex='-1'])"
)

# 焦点探针：标签 / id / class / 是否可交互 / :focus-visible 描边
FOCUS_PROBE = """
(function () {
  const node = document.activeElement;
  if (!node) return 'null';
  const style = getComputedStyle(node);
  const label = (
    node.getAttribute('aria-label') ||
    node.getAttribute('title') ||
    node.textContent ||
    ''
  ).trim().slice(0, 24);
  return JSON.stringify({
    tag: node.tagName.toLowerCase(),
    id: node.id || '',
    cls: typeof node.className === 'string' ? node.className.trim() : '',
    interactive: node.matches(%s),
    outlineWidth: parseFloat(style.outlineWidth) || 0,
    outlineStyle: style.outlineStyle,
    label: label
  });
})()
""" % json.dumps(INTERACTIVE_SELECTOR)

# 对比度探针：选择器 → 取实际渲染的前景色与「最近的不透明背景色」
CONTRAST_PROBE = """
(function (pairs) {
  const parse = (text) => {
    const match = String(text || '').match(/[\\d.]+/g);
    return match ? match.slice(0, 3).map(Number) : null;
  };
  const channel = (value) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  const luminance = (rgb) =>
    0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
  const backgroundOf = (node) => {
    let current = node;
    while (current) {
      const style = getComputedStyle(current);
      const rgb = parse(style.backgroundColor);
      const alpha = (String(style.backgroundColor).match(/[\\d.]+/g) || [])[3];
      if (rgb && (alpha === undefined || Number(alpha) > 0.9)) return rgb;
      current = current.parentElement;
    }
    return [255, 255, 255];
  };
  const out = [];
  for (const [name, selector] of pairs) {
    const node = document.querySelector(selector);
    if (!node) {
      out.push({ name, missing: true });
      continue;
    }
    const style = getComputedStyle(node);
    const fg = parse(style.color);
    const bg = backgroundOf(node);
    const a = luminance(fg);
    const b = luminance(bg);
    const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const size = parseFloat(style.fontSize) || 16;
    const weight = Number(style.fontWeight) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    out.push({
      name,
      ratio: Math.round(ratio * 100) / 100,
      fontSize: size,
      large,
      threshold: large ? 3 : 4.5,
      fg: style.color,
      bg: style.backgroundColor
    });
  }
  return JSON.stringify(out);
})(%s)
"""

CONTRAST_PAIRS = [
    ("正文段落", ".ql-editor p"),
    ("章节标题输入", "#chapter-title"),
    ("状态栏字数", "#stat-chapter"),
    ("保存状态文案", "#save-status"),
    ("侧栏项目名", ".sidebar__title"),
    ("树节点标题", ".tree__chapter .tree__name"),
    ("树节点字数", ".tree__chapter .tree__count"),
    ("侧栏提示", ".sidebar__hint"),
    ("顶栏按钮", "#open-settings"),
    ("作品卡片标题", ".card__title"),
]


def _max_width_ok(value: str) -> bool:
    """``max-width`` 实测值是否仍在 760px 以内（空值/未设置视为通过）。"""
    text = str(value or "").strip()
    if not text or text == "none":
        return True
    try:
        return float(text.replace("px", "")) <= 760
    except ValueError:
        return True


class A11yError(RuntimeError):
    """走查失败（消息里带检查项）。"""


def make_driver(
    window: Any,
    client: httpx.Client,
    ids: dict[str, int],
    data_dir: Path,
    timeout: float,
    result: dict[str, Any],
    quiet: bool,
) -> Any:
    """返回 pywebview 启动回调：真实按键走查 + 探针，收集检查结果。"""

    def js(code: str) -> Any:
        return window.evaluate_js(code)

    def wait(code: str, label: str, limit: float | None = None) -> None:
        deadline = time.time() + (limit or timeout)
        while time.time() < deadline:
            try:
                if js(code):
                    return
            except Exception:
                pass
            time.sleep(0.1)
        raise A11yError(f"超时未满足：{label}")

    def check(name: str, ok: bool, detail: Any = "") -> None:
        """记录一项检查（不中断：一趟走查要把问题都跑出来）。"""
        item = {"name": name, "ok": bool(ok), "detail": str(detail)[:400]}
        result["checks"].append(item)
        if not quiet:
            mark = "PASS" if ok else "FAIL"
            print(f"[{mark}] {name}" + (f"｜{detail}" if detail else ""), flush=True)

    def driver() -> None:
        nonlocal window
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

            import webview
            from System import Action as SysAction

            window = webview.windows[0]
            deadline = time.time() + 10
            while window.native is None and time.time() < deadline:
                time.sleep(0.05)
            form = window.native
            if form is None:
                raise A11yError("窗口 native 未就绪（无法发真实按键）")

            def press(
                spec: tuple[str, str, int], modifiers: int = 0, text: str | None = None
            ) -> None:
                """真实按键，触发浏览器默认行为。

                注：Enter 这类「会触发默认动作（按钮点击 / 表单提交）」的键必须带
                ``text``（keyDown + text），否则 WebView2 只当 rawKeyDown 不做默认动作。
                """
                key, code, vk = spec
                for event_type in ("rawKeyDown", "keyUp"):
                    payload: dict[str, Any] = {
                        "type": event_type,
                        "key": key,
                        "code": code,
                        "windowsVirtualKeyCode": vk,
                        "nativeVirtualKeyCode": vk,
                        "modifiers": modifiers,
                    }
                    if text and event_type == "rawKeyDown":
                        payload["type"] = "keyDown"
                        payload["text"] = text
                    holder: dict[str, Any] = {}

                    def start(params: dict[str, Any] = payload) -> None:
                        core = form.webview.CoreWebView2
                        holder["task"] = core.CallDevToolsProtocolMethodAsync(
                            "Input.dispatchKeyEvent", json.dumps(params)
                        )

                    form.Invoke(SysAction(start))
                    holder["task"].Wait()
                    time.sleep(0.02)

            def focus_probe() -> dict:
                raw = js(FOCUS_PROBE)
                return json.loads(raw) if raw else {"interactive": False}

            def tab_stops(count: int) -> list[dict]:
                stops = []
                for _ in range(count):
                    press(TAB)
                    time.sleep(0.05)
                    stops.append(focus_probe())
                return stops

            def blur_all() -> None:
                js(
                    "(function(){if(document.activeElement&&"
                    "document.activeElement.blur)document.activeElement.blur();"
                    "return true;})()"
                )

            result["checks"] = []

            # ---- 1. Tab 顺序（项目列表）----------------------------------
            blur_all()
            stops = tab_stops(6)
            ids_seen = [stop.get("id") or stop.get("cls", "") for stop in stops]
            check(
                "Tab 顺序：顶栏「搜索 → 设置」在最前",
                ids_seen[:2] == ["nav-search", "open-settings"],
                json.dumps(ids_seen[:3], ensure_ascii=False),
            )
            check(
                "Tab 落在作品卡片（role=button）",
                any("card" in (stop.get("cls") or "") for stop in stops),
                json.dumps(ids_seen, ensure_ascii=False),
            )
            check(
                "Tab 只停在可交互元素上",
                all(stop.get("interactive") for stop in stops),
                json.dumps([s.get("tag") for s in stops], ensure_ascii=False),
            )

            # ---- 2. Enter 打开作品 ----------------------------------------
            js(
                "(function(){const card=document.querySelector('.card');"
                "card.focus();return document.activeElement===card;})()"
            )
            press(ENTER, text="\r")
            wait(
                "document.getElementById('view-writer').hidden === false"
                " && !!document.querySelector('.ql-editor')",
                "Enter 打开写作页",
            )
            check("Enter 可打开作品（卡片 role=button）", True)

            # ---- 3. 写作页 Tab 覆盖关键控件 -------------------------------
            blur_all()
            stops = tab_stops(36)
            seen = set()
            for stop in stops:
                if stop.get("id"):
                    seen.add(f"#{stop['id']}")
                if stop.get("cls"):
                    for part in stop["cls"].split():
                        seen.add(f".{part}")
                    # Quill 给容器/工具栏补的类
                    if "ql-editor" in stop["cls"]:
                        seen.add(".ql-editor")
                    if "ql-toolbar" in stop.get("cls", ""):
                        seen.add(".ql-toolbar")
            required = {
                "#nav-home",
                "#add-volume",
                "#add-chapter",
                "#chapter-title",
                ".ql-editor",
                "#manual-snapshot",
                "#open-versions",
                "#save-chapter",
            }
            toolbar_seen = sum(
                1
                for stop in stops
                if any(
                    part.startswith("ql-") for part in (stop.get("cls") or "").split()
                )
            )
            check(
                "写作页 Tab 可达：侧栏 / 标题 / 工具栏 / 正文 / 状态栏",
                required.issubset(seen) and toolbar_seen >= 3,
                json.dumps(
                    {
                        "missing": sorted(required - seen),
                        "toolbar": toolbar_seen,
                        "path": [s.get("id") or s.get("cls", "")[:18] for s in stops],
                    },
                    ensure_ascii=False,
                ),
            )
            check(
                "写作页 Tab 只停在可交互元素上",
                all(stop.get("interactive") for stop in stops),
                json.dumps([s.get("tag") for s in stops], ensure_ascii=False),
            )
            outlined = [
                stop
                for stop in stops
                if stop.get("outlineStyle") != "none"
                and stop.get("outlineWidth", 0) >= 2
            ]
            check(
                "键盘聚焦有可见描边（:focus-visible，≥2px）",
                len(outlined) >= 3,
                json.dumps(
                    [
                        [s.get("id") or s.get("cls", "")[:18], s.get("outlineWidth")]
                        for s in stops[:8]
                    ],
                    ensure_ascii=False,
                ),
            )

            # ---- 4. 大纲树方向键 ------------------------------------------
            js(
                "(function(){const node=document.querySelector('.tree__chapter');"
                "if(!node) return false;node.focus();return true;})()"
            )
            before = js(
                "(function(){const n=document.activeElement;"
                "return n&&n.dataset?n.dataset.chapterId:'';})()"
            )
            press(ARROW_DOWN)
            time.sleep(0.1)
            after = js(
                "(function(){const n=document.activeElement;"
                "return n&&n.dataset?n.dataset.chapterId:'';})()"
            )
            check(
                "树节点 ↓ 移动到下一章",
                bool(before) and bool(after) and before != after,
                f"{before} → {after}",
            )
            press(HOME)
            time.sleep(0.1)
            first = js(
                "(function(){const n=document.activeElement;"
                "return n&&n.dataset?n.dataset.chapterId:'';})()"
            )
            check("树节点 Home 回到首个", first == before, f"{first} / {before}")
            expanded_before = js(
                "(function(){const t=document.querySelector('.volume__toggle');"
                "return t?t.getAttribute('aria-expanded'):'';})()"
            )
            press(ARROW_LEFT)
            time.sleep(0.1)
            collapsed = js(
                "(function(){const t=document.querySelector('.volume__toggle');"
                "return t?t.getAttribute('aria-expanded'):'';})()"
            )
            focus_after_collapse = js(
                "(function(){const n=document.activeElement;"
                "return n&&typeof n.className==='string'?n.className:'';})()"
            )
            press(ARROW_RIGHT)
            time.sleep(0.1)
            expanded = js(
                "(function(){const t=document.querySelector('.volume__toggle');"
                "return t?t.getAttribute('aria-expanded'):'';})()"
            )
            check(
                "树节点 ← 折叠 / → 展开",
                expanded_before == "true"
                and collapsed == "false"
                and expanded == "true",
                f"{expanded_before} → {collapsed} → {expanded}",
            )
            check(
                "折叠后焦点不丢失（落在卷折叠按钮上）",
                "volume__toggle" in (focus_after_collapse or ""),
                focus_after_collapse,
            )

            # ---- 5. 对话框：焦点 / 陷阱 / Esc / 归还 -----------------------
            js(
                "(function(){const b=document.getElementById('add-chapter');"
                "b.focus();return document.activeElement===b;})()"
            )
            press(ENTER, text="\r")
            wait(
                "document.getElementById('prompt-dialog').open === true",
                "新建章节对话框",
            )
            check(
                "对话框打开后焦点在首个输入框",
                js("document.activeElement === document.getElementById('prompt-input')")
                is True,
                focus_probe().get("id", ""),
            )
            inside = []
            for _ in range(4):
                press(TAB)
                time.sleep(0.05)
                inside.append(
                    js(
                        "document.getElementById('prompt-dialog')"
                        ".contains(document.activeElement)"
                    )
                    is True
                )
            check(
                "对话框 Tab 不逃逸（焦点陷阱）",
                all(inside),
                json.dumps(inside),
            )
            press(ESCAPE)
            wait(
                "document.getElementById('prompt-dialog').open === false",
                "Esc 关闭对话框",
            )
            check("Esc 关闭对话框", True)
            check(
                "关闭后焦点归还触发按钮",
                js("document.activeElement === document.getElementById('add-chapter')")
                is True,
                focus_probe().get("id", ""),
            )

            # ---- 6. 对比度（真实渲染配色）---------------------------------
            rows = json.loads(js(CONTRAST_PROBE % json.dumps(CONTRAST_PAIRS)))
            result["contrast"] = rows
            measured = [row for row in rows if not row.get("missing")]
            check(
                "对比度样本可测（≥8 组）",
                len(measured) >= 8,
                f"{len(measured)}/{len(rows)}",
            )
            low = [row for row in measured if row["ratio"] < row["threshold"] - 0.001]
            check(
                "对比度满足 AA（正文 4.5 / 大字 3.0）",
                not low,
                json.dumps(
                    [[row["name"], row["ratio"], row["threshold"]] for row in low]
                    or [[row["name"], row["ratio"]] for row in measured],
                    ensure_ascii=False,
                ),
            )

            # ---- 7. 缩放 100% / 125% / 150% -------------------------------
            zoom_mode = "ZoomFactor"

            def set_zoom(factor: float) -> None:
                holder: dict[str, Any] = {}

                def start() -> None:
                    try:
                        form.webview.ZoomFactor = factor
                    except Exception as exc:
                        holder["error"] = str(exc)

                form.Invoke(SysAction(start))
                time.sleep(0.5)
                if holder.get("error"):
                    nonlocal zoom_mode
                    zoom_mode = "css-zoom"
                    js(
                        "document.documentElement.style.zoom = %s;true"
                        % json.dumps(str(factor))
                    )
                    time.sleep(0.3)

            zoom_rows = []
            for factor in (1.0, 1.25, 1.5):
                set_zoom(factor)
                probe = json.loads(
                    js(
                        "(function(){const root=document.documentElement;"
                        "const editor=document.querySelector('.ql-editor');"
                        "const style=editor?getComputedStyle(editor):null;"
                        "return JSON.stringify({innerWidth:innerWidth,"
                        "scrollWidth:root.scrollWidth,clientWidth:root.clientWidth,"
                        "editorMax:style?style.maxWidth:'',"
                        "statusbar:!!document.querySelector('.statusbar'),"
                        "sidebar:!!document.querySelector('.sidebar')});})()"
                    )
                )
                overflow = probe["scrollWidth"] - probe["clientWidth"]
                zoom_rows.append(
                    {
                        "factor": factor,
                        "innerWidth": probe["innerWidth"],
                        "overflow": overflow,
                        "editorMax": probe["editorMax"],
                        "statusbar": probe["statusbar"],
                        "sidebar": probe["sidebar"],
                    }
                )
            set_zoom(1.0)
            result["zoom"] = {"mode": zoom_mode, "rows": zoom_rows}
            check(
                "100/125/150% 缩放无横向溢出且关键区域可见",
                all(
                    row["overflow"] <= 2 and row["statusbar"] and row["sidebar"]
                    for row in zoom_rows
                ),
                json.dumps(zoom_rows, ensure_ascii=False),
            )
            check(
                "缩放各档正文行宽仍 ≤760px",
                all(_max_width_ok(row["editorMax"]) for row in zoom_rows),
                json.dumps([row["editorMax"] for row in zoom_rows]),
            )

            # ---- 8. 页面无 JS 异常 ----------------------------------------
            errors = js("window.__errs || []")
            check(
                "页面无 JS 异常", errors == [], json.dumps(errors, ensure_ascii=False)
            )
            result["ok"] = all(item["ok"] for item in result["checks"])
        except A11yError as exc:
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
    parser = argparse.ArgumentParser(
        description="Inkwell 键盘与无障碍走查（3.9 / 回归 28）"
    )
    parser.add_argument("--json", action="store_true", help="仅输出 JSON 结果")
    parser.add_argument("--keep-data", action="store_true", help="保留临时数据目录")
    parser.add_argument(
        "--timeout", type=float, default=20.0, help="单步等待上限（秒）"
    )
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    data_dir = Path(tempfile.mkdtemp(prefix="inkwell-a11y-"))
    os.environ["INKWELL_DATA_DIR"] = str(data_dir)
    clear_proxy_env()

    result: dict[str, Any] = {
        "ok": False,
        "checks": [],
        "errors": [],
        "data_dir": "",
        "contrast": [],
        "zoom": {},
    }
    database: Database | None = None
    thread: ws.UvicornThread | None = None

    try:
        config = load_config()
        ensure_data_dirs(config)
        database = Database(config.db_path)
        schema_version = apply_migrations(database, config.data_dir)

        app = create_app(config, database)
        app.state.schema_version = schema_version
        thread = ws.UvicornThread(app, config.host, config.port)
        thread.start()
        thread.wait_started()

        client = httpx.Client(
            base_url=config.base_url,
            trust_env=False,
            timeout=10.0,
            headers={TOKEN_HEADER: config.token},
        )
        try:
            ids = ws.seed(client)
            import webview

            window = webview.create_window(
                title="Inkwell 无障碍走查",
                url=f"{config.base_url}/",
                js_api=ws.TokenApi(config.token, config.data_dir),
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
        passed = sum(1 for item in result["checks"] if item["ok"])
        print(flush=True)
        print(
            f"结果：{'通过' if result['ok'] else '失败'}"
            f"（{passed}/{len(result['checks'])} 项检查通过）",
            flush=True,
        )
        if result["contrast"]:
            print("对比度实测：", flush=True)
            for row in result["contrast"]:
                if row.get("missing"):
                    print(f"  - {row['name']}：样本缺失", flush=True)
                    continue
                print(
                    f"  - {row['name']}：{row['ratio']}:1"
                    f"（阈值 {row['threshold']}，{row['fontSize']}px）",
                    flush=True,
                )
        if result["zoom"].get("rows"):
            mode = result["zoom"].get("mode")
            print(f"缩放实测（{mode}）：", flush=True)
            for row in result["zoom"]["rows"]:
                print(
                    f"  - {int(row['factor'] * 100)}%：视口 {row['innerWidth']}px，"
                    f"横向溢出 {row['overflow']}px，正文 maxWidth {row['editorMax']}",
                    flush=True,
                )
        for error in result["errors"]:
            print(f"  - {error}", flush=True)
        if args.keep_data:
            print(f"临时数据目录：{data_dir}", flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
