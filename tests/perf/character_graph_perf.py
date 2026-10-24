"""关系图性能实测（V2.0 / 5.9 / AC-21）。

测三段：
  ① 后端 `build_graph`：80 角色 / 200 关系 / 3 种模式
  ② JSON 序列化体积
  ③ 前端简化力导向 300 轮（调用 Node 跑 `graph_layout_perf.mjs`）

门槛按验收标准 80 节点 ≤800ms 留足余量：
  · 后端单次 ≤200ms
  · 前端布局 ≤400ms
  · 合计 ≤800ms

用法：``.venv\\Scripts\\python.exe tests/perf/character_graph_perf.py``
退出码非 0 表示超出预算。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

NODES = 80
RELATIONS = 200
BACKEND_BUDGET_MS = 200.0
LAYOUT_BUDGET_MS = 400.0
TOTAL_BUDGET_MS = 800.0


def _build_fixture(session, project_service, character_service, faction_service,
                   organization_service) -> tuple[int, list[int]]:
    project = project_service.create_project(session, title="图性能样本")
    project_id = int(project.id)
    faction = faction_service.create_faction(session, project_id, name="测试阵营")
    org = organization_service.create_organization(
        session, project_id, name="测试宗门", faction_id=int(faction.id)
    )
    roles = ("protagonist", "heroine", "supporting", "antagonist", "extra")
    character_ids: list[int] = []
    for index in range(NODES):
        row = character_service.create_character(
            session,
            project_id,
            name=f"角色{index + 1:02d}",
            role=roles[index % len(roles)],
        )
        character_ids.append(int(row.id))
        if index < 40:
            organization_service.add_member(
                session,
                int(org.id),
                character_id=int(row.id),
                is_primary=True,
                position="弟子",
            )
    return project_id, character_ids


def main() -> int:
    data_dir = Path(tempfile.mkdtemp(prefix="inkwell-graph-perf-"))
    os.environ["INKWELL_DATA_DIR"] = str(data_dir)

    from backend.config import ensure_data_dirs, load_config
    from backend.database import Database
    from backend.migrate import apply_migrations
    from backend.models import session_scope
    from backend.services import (
        character_service,
        faction_service,
        graph_service,
        organization_service,
        project_service,
        relation_service,
    )

    config = replace(
        load_config(),
        data_dir=data_dir,
        db_path=data_dir / "inkwell.db",
    )
    ensure_data_dirs(config)
    database = Database(config.db_path)
    apply_migrations(database, config.data_dir)

    with session_scope(database.engine) as session:
        project_id, character_ids = _build_fixture(
            session,
            project_service,
            character_service,
            faction_service,
            organization_service,
        )
        created = 0
        for offset in range(1, NODES):
            for index in range(NODES):
                if created >= RELATIONS:
                    break
                from_id = character_ids[index]
                to_id = character_ids[(index + offset) % NODES]
                relation_service.create_character_relation(
                    session,
                    from_id,
                    to_id=to_id,
                    relation_type="friend",
                )
                created += 1
            if created >= RELATIONS:
                break

    print(f"样本：{NODES} 角色 / {created} 关系 / 数据目录 {data_dir}")
    print("-" * 72)

    timings: dict[str, float] = {}
    sizes: dict[str, int] = {}
    for mode in ("character", "organization", "faction"):
        samples = []
        payload = None
        for _ in range(3):
            with session_scope(database.engine) as session:
                start = time.perf_counter()
                payload = graph_service.build_graph(
                    session, project_id, mode=mode, limit=NODES
                )
                samples.append((time.perf_counter() - start) * 1000)
        timings[mode] = min(samples)
        sizes[mode] = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        print(
            f"后端 {mode:<12} 最快 {timings[mode]:6.1f} ms"
            f"  节点 {len(payload['nodes']):2d} / 边 {len(payload['edges']):3d}"
            f" / JSON {sizes[mode] / 1024:6.1f} KB"
        )

    node = shutil.which("node")
    if not node:
        print("找不到 node，跳过前端布局计时")
        return 1
    script = ROOT / "tests" / "perf" / "graph_layout_perf.mjs"
    completed = subprocess.run(
        [node, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        print("前端布局失败：", completed.stderr.strip())
        return 1
    layout = json.loads(completed.stdout.strip().splitlines()[-1])
    print(
        f"前端布局         {layout['ms']:6.1f} ms"
        f"  （{layout['nodes']} 节点 / {layout['edges']} 边 / "
        f"{layout['iterations']} 轮）"
    )

    total = timings["character"] + layout["ms"]
    print("-" * 72)
    print(
        f"合计 {total:6.1f} ms（后端 + 布局；不含 DOM 首次绘制）"
    )

    failures = []
    if timings["character"] > BACKEND_BUDGET_MS:
        failures.append(f"后端 {timings['character']:.1f}ms > {BACKEND_BUDGET_MS}ms")
    if layout["ms"] > LAYOUT_BUDGET_MS:
        failures.append(f"布局 {layout['ms']:.1f}ms > {LAYOUT_BUDGET_MS}ms")
    if total > TOTAL_BUDGET_MS:
        failures.append(f"合计 {total:.1f}ms > {TOTAL_BUDGET_MS}ms")
    if not layout.get("finite"):
        failures.append("布局出现非有限坐标")
    if failures:
        print("未达标：", "；".join(failures))
        return 1
    print("达标：AC-21 80 节点链路 ≤800ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
