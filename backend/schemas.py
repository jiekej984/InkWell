"""统一响应结构与错误码。

对应报告 §6.1「接口约定」：
    统一响应 { "code": 0, "message": "ok", "data": {...} }
    字段级错误 data.errors: [{"field": "title", "reason": "不能为空"}]
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi.responses import JSONResponse

CODE_OK = 0
CODE_PARAM_INVALID = 1001  # 参数校验失败
CODE_TOKEN_INVALID = 1002  # token 无效
CODE_NOT_FOUND = 2001  # 资源不存在
CODE_DELETED = 2002  # 资源已删除
CODE_DB_ERROR = 3001  # 数据库错误
CODE_VERSION_CONFLICT = 3002  # 版本冲突
CODE_SCHEMA_INCOMPATIBLE = 3003  # 迁移/版本不兼容
CODE_FILE_WRITE_FAILED = 4001  # 文件写入失败
CODE_FILE_INVALID = 4002  # 文件格式/大小不合法
CODE_PATH_INVALID = 4003  # 路径非法
CODE_SIGNATURE_INVALID = 4004  # 签名无效或过期
CODE_AI_UNAVAILABLE = 5001  # AI 服务不可用
# 阶段二新增（决策 S2-03 / C-05）：长任务互斥。
# 报告 §6.1 错误码表无此条目，按发起人结论「加一个 3004 即可」补入。
CODE_TASK_CONFLICT = 3004  # 已有长任务进行中

# 错误码 → HTTP 状态码。
# 报告 §6.1 只定义了业务错误码、未规定 HTTP 映射（决策 S1-02）：
#   · 鉴权 / 访问控制类（1002、4004）→ 401
#   · 请求行非法（4003）→ 400
#   · 长任务冲突（3004）→ 409（S2-03：不排队、不静默挂起）
#   · 其余业务错误 → 200，由 code 字段表达
STATUS_BY_CODE: dict[int, int] = {
    CODE_TOKEN_INVALID: 401,
    CODE_SIGNATURE_INVALID: 401,
    CODE_PATH_INVALID: 400,
    CODE_TASK_CONFLICT: 409,
}


def status_for(code: int) -> int:
    return STATUS_BY_CODE.get(code, 200)


def build_body(
    code: int,
    message: str,
    data: Any = None,
    errors: Sequence[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {} if data is None else dict(data)
    if errors:
        payload = {**payload, "errors": [dict(item) for item in errors]}
    return {"code": code, "message": message, "data": payload}


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    return build_body(CODE_OK, message, data)


def fail(
    code: int,
    message: str,
    errors: Sequence[dict[str, str]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_for(code),
        content=build_body(code, message, errors=errors),
    )


class ApiError(Exception):
    """业务异常：由统一异常处理器转换为统一响应。"""

    def __init__(
        self,
        code: int,
        message: str,
        errors: Sequence[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.errors = list(errors) if errors else None
