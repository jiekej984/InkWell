"""任务 2.13 测试：日志落盘/脱敏/轮转、#44 上报、请求日志与诊断包。"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import TOKEN_HEADER
from backend.services import logging_service


def _headers(config) -> dict[str, str]:
    return {TOKEN_HEADER: config.token}


@pytest.fixture
def log_env(config):
    logging_service.reset_logging()
    logging_service.configure_logging(config.data_dir)
    yield logging.getLogger("inkwell")
    logging_service.reset_logging()


def _log_text(config) -> str:
    directory = config.data_dir / "logs"
    files = sorted(directory.glob("inkwell-*.log"))
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def test_log_written_and_redacted(config, log_env) -> None:
    logging_service.log_event(
        "error",
        "前端异常 token=SECRET_VALUE sig=abcdef 正文日志",
        scope="frontend",
        context={"sig": "zzz", "scope": "test"},
    )
    text = _log_text(config)
    assert "正文日志" in text
    assert "SECRET_VALUE" not in text
    assert "abcdef" not in text
    assert "zzz" not in text
    assert "***" in text
    assert "[frontend]" in text


def test_log_file_size_rotation(config, log_env, monkeypatch) -> None:
    monkeypatch.setattr(logging_service, "MAX_FILE_BYTES", 300)
    logger = logging.getLogger("inkwell")
    for index in range(40):
        logger.info("第 %s 行 %s", index, "x" * 80)

    files = list((config.data_dir / "logs").glob("inkwell-*.log"))
    assert len(files) >= 2


def test_total_size_cap_deletes_oldest(config) -> None:
    directory = config.data_dir / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    now = time.time()
    paths = []
    for index in range(3):
        path = directory / f"inkwell-2026-01-0{index + 1}.log"
        path.write_bytes(b"x" * 1000)
        os.utime(path, (now + index, now + index))
        paths.append(path)

    remaining = logging_service.enforce_total_size(directory, max_bytes=1500)
    assert remaining <= 1500
    assert not paths[0].exists()
    assert paths[2].exists()


def test_client_log_endpoint(client, config, log_env) -> None:
    body = client.post(
        "/api/system/logs",
        json={
            "level": "error",
            "message": "前端异常 sig=SECRET123 token=TOKEN456",
            "context": {"scope": "window.error"},
        },
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body

    text = _log_text(config)
    assert "前端异常" in text
    assert "SECRET123" not in text
    assert "TOKEN456" not in text


def test_client_log_validation(client, config, log_env) -> None:
    bad_level = client.post(
        "/api/system/logs",
        json={"level": "fatal", "message": "x"},
        headers=_headers(config),
    ).json()
    assert bad_level["code"] == 1001

    empty = client.post(
        "/api/system/logs",
        json={"level": "error", "message": ""},
        headers=_headers(config),
    ).json()
    assert empty["code"] == 1001


def test_client_log_elides_html_and_body_fields(client, config, log_env) -> None:
    """NFR-M4 正文兜底：去标签、正文字段整值省略，诊断字段保留。"""
    body = client.post(
        "/api/system/logs",
        json={
            "level": "error",
            "message": "<p>午夜码头，她把信折成两半</p>保存失败",
            "context": {
                "scope": "writer",
                "chapter_id": 3,
                "content_html": "<p>绝密正文片段</p>",
            },
        },
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body

    text = _log_text(config)
    assert "保存失败" in text
    assert "午夜码头，她把信折成两半" in text  # 去标签后保留，便于诊断
    assert "<p>" not in text
    assert "绝密正文片段" not in text  # 正文字段整值省略
    assert "[正文已省略]" in text
    assert '"chapter_id": 3' in text and '"scope": "writer"' in text


def test_client_log_truncates_long_message(client, config, log_env) -> None:
    """即使误传近 1000 字的长文本，日志里也只留 300 字 + 截断标记。"""
    body = client.post(
        "/api/system/logs",
        json={"level": "error", "message": "甲" * 900},
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body

    text = _log_text(config)
    assert "甲" * 300 in text
    assert "甲" * 301 not in text
    assert "[已截断]" in text


def test_client_log_truncates_long_context_value(client, config, log_env) -> None:
    body = client.post(
        "/api/system/logs",
        json={
            "level": "error",
            "message": "请求失败",
            "context": {"detail": "x" * 500},
        },
        headers=_headers(config),
    ).json()
    assert body["code"] == 0, body

    text = _log_text(config)
    assert "x" * 120 in text
    assert "x" * 121 not in text


def test_request_log_strips_query(client, config, log_env) -> None:
    client.get(
        "/api/system/health?foo=1&sig=SECRET_SIGNATURE",
        headers=_headers(config),
    )
    text = _log_text(config)
    assert "GET /api/system/health" in text
    assert "sig=" not in text
    assert "SECRET_SIGNATURE" not in text


def test_diagnostics_zip_excludes_content(client, config, log_env) -> None:
    project = client.post(
        "/api/projects", json={"title": "诊断测试"}, headers=_headers(config)
    ).json()["data"]
    tree = client.get(
        f"/api/projects/{project['id']}/volumes", headers=_headers(config)
    ).json()["data"]
    chapter = client.post(
        f"/api/volumes/{tree['default_volume']['id']}/chapters",
        json={"title": "第一章"},
        headers=_headers(config),
    ).json()["data"]
    client.put(
        f"/api/chapters/{chapter['id']}/content",
        json={"content_html": "<p>绝密正文内容</p>"},
        headers=_headers(config),
    )
    logging_service.log_event("info", "诊断前的日志条目")

    response = client.get("/api/system/diagnostics", headers=_headers(config))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert "diagnostics.txt" in names
        assert "schema.json" in names
        assert any(name.startswith("logs/") for name in names)

        payload = b"".join(archive.read(name) for name in names)
        assert "绝密正文内容".encode() not in payload

        schema = json.loads(archive.read("schema.json"))
        assert "chapter" in schema["tables"]
        assert schema["schema_version"] == "2"

        headline = archive.read("diagnostics.txt").decode("utf-8")
        assert "Inkwell" in headline
        assert "不包含正文" in headline


def test_logging_endpoints_require_token(client) -> None:
    logs = client.post("/api/system/logs", json={"level": "error", "message": "x"})
    assert logs.status_code == 401
    assert logs.json()["code"] == 1002

    diagnostics = client.get("/api/system/diagnostics")
    assert diagnostics.status_code == 401
