"""Local app configuration stored outside the database: a single 0600 JSON file.

The bank access URL (bearer-grade) lives encrypted in the ``credentials`` table, not here.
This file holds only local, lower-sensitivity settings the app needs *before* it can open
the database — chiefly the password for the user's own 127.0.0.1 Postgres. It is created
0600 inside a user-scoped directory, is never committed, and is never put in the environment
(invariant 8). Paths are cross-platform: ``%APPDATA%`` on Windows, ``XDG_CONFIG_HOME`` (or
``~/.config``) elsewhere.
"""

import json
import os
from pathlib import Path

DB_PASSWORD = "db_password"
DATABASE_URL = "database_url"


def app_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "finance-agent"


def default_config_path() -> Path:
    return app_data_dir() / "config.json"


def default_keys_path() -> Path:
    return app_data_dir() / "keys.json"


class FileSecretStore:
    """A single JSON file, created 0600 inside a 0700 directory."""

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
        os.chmod(self._path, 0o600)

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
