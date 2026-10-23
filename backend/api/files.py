"""静态资源与签名接口（§6.2 #36 / #37，任务 2.3）。

GET  /files/{relpath}?sig=   读取 covers/ 或 media/ 下的文件（不走 token 头，ADR-009）
POST /files/sign             批量签发/续签签名 URL（需 token）

失败语义（回归 13 / 18）：
    · 路径非法（穿越、盘符、绝对路径、非白名单根）→ **4003**
    · 签名缺失/无效/过期 → **4004**
    · 文件不存在 → **2001**

说明：报告 §6.3 列出的校验顺序是「Host → 签名 → 路径 → 存在」，本实现把
**路径规范化提到签名之前**，否则 `/files/../../inkwell.db` 会先因签名失败返回
4004，与回归 13 要求的 4003 冲突（决策 S2-08）。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..schemas import (
    CODE_NOT_FOUND,
    CODE_PATH_INVALID,
    CODE_SIGNATURE_INVALID,
    ApiError,
    ok,
)
from ..storage import DEFAULT_TTL_SECONDS, normalize_relpath, resolve_path, sign, verify

# 挂在根路径（不带 /api 前缀），由 server.create_app 直接注册
public_router = APIRouter(tags=["files"])
# 需要 token 的签名接口（挂在 /api 前缀下）
api_router = APIRouter(tags=["files"])


class SignRequest(BaseModel):
    """批量签发入参；单次上限 200 条，防止异常放大。"""

    paths: list[str] = Field(default_factory=list, max_length=200)


@public_router.get("/files/{relpath:path}")
def get_file(request: Request, relpath: str, sig: str | None = None):
    """§6.2 #36：签名静态资源（封面 / 正文图片）。"""
    config = request.app.state.config

    # 先做路径规范化：非法路径一律 4003，不因签名缺失而变成 4004
    target = resolve_path(config.data_dir, relpath)
    if target is None:
        raise ApiError(CODE_PATH_INVALID, "路径非法")

    if not verify(relpath, sig):
        raise ApiError(CODE_SIGNATURE_INVALID, "签名无效或已过期")

    if not target.is_file():
        raise ApiError(CODE_NOT_FOUND, "文件不存在")
    return FileResponse(target)


@api_router.post("/files/sign")
def sign_paths(payload: SignRequest) -> dict:
    """§6.2 #37：批量签发静态资源签名（默认 30 分钟，D-11）。"""
    items = []
    invalid = []
    for raw_path in payload.paths:
        normalized = normalize_relpath(raw_path)
        if normalized is None:
            invalid.append(raw_path)
            continue
        signature = sign(normalized)
        if signature is None:  # pragma: no cover - normalize 已校验
            invalid.append(raw_path)
            continue
        items.append(
            {
                "path": normalized,
                "url": f"/files/{normalized}?sig={signature}",
            }
        )
    return ok({"items": items, "invalid": invalid, "ttl": DEFAULT_TTL_SECONDS})
