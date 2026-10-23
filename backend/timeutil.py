"""时间与序列化工具。

BR-8：**持久化用 UTC**；§6.1 时间格式约定为 ISO 8601（UTC，带 ``Z``）。

SQLite 的 ``DATETIME`` 列经 SQLAlchemy 读写的是 **naive datetime**（不带 tzinfo），
因此这里统一约定：库里的 naive datetime 一律视为 **UTC**，读写两端都不做本地时区转换。
"""

from __future__ import annotations

from datetime import UTC, datetime

ISO_FORMAT = "seconds"


def utc_now() -> datetime:
    """当前 UTC 时间（naive，与库中 DATETIME 列一致）。"""
    return datetime.now(UTC).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    """序列化为 ISO 8601（UTC，带 ``Z``）；``None`` 原样返回。"""
    if value is None:
        return None
    return value.isoformat(timespec=ISO_FORMAT) + "Z"


def parse_iso(value: str | None) -> datetime | None:
    """从 ISO 8601 字符串解析（容忍结尾的 ``Z`` 与 ``+00:00``）。

    解析失败一律返回 ``None``，由调用方决定是否报 1001。
    """
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
