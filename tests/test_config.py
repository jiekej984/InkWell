"""任务 1.3 配置层测试：数据目录解析、代理清理、端口与 token。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import (
    DATA_SUBDIRS,
    AppConfig,
    clear_proxy_env,
    ensure_data_dirs,
    generate_token,
    is_frozen,
    load_config,
    pick_free_port,
    resolve_data_dir,
    source_root,
)


def test_env_override_has_highest_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "CustomDir"
    monkeypatch.setenv("INKWELL_DATA_DIR", str(override))
    assert resolve_data_dir() == override


def test_env_override_expands_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INKWELL_DATA_DIR", "~")
    resolved = resolve_data_dir()
    assert resolved.is_absolute()
    assert "~" not in str(resolved)


def test_dev_mode_falls_back_to_repo_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INKWELL_DATA_DIR", raising=False)
    if is_frozen():
        pytest.skip("当前运行在打包环境中，不适用开发模式判定")
    assert resolve_data_dir() == source_root() / "data"


def test_ensure_data_dirs_creates_all_subdirs(config: AppConfig) -> None:
    ensure_data_dirs(config)
    assert config.data_dir.is_dir()
    for name in DATA_SUBDIRS:
        assert config.subdir(name).is_dir(), name


def test_ensure_data_dirs_rejects_unknown_subdir(config: AppConfig) -> None:
    with pytest.raises(ValueError):
        config.subdir("not-a-subdir")


def test_clear_proxy_env_removes_known_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:64530")
    removed = clear_proxy_env()
    # Windows 的 os.environ 会把键名规范化为大写，但 clear_proxy_env 按
    # _PROXY_ENV_VARS 的字面量返回，因此这里比较的是"被清除的变量名"。
    assert set(removed) == {"http_proxy", "https_proxy", "all_proxy"}
    assert clear_proxy_env() == []


def test_pick_free_port_returns_bindable_port() -> None:
    port = pick_free_port()
    assert 1024 < port < 65536


def test_generate_token_is_unique_and_url_safe() -> None:
    first, second = generate_token(), generate_token()
    assert first != second
    assert len(first) >= 32
    assert all(char.isalnum() or char in "-_" for char in first)


def test_load_config_uses_env_data_dir(data_dir: Path) -> None:
    cfg = load_config()
    assert cfg.data_dir == data_dir
    assert cfg.db_path == data_dir / "inkwell.db"
    assert isinstance(cfg, AppConfig)


def test_frozen_mode_disables_dev_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """阶段四 4.2「禁调试」：打包产物里 dev 必须为 False（DevTools / 右键菜单随之关闭）。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("INKWELL_DATA_DIR", str(tmp_path))
    cfg = load_config()
    assert is_frozen() is True
    assert cfg.dev is False


def test_source_mode_keeps_dev_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("INKWELL_DATA_DIR", str(tmp_path))
    cfg = load_config()
    assert cfg.dev is True
