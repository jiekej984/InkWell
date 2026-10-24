"""用真实书库的副本给《天穹之外》截图，验证关系图修复（V2.0 / 5.9 补丁）。

检查点：
  1. 18 节点人物图的分层与连线弧度（节点不压在无关连线上）
  2. 阵营模式：关系线从阵营卡片上穿过，不再被挡住
  3. 节点可以拖出旧的 1200×800「空气墙」
  4. 双击节点真的会打开角色卡（自定义双击判定）

不修改真实书库：先把 `data/inkwell.db` 复制到临时目录，再以该目录启动。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests" / "e2e") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests" / "e2e"))

import window_smoke as ws

from backend.config import clear_proxy_env, ensure_data_dirs, load_config
from backend.database import Database
from backend.migrate import apply_migrations
from backend.server import create_app

VIEWPORT = (1280, 800)
OUT_DEFAULT = ROOT / "docs" / "版本更新" / "V2.0_截图"
SOURCE_DB = ROOT / "data" / "inkwell.db"
TITLE = "天穹之外"


class CaptureError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="示例书关系图截图")
    parser.add_argument("--out", default=str(OUT_DEFAULT))
    parser.add_argument("--label", default="5.9fix")
    parser.add_argument("--keep-data", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    if not SOURCE_DB.exists():
        print(f"找不到书库：{SOURCE_DB}")
        return 1

    data_dir = Path(tempfile.mkdtemp(prefix="inkwell-demo-graph-"))
    shutil.copy2(SOURCE_DB, data_dir / "inkwell.db")
    # SQLite WAL 里可能还有未合并的写入，一起复制才不会读到旧数据
    for suffix in ("-wal", "-shm"):
        source = SOURCE_DB.with_name(SOURCE_DB.name + suffix)
        if source.exists():
            shutil.copy2(source, data_dir / f"inkwell.db{suffix}")
    # 副本里清掉旧布局，按新算法（BFS 初始 + 松弛）重新算
    import sqlite3

    connection = sqlite3.connect(data_dir / "inkwell.db")
    connection.execute("DELETE FROM graph_layout")
    connection.commit()
    connection.close()
    os.environ["INKWELL_DATA_DIR"] = str(data_dir)
    clear_proxy_env()

    result: dict[str, Any] = {"label": args.label, "files": [], "errors": []}
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

        import webview

        window = webview.create_window(
            title="Inkwell 关系图验证",
            url=f"{config.base_url}/",
            js_api=ws.TokenApi(config.token, config.data_dir),
            width=VIEWPORT[0],
            height=VIEWPORT[1],
            text_select=True,
        )
        webview.start(
            make_driver(window, result, out_dir),
            debug=False,
            private_mode=False,
            storage_path=str(config.webview_storage_dir),
        )
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if thread is not None:
            thread.stop()
        if database is not None:
            database.dispose()
        result["data_dir"] = str(data_dir)
        if not args.keep_data:
            shutil.rmtree(data_dir, ignore_errors=True)

    manifest = out_dir / f"{args.label}_manifest.json"
    manifest.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for item in result["files"]:
        print(f"[OK] {item['name']}  {item['bytes']} bytes", flush=True)
    for error in result["errors"]:
        print(f"[FAIL] {error}", flush=True)
    print(
        f"结果：{'通过' if not result['errors'] else '失败'}"
        f"（{len(result['files'])} 张）→ {out_dir}",
        flush=True,
    )
    return 0 if not result["errors"] else 1


def make_driver(window: Any, result: dict[str, Any], out_dir: Path) -> Any:
    def driver() -> None:
        nonlocal window
        import webview
        from System import Action as SysAction

        window = webview.windows[0]
        deadline = time.time() + 10
        while window.native is None and time.time() < deadline:
            time.sleep(0.05)
        form = window.native
        if form is None:
            raise CaptureError("窗口 native 未就绪")

        def js(code: str) -> Any:
            return window.evaluate_js(code)

        def wait(code: str, label: str, timeout: float = 30.0) -> None:
            end = time.time() + timeout
            while time.time() < end:
                try:
                    if js(code):
                        return
                except Exception:
                    pass
                time.sleep(0.15)
            raise CaptureError(f"等待超时：{label}")

        def cdp(method: str, params: dict[str, Any]) -> dict[str, Any]:
            holder: dict[str, Any] = {}

            def call() -> None:
                holder["task"] = form.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(
                    method, json.dumps(params)
                )

            form.Invoke(SysAction(call))
            task = holder.get("task")
            if task is None:
                raise CaptureError(f"CDP {method} 未启动")
            task.Wait()
            return json.loads(task.Result or "{}")

        def capture(name: str) -> None:
            response = cdp("Page.captureScreenshot", {"format": "png"})
            raw = base64.b64decode(response["data"])
            path = out_dir / f"{result['label']}_{name}.png"
            path.write_bytes(raw)
            result["files"].append({"name": path.name, "bytes": len(raw)})
            print(f"[OK] {path.name}", flush=True)

        def step(name: str) -> None:
            time.sleep(0.5)
            capture(name)

        def mouse(kind: str, x: float, y: float, buttons: int) -> None:
            cdp(
                "Input.dispatchMouseEvent",
                {
                    "type": kind,
                    "x": x,
                    "y": y,
                    "button": "left" if kind != "mouseMoved" else "none",
                    "buttons": buttons,
                    "clickCount": 1 if kind != "mouseMoved" else 0,
                },
            )

        def node_rect(match: str) -> dict[str, float]:
            payload = js(
                """(() => {
  const node = [...document.querySelectorAll('.graph-node')]
    .find((item) => item.getAttribute('aria-label').includes(%s));
  if (!node) return null;
  const box = node.getBoundingClientRect();
  return JSON.stringify({
    x: box.x + box.width / 2,
    y: box.y + box.height / 2,
    label: node.getAttribute('aria-label'),
    transform: node.getAttribute('transform'),
  });
})()"""
                % json.dumps(match, ensure_ascii=False)
            )
            if not payload:
                raise CaptureError(f"找不到节点：{match}")
            return json.loads(payload)

        def drag_node(match: str, target: tuple[float, float]) -> str:
            rect = node_rect(match)
            start = (rect["x"], rect["y"])
            mouse("mousePressed", start[0], start[1], 1)
            for step_index in range(1, 7):
                x = start[0] + (target[0] - start[0]) * step_index / 6
                y = start[1] + (target[1] - start[1]) * step_index / 6
                mouse("mouseMoved", x, y, 1)
                time.sleep(0.04)
            mouse("mouseReleased", target[0], target[1], 0)
            time.sleep(0.4)
            return node_rect(match)["transform"]

        try:
            js(
                "window.__errs = [];"
                "window.addEventListener('error', e => window.__errs.push(String(e.message)));"
                "window.addEventListener('unhandledrejection', e =>"
                " window.__errs.push(String((e.reason && e.reason.message) || e.reason)));"
            )
            wait("document.querySelectorAll('.card').length >= 4", "作品列表")
            js(
                """(() => {
  const card = [...document.querySelectorAll('.card')]
    .find((item) => item.textContent.includes(%s));
  if (!card) return false;
  card.querySelectorAll('.card__actions .btn')[0].click();
  return true;
})()"""
                % json.dumps(TITLE, ensure_ascii=False)
            )
            wait("!document.getElementById('view-writer').hidden", "写作页")
            js("document.getElementById('open-characters').click()")
            wait(
                "!document.getElementById('view-characters').hidden"
                " && document.querySelectorAll('.character-row').length >= 10",
                "角色库",
            )
            js("document.getElementById('open-graph').click()")
            wait(
                "!document.getElementById('view-graph').hidden"
                " && document.querySelectorAll('.graph-node').length >= 18"
                " && document.getElementById('graph-status').textContent"
                ".includes('18 个角色')",
                "人物关系图",
                60,
            )
            step("P12_tianqiong_character")

            js("document.querySelector('.graph-mode[data-mode=\"organization\"]').click()")
            wait(
                "document.getElementById('graph-status').textContent"
                ".includes('个组织')"
                " && document.getElementById('graph-title').textContent"
                ".includes('组织')",
                "组织层级树",
                30,
            )
            step("P12_tianqiong_org")

            js("document.querySelector('.graph-mode[data-mode=\"faction\"]').click()")
            wait(
                "document.getElementById('graph-status').textContent"
                ".includes('个阵营')",
                "阵营全景",
                30,
            )
            step("P12_tianqiong_faction")

            js("document.querySelector('.graph-mode[data-mode=\"character\"]').click()")
            wait(
                "document.getElementById('graph-status').textContent"
                ".includes('18 个角色')",
                "回到人物图",
                60,
            )

            # 空气墙：先拖到角落（应超过旧的 1200×800 边界），再拖回中心
            before = node_rect("顾长庚")["transform"]
            corner = drag_node(
                "顾长庚", (VIEWPORT[0] - 90, VIEWPORT[1] - 70)
            )
            center = drag_node(
                "顾长庚", (VIEWPORT[0] / 2, VIEWPORT[1] / 2)
            )
            result["drag"] = {
                "before": before,
                "corner": corner,
                "center": center,
            }

            def coords(text: str) -> tuple[float, float]:
                match = re.search(r"translate\(([-\d.]+) ([-\d.]+)\)", text)
                if not match:
                    raise CaptureError(f"transform 解析失败: {text}")
                return float(match.group(1)), float(match.group(2))

            corner_x, corner_y = coords(corner)
            if corner_x <= 1200 and corner_y <= 800:
                result["errors"].append(
                    f"拖拽仍被旧边界限制：{corner_x:.1f}, {corner_y:.1f}"
                )
            if coords(center) == coords(corner):
                result["errors"].append("拖回中心时节点没有移动")
            if coords(center) == coords(before):
                result["errors"].append("拖回中心后位置与初始一致")

            # 双击：用 CDP 真实双击，验证打开角色卡
            js("document.getElementById('graph-relayout').click()")
            wait(
                "document.getElementById('graph-status').textContent"
                ".includes('18 个角色')",
                "重排",
                60,
            )
            rect = node_rect("顾长庚")
            for _ in range(2):
                mouse("mousePressed", rect["x"], rect["y"], 1)
                mouse("mouseReleased", rect["x"], rect["y"], 0)
                time.sleep(0.09)
            wait(
                "!document.getElementById('view-characters').hidden"
                " && document.getElementById('character-name').value.length > 0",
                "双击打开角色卡",
                20,
            )
            opened = js("document.getElementById('character-name').value")
            result["double_click"] = {"node": rect["label"], "opened": opened}
            if opened not in rect["label"]:
                result["errors"].append(
                    f"双击打开的角色不对：{opened} / {rect['label']}"
                )
        except Exception as exc:
            result["errors"].append(f"{type(exc).__name__}: {exc}")
            print(f"[FAIL] {type(exc).__name__}: {exc}", flush=True)
        finally:
            try:
                result["page_errors"] = js("window.__errs || []")
            except Exception:
                pass
            window.destroy()

    return driver


if __name__ == "__main__":
    raise SystemExit(main())
