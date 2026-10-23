"""阶段三 UI 截图基线（任务 3.0 / 3.9）。

用真实窗口 + WebView2 CDP 抓**页面内容**截图（不受窗口遮挡影响），
作为 UI 改动前后的视觉对照；每次跑都用临时数据目录，不读写项目 ``data/``。

运行：
    D:\\小说辅助\\.venv\\Scripts\\python.exe tests\\e2e\\capture_ui.py
    ... --out "版本更新/阶段三_截图" --label baseline
    ... --json          # 仅输出 JSON 清单
    ... --keep-data     # 保留临时数据目录

输出：
    <out>/<label>_P1_projects.png ... <out>/<label>_P8_trash.png
    <out>/<label>_manifest.json（视口尺寸、文件清单、备注、页面异常）

说明：P9「应用设置页」目前不存在，基线不产出截图（清单里注明）。
退出码：0 全部抓取成功；1 任一步失败。
"""

from __future__ import annotations

import argparse
import base64
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

VIEWPORT = (1280, 800)
CAPTURES = [
    ("P1_projects", "项目列表（两张卡片 + 空态外）"),
    ("P2_writer", "写作页（大纲树 + 编辑器 + 状态栏）"),
    ("P3_documents", "设定文档页"),
    ("P4_project_settings", "项目设置对话框"),
    ("P5_versions", "版本历史弹窗"),
    ("P6_search", "全局搜索（命中 + 高亮）"),
    ("P7_backup", "备份与导出页"),
    ("P8_trash", "回收站页"),
]


class CaptureError(RuntimeError):
    """截图失败（带步骤名）。"""


def seed(client: httpx.Client) -> dict[str, Any]:
    """造出各页面都有内容的样例数据。"""
    project = client.post(
        "/api/projects",
        json={
            "title": "长夜将尽",
            "description": "一部关于潮汐与灯塔的长篇。",
            "status": "writing",
            "target_word_count": 200000,
            "tags": ["奇幻", "连载"],
        },
    ).json()["data"]
    pid = project["id"]
    tree = client.get(f"/api/projects/{pid}/volumes").json()["data"]
    default_vid = tree["default_volume"]["id"]
    volume = client.post(
        f"/api/projects/{pid}/volumes", json={"title": "第一卷 潮汐"}
    ).json()["data"]
    vid = volume["id"]

    def chapter(title: str, html: str) -> int:
        detail = client.post(
            f"/api/volumes/{vid}/chapters", json={"title": title}
        ).json()["data"]
        saved = client.put(
            f"/api/chapters/{detail['id']}/content",
            json={"content_html": html},
        ).json()
        assert saved["code"] == 0, saved
        return detail["id"]

    first = chapter(
        "第一章 码头",
        "<p>深夜的码头，海风带着咸味。她低声说：“走吧。”</p><p>潮水退去，露出半截旧船。</p>",
    )
    chapter(
        "第二章 灯塔",
        "<p>灯塔的光每隔七秒扫过一次海面。</p>",
    )
    # 默认卷章节：用于暴露「创建命名卷后默认卷章节不可达」的现状（C-04）
    prologue = client.post(
        f"/api/volumes/{default_vid}/chapters", json={"title": "楔子"}
    ).json()["data"]
    client.put(
        f"/api/chapters/{prologue['id']}/content",
        json={"content_html": "<p>这是写在默认卷里的楔子。</p>"},
    )

    client.post(
        f"/api/projects/{pid}/documents",
        json={
            "title": "世界观 · 潮汐历法",
            "category": "world",
            "content_html": "<p>潮汐历法：海风与月相决定潮位。</p>",
        },
    )
    client.post(
        f"/api/projects/{pid}/documents",
        json={
            "title": "人物 · 守塔人",
            "category": "faction",
            "content_html": "<p>守塔人世代居住在北礁。</p>",
        },
    )

    # 版本历史：两次手动快照
    for _ in range(2):
        client.post(f"/api/chapters/{first}/versions", json={"change_type": "manual"})

    # 回收站：一篇废弃章节
    draft = client.post(
        f"/api/volumes/{vid}/chapters", json={"title": "废稿 · 删掉的段落"}
    ).json()["data"]
    client.put(
        f"/api/chapters/{draft['id']}/content",
        json={"content_html": "<p>这段不要了。</p>"},
    )
    client.delete(f"/api/chapters/{draft['id']}")

    # 第二本书：卡片多样性与空项目
    second = client.post(
        "/api/projects",
        json={"title": "短篇练习集", "description": "零散短篇。", "status": "paused"},
    ).json()["data"]

    # 备份页至少有一条手动备份
    backup = client.post("/api/backup").json()
    assert backup["code"] == 0, backup

    # 最近打开时间：让「长夜将尽」排前面
    client.patch(f"/api/projects/{pid}", json={"last_chapter_id": first})

    return {
        "project_id": pid,
        "chapter_id": first,
        "second_project_id": second["id"],
        "backup": backup.get("data", {}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inkwell UI 截图基线")
    parser.add_argument(
        "--out",
        default=str(ROOT / "版本更新" / "阶段三_截图"),
        help="输出目录",
    )
    parser.add_argument("--label", default="baseline", help="文件名前缀")
    parser.add_argument("--json", action="store_true", help="仅输出 JSON 清单")
    parser.add_argument("--keep-data", action="store_true", help="保留临时数据目录")
    args = parser.parse_args(argv)

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    data_dir = Path(tempfile.mkdtemp(prefix="inkwell-capture-"))
    os.environ["INKWELL_DATA_DIR"] = str(data_dir)
    clear_proxy_env()

    result: dict[str, Any] = {
        "label": args.label,
        "viewport": list(VIEWPORT),
        "files": [],
        "errors": [],
        "notes": [
            "P9 应用设置页当前不存在，基线无截图（阶段三 3.6 新建）",
            "截图通过 WebView2 CDP Page.captureScreenshot 获取，为页面内容区（不含窗口标题栏）",
        ],
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
            result["seed"] = seed(client)

            import webview

            window = webview.create_window(
                title="Inkwell UI 基线",
                url=f"{config.base_url}/",
                js_api=ws.TokenApi(config.token),
                width=VIEWPORT[0],
                height=VIEWPORT[1],
                text_select=True,
            )
            webview.start(
                make_driver(window, result["seed"], result, args, out_dir),
                debug=False,
                private_mode=False,
            )
            result["page_errors"] = result.get("page_errors", [])
        finally:
            client.close()
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

    manifest_path = out_dir / f"{args.label}_manifest.json"
    manifest_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result["manifest"] = str(manifest_path)

    if args.json:
        print(json.dumps(result, ensure_ascii=True), flush=True)
    else:
        for item in result["files"]:
            print(f"[OK] {item['name']}  {item['bytes']} bytes", flush=True)
        for error in result["errors"]:
            print(f"[FAIL] {error}", flush=True)
        print(
            f"结果：{'通过' if not result['errors'] else '失败'}"
            f"（{len(result['files'])} 张）→ {out_dir}",
            flush=True,
        )
    return 0 if not result["errors"] and len(result["files"]) == len(CAPTURES) else 1


def make_driver(
    window: Any,
    ids: dict[str, Any],
    result: dict[str, Any],
    args: argparse.Namespace,
    out_dir: Path,
) -> Any:
    """返回 pywebview 启动回调：逐页导航并截图。"""
    descriptions = dict(CAPTURES)

    def js(code: str) -> Any:
        return window.evaluate_js(code)

    def wait(code: str, label: str, timeout: float = 20.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if js(code):
                    return
            except Exception:
                pass
            time.sleep(0.15)
        raise CaptureError(f"超时：{label}")

    def driver() -> None:
        nonlocal window
        import webview
        from System import Action as SysAction

        # create_window 返回的包装对象在部分后端上取不到 native，
        # 统一从 webview.windows 取运行中的窗口实例（与 window_smoke 一致）。
        window = webview.windows[0]
        deadline = time.time() + 10
        while window.native is None and time.time() < deadline:
            time.sleep(0.05)
        form = window.native
        if form is None:
            raise CaptureError("窗口 native 未就绪")

        def capture(name: str) -> None:
            holder: dict[str, Any] = {}

            def start() -> None:
                core = form.webview.CoreWebView2
                holder["task"] = core.CallDevToolsProtocolMethodAsync(
                    "Page.captureScreenshot", json.dumps({"format": "png"})
                )

            form.Invoke(SysAction(start))
            task = holder.get("task")
            if task is None:
                raise CaptureError(f"{name}: CDP 调用未启动")
            task.Wait()
            raw = base64.b64decode(json.loads(task.Result)["data"])
            path = out_dir / f"{args.label}_{name}.png"
            path.write_bytes(raw)
            result["files"].append(
                {
                    "name": path.name,
                    "bytes": len(raw),
                    "description": descriptions.get(name, ""),
                }
            )

        def step(name: str) -> None:
            time.sleep(0.45)  # 等一帧渲染/过渡落定
            capture(name)
            if not args.json:
                print(f"[OK] {args.label}_{name}.png", flush=True)

        try:
            js(
                "window.__errs = [];"
                "window.addEventListener('error', e =>"
                " window.__errs.push(String(e.message)));"
                "window.addEventListener('unhandledrejection', e =>"
                " window.__errs.push(String((e.reason && e.reason.message)"
                " || e.reason)));"
            )
            result["inner"] = json.loads(
                js("JSON.stringify({w: innerWidth, h: innerHeight})")
            )
            wait("document.querySelectorAll('.card').length >= 2", "项目列表")
            step("P1_projects")

            js(
                "document.querySelector('.card[data-id=\"%d\"]')"
                ".querySelectorAll('.card__actions .btn')[0].click()"
                % ids["project_id"]
            )
            wait(
                "!document.getElementById('view-writer').hidden"
                " && document.querySelectorAll('.tree__chapter').length >= 2",
                "写作页",
            )
            step("P2_writer")
            result["checks"] = {
                "tree_volumes": js("document.querySelectorAll('.volume').length"),
                "tree_chapters": js(
                    "document.querySelectorAll('.tree__chapter').length"
                ),
                "status_text": js("document.getElementById('save-status').textContent"),
                "statusbar": js("document.querySelector('.statusbar').innerText"),
                "editor_font_size": js(
                    "getComputedStyle(document.querySelector('.ql-editor')).fontSize"
                ),
                "editor_line_height": js(
                    "getComputedStyle(document.querySelector('.ql-editor')).lineHeight"
                ),
                "editor_max_width": js(
                    "getComputedStyle(document.querySelector('.ql-editor')).maxWidth"
                ),
                "body_bg": js("getComputedStyle(document.body).backgroundColor"),
                "sidebar_bg": js(
                    "getComputedStyle(document.querySelector('.sidebar'))"
                    ".backgroundColor"
                ),
                "statusbar_bg": js(
                    "getComputedStyle(document.querySelector('.statusbar'))"
                    ".backgroundColor"
                ),
                "focus_visible_supported": js(
                    "CSS.supports('selector(:focus-visible)')"
                ),
            }

            js("document.getElementById('open-versions').click()")
            wait('document.getElementById("versions-dialog").open === true', "版本弹窗")
            wait(
                "document.querySelectorAll('.versions__list > *').length > 0",
                "版本列表",
            )
            step("P5_versions")
            js("document.getElementById('close-versions').click()")

            js("document.getElementById('open-documents').click()")
            wait("document.getElementById('view-documents').hidden === false", "设定页")
            wait("document.querySelectorAll('.tree__chapter').length >= 2", "设定列表")
            step("P3_documents")
            js("document.getElementById('back-to-writer').click()")
            wait(
                "document.getElementById('view-writer').hidden === false", "返回写作页"
            )

            js("document.getElementById('nav-home').click()")
            wait(
                "document.getElementById('view-projects').hidden === false", "项目列表"
            )
            js(
                "document.querySelector('.card[data-id=\"%d\"]')"
                ".querySelectorAll('.card__actions .btn')[1].click()"
                % ids["second_project_id"]
            )
            wait('document.getElementById("project-dialog").open === true', "项目设置")
            step("P4_project_settings")
            js("document.getElementById('project-dialog').close()")

            js("document.getElementById('nav-search').click()")
            wait("document.getElementById('view-search').hidden === false", "搜索页")
            js(
                "(function(){const input=document.getElementById('search-input');"
                "input.value='海风';"
                "document.getElementById('search-go').click();return true;})()"
            )
            wait("document.querySelectorAll('.search-hit').length > 0", "搜索命中")
            step("P6_search")
            js("document.getElementById('close-search').click()")
            wait(
                "document.getElementById('view-projects').hidden === false", "项目列表"
            )

            js("document.getElementById('open-backup').click()")
            wait("document.getElementById('view-backup').hidden === false", "备份页")
            wait("document.querySelectorAll('#backup-list > *').length > 0", "备份列表")
            step("P7_backup")
            js("document.getElementById('close-backup').click()")
            wait(
                "document.getElementById('view-projects').hidden === false", "项目列表"
            )

            js("document.getElementById('open-trash').click()")
            wait("document.getElementById('view-trash').hidden === false", "回收站")
            wait(
                "document.querySelectorAll('#trash-list > *').length > 0", "回收站列表"
            )
            step("P8_trash")

            result["page_errors"] = js("window.__errs || []")
        except Exception as exc:
            result["errors"].append(f"{type(exc).__name__}: {exc}")
            if not args.json:
                print(f"[FAIL] {exc}", flush=True)
        finally:
            try:
                result["page_errors"] = result.get("page_errors") or js(
                    "window.__errs || []"
                )
            except Exception:
                pass
            window.destroy()

    return driver


if __name__ == "__main__":
    raise SystemExit(main())
