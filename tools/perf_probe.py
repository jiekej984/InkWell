"""阶段四 4.4 性能实测（AC-1 / AC-2 / AC-3 / AC-10 + §12.1 的体积/内存/导出假设）。

跑法（先跑过 `tools/build_release.py`，需要 `dist/Inkwell/Inkwell.exe`）：

    .venv\\Scripts\\python.exe tools\\perf_probe.py
    ... --runs 5           # 冷启动取几次（默认 5，取中位数）
    ... --keep             # 保留临时数据目录（复测/排查）
    ... --skip-export      # 跳过 500 万字导出（耗时较长时可用）
    ... --json docs/版本更新/阶段四_性能实测.json

测量口径：

| 项 | 口径 | 数据来源 |
|---|---|---|
| AC-2 冷启动 | 进程起 → 项目列表可见（可交互），5 次取**中位数** | 打点：`[perf] 首屏就绪=` |
| AC-3 打开 5 万字章节 | 点开 → 标题就绪且正文 >4 万字 | 打点：`[perf] 打开五万字章=` |
| AC-10 检索（后端） | `/api/search` 10 组关键词的 p50 / p95 | 本脚本 httpx 直连 |
| AC-10 检索（UI） | 输入 → 首条命中出现 | 打点：`[perf] 检索首命中=` |
| AC-1 2000 章规模 | 打开项目 → 大纲树节点数稳定 | 打点：`[perf] 大纲树渲染=` |
| 常驻内存 | 主进程 + 其 WebView2 子进程工作集 | WMI（PowerShell） |
| 导出 500 万字 | 长任务 `POST /projects/{pid}/export` 全流程 | httpx 轮询 |

AC-1 的数据：20 卷 × 100 章 = 2000 章、每章 2500 字（全书 ≈500 万字）+ 一篇 5 万字章，
比 AC-10 要求的「10 万字项目」高一个量级。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import httpx

from backend.config import TOKEN_HEADER, clear_proxy_env, ensure_data_dirs, load_config
from backend.database import Database
from backend.migrate import apply_migrations
from backend.server import create_app
from build_release import (
    EXE,
    _clean_env,
    _close_window_and_wait,
    find_window,
    log_lines,
)

VOLUME_COUNT = 20
CHAPTERS_PER_VOLUME = 100
CHAPTER_CHARS = 2500
FIVE_WAN_CHARS = 50000
DOCUMENT_COUNT = 10
SEARCH_KEYWORD = "性能关键词"
SEARCH_DOC_KEYWORD = "守塔人档案"
SEARCH_ROUNDS = 10
EXPORT_TIMEOUT = 180.0

STARTUP_RE = re.compile(r"\[perf\] 首屏就绪=(\d+) ms")
TREE_RE = re.compile(r"\[perf\] 大纲树渲染=(\d+) ms（(\d+) 章）")
OPEN_FIVE_RE = re.compile(r"\[perf\] 打开五万字章=(\d+) ms")
SEARCH_RE = re.compile(r"\[perf\] 检索首命中=(\d+) ms（(\d+) 条）")


class UvicornThread(threading.Thread):
    def __init__(self, app: object, port: int) -> None:
        super().__init__(daemon=True, name="perf-uvicorn")
        import uvicorn

        self.server = uvicorn.Server(
            uvicorn.Config(
                app, host="127.0.0.1", port=port, log_level="warning", access_log=False
            )
        )

    def run(self) -> None:
        self.server.run()


def fill_text(prefix: str, target: int) -> str:
    """把前缀重复到恰好 `target` 个字符（真实字数口径与 BR-1 一致：CJK 逐字）。"""
    if not prefix:
        return ""
    return (prefix * (target // len(prefix) + 1))[:target]


def seed(client: httpx.Client) -> dict:
    """造 AC-1 规模的数据：20 卷 × 100 章 × 2500 字 + 一篇 5 万字章 + 10 份设定。"""
    project = client.post("/api/projects", json={"title": "性能样书"}).json()["data"]
    pid = project["id"]

    chapter_body = fill_text(
        "潮声漫过礁石，灯塔在雨里转了一圈。" + SEARCH_KEYWORD + "。", CHAPTER_CHARS
    )
    chapter_ids: list[int] = []
    first_volume_id = 0
    for volume_index in range(VOLUME_COUNT):
        volume = client.post(
            f"/api/projects/{pid}/volumes", json={"title": f"卷{volume_index + 1:02d}"}
        ).json()["data"]
        if volume_index == 0:
            first_volume_id = volume["id"]
        for chapter_index in range(CHAPTERS_PER_VOLUME):
            chapter = client.post(
                f"/api/volumes/{volume['id']}/chapters",
                json={
                    "title": f"第{volume_index + 1:02d}卷第{chapter_index + 1:03d}章"
                },
            ).json()["data"]
            client.put(
                f"/api/chapters/{chapter['id']}/content",
                json={"content_html": f"<p>{chapter_body}</p>"},
            )
            chapter_ids.append(chapter["id"])
        print(
            f"      卷 {volume_index + 1}/{VOLUME_COUNT} 完成（累计 {len(chapter_ids)} 章）",
            flush=True,
        )

    # 五万字章放进第一个**新建**卷：默认卷在大纲树里是隐藏的，放里面会点不到（场景会失败）
    five_wan_body = fill_text(
        "五万字样本：雨夜码头，她把最后一页手稿合上。", FIVE_WAN_CHARS
    )
    five_wan = client.post(
        f"/api/volumes/{first_volume_id}/chapters", json={"title": "五万字章"}
    ).json()["data"]
    client.put(
        f"/api/chapters/{five_wan['id']}/content",
        json={"content_html": f"<p>{five_wan_body}</p>"},
    )

    for index in range(DOCUMENT_COUNT):
        client.post(
            f"/api/projects/{pid}/documents",
            json={
                "title": f"设定{index + 1:02d}",
                "category": "world",
                "content_html": (
                    f"<p>{SEARCH_KEYWORD}与{SEARCH_DOC_KEYWORD}只出现在设定文档里："
                    "海风、黑水河、守塔人。</p>"
                ),
            },
        )
    return {
        "project_id": pid,
        "chapter_count": len(chapter_ids) + 1,
        "chapter_chars": CHAPTER_CHARS,
        "five_wan_chapter_id": five_wan["id"],
        "five_wan_chars": FIVE_WAN_CHARS,
        "total_chars": len(chapter_ids) * CHAPTER_CHARS + FIVE_WAN_CHARS,
    }


def measure_search_http(client: httpx.Client) -> dict:
    """AC-10 后端侧：章节专属 / 设定专属关键词交替各 5 次，取 p50 / p95。"""
    timings: list[float] = []
    chapter_kinds: set[str] = set()
    document_kinds: set[str] = set()
    hits = 0
    for index in range(SEARCH_ROUNDS):
        query = SEARCH_KEYWORD if index % 2 == 0 else SEARCH_DOC_KEYWORD
        started = time.perf_counter()
        payload = client.get("/api/search", params={"q": query, "page_size": 20}).json()
        timings.append((time.perf_counter() - started) * 1000)
        if payload.get("code") != 0:
            continue
        data = payload["data"]
        hits = data.get("total", hits)
        kinds = {str(item.get("type")) for item in data.get("items", [])}
        if query == SEARCH_KEYWORD:
            chapter_kinds |= kinds
        else:
            document_kinds |= kinds
    ordered = sorted(timings)
    return {
        "p50_ms": round(statistics.median(timings), 1),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 1),
        "max_ms": round(max(timings), 1),
        "hits": hits,
        "chapter_hit": "chapter" in chapter_kinds,
        "document_hit": "document" in document_kinds,
    }


def measure_export(client: httpx.Client, project_id: int) -> dict:
    """§12.1「导出 500 万字 ≤60s」：长任务全流程（提交 → 轮询 → 完成）。"""
    started = time.perf_counter()
    created = client.post(
        f"/api/projects/{project_id}/export", json={"format": "txt"}
    ).json()
    if created.get("code") != 0:
        return {"ok": False, "error": created}
    task_id = created["data"]["tid"]
    deadline = started + EXPORT_TIMEOUT
    while time.perf_counter() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        # 注意字段名是 `state`（pending / running / success / failed），不是 status
        data = task.get("data") or {}
        state = data.get("state")
        if state in {"success", "failed"}:
            elapsed = (time.perf_counter() - started) * 1000
            return {
                "ok": state == "success",
                "state": state,
                "elapsed_ms": round(elapsed, 1),
                "result": data.get("result"),
                "error": data.get("error"),
            }
        time.sleep(0.3)
    return {"ok": False, "state": "timeout", "elapsed_ms": EXPORT_TIMEOUT * 1000}


def process_tree_memory(pid: int) -> dict:
    """主进程 + 其 WebView2 子进程的内存（MB）。

    两种口径都记：

    - **工作集**（WorkingSetSize 求和）：任务管理器里各进程「内存」相加，会把 DLL 等
      共享页重复计入，是**上界**；
    - **私有内存**（PrivatePageCount 求和）：只算各进程独占的提交量，不含共享页，
      更接近「这个应用真正占了多少」，对应 NFR-P6「常驻内存 ≤300MB」的判定口径。
    """
    script = (
        "Get-CimInstance Win32_Process | "
        "Select-Object Name,ProcessId,ParentProcessId,WorkingSetSize,PrivatePageCount "
        "| ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=90,
        )
        rows = json.loads(completed.stdout or "[]")
    except Exception as error:  # 内存测量失败不该拖垮实测
        return {"error": str(error)}
    if isinstance(rows, dict):
        rows = [rows]

    def mb(value: object) -> float:
        return float(value or 0) / (1024 * 1024)

    by_parent: dict[int, list[dict]] = {}
    for row in rows:
        by_parent.setdefault(int(row["ParentProcessId"]), []).append(row)

    children_ws = 0.0
    children_private = 0.0
    found: list[str] = []
    queue = [pid]
    seen: set[int] = set()
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        for child in by_parent.get(current, []):
            name = str(child["Name"])
            if name.lower().endswith(".exe"):
                children_ws += mb(child.get("WorkingSetSize"))
                children_private += mb(child.get("PrivatePageCount"))
                found.append(f"{name}#{child['ProcessId']}")
                queue.append(int(child["ProcessId"]))
    own = next((row for row in rows if int(row["ProcessId"]) == pid), None)
    own_ws = mb(own.get("WorkingSetSize")) if own else 0.0
    own_private = mb(own.get("PrivatePageCount")) if own else 0.0
    return {
        "working_set_total_mb": round(own_ws + children_ws, 1),
        "private_total_mb": round(own_private + children_private, 1),
        "main_process_mb": round(own_ws, 1),
        "main_private_mb": round(own_private, 1),
        "children_mb": round(children_ws, 1),
        "children_private_mb": round(children_private, 1),
        "children": found[:8],
    }


def _log_line_count(data_dir: Path) -> int:
    """当前日志行数；每次启动前记一次，只认之后的打点（否则会读到上一轮的数）。"""
    return len(log_lines(data_dir))


def _wait_for_line(
    data_dir: Path, pattern: re.Pattern, timeout: float, from_index: int = 0
) -> re.Match | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for line in log_lines(data_dir)[from_index:]:
            match = pattern.search(line)
            if match:
                return match
        time.sleep(0.25)
    return None


def run_packaged(
    data_dir: Path,
    runs: int,
    scenario: bool = False,
) -> dict:
    """启动冻结产物：`runs` 次冷启动；scenario=True 时顺带跑 AC-1/3/10 的 UI 场景。"""
    startups: list[int] = []
    scenario_result: dict = {}
    env = _clean_env(data_dir)
    env["INKWELL_PERF_TRACE"] = "1"
    if scenario:
        env["INKWELL_PERF_SCENARIO"] = "1"
    for index in range(runs):
        start_line = _log_line_count(data_dir)
        process = subprocess.Popen([str(EXE)], env=env)
        try:
            if not find_window(process.pid, timeout=60.0):
                raise SystemExit(f"第 {index + 1} 次启动没有等到窗口")
            first = _wait_for_line(
                data_dir,
                re.compile(r"\[perf\] 首屏就绪=(\d+) ms"),
                timeout=90.0,
                from_index=start_line,
            )
            if not first:
                raise SystemExit(f"第 {index + 1} 次启动没有打出「首屏就绪」")
            startups.append(int(first.group(1)))
            print(
                f"      第 {index + 1}/{runs} 次：首屏就绪 {first.group(1)} ms",
                flush=True,
            )
            if scenario:
                tree = _wait_for_line(
                    data_dir, TREE_RE, timeout=120.0, from_index=start_line
                )
                if not tree:
                    raise SystemExit("场景：大纲树渲染打点缺失")
                scenario_result["tree_render_ms"] = int(tree.group(1))
                scenario_result["tree_chapters"] = int(tree.group(2))
                opened = _wait_for_line(
                    data_dir, OPEN_FIVE_RE, timeout=120.0, from_index=start_line
                )
                if not opened:
                    raise SystemExit("场景：五万字章打开打点缺失")
                scenario_result["open_five_wan_ms"] = int(opened.group(1))
                hit = _wait_for_line(
                    data_dir, SEARCH_RE, timeout=60.0, from_index=start_line
                )
                if not hit:
                    raise SystemExit("场景：检索首命中打点缺失")
                scenario_result["search_ui_ms"] = int(hit.group(1))
                scenario_result["search_hits"] = int(hit.group(2))
                scenario_result["memory"] = process_tree_memory(process.pid)
                print(
                    f"      场景：树渲染 {scenario_result['tree_render_ms']} ms / "
                    f"打开五万字 {scenario_result['open_five_wan_ms']} ms / "
                    f"检索 {scenario_result['search_ui_ms']} ms",
                    flush=True,
                )
            elif index == runs - 1:
                # 空闲态内存：项目列表、无打开项目，等 2s 让 GC / 渲染稳定
                time.sleep(2.0)
                scenario_result["idle_memory"] = process_tree_memory(process.pid)
                print(f"      空闲态内存：{scenario_result['idle_memory']}", flush=True)
        finally:
            _close_window_and_wait(process)
    result: dict = {
        "runs": startups,
        "median_ms": int(statistics.median(startups)),
        "min_ms": min(startups),
        "max_ms": max(startups),
    }
    result.update(scenario_result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inkwell 阶段四性能实测")
    parser.add_argument("--runs", type=int, default=5, help="冷启动次数（默认 5）")
    parser.add_argument("--keep", action="store_true", help="保留临时数据目录")
    parser.add_argument("--skip-export", action="store_true", help="跳过 500 万字导出")
    parser.add_argument(
        "--json",
        default=str(ROOT / "docs" / "版本更新" / "阶段四_性能实测.json"),
        help="结果 JSON 输出路径",
    )
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not EXE.exists():
        raise SystemExit(f"找不到打包产物：{EXE}\n先跑 tools/build_release.py")

    clear_proxy_env()
    data_dir = Path(tempfile.mkdtemp(prefix="inkwell-perf-"))
    os.environ["INKWELL_DATA_DIR"] = str(data_dir)  # 先指到临时目录，再解析配置
    print(f"临时数据目录：{data_dir}", flush=True)
    result: dict = {
        "data_dir": str(data_dir),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    config = load_config()
    ensure_data_dirs(config)
    database = Database(config.db_path)
    schema_version = apply_migrations(database, config.data_dir)
    app = create_app(config, database)
    app.state.schema_version = schema_version
    thread = UvicornThread(app, config.port)
    thread.start()
    deadline = time.time() + 15
    while time.time() < deadline and not thread.server.started:
        time.sleep(0.05)
    client = httpx.Client(
        base_url=config.base_url,
        trust_env=False,
        timeout=120.0,
        headers={TOKEN_HEADER: config.token},
    )
    try:
        print("[1/4] 造 AC-1 规模数据（20 卷 × 100 章 ≈ 500 万字）…", flush=True)
        started = time.perf_counter()
        seeded = seed(client)
        print(
            f"      种子完成：{seeded['chapter_count']} 章，耗时 "
            f"{time.perf_counter() - started:.1f}s",
            flush=True,
        )
        result["seed"] = seeded
        print("[2/4] AC-10 后端检索 …", flush=True)
        result["search_http"] = measure_search_http(client)
        print(f"      {result['search_http']}", flush=True)
        if args.skip_export:
            result["export"] = {"skipped": True}
        else:
            print("[3/4] 导出 500 万字（长任务）…", flush=True)
            result["export"] = measure_export(client, seeded["project_id"])
            print(f"      {result['export']}", flush=True)
    finally:
        client.close()
        thread.server.should_exit = True
        time.sleep(0.3)
        database.dispose()

    print("[4/4] 冻结产物：冷启动 ×%d + AC-1/3/10 场景 …" % args.runs, flush=True)
    result["packaged"] = run_packaged(data_dir, args.runs, scenario=False)
    result["scenario"] = run_packaged(data_dir, 1, scenario=True)

    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== 汇总 =====", flush=True)
    print(
        f"AC-2 冷启动中位数：{result['packaged']['median_ms']} ms "
        f"（{result['packaged']['runs']} 次，min {result['packaged']['min_ms']} / "
        f"max {result['packaged']['max_ms']}）",
        flush=True,
    )
    print(
        f"AC-3 打开 5 万字章：{result['scenario']['open_five_wan_ms']} ms", flush=True
    )
    print(
        f"AC-10 后端检索 p50：{result['search_http']['p50_ms']} ms / "
        f"p95 {result['search_http']['p95_ms']} ms / 命中 {result['search_http']['hits']}",
        flush=True,
    )
    print(
        f"AC-10 UI 检索：{result['scenario']['search_ui_ms']} ms "
        f"（{result['scenario']['search_hits']} 条）",
        flush=True,
    )
    print(
        f"AC-1 大纲树渲染：{result['scenario']['tree_render_ms']} ms "
        f"（{result['scenario']['tree_chapters']} 章）",
        flush=True,
    )
    memory = result["scenario"].get("memory") or {}
    print(
        f"内存（重负载：2000 章 + 5 万字章 + 检索结果）："
        f"私有 {memory.get('private_total_mb')} MB / "
        f"工作集（上界，含共享页重复计入）{memory.get('working_set_total_mb')} MB "
        f"（主进程 {memory.get('main_process_mb')} + WebView2 {memory.get('children_mb')}）",
        flush=True,
    )
    idle = result["packaged"].get("idle_memory") or {}
    if idle:
        print(
            f"内存（空闲：项目列表，无打开项目）："
            f"私有 {idle.get('private_total_mb')} MB / "
            f"工作集（上界）{idle.get('working_set_total_mb')} MB "
            f"（主进程 {idle.get('main_process_mb')} + WebView2 {idle.get('children_mb')}）",
            flush=True,
        )
    if result["export"].get("ok"):
        print(f"导出 500 万字：{result['export']['elapsed_ms']} ms", flush=True)
    print(f"\n结果 JSON：{out}", flush=True)

    if args.keep:
        print(f"数据目录保留在 {data_dir}", flush=True)
    else:
        shutil.rmtree(data_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
