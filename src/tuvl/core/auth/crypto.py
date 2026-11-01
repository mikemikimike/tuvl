"""Password hashing and verification using bcrypt.

Uses the ``bcrypt`` package directly (no passlib wrapper) since passlib
is in maintenance-only mode.  bcrypt ≥ 4.0 ships its own native bindings —
no additional C compiler is required.

Usage
-----
>>> from tuvl.core.auth.crypto import get_password_hash, verify_password
>>> hashed = get_password_hash("s3cret")
>>> verify_password("s3cret", hashed)
True
>>> verify_password("wrong", hashed)
False
"""

from __future__ import annotations

import bcrypt
from fastapi.concurrency import run_in_threadpool


def _bcrypt_bytes(password: str) -> bytes:
    """Encode *password* and truncate to bcrypt's 72-byte limit.

    bcrypt only considers the first 72 bytes; on bcrypt>=5 a longer input raises
    ``ValueError`` — which would surface as an uncaught 500 on register/login.
    Truncating matches bcrypt's own semantics and keeps those paths robust.
    """
    return password.encode("utf-8")[:72]


def get_password_hash(password: str) -> str:
    """Return a bcrypt hash string for *password*.

    A unique salt is generated automatically; the cost factor defaults to 12.
    The result is safe to store directly in the database.
    """
    return bcrypt.hashpw(_bcrypt_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return ``True`` iff *plain_password* matches *hashed_password*.

    Uses a constant-time comparison internally (bcrypt.checkpw) to prevent
    timing side-channel attacks.
    """
    return bcrypt.checkpw(
        _bcrypt_bytes(plain_password),
        hashed_password.encode("utf-8"),
    )


async def aget_password_hash(password: str) -> str:
    """Async wrapper for :func:`get_password_hash` that offloads the bcrypt work.

    bcrypt at cost 12 is ~200-300ms of pure CPU; calling it inline in an async
    request handler stalls the shared ASGI event loop, so auth handlers must
    route through this.
    """
    return await run_in_threadpool(get_password_hash, password)


async def averify_password(plain_password: str, hashed_password: str) -> bool:
    """Async wrapper for :func:`verify_password` — see :func:`aget_password_hash`."""
    return await run_in_threadpool(verify_password, plain_password, hashed_password)
