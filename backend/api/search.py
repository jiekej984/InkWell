"""全文检索接口（§6.2 #31，任务 2.11）。

GET /search?q=&scope=all|chapters|documents&project_id=&page=&page_size=
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..database import Database
from ..schemas import CODE_NOT_FOUND, ApiError, ok
from ..services import search_service

router = APIRouter(tags=["search"])


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


@router.get("/search")
def search(
    request: Request,
    q: str = Query(default="", description="搜索词（≥3 字符走 FTS，否则 LIKE）"),
    scope: str = Query(default="all", description="all / chapters / documents"),
    project_id: int | None = Query(default=None, description="限定项目"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    """§6.2 #31：章节标题 + 正文 + 设定文档的全文检索。"""
    database = _database(request)
    data = search_service.search(
        database,
        query=q,
        project_id=project_id,
        scope=scope,
        page=page,
        page_size=page_size,
    )
    return ok(data)
