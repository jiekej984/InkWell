"""日志、脱敏与诊断包（任务 2.13 / NFR-M4、NFR-M6）。

要求：
    · 日志落 ``logs/inkwell-YYYY-MM-DD.log``，按天切换；单文件超过 10MB 再按时间切分
    · 日志总量 ≤ **50MB**（假设阈值），超出删除最老文件；当前活动文件不删
    · **脱敏**：token、`X-Inkwell-Token`、`sig=` 签名一律替换为 ``***``；
      不记录请求正文、响应正文或认证头（请求日志只记方法/路径/状态/耗时）
    · **前端上报兜底**（#44）：``sanitize_client_report`` 去 HTML 标签、按字段名
      丢弃正文字段、限长后再落盘 —— 即使调用方误把正文 HTML 传给 ``message``/``context``，
      写进日志的也只是一行脱敏摘要（≥300 字符截断，正文字段整值省略）
    · 诊断包：日志 + 库结构摘要（表/列/索引/计数），**不含正文 / token / 签名**

说明：日志格式与阈值是报告 §12.1 的假设值，阶段四可调。
"""

from __future__ import annotations

import io
import json
import logging
import re
import sqlite3
import zipfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import SCHEMA_VERSION, AppConfig
from ..database import Database

LOG_SUBDIR = "logs"
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_MESSAGE_CHARS = 1000
MAX_DIAGNOSTIC_LOG_BYTES = 5 * 1024 * 1024
DIAGNOSTIC_LOG_FILES = 7
MAX_CLIENT_MESSAGE_CHARS = 300
MAX_CLIENT_CONTEXT_CHARS = 120
BODY_ELIDED = "[正文已省略]"

LEVELS = {
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}

_SECRET_PATTERNS = (
    re.compile(r"(?i)(x-inkwell-token\s*[:=]\s*)[^\s,;\"']+"),
    re.compile(r"(?i)(\"?(?:token|signature|sig)\"?\s*[:=]\s*\"?)[^\s,;\"'}&]+"),
)

# 前端上报里「一看就是正文」的字段名：整值丢弃，只保留占位符
_CLIENT_BODY_KEYS = frozenset(
    {
        "body",
        "content",
        "content_html",
        "content_text",
        "draft",
        "excerpt",
        "html",
        "payload",
        "response",
        "snippet",
        "text",
    }
)
_HTML_TAG_RE = re.compile(r"<[^>]{1,500}>")
_WHITESPACE_RE = re.compile(r"\s+")


def redact(text: Any) -> str:
    """敏感信息脱敏 + 长度截断（日志专用）。"""
    if text is None:
        return ""
    value = str(text)
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(lambda match: match.group(1) + "***", value)
    return value[:MAX_MESSAGE_CHARS]


def _strip_html(text: str) -> str:
    """去掉富文本标签：正文片段几乎都带标签，标签本身就是「这段是正文」的信号。"""
    return _HTML_TAG_RE.sub("", text)


def sanitize_client_report(
    message: Any, context: Mapping[str, Any] | None
) -> tuple[str, dict[str, Any] | None]:
    """#44 前端上报的正文兜底（NFR-M4 的「设计安全」部分）。

    ``redact`` 只按 token / 签名关键字处理；若调用方把响应正文或编辑器片段
    传进 ``message`` / ``context``，这里按「去标签 + 正文字段整值省略 + 限长」
    再兜一层，保证日志文件里不会出现成段正文。
    """
    text = _WHITESPACE_RE.sub(" ", _strip_html(str(message or ""))).strip()
    if len(text) > MAX_CLIENT_MESSAGE_CHARS:
        text = f"{text[:MAX_CLIENT_MESSAGE_CHARS]}…[已截断]"

    safe_context: dict[str, Any] | None = None
    if context:
        safe_context = {}
        for key, value in context.items():
            if str(key).lower() in _CLIENT_BODY_KEYS:
                safe_context[key] = BODY_ELIDED
                continue
            if value is None or isinstance(value, (bool, int, float)):
                safe_context[key] = value  # 标量无正文风险，保留原类型
                continue
            if isinstance(value, str):
                rendered = value
            else:
                try:
                    rendered = json.dumps(value, ensure_ascii=False, default=str)
                except (TypeError, ValueError):  # pragma: no cover - 防御性兜底
                    rendered = str(value)
            rendered = _WHITESPACE_RE.sub(" ", _strip_html(rendered)).strip()
            safe_context[key] = rendered[:MAX_CLIENT_CONTEXT_CHARS]
    return text, safe_context


class DailyRotatingHandler(logging.Handler):
    """按本地日期写文件；单文件超限时按时间切分。"""

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._day: str | None = None
        self._stream: Any = None
        self._bytes = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            day = datetime.now().strftime("%Y-%m-%d")
            self._ensure_stream(day)
            line = self.format(record) + "\n"
            encoded = line.encode("utf-8")
            if self._bytes + len(encoded) > MAX_FILE_BYTES:
                self._rotate_size(day)
                self._ensure_stream(day)
            self._stream.write(line)
            self._stream.flush()
            self._bytes += len(encoded)
            enforce_total_size(self.directory)
        except Exception:  # pragma: no cover - 日志失败不能影响主流程
            self.handleError(record)

    def _ensure_stream(self, day: str) -> None:
        if self._stream is not None and self._day == day:
            return
        self._close()
        self._day = day
        path = self.directory / f"inkwell-{day}.log"
        self._stream = open(path, "a", encoding="utf-8")
        self._bytes = path.stat().st_size

    def _rotate_size(self, day: str) -> None:
        self._close()
        path = self.directory / f"inkwell-{day}.log"
        if not path.exists():
            return
        stamp = datetime.now().strftime("%H%M%S")
        target = self.directory / f"inkwell-{day}-{stamp}.log"
        index = 1
        while target.exists():
            target = self.directory / f"inkwell-{day}-{stamp}_{index}.log"
            index += 1
        path.rename(target)

    def _close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
            self._bytes = 0

    def close(self) -> None:
        self._close()
        super().close()


def enforce_total_size(
    directory: Path,
    max_bytes: int | None = None,
) -> int:
    """日志总量控制：按修改时间删最老文件，返回剩余字节数。"""
    limit = MAX_TOTAL_BYTES if max_bytes is None else max_bytes
    directory = Path(directory)
    if not directory.is_dir():
        return 0
    files = sorted(
        (path for path in directory.glob("inkwell-*.log") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
    )
    total = sum(path.stat().st_size for path in files)
    while total > limit and len(files) > 1:
        victim = files.pop(0)
        size = victim.stat().st_size
        try:
            victim.unlink()
        except OSError:  # pragma: no cover
            break
        total -= size
    return total


def configure_logging(data_dir: Path) -> logging.Logger:
    """配置 ``inkwell`` 日志器（幂等；换目录时重建 handler）。"""
    logger = logging.getLogger("inkwell")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    directory = Path(data_dir) / LOG_SUBDIR
    for handler in list(logger.handlers):
        if isinstance(handler, DailyRotatingHandler):
            if handler.directory == directory:
                return logger
            logger.removeHandler(handler)
            handler.close()

    handler = DailyRotatingHandler(directory)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    return logger


def reset_logging() -> None:
    """关闭并移除 ``inkwell`` 日志 handler（测试与退出时使用）。"""
    logger = logging.getLogger("inkwell")
    for handler in list(logger.handlers):
        if isinstance(handler, DailyRotatingHandler):
            logger.removeHandler(handler)
            handler.close()


def log_event(
    level: str,
    message: Any,
    *,
    scope: str = "frontend",
    context: Mapping[str, Any] | None = None,
) -> None:
    """写一条脱敏日志（#44 与后端关键路径共用）。"""
    logger = logging.getLogger("inkwell")
    text = redact(message)
    if context:
        try:
            rendered = json.dumps(dict(context), ensure_ascii=False)
        except (TypeError, ValueError):
            rendered = str(context)
        text = f"{text} | {redact(rendered)}"
    logger.log(LEVELS.get(level, logging.INFO), "[%s] %s", scope, text)


# --------------------------------------------------------------------------
# 诊断包
# --------------------------------------------------------------------------


def _schema_summary(database: Database) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{database.db_path.as_posix()}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        summary: dict[str, Any] = {"tables": {}}
        for table in tables:
            columns = [
                {
                    "name": row[1],
                    "type": row[2],
                    "notnull": bool(row[3]),
                    "pk": bool(row[5]),
                }
                for row in conn.execute(f"PRAGMA table_info({table})")
            ]
            indexes = [row[1] for row in conn.execute(f"PRAGMA index_list({table})")]
            try:
                count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:  # pragma: no cover - 虚拟表
                count = None
            summary["tables"][table] = {
                "columns": columns,
                "indexes": indexes,
                "rows": count,
            }
        try:
            version = conn.execute(
                "SELECT value FROM app_meta WHERE key='schema_version'"
            ).fetchone()
        except sqlite3.Error:
            version = None
        summary["schema_version"] = version[0] if version else None
        return summary
    finally:
        conn.close()


def build_diagnostics(config: AppConfig, database: Database) -> bytes:
    """生成诊断包 zip：日志 + 库结构摘要，不含正文。"""
    buffer = io.BytesIO()
    schema = _schema_summary(database)
    headline = (
        "Inkwell 诊断包\n"
        f"生成时间：{datetime.now().isoformat(timespec='seconds')}\n"
        f"应用版本：{config.version}\n"
        f"schema_version：{schema.get('schema_version')}（应用支持 {SCHEMA_VERSION}）\n"
        f"数据目录：{config.data_dir}\n"
        "说明：本包仅含运行日志与库结构摘要，不包含正文、token 或签名。\n"
    )

    log_dir = Path(config.data_dir) / LOG_SUBDIR
    logs = sorted(
        (path for path in log_dir.glob("inkwell-*.log") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:DIAGNOSTIC_LOG_FILES]

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.txt", headline)
        archive.writestr(
            "schema.json", json.dumps(schema, ensure_ascii=False, indent=2)
        )
        total = 0
        for path in logs:
            size = path.stat().st_size
            if total + size > MAX_DIAGNOSTIC_LOG_BYTES:
                continue
            archive.write(path, arcname=f"logs/{path.name}")
            total += size
    return buffer.getvalue()
