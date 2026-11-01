"""Tests for Phase 0 multi-tenancy correctness.

Covers:
- The public ``tuvl.tenancy`` API: ``set_tenant_context``,
  ``tenant_scope``, ``async_tenant_scope``, ``require_tenant_context``.
- ``MissingTenantContextError`` is raised when multi-tenant mode is on and
  ``current_tenant_id`` is empty.
- Tenant context survives ``asyncio.create_task`` (proves the ContextVar
  is correctly inherited by spawned tasks \u2014 the property the gRPC servicer
  fix depends on for its ``contextvars.copy_context()`` bridge).
- Tenant context isolation between concurrent tasks.
- The pre-Phase-0 pool-checkout listener (``_tenant_checkout_listener`` /
  ``_register_tenant_listener``) has been deleted outright (TD-9) — it was
  registered by nothing and raced with transaction begin.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

import tuvl.core.bootstrap as bootstrap
from tuvl.core.context import current_tenant_id
from tuvl.core.datasources.postgres import (
    MissingTenantContextError,
    _bind_tenant_isolation,
)
from tuvl.tenancy import (
    TENANT_ID_PATTERN,
    async_tenant_scope,
    require_tenant_context,
    set_tenant_context,
    tenant_scope,
)

# ── Public API surface ───────────────────────────────────────────────────────


def test_public_api_reexports_contextvar() -> None:
    from tuvl.tenancy import current_tenant_id as public_var

    assert public_var is current_tenant_id


def test_tenant_id_pattern_is_a_compiled_regex() -> None:
    assert TENANT_ID_PATTERN.fullmatch("acme-corp_1")
    assert not TENANT_ID_PATTERN.fullmatch("acme corp")


# ── set_tenant_context / tenant_scope ────────────────────────────────────────


def test_set_tenant_context_validates_input() -> None:
    with pytest.raises(ValueError):
        set_tenant_context("")
    with pytest.raises(ValueError):
        set_tenant_context("has space")
    with pytest.raises(ValueError):
        set_tenant_context("a'; DROP TABLE x;--")


def test_tenant_scope_restores_previous_value() -> None:
    token = current_tenant_id.set("outer")
    try:
        assert current_tenant_id.get() == "outer"
        with tenant_scope("inner"):
            assert current_tenant_id.get() == "inner"
        assert current_tenant_id.get() == "outer"
    finally:
        current_tenant_id.reset(token)


def test_tenant_scope_restores_on_exception() -> None:
    token = current_tenant_id.set("outer")
    try:
        with pytest.raises(RuntimeError), tenant_scope("inner"):
            raise RuntimeError("boom")
        assert current_tenant_id.get() == "outer"
    finally:
        current_tenant_id.reset(token)


def test_async_tenant_scope_works_in_async_context() -> None:
    async def _run() -> str:
        async with async_tenant_scope("acme"):
            return current_tenant_id.get()

    assert asyncio.run(_run()) == "acme"


# ── require_tenant_context dependency ────────────────────────────────────────


def test_require_tenant_context_returns_tid_when_set() -> None:
    token = current_tenant_id.set("acme")
    try:
        assert require_tenant_context() == "acme"
    finally:
        current_tenant_id.reset(token)


def test_require_tenant_context_raises_when_empty() -> None:
    # Ensure no leaked context from prior tests.
    token = current_tenant_id.set("")
    try:
        with pytest.raises(HTTPException) as exc:
            require_tenant_context()
        assert exc.value.status_code == 400
    finally:
        current_tenant_id.reset(token)


# ── Async task contextvar propagation (gRPC fix relies on this) ──────────────


def test_tenant_context_propagates_into_spawned_task() -> None:
    """``asyncio.create_task`` copies the current Context; the tenant set
    in the parent must be visible inside the child task."""

    async def _child() -> str:
        return current_tenant_id.get()

    async def _parent() -> str:
        with tenant_scope("parent_tid"):
            return await asyncio.create_task(_child())

    assert asyncio.run(_parent()) == "parent_tid"


def test_concurrent_tasks_see_their_own_tenant() -> None:
    """Two tasks created under different tenant_scope contexts must see
    their own tenant id, not each other's \u2014 the standard ContextVar
    isolation guarantee that TUVL's multi-tenant safety relies on."""

    async def _worker(tid: str) -> str:
        with tenant_scope(tid):
            await asyncio.sleep(0)  # force scheduler interleave
            return current_tenant_id.get()

    async def _run() -> list[str]:
        return await asyncio.gather(_worker("alpha"), _worker("beta"))

    results = asyncio.run(_run())
    assert sorted(results) == ["alpha", "beta"]


# ── Deprecated pool-checkout listener removed (TD-9) ─────────────────────


def test_pool_checkout_listener_symbols_no_longer_exist() -> None:
    """The pre-Phase-0 fire-and-forget ``SET LOCAL`` pool-checkout listener
    (``_tenant_checkout_listener`` / ``_register_tenant_listener``) was
    registered by nothing and raced with transaction begin. It has been
    deleted outright rather than kept as an unwired shim."""
    from tuvl.core.datasources import postgres

    assert not hasattr(postgres, "_tenant_checkout_listener")
    assert not hasattr(postgres, "_register_tenant_listener")


def test_build_engines_does_not_register_pool_checkout_listener() -> None:
    """Phase 0 moved tenant isolation from pool-checkout to per-transaction
    ``after_begin`` session events.  ``_build_engines`` must not reference a
    pool-checkout listener at all — otherwise asyncpg deployments would
    silently revert to a fire-and-forget pattern that races with transaction
    begin and can fail to apply ``SET LOCAL`` before the first query."""
    import inspect

    from tuvl.core.datasources import postgres

    source = inspect.getsource(postgres._build_engines)
    assert "checkout" not in source, (
        "_build_engines must not register a pool-checkout tenant listener; "
        "tenant isolation is bound per-transaction via _bind_tenant_isolation."
    )


# ── MissingTenantContextError fires when MT mode is active ───────────────────


def test_bind_tenant_isolation_noop_in_single_tenant_mode(monkeypatch) -> None:
    """In single_tenant mode the bind helper must not touch the session at
    all \u2014 zero overhead, no event registration."""
    monkeypatch.setattr(bootstrap, "LOCKED_DEPLOYMENT_MODE", "single_tenant")

    class _FakeSession:
        sync_session = object()

    # Must return without raising and without touching sync_session in any
    # way that would error.
    _bind_tenant_isolation(_FakeSession())  # type: ignore[arg-type]


def test_bind_tenant_isolation_registers_hook_in_multi_tenant(monkeypatch) -> None:
    """In multi_tenant mode the bind helper installs an ``after_begin``
    listener on the session's sync_session.  We assert it was registered
    by inspecting SQLAlchemy's dispatcher."""
    monkeypatch.setattr(bootstrap, "LOCKED_DEPLOYMENT_MODE", "multi_tenant")

    from sqlalchemy import event

    captured: list[object] = []

    def _capture(target, identifier, fn):
        captured.append((target, identifier, fn))

    monkeypatch.setattr(event, "listen", _capture)

    class _FakeSession:
        sync_session = object()

    _bind_tenant_isolation(_FakeSession())  # type: ignore[arg-type]

    assert any(ident == "after_begin" for _, ident, _ in captured)


def test_after_begin_callback_raises_when_tenant_missing(monkeypatch) -> None:
    """When the listener fires inside a transaction and no tenant has been
    set, ``MissingTenantContextError`` must be raised so the request fails
    closed instead of silently bypassing RLS."""
    monkeypatch.setattr(bootstrap, "LOCKED_DEPLOYMENT_MODE", "multi_tenant")

    from sqlalchemy import event

    registered: list = []

    def _capture(_target, _identifier, fn):
        registered.append(fn)

    monkeypatch.setattr(event, "listen", _capture)

    class _FakeSession:
        sync_session = object()

    _bind_tenant_isolation(_FakeSession())  # type: ignore[arg-type]
    assert registered, "after_begin listener was not registered"

    # Clear any context that prior tests may have set.
    token = current_tenant_id.set("")
    try:
        with pytest.raises(MissingTenantContextError):
            registered[0](object(), object(), object())
    finally:
        current_tenant_id.reset(token)


def test_after_begin_callback_executes_set_local_when_tenant_present(
    monkeypatch,
) -> None:
    """When a tenant is set, the listener must call ``exec_driver_sql``
    with the literal SET LOCAL statement.  The tenant value goes through
    the regex allowlist so interpolation is safe."""
    monkeypatch.setattr(bootstrap, "LOCKED_DEPLOYMENT_MODE", "multi_tenant")

    from sqlalchemy import event

    registered: list = []

    def _capture(_target, _identifier, fn):
        registered.append(fn)

    monkeypatch.setattr(event, "listen", _capture)

    class _FakeSession:
        sync_session = object()

    _bind_tenant_isolation(_FakeSession())  # type: ignore[arg-type]

    executed: list[str] = []

    class _FakeConn:
        def exec_driver_sql(self, sql: str) -> None:
            executed.append(sql)

    token = current_tenant_id.set("acme_corp")
    try:
        registered[0](object(), object(), _FakeConn())
    finally:
        current_tenant_id.reset(token)

    assert executed == ["SET LOCAL app.current_tenant_id = 'acme_corp'"]


def test_after_begin_callback_rejects_malformed_tenant_id(monkeypatch) -> None:
    """A tenant id that smuggled past ``set_tenant_context`` (e.g. set
    directly on the ContextVar) must still be rejected by the listener \u2014
    defense in depth at the database boundary."""
    monkeypatch.setattr(bootstrap, "LOCKED_DEPLOYMENT_MODE", "multi_tenant")

    from sqlalchemy import event

    registered: list = []
    monkeypatch.setattr(event, "listen", lambda _t, _i, fn: registered.append(fn))

    class _FakeSession:
        sync_session = object()

    _bind_tenant_isolation(_FakeSession())  # type: ignore[arg-type]

    token = current_tenant_id.set("a'; DROP TABLE x;--")
    try:
        with pytest.raises(MissingTenantContextError):
            registered[0](object(), object(), object())
    finally:
        current_tenant_id.reset(token)


# ── TUVL_REQUIRE_TENANT_CONTEXT opt-out path ─────────────────────────────────


def test_after_begin_does_not_raise_when_safety_net_disabled(monkeypatch) -> None:
    """When the operator explicitly disables the safety net, a missing
    tenant must NOT raise \u2014 the listener falls through silently so the
    request reaches the database with no ``SET LOCAL``.  This is the
    documented opt-out path for hosts that enforce isolation at a
    different layer (e.g. per-tenant connection pools)."""
    monkeypatch.setattr(bootstrap, "LOCKED_DEPLOYMENT_MODE", "multi_tenant")

    from tuvl.core.config import settings

    monkeypatch.setattr(settings, "tuvl_require_tenant_context", False)

    from sqlalchemy import event

    registered: list = []
    monkeypatch.setattr(event, "listen", lambda _t, _i, fn: registered.append(fn))

    class _FakeSession:
        sync_session = object()

    _bind_tenant_isolation(_FakeSession())  # type: ignore[arg-type]

    executed: list[str] = []

    class _FakeConn:
        def exec_driver_sql(self, sql: str) -> None:
            executed.append(sql)

    token = current_tenant_id.set("")
    try:
        # Must not raise even though no tenant is set.
        registered[0](object(), object(), _FakeConn())
    finally:
        current_tenant_id.reset(token)

    # And must not have issued SET LOCAL (no tenant to bind).
    assert executed == []


# ── Bootstrap warning on safety-net opt-out ──────────────────────────────────


def test_warn_if_safety_net_disabled_emits_warning(monkeypatch) -> None:
    """When MT mode is locked but the safety net is off, bootstrap must
    log a loud warning at startup so the operator cannot silently ship a
    misconfigured deployment."""
    from tuvl.core.config import settings

    monkeypatch.setattr(settings, "tuvl_require_tenant_context", False)

    captured: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        bootstrap.logger,
        "warning",
        lambda msg, *a, **kw: captured.append((msg, kw)),
    )

    bootstrap._warn_if_tenant_safety_net_disabled()

    assert any(
        evt == "bootstrap.tenant_safety_net.disabled"
        and kw.get("env_var") == "TUVL_REQUIRE_TENANT_CONTEXT"
        and kw.get("value") is False
        for evt, kw in captured
    )


def test_warn_if_safety_net_enabled_is_silent(monkeypatch) -> None:
    """In the default configuration the warning must not fire."""
    from tuvl.core.config import settings

    monkeypatch.setattr(settings, "tuvl_require_tenant_context", True)

    captured: list[str] = []
    monkeypatch.setattr(
        bootstrap.logger,
        "warning",
        lambda msg, *a, **kw: captured.append(msg % a if a else msg),
    )

    bootstrap._warn_if_tenant_safety_net_disabled()

    assert captured == []


# ── Public re-export identity ────────────────────────────────────────────────


def test_tenancy_module_reexports_missing_tenant_error_identity() -> None:
    """The same exception class must be visible under both the internal
    location and the public ``tuvl.tenancy`` namespace, so ``except``
    clauses written against either path catch the same error."""
    from tuvl.core.datasources import postgres as pg
    from tuvl.tenancy import MissingTenantContextError as PublicErr

    assert PublicErr is pg.MissingTenantContextError
