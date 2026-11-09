"""Where the user's secrets live: the OS keychain, or a 0600 file if there is none.

Two secrets are kept, both out of the database, bronze, logs and the repo (invariant 8):
the SimpleFIN access URL (which carries bank credentials) and the local database
password. The keychain is preferred because a file in the home directory is readable by
anything running as the user; a keychain item is not. When no keychain backend is
available the file fallback is used and setup says so.
"""

import contextlib
import json
import os
from pathlib import Path
from typing import Protocol

import keyring
import keyring.errors
from keyring.backends import fail

SERVICE = "finance-agent"

# Secret names (one local tenant, so no namespacing).
ACCESS_URL = "simplefin_access_url"
DB_PASSWORD = "db_password"


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class KeyringSecretStore:
    """Backed by the OS keychain. ``backend`` is the ``keyring`` module by default; tests
    pass a fake with the same three methods so the real keychain is never touched."""

    def __init__(self, backend: object = keyring, service: str = SERVICE) -> None:
        self._kr = backend
        self._service = service

    def get(self, name: str) -> str | None:
        return self._kr.get_password(self._service, name)  # type: ignore[attr-defined,no-any-return]

    def set(self, name: str, value: str) -> None:
        self._kr.set_password(self._service, name, value)  # type: ignore[attr-defined]

    def delete(self, name: str) -> None:
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            self._kr.delete_password(self._service, name)  # type: ignore[attr-defined]


class FileSecretStore:
    """A single JSON file, created 0600 inside a 0700 directory. The fallback when there is
    no keychain; the location is shown to the user at setup."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        data = json.loads(self._path.read_text("utf-8"))
        return {str(k): str(v) for k, v in data.items()}

    def _save(self, data: dict[str, str]) -> None:
        parent = self._path.parent
        parent.mkdir(parents=True, exist_ok=True)
        os.chmod(parent, 0o700)
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.chmod(self._path, 0o600)  # tighten if the file pre-existed with looser bits

    def get(self, name: str) -> str | None:
        return self._load().get(name)

    def set(self, name: str, value: str) -> None:
        data = self._load()
        data[name] = value
        self._save(data)

    def delete(self, name: str) -> None:
        data = self._load()
        if data.pop(name, None) is not None:
            self._save(data)


def default_secret_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "finance-agent" / "secrets.json"


def keychain_available(backend: object = keyring) -> bool:
    """True when a real keychain backend is present (not the null ``fail`` backend)."""
    get_keyring = getattr(backend, "get_keyring", None)
    if get_keyring is None:
        return True  # an injected fake store counts as available
    try:
        return not isinstance(get_keyring(), fail.Keyring)
    except Exception:
        return False


def open_secret_store(
    *, backend: object = keyring, file_path: Path | None = None
) -> tuple[SecretStore, bool]:
    """Return ``(store, used_keychain)``. Keychain first, else a 0600 file."""
    if keychain_available(backend):
        return KeyringSecretStore(backend), True
    return FileSecretStore(file_path or default_secret_path()), False
