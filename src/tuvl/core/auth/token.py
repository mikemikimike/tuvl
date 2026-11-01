"""Access-token minting: Ed25519-signed JWTs (``alg: EdDSA``).

Claims::

    iss     "tuvl"
    sub     the user id
    groups  the user's IAM role names
    scopes  the permissions those roles grant, e.g. "requisition:write"
    tenant  the tenant id (multi-tenant deployments only)
    iat     issued at, seconds with millisecond precision
    exp     expiry, seconds — omitted only when ``ttl_seconds`` is 0/None
    jti     a unique token id

Group, scope and tenant values are validated before signing, so a token can't
carry a name the rest of the system would reject.

>>> token = mint_token("usr-123", ["hr_manager"], ["requisition:write"], ttl_seconds=3600)
"""

from __future__ import annotations

import re
import time
import uuid

import jwt

from tuvl.core.auth.keys import get_key_manager

ISSUER = "tuvl"
ALGORITHM = "EdDSA"

# Allowed characters in a scope / group name.
_SAFE_RE = re.compile(r"^[\w:.\-/]+$")


def _assert_safe(value: str, label: str) -> None:
    """Raise ``ValueError`` if *value* contains characters outside the safe set."""
    if not _SAFE_RE.match(value):
        raise ValueError(
            f"Unsafe {label} value '{value}'. "
            "Only word chars (a-z A-Z 0-9 _), ':', '.', '-', '/' are allowed."
        )


def mint_token(
    user_id: str,
    groups: list[str],
    scopes: list[str],
    ttl_seconds: int | None = None,
    tenant_id: str | None = None,
) -> str:
    """A signed access token for *user_id* with these groups and scopes.

    Raises ``ValueError`` when a group, scope or tenant id has unsafe characters.
    """
    for g in groups:
        _assert_safe(g, "group")
    for s in scopes:
        _assert_safe(s, "scope")
    if tenant_id is not None:
        # the same allowlist the database session enforces at SET LOCAL time
        from tuvl.core.datasources.postgres import _TENANT_ID_RE

        if not _TENANT_ID_RE.fullmatch(tenant_id):
            raise ValueError(f"Unsafe tenant id '{tenant_id}'. Must match {_TENANT_ID_RE.pattern}.")

    now = time.time()
    claims: dict[str, object] = {
        "iss": ISSUER,
        "sub": user_id,
        "groups": list(groups),
        "scopes": list(scopes),
        # ms precision: a session ended now must refuse a token issued a moment before
        "iat": round(now, 3),
        "jti": uuid.uuid4().hex,
    }
    if tenant_id is not None:
        claims["tenant"] = tenant_id
    if ttl_seconds:
        claims["exp"] = int(now) + ttl_seconds
    keys = get_key_manager()
    return jwt.encode(claims, keys.private_key, algorithm=ALGORITHM, headers={"kid": keys.kid})
