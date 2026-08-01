"""Application-level envelope encryption for PHI at rest.

Opt-in: active only when a master key is configured (via MDPLUS_ENCRYPTION_KEY,
a base64 32-byte key, or MDPLUS_ENCRYPTION_KEY_FILE pointing at a file holding
one). When no key is set, callers fall back to plaintext writes, so dev/demo is
unaffected.

Envelope design: each object gets a fresh random data key (DEK); the payload is
sealed with the DEK, and the DEK is wrapped with the master key (KEK). Both use
AES-256-GCM (authenticated, so tampering is detected on decrypt). The point of
the envelope is portability: moving the master key to a managed KMS later only
changes `_load_master_key` / the wrap step — the stored objects and every
read/write path stay the same, with no data migration.

Blob layout:
    MAGIC(8) | version(1) | len(wrapped_dek) u16-be | dek_nonce(12) |
    wrapped_dek | data_nonce(12) | ciphertext
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

MAGIC = b"MDPLUSE1"
_VERSION = 1


def _load_master_key() -> bytes | None:
    b64 = os.environ.get("MDPLUS_ENCRYPTION_KEY", "").strip()
    if not b64:
        path = os.environ.get("MDPLUS_ENCRYPTION_KEY_FILE", "").strip()
        if path and Path(path).exists():
            b64 = Path(path).read_text(encoding="utf-8").strip()
    if not b64:
        return None
    try:
        key = base64.b64decode(b64)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("MDPLUS_ENCRYPTION_KEY is not valid base64") from exc
    if len(key) != 32:
        raise ValueError(
            "MDPLUS_ENCRYPTION_KEY must decode to 32 bytes (AES-256); "
            f"got {len(key)}"
        )
    return key


def _aesgcm():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM


def available() -> bool:
    """True when encryption can run: a valid key is set and the library imports."""
    try:
        _aesgcm()
    except Exception:  # noqa: BLE001 - library not installed
        return False
    try:
        return _load_master_key() is not None
    except ValueError:
        # A misconfigured key should surface loudly at use time, not silently
        # disable encryption; report unavailable only when no key is set.
        return True


def generate_key_b64() -> str:
    """A fresh base64 master key. Run once, store it as a secret."""
    return base64.b64encode(os.urandom(32)).decode("ascii")


def is_encrypted(blob: bytes) -> bool:
    return blob[: len(MAGIC)] == MAGIC


def encrypt(plaintext: bytes) -> bytes:
    AESGCM = _aesgcm()
    kek = _load_master_key()
    if kek is None:
        raise RuntimeError("no encryption key configured")
    dek = os.urandom(32)
    data_nonce = os.urandom(12)
    ciphertext = AESGCM(dek).encrypt(data_nonce, plaintext, None)
    dek_nonce = os.urandom(12)
    wrapped = AESGCM(kek).encrypt(dek_nonce, dek, None)
    return b"".join(
        [
            MAGIC,
            bytes([_VERSION]),
            len(wrapped).to_bytes(2, "big"),
            dek_nonce,
            wrapped,
            data_nonce,
            ciphertext,
        ]
    )


def decrypt(blob: bytes) -> bytes:
    AESGCM = _aesgcm()
    if not is_encrypted(blob):
        raise ValueError("not an MDPLUS encrypted blob")
    kek = _load_master_key()
    if kek is None:
        raise RuntimeError("no encryption key configured")
    off = len(MAGIC)
    version = blob[off]
    off += 1
    if version != _VERSION:
        raise ValueError(f"unsupported encryption version {version}")
    wlen = int.from_bytes(blob[off : off + 2], "big")
    off += 2
    dek_nonce = blob[off : off + 12]
    off += 12
    wrapped = blob[off : off + wlen]
    off += wlen
    data_nonce = blob[off : off + 12]
    off += 12
    ciphertext = blob[off:]
    dek = AESGCM(kek).decrypt(dek_nonce, wrapped, None)
    return AESGCM(dek).decrypt(data_nonce, ciphertext, None)


def maybe_encrypt(plaintext: bytes) -> tuple[bytes, bool]:
    """Encrypt when a key is configured; otherwise return plaintext unchanged.

    Returns (data, was_encrypted) so the caller can adjust the filename.
    """
    if available():
        return encrypt(plaintext), True
    return plaintext, False
