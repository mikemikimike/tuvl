"""Object-key rules. A key is relative, forward-slashed, and never leaves its store's prefix."""

from __future__ import annotations

from tuvl.storage.errors import InvalidKey

MAX_KEY_BYTES = 1024


def validate_key(key: object) -> str:
    if not isinstance(key, str) or not key:
        raise InvalidKey("key must be a non-empty string")
    if len(key.encode()) > MAX_KEY_BYTES:
        raise InvalidKey(f"key is longer than {MAX_KEY_BYTES} bytes")
    if key.startswith("/") or "\\" in key:
        raise InvalidKey("key must be relative and use '/' separators")
    if any(ord(c) < 32 or ord(c) == 127 for c in key):
        raise InvalidKey("key contains control characters")
    if any(part in ("", ".", "..") for part in key.split("/")):
        raise InvalidKey("key must not contain empty, '.' or '..' segments")
    return key


def validate_prefix(prefix: object) -> str:
    """A list prefix: ``""`` or a relative path that may end in ``/``."""
    if prefix in (None, ""):
        return ""
    text = str(prefix)
    validate_key(text.rstrip("/") or "x")
    return text


def literal_key_problem(key: str) -> str | None:
    """Why a *template-free* key is unsafe, for the validator."""
    if "{{" in key:
        return None
    try:
        validate_key(key)
    except InvalidKey as exc:
        return str(exc)
    return None


def join_prefix(prefix: str, key: str) -> str:
    return f"{prefix}{key}" if prefix else key


def strip_prefix(prefix: str, key: str) -> str:
    return key[len(prefix) :] if prefix and key.startswith(prefix) else key
