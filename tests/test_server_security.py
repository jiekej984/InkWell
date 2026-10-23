"""任务 1.3 / 1.4 安全链路测试。

覆盖：token 校验、Host 校验、absolute-form 拒绝（R-17）、连续请求不 404（R-17）、
静态页面挂载。
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import (
    ALLOWED_HOSTS,
    HOST,
    SCHEMA_VERSION,
    TOKEN_HEADER,
    AppConfig,
    ensure_data_dirs,
    frontend_dir,
    pick_free_port,
)
from backend.database import Database
from backend.migrate import apply_migrations
from backend.server import create_app, host_without_port, is_absolute_form


@pytest.fixture(scope="module")
def live_server(tmp_path_factory: pytest.TempPathFactory):
    """真实运行在子线程中的 uvicorn 服务（与生产启动方式一致）。"""
    data_dir = tmp_path_factory.mktemp("InkwellLive")
    config = AppConfig(
        version="0.1.0",
        schema_version=SCHEMA_VERSION,
        data_dir=data_dir,
        db_path=data_dir / "inkwell.db",
        frontend_dir=frontend_dir(),
        token="selfcheck-token",
        host=HOST,
        port=pick_free_port(),
        dev=True,
    )
    ensure_data_dirs(config)
    database = Database(config.db_path)
    apply_migrations(database, config.data_dir)

    application = create_app(config)
    application.state.schema_version = config.schema_version

    from main import start_server

    thread = start_server(application, config.host, config.port)
    try:
        yield config
    finally:
        thread.stop()
        database.dispose()


def _raw_request(host: str, port: int, target: str, token: str) -> str:
    """发送一行原始 HTTP 请求，返回首行状态行。用于构造 absolute-form 请求行。"""
    payload = (
        f"GET {target} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"{TOKEN_HEADER}: {token}\r\n"
        "Connection: close\r\n\r\n"
    )
    with socket.create_connection((host, port), timeout=5.0) as sock:
        sock.sendall(payload.encode("ascii"))
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\r\n\r\n" in b"".join(chunks):
                break
    return b"".join(chunks).split(b"\r\n", 1)[0].decode("latin-1")


def test_health_without_token_returns_1002(client) -> None:
    response = client.get("/api/system/health")
    assert response.status_code == 401
    assert response.json()["code"] == 1002


def test_health_with_wrong_token_returns_1002(client, config: AppConfig) -> None:
    response = client.get(
        "/api/system/health", headers={TOKEN_HEADER: config.token + "x"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == 1002


def test_health_with_valid_token_returns_ok(client, config: AppConfig) -> None:
    response = client.get("/api/system/health", headers={TOKEN_HEADER: config.token})
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["status"] == "ok"
    assert payload["data"]["schema_version"] == config.schema_version


def test_absolute_form_is_detected() -> None:
    assert is_absolute_form({"path": "http://127.0.0.1:8000/api/x"}) is True
    assert is_absolute_form({"path": "/api/x"}) is False
    assert is_absolute_form({"raw_path": b"https://example.com/api"}) is True


def test_host_without_port_strips_port() -> None:
    assert host_without_port("127.0.0.1:51234") == "127.0.0.1"
    assert host_without_port("localhost") == "localhost"
    assert host_without_port("[::1]:51234") == "[::1]"


def test_forged_host_is_rejected(client, config: AppConfig) -> None:
    response = client.get(
        "/api/system/health",
        headers={TOKEN_HEADER: config.token, "Host": "evil.example"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == 1002


def test_allowed_hosts_are_loopback_only() -> None:
    assert set(ALLOWED_HOSTS) == {"127.0.0.1", "localhost", "[::1]"}


def test_live_absolute_form_request_is_rejected(live_server: AppConfig) -> None:
    """R-17 缓解措施 ③：absolute-form 请求行必须被拒绝，而不是 200。"""
    status_line = _raw_request(
        live_server.host,
        live_server.port,
        f"http://{live_server.host}:{live_server.port}/api/system/health",
        live_server.token,
    )
    assert "200" not in status_line.split(" ")[:2], status_line


def test_live_sequential_requests_all_succeed(live_server: AppConfig) -> None:
    """R-17 回归：同一 keep-alive 连接上连续 20 次请求必须全部 200。"""
    import httpx

    with httpx.Client(
        base_url=live_server.base_url, trust_env=False, timeout=10.0
    ) as http:
        codes = [
            http.get(
                "/api/system/health", headers={TOKEN_HEADER: live_server.token}
            ).status_code
            for _ in range(20)
        ]
    assert set(codes) == {200}


def test_frontend_index_is_served(live_server: AppConfig) -> None:
    import httpx

    with httpx.Client(
        base_url=live_server.base_url, trust_env=False, timeout=10.0
    ) as http:
        response = http.get("/")
    assert response.status_code == 200
    assert "Inkwell" in response.text
