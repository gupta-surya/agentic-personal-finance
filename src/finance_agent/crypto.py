"""AES-256-GCM for credentials, and the key file that holds the keys.

The key never lives in the database: ciphertext goes in the ``credentials`` table, the key
in a 0600 file (a user-scoped file on Windows) outside the database, so a database dump
alone cannot decrypt anything. The hosted tier swaps ``FileKeyStore`` for a KMS-backed
``KeyStore`` without touching the table or the callers. ``key_id`` lets keys rotate: old
ciphertext is read with the key that sealed it, new writes use the current key.
"""

import json
import os
import secrets
from pathlib import Path
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12


def encrypt(key: bytes, plaintext: str) -> bytes:
    """``nonce || ciphertext``; a fresh random nonce every call."""
    nonce = secrets.token_bytes(_NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)


def decrypt(key: bytes, blob: bytes) -> str:
    nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")


class KeyStore(Protocol):
    def current_key(self, tenant_id: str) -> tuple[bytes, str]:
        """The key to seal new data with, and its id (created on first use)."""
        ...

    def key_for(self, tenant_id: str, key_id: str) -> bytes:
        """The key a stored ciphertext was sealed with."""
        ...


class FileKeyStore:
    """Per-tenant keys in one 0600 JSON file outside the database (``{tenant: {key_id: hex}}``)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, dict[str, str]]:
        if not self._path.exists():
            return {}
        raw = json.loads(self._path.read_text("utf-8"))
        return {str(t): {str(k): str(v) for k, v in keys.items()} for t, keys in raw.items()}

    def _save(self, data: dict[str, dict[str, str]]) -> None:
        parent = self._path.parent
        parent.mkdir(parents=True, exist_ok=True)
        os.chmod(parent, 0o700)
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.chmod(self._path, 0o600)

    def current_key(self, tenant_id: str) -> tuple[bytes, str]:
        data = self._load()
        keys = data.get(tenant_id, {})
        if keys:
            key_id = max(keys)
            return bytes.fromhex(keys[key_id]), key_id
        key_id = "k1"
        key = secrets.token_bytes(_KEY_BYTES)
        data.setdefault(tenant_id, {})[key_id] = key.hex()
        self._save(data)
        return key, key_id

    def key_for(self, tenant_id: str, key_id: str) -> bytes:
        keys = self._load().get(tenant_id, {})
        if key_id not in keys:
            raise KeyError(f"no key {key_id!r} for this tenant")
        return bytes.fromhex(keys[key_id])
