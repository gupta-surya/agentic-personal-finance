"""Local config store: a 0600 file in a 0700 dir. No keychain, no real network."""

import json
import os
import stat
from pathlib import Path

import pytest

from finance_agent.secrets import FileSecretStore, app_data_dir, default_config_path

VALUE = "postgresql://finance_app:pw@127.0.0.1:5432/finance"


def test_file_store_is_0600_in_a_0700_dir(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.json"
    store = FileSecretStore(path)
    store.set("database_url", VALUE)

    assert store.get("database_url") == VALUE
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert json.loads(path.read_text()) == {"database_url": VALUE}


def test_file_store_delete(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / "c.json")
    store.set("db_password", "x")
    store.delete("db_password")
    assert store.get("db_password") is None


def test_app_data_dir_is_platform_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg")
    if os.name != "nt":
        assert app_data_dir() == Path("/tmp/xdg/finance-agent")
        assert default_config_path() == Path("/tmp/xdg/finance-agent/config.json")
