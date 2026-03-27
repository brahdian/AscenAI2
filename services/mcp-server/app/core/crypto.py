"""
Fernet-based symmetric encryption for sensitive tool credentials stored at rest.

Usage:
    from app.core.crypto import encrypt_sensitive_fields, decrypt_sensitive_fields

    # Before saving tool_metadata / auth_config to the DB:
    safe = encrypt_sensitive_fields(raw_dict)

    # After reading from the DB, before passing to a handler:
    clear = decrypt_sensitive_fields(stored_dict)

The ENCRYPTION_KEY setting must be set in production. If absent, values are stored
and returned as plaintext (backward-compatible dev mode, logged as a warning at
startup). Values that were not encrypted (no "gAAAAA" Fernet prefix) are returned
unchanged, so migration from plaintext → encrypted is zero-downtime.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Any

import structlog
from cryptography.fernet import Fernet, InvalidToken

logger = structlog.get_logger(__name__)

# Fields whose string values should be encrypted when written to the database.
_SENSITIVE_FIELDS = frozenset({
    "secret_key",
    "api_key",
    "api_token",
    "auth_token",
    "access_token",
    "password",
    "smtp_password",
    "secret",
    "token",
    "private_key",
    "client_secret",
    "webhook_secret",
    "value",          # generic auth_config value field
})

_fernet_instance: Fernet | None = None
_fernet_loaded: bool = False


def _get_fernet() -> Fernet | None:
    global _fernet_instance, _fernet_loaded
    if _fernet_loaded:
        return _fernet_instance

    _fernet_loaded = True
    # Import lazily to avoid circular import at module load
    try:
        from app.core.config import settings
        raw = getattr(settings, "ENCRYPTION_KEY", None)
    except Exception:
        raw = None

    if not raw:
        logger.warning(
            "encryption_key_not_set",
            detail="ENCRYPTION_KEY is not configured — tool credentials stored as plaintext. "
                   "Set a strong key (python -c \"from cryptography.fernet import Fernet; "
                   "print(Fernet.generate_key().decode())\") before going to production.",
        )
        _fernet_instance = None
        return None

    key_bytes = raw.encode() if isinstance(raw, str) else raw
    # Accept raw Fernet keys (44-char base64url) or arbitrary strings (hashed)
    if len(key_bytes) == 44:
        try:
            _fernet_instance = Fernet(key_bytes)
            return _fernet_instance
        except Exception:
            pass
    # Derive a proper 32-byte Fernet key by SHA-256 hashing the raw value
    derived = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
    _fernet_instance = Fernet(derived)
    return _fernet_instance


def encrypt_value(value: str) -> str:
    """Encrypt *value* with Fernet. Returns ciphertext (str) or original if no key."""
    f = _get_fernet()
    if f is None:
        return value
    return f.encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    """
    Decrypt *value* if it looks like a Fernet token (starts with "gAAAAA").
    Returns the original string unchanged if it is not encrypted or decryption fails.
    """
    if not value or not value.startswith("gAAAAA"):
        return value
    f = _get_fernet()
    if f is None:
        return value
    try:
        return f.decrypt(value.encode()).decode()
    except (InvalidToken, Exception):
        logger.warning("credential_decryption_failed", prefix=value[:8])
        return value


def encrypt_sensitive_fields(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Return a shallow copy of *data* with sensitive string fields Fernet-encrypted.
    Already-encrypted values (Fernet prefix "gAAAAA") are left unchanged.
    Non-string and non-sensitive fields are left unchanged.
    Returns None unchanged.
    """
    if not data:
        return data
    out: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str) and k in _SENSITIVE_FIELDS and not v.startswith("gAAAAA"):
            out[k] = encrypt_value(v)
        else:
            out[k] = v
    return out


def decrypt_sensitive_fields(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Return a shallow copy of *data* with all Fernet-encrypted string values decrypted.
    Non-encrypted strings and non-string values are passed through unchanged.
    Returns None unchanged.
    """
    if not data:
        return data
    return {k: (decrypt_value(v) if isinstance(v, str) else v) for k, v in data.items()}
