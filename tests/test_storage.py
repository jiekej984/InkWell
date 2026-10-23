"""任务 1.3 静态资源签名测试（ADR-009 / D-10 / D-11 / NFR-S7）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.storage import (
    ALLOWED_ROOTS,
    DEFAULT_TTL_SECONDS,
    normalize_relpath,
    reset_secret,
    resolve_path,
    sign,
    verify,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_secret()
    yield
    reset_secret()


def test_sign_and_verify_roundtrip() -> None:
    signature = sign("media/chapter-1/a.png")
    assert signature is not None
    assert verify("media/chapter-1/a.png", signature) is True


def test_signature_binds_path() -> None:
    signature = sign("media/a.png")
    assert verify("media/b.png", signature) is False


def test_tampered_signature_rejected() -> None:
    signature = sign("media/a.png")
    assert signature is not None
    raw_expiry, raw_mac = signature.split(".", 1)
    tampered = f"{raw_expiry}.{raw_mac[:-2]}AA"
    assert verify("media/a.png", tampered) is False


def test_expired_signature_rejected() -> None:
    issued = 0.0
    signature = sign("media/a.png", ttl=60, now=issued)
    assert verify("media/a.png", signature, now=issued + 30) is True
    assert verify("media/a.png", signature, now=issued + 61) is False


def test_missing_signature_rejected() -> None:
    assert verify("media/a.png", "") is False
    assert verify("media/a.png", None) is False


def test_default_ttl_is_thirty_minutes() -> None:
    assert DEFAULT_TTL_SECONDS == 30 * 60


def test_sign_rejects_traversal() -> None:
    assert sign("media/../../inkwell.db") is None
    assert sign("../etc/passwd") is None


def test_sign_rejects_absolute_and_drive_paths() -> None:
    assert sign("/etc/passwd") is None
    assert sign("C:/Windows/win.ini") is None


def test_sign_rejects_paths_outside_whitelist() -> None:
    assert sign("backups/inkwell.db") is None
    assert sign("logs/app.log") is None
    assert sign("inkwell.db") is None


def test_normalize_relpath_cleans_segments() -> None:
    assert normalize_relpath("media//a.png") == "media/a.png"
    assert normalize_relpath("media/./a.png") == "media/a.png"
    assert normalize_relpath("media\\a.png") == "media/a.png"
    assert normalize_relpath("media/a%20b.png") == "media/a b.png"


def test_normalize_relpath_rejects_empty() -> None:
    assert normalize_relpath("") is None
    assert normalize_relpath("   ") is None
    assert normalize_relpath(None) is None


def test_resolve_path_stays_inside_data_dir(tmp_path: Path) -> None:
    target = resolve_path(tmp_path, "media/chapter-1/a.png")
    assert target == (tmp_path / "media" / "chapter-1" / "a.png").resolve()


def test_resolve_path_rejects_escape(tmp_path: Path) -> None:
    assert resolve_path(tmp_path, "media/../../../secret.db") is None
    assert resolve_path(tmp_path, "backups/x.db") is None


def test_allowed_roots_match_data_layout() -> None:
    # §4.4：可被外部访问的只有 covers/ 与 media/
    assert ALLOWED_ROOTS == ("covers", "media")
