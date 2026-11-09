"""Secret storage: keychain round-trips through a fake backend, the file fallback is 0600.
No real keychain is ever touched."""

import json
import stat
from pathlib import Path

from finance_agent.secrets import (
    FileSecretStore,
    KeyringSecretStore,
    keychain_available,
    open_secret_store,
)

SENTINEL = "SENTINEL-ACCESS-URL-9921"


class FakeKeyring:
    """An in-memory stand-in for the keyring module."""

    class _Fail:
        pass

    def __init__(self, available: bool = True) -> None:
        self._store: dict[tuple[str, str], str] = {}
        self._available = available

    def get_keyring(self) -> object:
        from keyring.backends import fail

        return object() if self._available else fail.Keyring()  # type: ignore[no-untyped-call]

    def get_password(self, service: str, name: str) -> str | None:
        return self._store.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        self._store[(service, name)] = value

    def delete_password(self, service: str, name: str) -> None:
        self._store.pop((service, name), None)


def test_keyring_store_round_trips() -> None:
    store = KeyringSecretStore(FakeKeyring())
    assert store.get("access_url") is None
    store.set("access_url", SENTINEL)
    assert store.get("access_url") == SENTINEL
    store.delete("access_url")
    assert store.get("access_url") is None


def test_file_store_is_0600_in_a_0700_dir(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "secrets.json"
    store = FileSecretStore(path)
    store.set("access_url", SENTINEL)

    assert store.get("access_url") == SENTINEL
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    # The value is really persisted, and nothing else is in the file.
    assert json.loads(path.read_text()) == {"access_url": SENTINEL}


def test_file_store_delete(tmp_path: Path) -> None:
    store = FileSecretStore(tmp_path / "s.json")
    store.set("db_password", SENTINEL)
    store.delete("db_password")
    assert store.get("db_password") is None


def test_open_secret_store_prefers_keychain_then_file(tmp_path: Path) -> None:
    store, used = open_secret_store(backend=FakeKeyring(available=True))
    assert used is True
    assert isinstance(store, KeyringSecretStore)

    store, used = open_secret_store(
        backend=FakeKeyring(available=False), file_path=tmp_path / "s.json"
    )
    assert used is False
    assert isinstance(store, FileSecretStore)


def test_keychain_available_detects_the_fail_backend() -> None:
    assert keychain_available(FakeKeyring(available=True)) is True
    assert keychain_available(FakeKeyring(available=False)) is False
