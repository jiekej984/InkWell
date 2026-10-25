"""回收站接口（§6.2 #39~#41，任务 2.8）。

GET    /trash                        回收站列表（项目/卷/章/文档/角色/组织/阵营）
POST   /trash/{type}/{id}/restore    恢复（父链校验；with_parent=true 一并恢复）
DELETE /trash/empty                  清空回收站（物理删除）
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..database import Database
from ..models import session_scope
from ..schemas import CODE_NOT_FOUND, ApiError, ok
from ..services import trash_service

router = APIRouter(tags=["trash"])


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


@router.get("/trash")
def list_trash(request: Request) -> dict:
    """§6.2 #39：回收站列表（30 天倒计时）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = trash_service.list_trash(session)
    return ok(data)


@router.post("/trash/{item_type}/{item_id}/restore")
def restore_item(
    request: Request,
    item_type: str,
    item_id: int,
    with_parent: bool = Query(
        default=False, description="父资源在回收站时是否一并恢复"
    ),
) -> dict:
    """§6.2 #40：恢复；父链缺失时返回 ``requires_parent`` 提示。

    注意：``requires_parent`` 是**提示而非错误**，HTTP 200 + code 0，
    前端据 ``data.requires_parent`` 决定是否二次确认。
    """
    database = _database(request)
    with session_scope(database.engine) as session:
        data = trash_service.restore(
            session, item_type, item_id, with_parent=with_parent
        )
    return ok(data)


@router.delete("/trash/empty")
def empty_trash(request: Request) -> dict:
    """§6.2 #41：清空回收站（物理删除，二次确认由前端负责）。"""
    database = _database(request)
    with session_scope(database.engine) as session:
        data = trash_service.empty_trash(session)
    return ok(data)
