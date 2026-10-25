"""Read-only API checks for the V2.1 demo projects in the configured database."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER, ensure_data_dirs, load_config
from backend.database import Database
from backend.migrate import apply_migrations
from backend.server import create_app
from backend.services.graph_service import MAX_NODES

TITLES = {
    "search": "【V2.1测试】雾港来信（出场检索）",
    "organization": "【V2.1测试】青云谱系（50组织）",
    "graph": "【V2.1测试】群星誓约（关系图标签）",
}


def main() -> None:
    config = load_config()
    ensure_data_dirs(config)
    database = Database(config.db_path)
    try:
        version = apply_migrations(database, config.data_dir)
        app = create_app(config, database)
        app.state.schema_version = version
        with TestClient(app, base_url="http://127.0.0.1:8000") as client:
            client.headers.update({TOKEN_HEADER: config.token})

            def get(path: str, **params):
                response = client.get(path, params=params)
                body = response.json()
                if response.status_code >= 400 or body.get("code") != 0:
                    raise RuntimeError(f"GET {path} 失败：{response.status_code} {body}")
                return body["data"]

            projects = get("/api/projects")["items"]
            by_title = {item["title"]: item for item in projects}
            missing = set(TITLES.values()) - set(by_title)
            if missing:
                raise RuntimeError("找不到测试书：" + "、".join(sorted(missing)))

            results = {"schema_version": version}
            org_project = by_title[TITLES["organization"]]
            org_graph = get(
                f"/api/projects/{org_project['id']}/graph",
                mode="organization",
                limit=MAX_NODES,
            )
            results["organization_graph"] = {
                "nodes": len(org_graph["nodes"]),
                "edges": len(org_graph["edges"]),
            }

            character_project = by_title[TITLES["graph"]]
            character_graph = get(
                f"/api/projects/{character_project['id']}/graph",
                mode="character",
                limit=MAX_NODES,
            )
            results["character_graph"] = {
                "nodes": len(character_graph["nodes"]),
                "edges": len(character_graph["edges"]),
                "labelled_edges": sum(bool(edge.get("label")) for edge in character_graph["edges"]),
            }

            search_project = by_title[TITLES["search"]]
            character_list = get(
                f"/api/projects/{search_project['id']}/characters",
                keyword="江知遥",
            )
            character_id = character_list["items"][0]["id"]
            appearances = get(f"/api/characters/{character_id}/appearances")
            results["appearances"] = {
                "chapters": appearances["chapter_count"],
                "occurrences": appearances["total_occurrences"],
                "first_chapter": appearances["first_appearance"]["chapter_title"],
            }

            if results["organization_graph"]["nodes"] != 50:
                raise RuntimeError(f"组织图节点数异常：{results['organization_graph']}")
            if results["character_graph"]["nodes"] != 12 or results["character_graph"]["edges"] != 36:
                raise RuntimeError(f"人物关系图数据异常：{results['character_graph']}")
            if results["character_graph"]["labelled_edges"] != 36:
                raise RuntimeError("人物关系图长标签未完整返回")
            if results["appearances"]["chapters"] != 2:
                raise RuntimeError("软删除章节仍被计入出场结果")

            ok, messages = database.quick_check()
            if not ok:
                raise RuntimeError(f"SQLite quick_check 失败：{messages}")
            results["sqlite_quick_check"] = "ok"
            print(results)
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
