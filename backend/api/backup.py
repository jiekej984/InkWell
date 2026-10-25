"""备份与恢复接口（§6.2 #32~#34，任务 2.9）。

POST /backup                 立即备份【长任务】
GET  /backups                备份列表（忽略 .tmp）+ 磁盘余量
POST /backups/{name}/restore 从备份恢复【长任务】（先校验，损坏/版本过高同步拒绝）
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..config import SCHEMA_VERSION, AppConfig
from ..database import Database
from ..schemas import (
    CODE_DB_ERROR,
    CODE_NOT_FOUND,
    CODE_SCHEMA_INCOMPATIBLE,
    ApiError,
    ok,
)
from ..services import backup_service
from .maintenance import submit_task

router = APIRouter(tags=["backup"])


def _database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:  # pragma: no cover - 由启动流程注入
        raise ApiError(CODE_NOT_FOUND, "数据库未就绪")
    return database


def _config(request: Request) -> AppConfig:
    return request.app.state.config


@router.post("/backup")
def create_backup(request: Request) -> dict:
    """§6.2 #32：立即备份（长任务，原子写入 + 完整性校验）。"""
    database = _database(request)
    config = _config(request)
    return submit_task(
        request,
        "backup",
        lambda report: backup_service.create_backup(
            database, config.data_dir, kind="manual", report=report
        ),
    )


@router.get("/backups")
def list_backups(request: Request) -> dict:
    """§6.2 #33：备份列表（忽略 .tmp）+ 磁盘余量。"""
    config = _config(request)
    data = {
        "items": backup_service.list_backups(config.data_dir),
        **backup_service.backup_metadata(config.data_dir),
    }
    return ok(data)


@router.post("/backups/{name}/restore")
def restore_backup(request: Request, name: str) -> dict:
    """§6.2 #34：从备份恢复（长任务）。

    同步阶段先做「路径 → 存在 → 完整性 → schema_version」校验：
    损坏 → **3001**，版本高于应用 → **3003**，非法文件名 → **4003**。
    """
    database = _database(request)
    config = _config(request)

    path = backup_service.backup_path(config.data_dir, name)
    verification = backup_service.verify_backup(path)
    if not verification.get("ok"):
        raise ApiError(
            CODE_DB_ERROR, f"备份校验失败：{verification.get('reason', '未知原因')}"
        )
    schema_version = int(verification["schema_version"])
    if schema_version == 0:
        raise ApiError(
            CODE_DB_ERROR,
            "该备份是首次建库前的空快照，恢复会清空全部数据；请选择其他备份",
        )
    if schema_version > SCHEMA_VERSION:
        raise ApiError(
            CODE_SCHEMA_INCOMPATIBLE,
            f"备份 schema_version={schema_version} 高于应用支持的 {SCHEMA_VERSION}",
        )

    # 恢复成功后会迁移到当前版本；先同步 health 的版本号
    request.app.state.schema_version = SCHEMA_VERSION
    return submit_task(
        request,
        "restore",
        lambda report: backup_service.restore_backup(
            database, config.data_dir, name, report=report
        ),
    )
