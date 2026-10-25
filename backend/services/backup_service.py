"""备份、恢复与启动后台流程（任务 2.9 / FR-6.1~6.3、6.7、6.8；NFR-R4/R5/R7~R10）。

命名约定（``backups/`` 目录）：
    · ``inkwell_backup_YYYYMMDD_HHMMSS.db``   手动备份（#32），保留由用户决定
    · ``inkwell_daily_YYYYMMDD_HHMMSS.db``    每日自动备份，保留 7 日 + 4 周
    · ``inkwell_premigrate_*.db``             迁移前自动备份（既有一致）
    · ``inkwell_prerestore_*.db``             恢复前自动备份
    · ``*.tmp``                               扫描时忽略（BR-7）

启动后台（L-03）：
    · 每日首次备份、回收站 30 天清理、过期备份清理、孤儿媒体清理
    · 每周完整 integrity_check、磁盘余量预警、WAL checkpoint
    · **时间回拨**（BR-8）：库内记录日期晚于今天 → 跳过备份与清理并告警

恢复（#34）：
    · 先校验（quick_check + schema_version）；损坏 → 3001，版本过高 → 3003
    · 恢复前自动备份当前库（prerestore）
    · 关闭连接 → 替换文件（去掉 WAL/SHM）→ 重开 → 必要时迁移
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from ..config import SCHEMA_VERSION
from ..database import Database
from ..migrate import apply_migrations
from ..models import (
    Chapter,
    ChapterVersion,
    Character,
    Document,
    DocumentVersion,
    session_scope,
)
from ..schemas import (
    CODE_DB_ERROR,
    CODE_NOT_FOUND,
    CODE_PATH_INVALID,
    CODE_SCHEMA_INCOMPATIBLE,
    ApiError,
)

log = logging.getLogger(__name__)

BACKUP_SUBDIR = "backups"
MANUAL_PREFIX = "inkwell_backup_"
DAILY_PREFIX = "inkwell_daily_"
PREMIGRATE_PREFIX = "inkwell_premigrate_"
PRERESTORE_PREFIX = "inkwell_prerestore_"
BACKUP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.db$")
PREMIGRATE_VERSION_RE = re.compile(r"_v(\d+)\.db$")

DISK_WARNING_BYTES = 1024 * 1024 * 1024  # NFR-R9 假设阈值 1GB
DAILY_KEEP_DAYS = 7
WEEKLY_KEEP = 4
ORPHAN_MIN_AGE_SECONDS = 24 * 3600

_META_BACKUP_DATE = "last_backup_date"
_META_CLEANUP_DATE = "last_cleanup_date"
_META_INTEGRITY_DATE = "last_integrity_check_date"

_MEDIA_REF_RE = re.compile(r'media/[^\s"\'<>]+')


# --------------------------------------------------------------------------
# 路径 / meta / 磁盘
# --------------------------------------------------------------------------


def backups_dir(data_dir: Path) -> Path:
    return Path(data_dir) / BACKUP_SUBDIR


def backup_path(data_dir: Path, name: str) -> Path:
    """校验备份名并返回绝对路径（防穿越）。"""
    if not BACKUP_NAME_RE.match(name or ""):
        raise ApiError(CODE_PATH_INVALID, "备份文件名非法")
    directory = backups_dir(data_dir).resolve()
    path = (directory / name).resolve()
    if path.parent != directory:
        raise ApiError(CODE_PATH_INVALID, "备份文件名非法")
    if not path.is_file():
        raise ApiError(CODE_NOT_FOUND, "备份不存在")
    return path


def _get_meta(database: Database, key: str) -> str | None:
    with session_scope(database.engine) as session:
        row = session.execute(
            text("SELECT value FROM app_meta WHERE key = :key"), {"key": key}
        ).first()
    return str(row[0]) if row else None


def _set_meta(database: Database, key: str, value: str) -> None:
    with session_scope(database.engine) as session:
        session.execute(
            text(
                "INSERT INTO app_meta(key, value) VALUES (:key, :value) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
            ),
            {"key": key, "value": value},
        )


def disk_free_bytes(data_dir: Path) -> int:
    try:
        return int(shutil.disk_usage(str(data_dir)).free)
    except OSError:  # pragma: no cover - 路径异常
        return -1


def _stamp(now: datetime) -> str:
    return now.strftime("%Y%m%d_%H%M%S")


def _local_date(value: float) -> date:
    return datetime.fromtimestamp(value).date()


def _iso_local(value: float) -> str:
    return datetime.fromtimestamp(value).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# 创建 / 列表 / 校验
# --------------------------------------------------------------------------


def _next_path(directory: Path, prefix: str, now: datetime) -> Path:
    stamp = _stamp(now)
    candidate = directory / f"{prefix}{stamp}.db"
    index = 1
    while candidate.exists():
        candidate = directory / f"{prefix}{stamp}_{index}.db"
        index += 1
    return candidate


def create_backup(
    database: Database,
    data_dir: Path,
    *,
    kind: str = "manual",
    now: datetime | None = None,
    report: Any = None,
) -> dict[str, Any]:
    """#32：立即备份（原子写入 + 完整性校验）。"""
    now = now or datetime.now()
    prefix = DAILY_PREFIX if kind == "daily" else MANUAL_PREFIX
    directory = backups_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = _next_path(directory, prefix, now)

    if report:
        report(10, "正在写入备份")
    database.atomic_backup(target)
    if report:
        report(90, "备份完成")

    stat = target.stat()
    return {
        "name": target.name,
        "kind": kind,
        "size": stat.st_size,
        "created_at": _iso_local(stat.st_mtime),
    }


def _kind_of(name: str) -> str:
    if name.startswith(PREMIGRATE_PREFIX):
        return "premigrate"
    if name.startswith(PRERESTORE_PREFIX):
        return "prerestore"
    if name.startswith(DAILY_PREFIX):
        return "daily"
    return "manual"


def _empty_snapshot(name: str) -> bool:
    """首次建库前的 ``_v0`` 空快照：可列出、但不可恢复（恢复等于清空数据）。"""
    match = PREMIGRATE_VERSION_RE.search(name or "")
    return bool(match and int(match.group(1)) == 0)


def list_backups(data_dir: Path) -> list[dict[str, Any]]:
    """#33：备份列表（忽略 .tmp 与损坏文件名），按时间倒序。"""
    directory = backups_dir(data_dir)
    if not directory.is_dir():
        return []
    items = []
    for path in directory.glob("*.db"):
        if not path.is_file() or path.name.endswith(".tmp"):
            continue
        try:
            stat = path.stat()
        except OSError:  # pragma: no cover
            continue
        empty = _empty_snapshot(path.name)
        items.append(
            {
                "name": path.name,
                "kind": _kind_of(path.name),
                "size": stat.st_size,
                "created_at": _iso_local(stat.st_mtime),
                "restorable": not empty,
                "warning": (
                    "首次建库前的空快照，恢复会清空全部数据，不可用于恢复"
                    if empty
                    else None
                ),
            }
        )
    items.sort(key=lambda item: str(item["created_at"]), reverse=True)
    return items


def verify_backup(path: Path) -> dict[str, Any]:
    """校验备份：quick_check + schema_version（#34 的前置）。"""
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            rows = [str(row[0]) for row in conn.execute("PRAGMA quick_check")]
            if rows != ["ok"]:
                return {"ok": False, "reason": f"完整性检查失败：{'; '.join(rows)}"}
            meta = conn.execute(
                "SELECT value FROM app_meta WHERE key = 'schema_version'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"ok": False, "reason": f"无法读取备份：{exc}"}

    if meta is None:
        return {"ok": False, "reason": "备份缺少 schema_version 元数据"}
    try:
        schema_version = int(meta[0])
    except (TypeError, ValueError):
        return {"ok": False, "reason": "schema_version 非法"}
    return {"ok": True, "schema_version": schema_version}


# --------------------------------------------------------------------------
# 恢复
# --------------------------------------------------------------------------


def restore_backup(
    database: Database,
    data_dir: Path,
    name: str,
    *,
    report: Any = None,
) -> dict[str, Any]:
    """#34：从备份恢复（长任务函数；调用方已做同步校验）。"""
    source = backup_path(data_dir, name)
    verification = verify_backup(source)
    if not verification.get("ok"):
        raise ApiError(CODE_DB_ERROR, f"备份校验失败：{verification.get('reason')}")
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

    directory = backups_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    prerestore = _next_path(directory, PRERESTORE_PREFIX, datetime.now())
    if report:
        report(10, "备份当前数据")
    database.atomic_backup(prerestore)

    if report:
        report(35, "关闭数据库连接")
    database.dispose()

    sidecars = [
        database.db_path.with_name(database.db_path.name + suffix)
        for suffix in ("-wal", "-shm")
    ]
    tmp = database.db_path.with_name(database.db_path.name + ".restore.tmp")
    if tmp.exists():
        tmp.unlink()
    try:
        for sidecar in sidecars:
            if sidecar.exists():
                sidecar.unlink()
        shutil.copyfile(source, tmp)
        os.replace(tmp, database.db_path)
    finally:
        if tmp.exists():
            tmp.unlink()
        database.reopen()

    if report:
        report(65, "检查数据库版本")
    version = apply_migrations(database, data_dir)
    if report:
        report(95, "恢复完成")

    return {
        "restored_from": name,
        "schema_version": version,
        "backup_before": prerestore.name,
        "restored_at": datetime.now().isoformat(timespec="seconds"),
    }


# --------------------------------------------------------------------------
# 备份保留 / 孤儿媒体（后台清理）
# --------------------------------------------------------------------------


def prune_old_backups(
    data_dir: Path,
    *,
    now: datetime | None = None,
    keep_daily: int = DAILY_KEEP_DAYS,
    keep_weekly: int = WEEKLY_KEEP,
) -> list[str]:
    """FR-6.1：每日备份保留 7 日 + 4 周；手动/迁移/恢复前备份不自动删。"""
    now = now or datetime.now()
    directory = backups_dir(data_dir)
    if not directory.is_dir():
        return []

    entries = [
        path
        for path in directory.glob(f"{DAILY_PREFIX}*.db")
        if path.is_file() and not path.name.endswith(".tmp")
    ]
    if not entries:
        return []

    entries.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    by_date: dict[date, list[Path]] = {}
    for path in entries:
        by_date.setdefault(_local_date(path.stat().st_mtime), []).append(path)

    ordered_dates = sorted(by_date, reverse=True)
    keep: set[Path] = set()
    for day in ordered_dates[:keep_daily]:
        keep.update(by_date[day])

    weekly: dict[tuple[int, int], Path] = {}
    for day in ordered_dates[keep_daily:]:
        iso = day.isocalendar()
        weekly.setdefault((iso.year, iso.week), by_date[day][0])
    for key in sorted(weekly, reverse=True)[:keep_weekly]:
        keep.add(weekly[key])

    removed = []
    for path in entries:
        if path not in keep:
            try:
                path.unlink()
                removed.append(path.name)
            except OSError:  # pragma: no cover
                log.warning("删除过期备份失败: %s", path)
    return removed


def _referenced_media(database: Database) -> set[str]:
    referenced: set[str] = set()
    with session_scope(database.engine) as session:
        for model in (Chapter, Document):
            last_id = 0
            while True:
                rows = session.execute(
                    select(model.id, model.content)
                    .where(model.id > last_id, model.content.is_not(None))
                    .order_by(model.id)
                    .limit(100)
                ).all()
                if not rows:
                    break
                for _, content in rows:
                    referenced.update(_MEDIA_REF_RE.findall(content or ""))
                last_id = int(rows[-1][0])

        # V2.0：角色立绘存在 character.avatar_path，正文里没有引用。
        # 不登记就会被「孤儿媒体清理」当成无主文件删掉（含回收站里的角色）。
        rows = session.execute(
            select(Character.avatar_path).where(Character.avatar_path.is_not(None))
        ).all()
        for (avatar_path,) in rows:
            if avatar_path:
                referenced.add(str(avatar_path))

        # 版本快照是永久数据：当前正文删掉的图片，旧快照仍可能引用。
        for model in (ChapterVersion, DocumentVersion):
            last_id = 0
            while True:
                rows = session.execute(
                    select(model.id, model.content)
                    .where(model.id > last_id)
                    .order_by(model.id)
                    .limit(100)
                ).all()
                if not rows:
                    break
                for _, content in rows:
                    referenced.update(_MEDIA_REF_RE.findall(content or ""))
                last_id = int(rows[-1][0])
    return referenced


def cleanup_orphan_media(
    database: Database,
    data_dir: Path,
    *,
    now: datetime | None = None,
    min_age_seconds: int = ORPHAN_MIN_AGE_SECONDS,
) -> int:
    """删除未被正文/设定引用且超过 24 小时的媒体文件（避免误删刚上传的图）。"""
    media_root = Path(data_dir) / "media"
    if not media_root.is_dir():
        return 0

    referenced = _referenced_media(database)
    # 保存失败时草稿可能仍是正文的唯一副本，其中的图片也要保住
    draft_dir = Path(data_dir) / "drafts"
    if draft_dir.is_dir():
        for path in draft_dir.glob("chapter_*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(payload, dict):
                content = payload.get("content_html") or ""
                referenced.update(_MEDIA_REF_RE.findall(str(content)))
    cutoff = (now or datetime.now()).timestamp() - min_age_seconds
    removed = 0
    base = Path(data_dir)
    for path in media_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            relpath = path.relative_to(base).as_posix()
            if relpath in referenced:
                continue
            if path.stat().st_mtime > cutoff:
                continue
            path.unlink()
            removed += 1
        except OSError:  # pragma: no cover - 正在被占用
            log.warning("清理孤儿媒体失败: %s", path)
    return removed


# --------------------------------------------------------------------------
# 启动后台流程（L-03）
# --------------------------------------------------------------------------


def _today(now: datetime) -> str:
    if now.tzinfo is not None:
        return now.astimezone().date().isoformat()
    return now.date().isoformat()


def run_startup_tasks(
    database: Database,
    data_dir: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """后台异步任务（NFR-R8）：只执行当日未做过的项；异常不阻断应用。"""
    now = now or datetime.now()
    today = _today(now)
    results: dict[str, Any] = {
        "skipped_rollback": False,
        "daily_backup": None,
        "cleanup": None,
        "integrity": None,
        "disk_free": disk_free_bytes(data_dir),
    }

    try:
        last_backup = _get_meta(database, _META_BACKUP_DATE)
        last_cleanup = _get_meta(database, _META_CLEANUP_DATE)
        last_integrity = _get_meta(database, _META_INTEGRITY_DATE)

        stored = [
            value for value in (last_backup, last_cleanup, last_integrity) if value
        ]
        if any(value > today for value in stored):
            results["skipped_rollback"] = True
            log.warning("检测到系统时间回拨（记录日期晚于今天），跳过本次备份与清理")
            database.checkpoint("TRUNCATE")
            return results

        if last_backup != today:
            results["daily_backup"] = create_backup(
                database, data_dir, kind="daily", now=now
            )
            _set_meta(database, _META_BACKUP_DATE, today)

        if last_cleanup != today:
            from . import trash_service  # 延迟导入，避免服务间循环

            with session_scope(database.engine) as session:
                trash = trash_service.purge_expired_trash(session)
            results["cleanup"] = {
                "trash": trash,
                "backups": prune_old_backups(data_dir, now=now),
                "orphan_media": cleanup_orphan_media(database, data_dir, now=now),
            }
            _set_meta(database, _META_CLEANUP_DATE, today)

        if (
            last_integrity is None
            or (now.date() - date.fromisoformat(last_integrity)).days >= 7
        ):
            healthy, messages = database.integrity_check()
            results["integrity"] = {"ok": healthy, "messages": messages}
            if healthy:
                _set_meta(database, _META_INTEGRITY_DATE, today)
            else:
                log.error("完整性检查失败: %s", "; ".join(messages))

        if 0 <= results["disk_free"] < DISK_WARNING_BYTES:
            log.warning(
                "磁盘余量低于 1GB（%.1f MB），请及时清理",
                results["disk_free"] / 1024 / 1024,
            )

        database.checkpoint("TRUNCATE")
    except Exception:  # 后台任务不允许拖垮应用
        log.exception("启动后台任务失败")
        results["error"] = True
    return results


def start_background(database: Database, data_dir: Path) -> threading.Thread:
    """在守护线程中执行启动后台流程（主线程不等待）。"""
    thread = threading.Thread(
        target=run_startup_tasks,
        args=(database, data_dir),
        name="inkwell-background",
        daemon=True,
    )
    thread.start()
    return thread


def backup_metadata(data_dir: Path) -> dict[str, Any]:
    """#33 附加信息：磁盘余量 + 最近每日备份日期。"""
    items = list_backups(data_dir)
    daily = [item for item in items if item["kind"] == "daily"]
    return {
        "disk_free_bytes": disk_free_bytes(data_dir),
        "last_daily_backup": daily[0] if daily else None,
    }
