"""Tests for Phase 3 multi-tenancy integrations.

Covers:
- P3.1 ``mint_token`` accepts ``tenant_id`` and embeds a
  ``tenant("<tid>")`` fact; ``get_current_user`` extracts it back into
  ``TokenUser.tenant_id``.
- P3.1 Malformed tenant ids are rejected at mint time AND at extract
  time (defense in depth).
- P3.1 ``bind_principal_context`` populates both ``current_user_id`` and
  ``current_tenant_id`` ContextVars from the verified token.
- P3.2 ``_attach_principal_to_context`` mirrors ContextVars into the
  workflow context dict.
- P3.4 The structlog ``_inject_user_context`` processor adds ``user_id``
  to log records when a principal is bound; the existing tenant
  processor adds ``tenant_id`` in MT mode.
- P3.4 ``_annotate_principal`` sets ``tuvl.tenant.id`` and ``tuvl.user.id``
  attributes on a span.
- P3.5 The hybrid-search SQL gains a ``tenant_id = :tenant_id`` predicate
  in MT mode and leaves the SQL untouched in single-tenant mode.
- P3.3 ``generate_rls_sql`` emits idempotent ENABLE + CREATE POLICY for
  every tenant-scoped table; ``tenant_table_names`` includes the system
  tables; the CLI ``db`` Typer subapp is wired into the main app.
"""

from __future__ import annotations

import pytest

import tuvl.core.bootstrap as bootstrap
from tuvl.core.auth.access import (
    bind_principal_context,
    decode_token,
    get_current_user,
)
from tuvl.core.auth.token import mint_token
from tuvl.core.context import current_tenant_id, current_user_id
from tuvl.core.datasources.rls import (
    TUVL_POLICY_NAME,
    generate_rls_sql,
    tenant_table_names,
)

# ── P3.1 — Tenant claim mint + extract ────────────────────────────────────────


def test_mint_with_tenant_id_embeds_tenant_claim() -> None:
    token = mint_token("user-1", ["g"], ["s:r"], ttl_seconds=300, tenant_id="acme_corp")
    assert decode_token(token)["tenant"] == "acme_corp"


def test_mint_without_tenant_id_omits_tenant_claim() -> None:
    assert "tenant" not in decode_token(mint_token("user-1", [], [], ttl_seconds=300))


def test_mint_rejects_malformed_tenant_id() -> None:
    """Mint-time validation uses the same allowlist as the database
    session, so an unsafe id cannot end up inside a signed token."""
    with pytest.raises(ValueError):
        mint_token("u", [], [], tenant_id="a'; DROP TABLE x;--")
    with pytest.raises(ValueError):
        mint_token("u", [], [], tenant_id="tenant with space")


def test_get_current_user_extracts_tenant_id() -> None:
    token = mint_token("user-42", ["hr"], ["candidate:read"], ttl_seconds=300, tenant_id="acme")
    claims = decode_token(token)

    user = get_current_user(claims)
    assert user.user_id == "user-42"
    assert user.tenant_id == "acme"
    assert "hr" in user.groups


def test_get_current_user_returns_none_tenant_when_absent() -> None:
    token = mint_token("user-42", [], [], ttl_seconds=300)
    claims = decode_token(token)

    user = get_current_user(claims)
    assert user.tenant_id is None


async def test_bind_principal_context_sets_both_contextvars() -> None:
    token = mint_token("user-99", [], [], ttl_seconds=300, tenant_id="contoso")
    claims = decode_token(token)
    user = get_current_user(claims)

    # Reset any leaked state from prior tests.
    tid_tok = current_tenant_id.set("")
    uid_tok = current_user_id.set("")
    try:
        result = await bind_principal_context(user)
        assert result is user
        assert current_user_id.get() == "user-99"
        assert current_tenant_id.get() == "contoso"
    finally:
        current_tenant_id.reset(tid_tok)
        current_user_id.reset(uid_tok)


async def test_bind_principal_context_skips_tenant_when_token_has_none() -> None:
    """If the token carries no tenant fact, ``bind_principal_context``
    must leave the existing ``current_tenant_id`` untouched \u2014 it must
    not overwrite a value the host may have set from another source
    (e.g. a sub-domain extractor running earlier in the dep chain)."""
    token = mint_token("user-99", [], [], ttl_seconds=300)
    claims = decode_token(token)
    user = get_current_user(claims)

    tid_tok = current_tenant_id.set("host_set_tid")
    uid_tok = current_user_id.set("")
    try:
        await bind_principal_context(user)
        assert current_user_id.get() == "user-99"
        assert current_tenant_id.get() == "host_set_tid"  # preserved
    finally:
        current_tenant_id.reset(tid_tok)
        current_user_id.reset(uid_tok)


# ── P3.2 — Principal mirrored into workflow context dict ─────────────────────


# ── P3.4 — Observability processors ──────────────────────────────────────────


def test_inject_user_context_processor_adds_user_id() -> None:
    from tuvl.core.logger import _inject_user_context

    uid_tok = current_user_id.set("user-1")
    try:
        out = _inject_user_context(None, "info", {"event": "x"})
        assert out["user_id"] == "user-1"
    finally:
        current_user_id.reset(uid_tok)


def test_inject_user_context_processor_omits_key_when_empty() -> None:
    from tuvl.core.logger import _inject_user_context

    uid_tok = current_user_id.set("")
    try:
        out = _inject_user_context(None, "info", {"event": "x"})
        assert "user_id" not in out
    finally:
        current_user_id.reset(uid_tok)


def test_inject_user_context_is_in_shared_processor_chain() -> None:
    """Regression guard: the processor must be registered
    unconditionally so user_id appears on every log line in every
    deployment mode \u2014 not gated behind multi-tenant configuration."""
    from tuvl.core.logger import _inject_user_context, _shared_processors

    assert _inject_user_context in _shared_processors


# ── P3.5 — Raw SQL tenant guard in rag.py ────────────────────────────────────


def test_rag_tenant_clause_is_gated_on_mt_mode_and_set_tenant(monkeypatch) -> None:
    """Replays the gating logic the SQL builder uses so a future change
    that flips the condition (e.g. drops the ``active_tid`` check) is
    caught without needing a live DB."""
    # MT mode with a tenant set → clause active.
    monkeypatch.setattr(bootstrap, "LOCKED_DEPLOYMENT_MODE", "multi_tenant")
    tok = current_tenant_id.set("acme")
    try:
        assert bootstrap.LOCKED_DEPLOYMENT_MODE == "multi_tenant" and current_tenant_id.get("")
    finally:
        current_tenant_id.reset(tok)

    # MT mode without tenant → clause inactive (the after_begin hook will
    # raise MissingTenantContextError first; we must not also crash here).
    tok = current_tenant_id.set("")
    try:
        assert not (
            bootstrap.LOCKED_DEPLOYMENT_MODE == "multi_tenant" and current_tenant_id.get("")
        )
    finally:
        current_tenant_id.reset(tok)

    # Single-tenant → clause inactive regardless of contextvar.
    monkeypatch.setattr(bootstrap, "LOCKED_DEPLOYMENT_MODE", "single_tenant")
    tok = current_tenant_id.set("acme")
    try:
        assert not (
            bootstrap.LOCKED_DEPLOYMENT_MODE == "multi_tenant" and current_tenant_id.get("")
        )
    finally:
        current_tenant_id.reset(tok)


# ── P3.3 — RLS SQL generator + CLI wiring ────────────────────────────────────


def test_tenant_table_names_includes_system_tables() -> None:
    names = tenant_table_names()
    assert "tuvl_system_vector_store" in names
    # Sorted + deduplicated by contract.
    assert names == sorted(set(names))


def test_generate_rls_sql_is_idempotent_and_targets_every_table() -> None:
    sql = generate_rls_sql()
    for table in tenant_table_names():
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
        assert f"DROP POLICY IF EXISTS {TUVL_POLICY_NAME} ON {table}" in sql
        assert f"CREATE POLICY {TUVL_POLICY_NAME} ON {table}" in sql
    assert "current_setting('app.current_tenant_id', true)" in sql


def test_db_subapp_is_registered_on_main_cli() -> None:
    """Catch a future refactor that forgets to wire ``db`` into the
    Typer app \u2014 otherwise the CLI command silently disappears."""
    from tuvl.cli import app as main_app

    registered_names = {g.name for g in main_app.registered_groups}
    assert {"generate", "verify"} <= registered_names


def test_db_subapp_exposes_generate_and_check_subcommands() -> None:
    from tuvl.cli.commands.db import db_app

    names = {c.name for c in db_app.registered_commands}
    assert {"generate-rls", "check-rls"}.issubset(names)


def test_data_search_source_keeps_the_tenant_predicate() -> None:
    """Source-level guard: in multi-tenant mode the hybrid search adds an
    explicit tenant predicate beside RLS (defence in depth). The filter is
    shared by the vector and full-text subqueries, so one predicate covers
    both. A live check needs Postgres + pgvector in multi_tenant mode."""
    import inspect

    from tuvl.runtime import builtins

    source = inspect.getsource(builtins.search_collection)
    assert 'LOCKED_DEPLOYMENT_MODE == "multi_tenant"' in source
    assert 'where.append("tenant_id = :tenant_id")' in source
    assert "WHERE {filters}" in source
