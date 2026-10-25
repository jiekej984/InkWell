"""Seed clearly labelled V2.1 demo novels into the configured app database.

Run from the repository root with the project venv. Existing projects are never
modified; the script refuses to run if any of its marker titles already exist.
"""

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


TITLES = (
    "【V2.1测试】雾港来信（出场检索）",
    "【V2.1测试】青云谱系（50组织）",
    "【V2.1测试】群星誓约（关系图标签）",
)


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
            existing = client.get("/api/projects").json()["data"]["items"]
            existing_titles = {item["title"] for item in existing}
            overlap = existing_titles.intersection(TITLES)
            if overlap:
                raise RuntimeError(
                    "测试书已存在，为避免重复或覆盖，停止写入："
                    + "、".join(sorted(overlap))
                )

            def request(method: str, path: str, **kwargs):
                response = client.request(method, path, **kwargs)
                body = response.json()
                if response.status_code >= 400 or body.get("code") != 0:
                    raise RuntimeError(
                        f"{method} {path} 失败: "
                        f"HTTP {response.status_code} {body}"
                    )
                return body["data"]

            def new_book(title: str, description: str) -> dict:
                return request(
                    "POST",
                    "/api/projects",
                    json={
                        "title": title,
                        "description": description,
                        "tags": ["V2.1测试", "可删除演示数据"],
                    },
                )

            def add_volume(project_id: int, title: str) -> int:
                return request(
                    "POST",
                    f"/api/projects/{project_id}/volumes",
                    json={"title": title},
                )["id"]

            def add_chapter(volume_id: int, title: str, content: str) -> int:
                chapter = request(
                    "POST",
                    f"/api/volumes/{volume_id}/chapters",
                    json={"title": title},
                )
                request(
                    "PUT",
                    f"/api/chapters/{chapter['id']}/content",
                    json={"content_html": "".join(f"<p>{p}</p>" for p in content.split("\n\n"))},
                )
                return chapter["id"]

            def add_character(project_id: int, name: str, role: str = "supporting") -> int:
                return request(
                    "POST",
                    f"/api/projects/{project_id}/characters",
                    json={"name": name, "role": role},
                )["id"]

            # Book 1: searchable canonical name plus multiple aliases across chapters.
            search_book = new_book(
                TITLES[0], "用于验证角色姓名/别名出场统计、章节排序、软删除过滤与跳转。"
            )
            search_pid = search_book["id"]
            search_volume = add_volume(search_pid, "第一卷·灯塔来信")
            search_chapters = [
                add_chapter(
                    search_volume,
                    "第一章 雨夜来信",
                    "江知遥走进雾港。阿遥接过一封没有署名的信，江知遥决定天亮后再拆。",
                ),
                add_chapter(
                    search_volume,
                    "第二章 灯下重逢",
                    "旧灯塔亮起时，灯塔医生认出了阿遥。江知遥问起那封信的来处。",
                ),
                add_chapter(
                    search_volume,
                    "第三章 潮汐退去",
                    "阿遥把信交给江知遥，灯塔医生守在门外。",
                ),
            ]
            search_character = add_character(search_pid, "江知遥", "protagonist")
            request(
                "PUT",
                f"/api/characters/{search_character}/aliases",
                json={"aliases": ["阿遥", "灯塔医生"]},
            )
            mentions = request(
                "GET", f"/api/characters/{search_character}/appearances"
            )
            if mentions["chapter_count"] != 3 or mentions["first_appearance"]["chapter_id"] != search_chapters[0]:
                raise RuntimeError(f"出场检索种子验收失败: {mentions}")
            if mentions["total_occurrences"] != 9:
                raise RuntimeError(
                    "出场检索次数与种子预期不符："
                    f"预期 9，实际 {mentions['total_occurrences']}"
                )
            request("DELETE", f"/api/chapters/{search_chapters[2]}")
            active_mentions = request(
                "GET", f"/api/characters/{search_character}/appearances"
            )
            if active_mentions["chapter_count"] != 2:
                raise RuntimeError("软删除章节仍被计入角色出场结果")

            # Book 2: a three-level 50-organization tree and a deletion-batch check.
            org_book = new_book(
                TITLES[1], "用于检查 1 根 + 9 分堂 + 40 分支的组织树，以及删除批次恢复。"
            )
            org_pid = org_book["id"]
            faction = request(
                "POST",
                f"/api/projects/{org_pid}/factions",
                json={"name": "云岭盟", "description": "守护北境商道的联盟。"},
            )
            root = request(
                "POST",
                f"/api/projects/{org_pid}/organizations",
                json={"name": "云岭盟总坛", "kind": "sect", "faction_id": faction["id"]},
            )
            second_level = []
            for index in range(1, 10):
                second_level.append(
                    request(
                        "POST",
                        f"/api/projects/{org_pid}/organizations",
                        json={
                            "name": f"第{index:02d}分堂",
                            "kind": "sect",
                            "parent_id": root["id"],
                            "faction_id": faction["id"],
                        },
                    )["id"]
                )
            for index in range(1, 41):
                parent_id = second_level[(index - 1) % len(second_level)]
                request(
                    "POST",
                    f"/api/projects/{org_pid}/organizations",
                    json={
                        "name": f"第{index:02d}支脉",
                        "kind": "other",
                        "parent_id": parent_id,
                        "faction_id": faction["id"],
                    },
                )
            tree = request("GET", f"/api/projects/{org_pid}/organizations?tree=true")
            if tree["total"] != 50:
                raise RuntimeError(f"组织树应有 50 个组织，实际为 {tree['total']}")

            removed_person = add_character(org_pid, "闻人旧雪")
            current_person = add_character(org_pid, "顾临川", "protagonist")
            old_member = request(
                "POST",
                f"/api/organizations/{root['id']}/members",
                json={"character_id": removed_person, "position": "旧任执事"},
            )
            current_member = request(
                "POST",
                f"/api/organizations/{root['id']}/members",
                json={"character_id": current_person, "position": "现任盟主"},
            )
            request("DELETE", f"/api/org-members/{old_member['id']}")
            request("DELETE", f"/api/organizations/{root['id']}?strategy=cascade")
            request("POST", f"/api/trash/organization/{root['id']}/restore")
            restored_members = request(
                "GET", f"/api/organizations/{root['id']}/members"
            )
            active_ids = {member["id"] for member in restored_members["items"]}
            if old_member["id"] in active_ids or current_member["id"] not in active_ids:
                raise RuntimeError("组织恢复未正确区分手动移除与本批次成员")

            # Book 3: overlapping relationship labels for each graph mode to inspect.
            graph_book = new_book(
                TITLES[2], "用于检查人物关系图中的交叉边与中文长标签避让。"
            )
            graph_pid = graph_book["id"]
            character_names = (
                "顾星河",
                "沈明月",
                "陆听澜",
                "谢云舟",
                "温知夏",
                "叶清辞",
                "裴照野",
                "苏槿年",
                "江望舒",
                "秦远山",
                "唐逐风",
                "白静姝",
            )
            graph_characters = [
                add_character(
                    graph_pid,
                    name,
                    "protagonist" if index == 0 else "supporting",
                )
                for index, name in enumerate(character_names)
            ]
            relation_types = ("friend", "ally", "rival", "enemy", "master", "kin")
            label_stories = (
                "少年时并肩守过北岸长堤",
                "曾在旧星台交换过秘密誓约",
                "因失踪的航海图结下宿怨",
                "共同追查沉船与失联船员",
                "名义师徒但各自隐瞒来历",
                "家族旧约延续到这一代",
            )
            edges = []
            edge_index = 0
            for index in range(12):
                source = graph_characters[index]
                targets = (
                    graph_characters[(index + 1) % 12],
                    graph_characters[(index + 4) % 12],
                    graph_characters[(index + 7) % 12],
                )
                for offset, target in enumerate(targets):
                    edges.append(
                        request(
                            "POST",
                            f"/api/characters/{source}/relations",
                            json={
                                "to_id": target,
                                "relation_type": relation_types[(index + offset) % len(relation_types)],
                                "custom_label": (
                                    f"关系{edge_index + 1:02d}·"
                                    f"{label_stories[edge_index % len(label_stories)]}"
                                ),
                                "is_bidirectional": True,
                            },
                        )
                    )
                    edge_index += 1

            print(
                {
                    "schema_version": version,
                    "search_book_id": search_pid,
                    "search_character_id": search_character,
                    "search_active_chapters": active_mentions["chapter_count"],
                    "organization_book_id": org_pid,
                    "organization_count": tree["total"],
                    "restored_current_member": current_member["id"] in active_ids,
                    "kept_manual_removal_deleted": old_member["id"] not in active_ids,
                    "graph_book_id": graph_pid,
                    "graph_characters": len(graph_characters),
                    "graph_relations": len(edges),
                    "titles": TITLES,
                }
            )
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
