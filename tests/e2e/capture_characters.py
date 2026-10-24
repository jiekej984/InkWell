"""V2.0 5.4 角色库截图（真实窗口 + WebView2 CDP）。

与 `capture_ui.py` 同一套机制：临时数据目录、真实窗口、CDP 截**页面内容**。
只覆盖角色库三张图：

    <label>_P10_characters.png      列表 + 卡片上半（头像/姓名/基础字段）
    <label>_P10b_card_detail.png    卡片下半（别名 / 自定义字段 / 标签）
    <label>_P10c_empty.png          角色库空态（新项目）
    <label>_P10d_organizations.png  组织面板（树 + 详情 + 成员）
    <label>_P10e_factions.png       阵营面板（卡片 + 关系）
    <label>_P10f_org_delete.png     删除组织三选一对话框
    <label>_P10g_relation_form.png  关系编辑表单（可搜索下拉 + 生效章）
    <label>_P10h_graph.png          人物关系图（力导向 / 分色边 / 图例）
    <label>_P10i_org_graph.png      组织层级树（从属折线 / 结盟敌对）
    <label>_P10j_faction_graph.png  阵营全景（阵营簇 / 归属 / 关系）
    <label>_P10k_filters.png        筛选抽屉（阵营 / 组织 / 章节 / 层数）
    <label>_P10l_character_filtered.png 按阵营筛选后的人物图
    <label>_P10m_export.png         导出的 PNG 实样（含图例与中文）

运行：
    .venv\\Scripts\\python.exe tests\\e2e\\capture_characters.py --label 5.4
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
OUT_DEFAULT = ROOT / "docs" / "版本更新" / "V2.0_截图"


class CaptureError(RuntimeError):
    """截图失败（带步骤名）。"""


def seed(client: httpx.Client) -> dict[str, Any]:
    """造角色库样例：4 个角色、别名、自定义字段、组织与立场、一条关系。"""
    project = client.post(
        "/api/projects", json={"title": "长夜将尽", "description": "潮汐与灯塔。"}
    ).json()["data"]
    pid = project["id"]

    faction = client.post(
        f"/api/projects/{pid}/factions",
        json={"name": "正道", "color": "#3b6ea5", "description": "守序阵营"},
    ).json()["data"]
    evil = client.post(
        f"/api/projects/{pid}/factions",
        json={"name": "魔道", "color": "#8b3a4a", "description": "与正道势同水火"},
    ).json()["data"]
    client.post(
        f"/api/projects/{pid}/faction-relations",
        json={
            "from_id": faction["id"],
            "to_id": evil["id"],
            "relation_type": "enemy",
            "description": "百年宿怨",
        },
    )
    sect = client.post(
        f"/api/projects/{pid}/organizations",
        json={"name": "青云宗", "kind": "sect", "faction_id": faction["id"]},
    ).json()["data"]
    peak = client.post(
        f"/api/projects/{pid}/organizations",
        json={"name": "剑峰", "kind": "sect", "parent_id": sect["id"]},
    ).json()["data"]
    blood = client.post(
        f"/api/projects/{pid}/organizations",
        json={"name": "血月教", "kind": "guild", "faction_id": evil["id"]},
    ).json()["data"]
    client.post(
        f"/api/projects/{pid}/org-relations",
        json={
            "from_id": sect["id"],
            "to_id": blood["id"],
            "relation_type": "war",
        },
    )

    def character(name: str, **fields) -> dict:
        body = client.post(
            f"/api/projects/{pid}/characters", json={"name": name, **fields}
        ).json()
        assert body["code"] == 0, body
        return body["data"]

    lin = character(
        "林昭",
        role="protagonist",
        gender="女",
        age="十六七岁",
        height="一六五",
        appearance="眉眼锋利，左手虎口有旧疤。",
        personality="冷峻、护短，不擅长道谢。",
        background="剑阁弃徒，后入青云宗剑峰。",
        abilities="御剑术（第三境）、听风辨位。",
        catchphrase="让开。",
        motivation="查出灭门真凶。",
        note="主角原型来自旧稿里的「阿昭」。",
        tags=["剑修", "复仇线"],
    )
    shen = character(
        "沈砚",
        role="supporting",
        gender="男",
        age="四十",
        height="一七八",
        personality="寡言，护短，重规矩。",
    )
    gu = character("顾长陵", role="antagonist", gender="男", age="五十七")
    aman = character("阿蛮", role="extra", gender="女", age="十二")

    client.put(
        f"/api/characters/{lin['id']}/aliases",
        json={"aliases": ["小昭", "昭儿", "剑阁那位"]},
    )
    client.post(
        f"/api/characters/{lin['id']}/fields",
        json={"key": "灵根", "value": "单系水灵根", "field_type": "text"},
    )
    client.post(
        f"/api/characters/{lin['id']}/fields",
        json={"key": "本命剑", "value": "照夜", "field_type": "text"},
    )
    client.post(
        f"/api/characters/{lin['id']}/relations",
        json={"to_id": shen["id"], "relation_type": "master", "description": "授业恩师"},
    )
    client.post(
        f"/api/characters/{lin['id']}/relations",
        json={
            "to_id": gu["id"],
            "relation_type": "blood_feud",
            "description": "灭门之仇",
        },
    )
    client.post(
        f"/api/characters/{lin['id']}/relations",
        json={"to_id": aman["id"], "relation_type": "friend"},
    )
    client.post(
        f"/api/characters/{gu['id']}/relations",
        json={
            "to_id": shen["id"],
            "relation_type": "rival",
            "is_secret": True,
            "description": "早年结怨",
        },
    )
    client.post(
        f"/api/organizations/{peak['id']}/members",
        json={"character_id": lin["id"], "position": "弟子", "is_primary": True},
    )
    client.post(
        f"/api/organizations/{sect['id']}/members",
        json={"character_id": shen["id"], "position": "宗主", "is_primary": True},
    )

    empty = client.post(
        "/api/projects", json={"title": "空项目（角色库空态）"}
    ).json()["data"]

    return {
        "project_id": pid,
        "empty_project_id": empty["id"],
        "character_id": lin["id"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="角色库截图")
    parser.add_argument("--out", default=str(OUT_DEFAULT))
    parser.add_argument("--label", default="5.4")
    parser.add_argument("--keep-data", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    data_dir = Path(tempfile.mkdtemp(prefix="inkwell-char-"))
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

        client = httpx.Client(
            base_url=config.base_url,
            trust_env=False,
            timeout=10.0,
            headers={TOKEN_HEADER: config.token},
        )
        try:
            ids = seed(client)
            result["seed"] = ids

            import webview

            window = webview.create_window(
                title="Inkwell 角色库截图",
                url=f"{config.base_url}/",
                js_api=ws.TokenApi(config.token, config.data_dir),
                width=VIEWPORT[0],
                height=VIEWPORT[1],
                text_select=True,
            )
            webview.start(
                make_driver(window, ids, result, out_dir),
                debug=False,
                private_mode=False,
                storage_path=str(config.webview_storage_dir),
            )
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
    return 0 if not result["errors"] and len(result["files"]) == 13 else 1


def make_driver(
    window: Any,
    ids: dict[str, Any],
    result: dict[str, Any],
    out_dir: Path,
) -> Any:
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

        def wait(code: str, label: str, timeout: float = 20.0) -> None:
            end = time.time() + timeout
            while time.time() < end:
                try:
                    if js(code):
                        return
                except Exception:
                    pass
                time.sleep(0.15)
            raise CaptureError(f"超时：{label}")

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
            path = out_dir / f"{result['label']}_{name}.png"
            path.write_bytes(raw)
            result["files"].append({"name": path.name, "bytes": len(raw)})
            print(f"[OK] {path.name}", flush=True)

        def step(name: str) -> None:
            time.sleep(0.5)
            capture(name)

        try:
            js(
                "window.__errs = [];"
                "window.addEventListener('error', e => window.__errs.push(String(e.message)));"
                "window.addEventListener('unhandledrejection', e =>"
                " window.__errs.push(String((e.reason && e.reason.message) || e.reason)));"
            )
            wait("document.querySelectorAll('.card').length >= 2", "项目列表")
            js(
                "document.querySelector('.card[data-id=\"%d\"]')"
                ".querySelectorAll('.card__actions .btn')[0].click()"
                % ids["project_id"]
            )
            wait("!document.getElementById('view-writer').hidden", "写作页")
            js("document.getElementById('open-characters').click()")
            wait(
                "!document.getElementById('view-characters').hidden"
                " && document.querySelectorAll('.character-row').length >= 4",
                "角色库",
            )
            step("P10_characters")

            js(
                "document.getElementById('character-card').scrollTop ="
                " document.getElementById('character-card').scrollHeight"
            )
            step("P10b_card_detail")

            # 关系编辑表单（5.6）
            js("document.querySelector('.relation-row__action').click()")
            wait(
                "!document.getElementById('relation-cancel').hidden"
                " && !document.getElementById('relation-form').hidden",
                "关系编辑表单",
            )
            step("P10g_relation_form")
            js("document.getElementById('relation-cancel').click()")

            # 人物关系图（5.7）
            js("document.getElementById('open-graph-character').click()")
            wait(
                "!document.getElementById('view-graph').hidden"
                " && document.querySelectorAll('.graph-node').length >= 2",
                "关系图",
            )
            wait(
                "document.getElementById('graph-status').textContent"
                ".includes('个角色')",
                "关系图布局完成",
                30,
            )
            step("P10h_graph")

            # 关系文字开关（不依赖颜色）
            js("document.getElementById('graph-labels').click()")
            wait(
                "document.querySelector('.graph-edge-labels').style.display"
                " === 'none'",
                "隐藏关系文字",
            )
            js("document.getElementById('graph-labels').click()")
            wait(
                "document.querySelector('.graph-edge-labels').style.display"
                " !== 'none'",
                "恢复关系文字",
            )

            # 筛选抽屉（5.9）
            js("document.getElementById('graph-filter-toggle').click()")
            wait(
                "!document.getElementById('graph-filters').hidden"
                " && document.getElementById('filter-faction').options.length >= 2",
                "筛选抽屉",
            )
            step("P10k_filters")

            # 按阵营筛选：正道 → 只剩林昭、沈砚
            js(
                """(() => {
  const select = document.getElementById('filter-faction');
  const option = [...select.options].find((item) =>
    item.textContent.includes('正道'));
  select.value = option.value;
  document.getElementById('filter-apply').click();
})()"""
            )
            wait(
                "document.getElementById('graph-filters').hidden"
                " && document.getElementById('graph-status').textContent"
                ".includes('2 个角色')",
                "阵营筛选生效",
                30,
            )
            step("P10l_character_filtered")

            # 重置筛选
            js("document.getElementById('graph-filter-toggle').click()")
            wait(
                "!document.getElementById('graph-filters').hidden",
                "重新打开筛选",
            )
            js("document.getElementById('filter-reset').click()")
            wait(
                "document.getElementById('graph-status').textContent"
                ".includes('4 个角色')",
                "筛选已重置",
                30,
            )

            # 锁定布局：按钮状态 + 重排禁用
            js("document.getElementById('graph-lock').click()")
            wait(
                "document.getElementById('graph-lock')"
                ".getAttribute('aria-pressed') === 'true'"
                " && document.getElementById('graph-relayout').disabled",
                "锁定布局",
            )
            js("document.getElementById('graph-lock').click()")
            wait(
                "document.getElementById('graph-lock')"
                ".getAttribute('aria-pressed') === 'false'",
                "解除布局锁定",
            )

            # 导出 PNG：拦截下载链接，验证是合法 data URL
            js(
                """(() => {
  window.__exportHref = '';
  window.__graphExport = null;
  window.__origAnchorClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (this.download) {
      window.__exportHref = this.href;
      return;
    }
    return window.__origAnchorClick.call(this);
  };
  document.getElementById('graph-export').click();
})()"""
            )
            wait(
                "window.__graphExport !== null"
                " && window.__graphExport.bytes > 10000",
                "导出 PNG",
                30,
            )
            export_ok = js(
                "window.__exportHref.startsWith('data:image/png;base64,')"
                " && window.__exportHref.length > 50000"
            )
            result["export_png"] = {
                "ok": bool(export_ok),
                "bytes": js("window.__graphExport.bytes"),
                "width": js("window.__graphExport.width"),
                "height": js("window.__graphExport.height"),
            }
            js(
                "HTMLAnchorElement.prototype.click = window.__origAnchorClick;"
            )
            if not export_ok:
                result["errors"].append("PNG 导出不是合法的 data:image/png")
            else:
                export_href = js("window.__exportHref")
                if isinstance(export_href, str) and "," in export_href:
                    raw = base64.b64decode(export_href.split(",", 1)[1])
                    export_path = out_dir / f"{result['label']}_P10m_export.png"
                    export_path.write_bytes(raw)
                    result["files"].append(
                        {"name": export_path.name, "bytes": len(raw)}
                    )
                    print(f"[OK] {export_path.name}  {len(raw)} bytes", flush=True)

            # 组织模式（5.8）
            js("document.querySelector('.graph-mode[data-mode=\"organization\"]').click()")
            wait(
                "document.getElementById('graph-status').textContent"
                ".includes('个组织')"
                " && document.getElementById('graph-title').textContent"
                ".includes('组织')",
                "组织层级树",
                30,
            )
            step("P10i_org_graph")

            # 阵营模式（5.8）
            js("document.querySelector('.graph-mode[data-mode=\"faction\"]').click()")
            wait(
                "document.getElementById('graph-status').textContent"
                ".includes('个阵营')",
                "阵营全景",
                30,
            )
            step("P10j_faction_graph")

            js("document.getElementById('graph-back').click()")
            wait(
                "!document.getElementById('view-characters').hidden",
                "回到角色页",
            )

            # 组织 / 阵营（5.5）
            js("document.getElementById('tab-organizations').click()")
            wait(
                "document.querySelectorAll('.org-tree__row').length >= 3"
                " && !document.getElementById('organization-detail').hidden",
                "组织面板",
            )
            step("P10d_organizations")

            js("document.getElementById('delete-org').click()")
            wait(
                "document.getElementById('org-delete-dialog').open === true",
                "删除组织对话框",
            )
            step("P10f_org_delete")
            js(
                "document.querySelector('#org-delete-dialog [data-dialog-cancel]')"
                ".click()"
            )
            wait(
                "document.getElementById('org-delete-dialog').open === false",
                "关闭删除对话框",
            )

            js("document.getElementById('tab-factions').click()")
            wait(
                "document.querySelectorAll('.faction-card').length >= 2"
                " && !document.getElementById('faction-detail').hidden",
                "阵营面板",
            )
            step("P10e_factions")

            js("document.getElementById('tab-characters').click()")
            wait(
                "!document.getElementById('view-characters').hidden"
                " && !document.getElementById('character-card').hidden",
                "回到角色页",
            )

            # 空态：回作品列表 → 打开空项目 → 角色页
            js("document.getElementById('nav-home').click()")
            wait(
                "!document.getElementById('view-projects').hidden"
                " && document.querySelector('.card[data-id=\"%d\"]') !== null"
                % ids["empty_project_id"],
                "项目列表（空项目卡片）",
            )
            result["card_ids"] = js(
                "Array.from(document.querySelectorAll('.card'))"
                ".map(c => c.dataset.id).join(',')"
            )
            js(
                "document.querySelector('.card[data-id=\"%d\"]')"
                ".querySelectorAll('.card__actions .btn')[0].click()"
                % ids["empty_project_id"]
            )
            wait(
                "!document.getElementById('view-writer').hidden"
                " && document.getElementById('open-characters') !== null",
                "空项目写作页",
            )
            js("document.getElementById('open-characters').click()")
            wait(
                "!document.getElementById('view-characters').hidden"
                " && !document.getElementById('character-empty').hidden",
                "角色库空态",
            )
            step("P10c_empty")

            result["page_errors"] = js("window.__errs || []")
        except Exception as exc:
            result["errors"].append(f"{type(exc).__name__}: {exc}")
            print(f"[FAIL] {type(exc).__name__}: {exc}", flush=True)
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
    sys.exit(main())
