"""真实窗口冒烟（pywebview + WebView2）—— 补足 pytest 覆盖不到的窗口层。

覆盖链路：临时数据目录 → 起后端 → 造样例数据 → 开真实窗口 → 驱动页面
（项目列表 → 写作页输入 → 3s 自动保存 → 检索）→ 回查 HTTP 侧结果 → 关窗退出。

运行（推荐用项目 venv）：

    D:\\小说辅助\\.venv\\Scripts\\python.exe tests\\e2e\\window_smoke.py
    ... --json          # 仅输出 JSON（ASCII 转义，便于脚本/CI 解析）
    ... --keep-data     # 保留临时数据目录，便于排查失败现场
    ... --timeout 30    # 单步等待上限（秒）

退出码：0 全部通过；1 任一步失败（失败原因在输出里）。

注意：会短暂弹出一个真实窗口（约 10 秒），跑完自动关闭；不读写项目 ``data/``。
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
CHAPTER_HTML = "<p>深夜的码头，海风带着咸味。她低声说：“走吧。”</p>"
DOCUMENT_HTML = "<p>海风来自黑水河。</p>"
TYPED_TEXT = "冒烟输入"


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
    """造最小样例：1 个项目、1 章正文、1 份设定文档（都命中「海风」）。"""
    project = client.post("/api/projects", json={"title": "冒烟之书"}).json()["data"]
    tree = client.get(f"/api/projects/{project['id']}/volumes").json()["data"]
    chapter = client.post(
        f"/api/volumes/{tree['default_volume']['id']}/chapters",
        json={"title": "第一章"},
    ).json()["data"]
    saved = client.put(
        f"/api/chapters/{chapter['id']}/content",
        json={"content_html": CHAPTER_HTML},
    ).json()
    if saved["code"] != 0:
        raise SmokeError(f"造章节正文失败：{saved}")
    client.post(
        f"/api/projects/{project['id']}/documents",
        json={"title": "世界观", "category": "world", "content_html": DOCUMENT_HTML},
    )
    return {"project_id": project["id"], "chapter_id": chapter["id"]}


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
            bridge = js("document.getElementById('bridge').textContent")
            step("桥接 token 注入", "已就绪" in (bridge or ""), bridge)
            health = js("document.getElementById('health').textContent")
            step("健康检查 200", "200" in (health or ""), health)

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

            js(
                "(function(){const ed=document.querySelector('.ql-editor');"
                "ed.focus();document.execCommand('insertText', false, '%s');"
                "return true;})()" % TYPED_TEXT
            )
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
