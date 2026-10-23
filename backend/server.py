"""FastAPI 应用工厂与安全中间件。

对应 §6.1 接口约定 / ADR-002（本地 HTTP）/ ADR-009（签名 query）/ R-17（代理污染防护）。

中间件由外到内的执行顺序：
    1. ``OriginFormGuardMiddleware``  —— 拒绝 absolute-form 请求行（R-17 缓解措施 ③）
    2. ``HostGuardMiddleware``        —— 仅放行 127.0.0.1 / localhost（NFR-S5）
    3. ``TokenGuardMiddleware``       —— 校验 X-Inkwell-Token（NFR-S2）

Starlette 的 ``add_middleware`` 会把后添加的中间件放在更外层，因此下面按
「内 → 外」的顺序注册。
"""

from __future__ import annotations

import hmac
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .api import api_router
from .api.files import public_router as files_router
from .config import ALLOWED_HOSTS, APP_NAME, TOKEN_HEADER, AppConfig
from .database import Database
from .schemas import (
    CODE_PARAM_INVALID,
    CODE_PATH_INVALID,
    CODE_TOKEN_INVALID,
    ApiError,
    fail,
)
from .services.tasks import TaskManager

API_PREFIX = "/api"
STATIC_PREFIX = "/files"

Dispatch = Callable[[Request], Awaitable[Any]]
_ABSOLUTE_FORM_RE = re.compile(r"^https?://", re.IGNORECASE)
_request_logger = logging.getLogger("inkwell")


class RequestLogMiddleware(BaseHTTPMiddleware):
    """访问日志（NFR-M4）：只记方法 / 路径（去 query）/ 状态码 / 耗时，不记正文与凭据。"""

    async def dispatch(self, request: Request, call_next: Dispatch) -> Any:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            _request_logger.exception(
                "请求处理异常 %s %s", request.method, request.url.path
            )
            raise
        if request.url.path.startswith(API_PREFIX + "/"):
            duration_ms = int((time.perf_counter() - started) * 1000)
            _request_logger.info(
                "%s %s -> %s (%dms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
        return response


def is_absolute_form(scope: dict[str, Any]) -> bool:
    """判断请求行是否为 absolute-form（代理污染的典型症状）。

    origin-form 应为 ``/api/system/health``；被环境变量代理污染的客户端会发出
    ``http://127.0.0.1:8000/api/system/health``，本地源站无法匹配路由。
    """
    for key in ("path", "raw_path"):
        value = scope.get(key)
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("latin-1", errors="ignore")
        if isinstance(value, str) and _ABSOLUTE_FORM_RE.match(value):
            return True
    return False


def host_without_port(header: str) -> str:
    """从 Host 头中剥离端口，兼容 IPv6（``[::1]:8000`` → ``[::1]``）。"""
    host = header.strip().lower()
    if host.startswith("["):
        end = host.find("]")
        if end != -1:
            return host[: end + 1]
    return host.rsplit(":", 1)[0] if ":" in host else host


class OriginFormGuardMiddleware(BaseHTTPMiddleware):
    """拒绝 absolute-form 请求行（R-17 缓解措施 ③）。"""

    async def dispatch(self, request: Request, call_next: Dispatch) -> Any:
        if is_absolute_form(request.scope):
            return fail(CODE_PATH_INVALID, "非法的请求行")
        return await call_next(request)


class HostGuardMiddleware(BaseHTTPMiddleware):
    """仅放行本机来源（§6.1 / NFR-S5）。"""

    async def dispatch(self, request: Request, call_next: Dispatch) -> Any:
        host = host_without_port(request.headers.get("host", ""))
        if host not in ALLOWED_HOSTS:
            # 错误码表未定义「Host 非法」，按决策 S1-03 归入访问控制类 1002。
            return fail(CODE_TOKEN_INVALID, "非法访问来源")
        return await call_next(request)


class TokenGuardMiddleware(BaseHTTPMiddleware):
    """校验业务接口 token（§6.1 / NFR-S2）。

    ``/files/`` 前缀不在此校验：静态资源由签名 query token 保护（ADR-009），
    该路由在阶段二 2.3 实装。
    """

    def __init__(self, app: Any, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next: Dispatch) -> Any:
        if request.url.path.startswith(API_PREFIX + "/"):
            provided = request.headers.get(TOKEN_HEADER, "")
            if not _safe_equals(provided, self._token):
                return fail(CODE_TOKEN_INVALID, "token 无效")
        return await call_next(request)


def _safe_equals(left: str, right: str) -> bool:
    """定长比较，避免通过响应时间侧信道猜测 token。"""
    return hmac.compare_digest(left, right)


def create_app(config: AppConfig, database: Database | None = None) -> FastAPI:
    """构建 FastAPI 应用。"""
    app = FastAPI(
        title=APP_NAME,
        version=config.version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = config
    app.state.schema_version = None
    # 数据库在开发期允许为空（启动流程注入后才有值）
    app.state.database = database
    # 长任务管理器（进程内内存，任务 2.12 / S2-03）；重启即失是设计，不是缺陷
    app.state.tasks = TaskManager()

    app.include_router(api_router, prefix=API_PREFIX)
    # 静态资源走签名 query（ADR-009），不带 /api 前缀，也不走 token 头
    app.include_router(files_router)

    # 由内到外注册，实际执行顺序为：request-log → origin-form → host → token
    app.add_middleware(TokenGuardMiddleware, token=config.token)
    app.add_middleware(HostGuardMiddleware)
    app.add_middleware(OriginFormGuardMiddleware)
    app.add_middleware(RequestLogMiddleware)

    if config.frontend_dir.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(config.frontend_dir), html=True),
            name="frontend",
        )

    @app.exception_handler(ApiError)
    async def _handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return fail(exc.code, exc.message, exc.errors)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """入参类型错误 → 1001，保持统一响应结构（§6.1）。

        FastAPI 默认返回 422 + 自带结构，与「统一 {code,message,data}」约定冲突。
        字段级错误按约定放进 ``data.errors: [{field, reason}]``。
        """
        errors = [
            {
                "field": ".".join(str(part) for part in err.get("loc", ())[1:])
                or "body",
                "reason": err.get("msg", "参数不合法"),
            }
            for err in exc.errors()
        ]
        return fail(CODE_PARAM_INVALID, "参数校验失败", errors)

    return app
