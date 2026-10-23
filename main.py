"""Inkwell 桌面应用入口。

对应 §4.5「启动与生命周期」的前台部分：

    清代理 → 解析数据目录 → 建目录 → 开库 → 自检 → 迁移 → 起后端 → 起窗口

生产禁调试：``webview.start(debug=False)``。已在 pywebview 6.2.1 源码中核实
``webview/platforms/edgechromium.py`` 第 287 / 288 / 290 行将
``AreBrowserAcceleratorKeysEnabled`` / ``AreDefaultContextMenusEnabled`` /
``AreDevToolsEnabled`` 三项全部绑定 ``_state['debug']``，
因此 ``debug=False`` 时 DevTools 与右键菜单均已关闭（NFR-S9）。
前端另有一层快捷键拦截作为纵深防御。
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

from backend.config import (
    TOKEN_HEADER,
    WINDOW_HEIGHT,
    WINDOW_MIN_SIZE,
    WINDOW_TITLE,
    WINDOW_WIDTH,
    AppConfig,
    clear_proxy_env,
    ensure_data_dirs,
    load_config,
)
from backend.database import Database
from backend.migrate import apply_migrations
from backend.server import create_app
from backend.services import backup_service, logging_service

STARTUP_TIMEOUT_SECONDS = 10.0
CHECK_ROUNDS = 20  # R-17 回归：连续请求轮次


class UvicornThread(threading.Thread):
    """在**子线程**中运行 uvicorn（ADR-002）。

    已核实 uvicorn 0.54.0 源码：``Server.capture_signals()`` 检测到
    ``threading.current_thread() is not threading.main_thread()`` 时直接返回，
    不会注册 signal handler；环境冒烟测试亦已验证子线程启动无异常。
    """

    def __init__(self, app: object, host: str, port: int) -> None:
        super().__init__(daemon=True, name="inkwell-uvicorn")
        self.server = uvicorn.Server(
            uvicorn.Config(
                app=app,  # type: ignore[arg-type]
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


def start_server(app: object, host: str, port: int) -> UvicornThread:
    """启动后端并等待其进入 started 状态。"""
    thread = UvicornThread(app, host, port)
    thread.start()
    deadline = time.time() + STARTUP_TIMEOUT_SECONDS
    while time.time() < deadline:
        if thread.server.started:
            return thread
        if not thread.is_alive():
            break
        time.sleep(0.02)
    thread.stop()
    raise RuntimeError("后端服务启动超时")


class WindowApi:
    """暴露给前端的桥接接口（pywebview ``js_api``）。

    pywebview 会把公有方法映射为 ``window.pywebview.api.<方法名>``，
    下划线开头的成员不会被暴露。token 经桥接传递，**不写入 URL**（NFR-S2）。
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def get_token(self) -> str:
        """返回本次进程的一次性 token。"""
        return self._config.token

    def is_dev(self) -> bool:
        """是否为开发模式（决定前端是否放开调试入口）。"""
        return self._config.dev


def _raw_request(host: str, port: int, target: str, token: str) -> str:
    """发送一行原始 HTTP 请求并返回状态行，用于构造 absolute-form 请求行。"""
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


def run_selfcheck(config: AppConfig, schema_version: int) -> int:
    """阶段一验收自检：只跑 HTTP 层检查，不打开窗口。

    覆盖：
      1. 无 token 请求被拒（1002 / 401）
      2. 带 token 健康检查返回 200 且 code=0
      3. ``schema_version`` 已写入且与配置一致
      4. 连续 20 次复用 keep-alive 的请求全部 200（R-17 回归）
      5. 伪造 Host 被拒绝（NFR-S5）
      6. absolute-form 请求行被拒绝（R-17 缓解措施 ③）

    返回 0 表示全部通过，1 表示存在失败项。
    """
    import httpx

    failures: list[str] = []

    def report(name: str, passed: bool, detail: str = "") -> None:
        status = "PASS" if passed else "FAIL"
        suffix = f" — {detail}" if detail else ""
        print(f"[{status}] {name}{suffix}")
        if not passed:
            failures.append(name)

    # trust_env=False：R-17 缓解措施 ①，禁止 httpx 读取环境代理
    with httpx.Client(
        base_url=config.base_url, trust_env=False, timeout=10.0
    ) as client:
        response = client.get("/api/system/health")
        report(
            "无 token 请求被拒",
            response.status_code == 401 and response.json().get("code") == 1002,
            f"HTTP {response.status_code}, code={response.json().get('code')}",
        )

        response = client.get(
            "/api/system/health", headers={TOKEN_HEADER: config.token}
        )
        payload = response.json()
        report(
            "健康检查返回 200",
            response.status_code == 200 and payload.get("code") == 0,
            f"HTTP {response.status_code}, code={payload.get('code')}, "
            f"schema={payload.get('data', {}).get('schema_version')}",
        )
        report(
            "schema_version 已写入",
            payload.get("data", {}).get("schema_version") == config.schema_version,
            f"期望 {config.schema_version}，"
            f"实际 {payload.get('data', {}).get('schema_version')}",
        )
        report(
            "迁移后版本号与配置一致",
            schema_version == config.schema_version,
            f"apply_migrations 返回 {schema_version}",
        )

        codes = [
            client.get(
                "/api/system/health", headers={TOKEN_HEADER: config.token}
            ).status_code
            for _ in range(CHECK_ROUNDS)
        ]
        report(
            f"连续 {CHECK_ROUNDS} 次请求全部 200",
            set(codes) == {200},
            f"状态码集合={sorted(set(codes))}",
        )

        response = client.get(
            "/api/system/health",
            headers={TOKEN_HEADER: config.token, "Host": "evil.example"},
        )
        report(
            "伪造 Host 被拒",
            response.status_code == 401 and response.json().get("code") == 1002,
            f"HTTP {response.status_code}",
        )

    # absolute-form 请求行需绕过 httpx，直接写 socket
    status_line = _raw_request(
        config.host,
        config.port,
        f"http://{config.host}:{config.port}/api/system/health",
        config.token,
    )
    report(
        "absolute-form 请求行被拒",
        "200" not in status_line,
        f"响应首行={status_line!r}",
    )

    print()
    if failures:
        print(f"自检失败：{len(failures)} 项未通过 -> {', '.join(failures)}")
        return 1
    print("自检通过：阶段一验收项全部满足")
    return 0


def bootstrap() -> tuple[AppConfig, Database, int]:
    """执行窗口创建之前的全部启动步骤，返回 ``(config, database, schema_version)``。"""
    # R-17 缓解措施 ②：必须在创建 WebView 之前清除，避免子进程继承代理设置
    removed = clear_proxy_env()
    if removed:
        print(f"已清除代理环境变量: {', '.join(removed)}")

    config: AppConfig = load_config()
    ensure_data_dirs(config)
    logging_service.configure_logging(config.data_dir)
    logging.getLogger("inkwell").info(
        "启动: version=%s data_dir=%s", config.version, config.data_dir
    )

    database = Database(config.db_path)
    healthy, messages = database.quick_check()
    if not healthy:
        raise RuntimeError(f"数据库自检失败：{'; '.join(messages)}")

    schema_version = apply_migrations(database, config.data_dir)
    logging.getLogger("inkwell").info("数据库就绪: schema_version=%s", schema_version)
    print(f"数据目录: {config.data_dir}")
    print(f"schema_version: {schema_version}")
    return config, database, schema_version


def launch_window(config: AppConfig) -> None:
    """创建并运行窗口（必须在主线程调用）。"""
    import webview

    webview.create_window(
        title=WINDOW_TITLE,
        url=f"{config.base_url}/",
        js_api=WindowApi(config),
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=WINDOW_MIN_SIZE,
        text_select=True,  # 默认 False；写作应用必须允许选中文本
    )
    # private_mode=False：默认 True 会让 localStorage 不保留，
    # 破坏「暂存兜底」(AC-4) 与「恢复上次项目」。
    # storage_path：不指定时 pywebview 会把 WebView2 的 UserDataFolder 放在
    # %APPDATA%\pywebview（系统盘）并随使用增长；显式指向数据目录，避免 C 盘膨胀。
    webview.start(
        debug=config.dev,
        private_mode=False,
        storage_path=str(config.webview_storage_dir),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inkwell 小说写作辅助工具")
    parser.add_argument(
        "--selfcheck",
        action="store_true",
        help="启动后端并执行阶段一验收自检，不打开窗口",
    )
    args = parser.parse_args(argv)

    config, database, schema_version = bootstrap()

    app = create_app(config, database)
    app.state.schema_version = schema_version
    thread = start_server(app, config.host, config.port)
    print(f"后端已启动: {config.base_url}")

    try:
        if args.selfcheck:
            return run_selfcheck(config, schema_version)
        # NFR-R8：每日备份/清理/自检全部后台异步，不阻塞窗口
        backup_service.start_background(database, config.data_dir)
        launch_window(config)
    finally:
        thread.stop()
        database.dispose()
        logging_service.reset_logging()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
