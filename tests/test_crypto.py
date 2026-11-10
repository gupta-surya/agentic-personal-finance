"""AES-GCM round-trip and tamper detection, plus the keyfile store (0600, per-tenant)."""

import stat
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from finance_agent.crypto import FileKeyStore, decrypt, encrypt

SECRET = "https://user:SENTINEL-ACCESS-URL-9921@bank.example.com/simplefin"


def test_round_trip_with_random_nonce() -> None:
    key = b"\x01" * 32
    first, second = encrypt(key, SECRET), encrypt(key, SECRET)
    assert first != second  # fresh nonce each time
    assert decrypt(key, first) == SECRET == decrypt(key, second)
    assert SECRET.encode() not in first  # plaintext never appears in the ciphertext


def test_tampered_ciphertext_is_rejected() -> None:
    key = b"\x02" * 32
    blob = bytearray(encrypt(key, SECRET))
    blob[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        decrypt(key, bytes(blob))


def test_wrong_key_is_rejected() -> None:
    with pytest.raises(InvalidTag):
        decrypt(b"\x03" * 32, encrypt(b"\x04" * 32, SECRET))


def test_keystore_is_0600_per_tenant_and_stable(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "keys.json"
    store = FileKeyStore(path)
    key_local, key_id = store.current_key("local")

    assert len(key_local) == 32
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert store.current_key("local") == (key_local, key_id)  # stable for a tenant
    assert store.current_key("other")[0] != key_local  # isolated per tenant
    assert store.key_for("local", key_id) == key_local
    with pytest.raises(KeyError):
        store.key_for("local", "missing")
