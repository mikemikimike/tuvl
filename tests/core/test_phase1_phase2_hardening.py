"""Regression tests for Phase 1 + Phase 2 hardening.

Covers:
- Phase 1.5: ``verify_token`` fails closed on malformed or expired tokens.
- Phase 1.7: ``mint_token`` signs ``exp`` into the token, so expiry is
  enforced by signature verification itself.
- Phase 2.10: every async engine is built with ``pool_recycle`` and
  ``pool_timeout`` configured.
- Phase 2.11: ``get_http_client`` returns a process-wide singleton per
  timeout bucket; ``aclose_all`` releases them.
- Phase 2.12: the tenant identifier allowlist regex rejects injection
  payloads.
"""

from __future__ import annotations

import asyncio

import jwt
import pytest
from fastapi import HTTPException

from tuvl.core.auth.access import decode_token, verify_token
from tuvl.core.auth.token import mint_token
from tuvl.core.datasources.postgres import (
    _POOL_RECYCLE_SECONDS,
    _POOL_TIMEOUT_SECONDS,
    _TENANT_ID_RE,
)
from tuvl.core.infra.http_client import aclose_all, get_http_client

# ── Phase 1.7 — expiry is part of the signed token ───────────────────────────


def test_a_fresh_token_verifies() -> None:
    claims = decode_token(mint_token("usr-1", ["g"], ["s"], ttl_seconds=60))
    assert claims["sub"] == "usr-1" and claims["exp"] > claims["iat"]


def test_an_expired_token_is_refused_by_signature_verification() -> None:
    """``exp`` is signed: verification itself refuses the token, no separate clock check needed."""
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(mint_token("usr-2", [], [], ttl_seconds=-1))


def test_token_without_ttl_has_no_expiry() -> None:
    """Tokens minted with ttl_seconds=0/None carry no ``exp`` and stay accepted."""
    assert "exp" not in decode_token(mint_token("usr-3", [], [], ttl_seconds=None))


# ── Phase 1.5 — verify_token fails closed ─────────────────────────────────────


def test_verify_token_rejects_garbage_input() -> None:
    """An unparseable token string must raise 401, not 500."""
    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_token("not-a-real-token"))
    assert exc.value.status_code == 401


def test_verify_token_rejects_expired_token() -> None:
    """End-to-end: a token minted with negative TTL is rejected by verify_token.

    Exercises the fail-closed path: an expiry error becomes a 401, not a 500.
    """
    # Pre-warm the dev-blacklist so token_blacklist.is_revoked() doesn't try
    # to touch Redis in the unit-test environment.
    from tuvl.core.auth import blacklist

    async def _never_revoked(_token: str) -> bool:
        return False

    blacklist.token_blacklist.is_revoked = _never_revoked  # type: ignore[method-assign]

    expired = mint_token("usr-x", [], [], ttl_seconds=-1)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(verify_token(expired))
    assert exc.value.status_code == 401


# ── Phase 2.10 — Pool tuning constants are sane ───────────────────────────────


def test_pool_tuning_defaults_present() -> None:
    """The defaults applied to every engine must be positive integers."""
    assert isinstance(_POOL_RECYCLE_SECONDS, int) and _POOL_RECYCLE_SECONDS > 0
    assert isinstance(_POOL_TIMEOUT_SECONDS, int) and _POOL_TIMEOUT_SECONDS > 0


# ── Phase 2.11 — Shared httpx client is reused per timeout bucket ─────────────


def test_get_http_client_returns_singleton_per_timeout() -> None:
    c1 = get_http_client(timeout=15.0)
    c2 = get_http_client(timeout=15.0)
    assert c1 is c2
    # Distinct timeout bucket → distinct client instance.
    c3 = get_http_client(timeout=30.0)
    assert c3 is not c1


def test_aclose_all_releases_pool() -> None:
    """After aclose_all, the next get_http_client call returns a fresh client."""
    before = get_http_client(timeout=15.0)
    asyncio.run(aclose_all())
    after = get_http_client(timeout=15.0)
    assert after is not before
    assert not after.is_closed


# ── Phase 2.12 — Tenant identifier allowlist ──────────────────────────────────


@pytest.mark.parametrize(
    "tid",
    ["acme", "acme-corp", "acme_corp_42", "T-" + "x" * 126],
)
def test_tenant_id_regex_accepts_safe_values(tid: str) -> None:
    assert _TENANT_ID_RE.fullmatch(tid)


@pytest.mark.parametrize(
    "tid",
    [
        "",
        "a'; DROP TABLE x;--",
        "tenant with space",
        "tenant\nnewline",
        "x" * 129,  # over length cap
        "tenant'or'1'='1",
    ],
)
def test_tenant_id_regex_rejects_injection_payloads(tid: str) -> None:
    assert not _TENANT_ID_RE.fullmatch(tid)
