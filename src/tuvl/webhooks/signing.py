"""``Tuvl-Signature: t=<unix seconds>,v1=<hex>[,v1=<hex>]`` — HMAC-SHA256 over ``<t>.<raw body>``.

One ``v1`` entry per secret, so a secret can be rotated without a gap: the receiver accepts a
notification when any entry matches a secret it holds.
"""

from __future__ import annotations

import hashlib
import hmac
import time

MIN_SECRET_BYTES = 32


def digest(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def sign(body: bytes, secrets: list[str], *, now: int | None = None) -> str:
    t = int(time.time()) if now is None else now
    return ",".join([f"t={t}", *(f"v1={digest(s, t, body)}" for s in secrets)])


def verify(header: str, body: bytes, secrets: list[str], *, tolerance: int = 300) -> bool:
    """The same check the client library makes (used by the tests)."""
    fields = [part.partition("=") for part in header.split(",")]
    stamps = [v for k, _, v in fields if k == "t"]
    if len(stamps) != 1 or not stamps[0].isdigit():
        return False
    t = int(stamps[0])
    if abs(time.time() - t) > tolerance:
        return False
    given = [v for k, _, v in fields if k == "v1"]
    return any(
        hmac.compare_digest(digest(secret, t, body), candidate)
        for secret in secrets
        for candidate in given
    )
