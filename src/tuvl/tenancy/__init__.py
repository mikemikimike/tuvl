"""Public tenancy API for host applications embedding the TUVL engine.

TUVL core itself is **tenant-agnostic**: it provides the plumbing
(ContextVar, ``after_begin`` session hook, ``DynamicTenantModel`` column
injection, ``MissingTenantContextError`` safety net), but does not decide
*how* tenant identity is extracted from a request.  The host application
\u2014 typically a wrapper that imports TUVL as a subsystem \u2014 is responsible
for extracting the tenant id from its authentication layer (token claim,
HTTP header, JWT claim, \u2026) and populating ``current_tenant_id`` before
any TUVL request handler runs.

This module is the **stable, documented surface** for that contract.

Quick start (FastAPI host)
--------------------------
::

    from fastapi import FastAPI, Request, Depends, HTTPException
    from tuvl.core import app as tuvl_app
    from tuvl.tenancy import set_tenant_context, current_tenant_id

    async def extract_tenant(request: Request) -> None:
        # Your auth layer here \u2014 e.g. verify the token + read its tenant claim.
        tid = request.headers.get("x-tenant-id")
        if not tid:
            raise HTTPException(401, "Missing tenant header")
        set_tenant_context(tid)

    tuvl_app.router.dependencies.append(Depends(extract_tenant))

Quick start (background / non-HTTP work)
----------------------------------------
::

    from tuvl.tenancy import async_tenant_scope

    async with async_tenant_scope("acme_corp"):
        await run_some_workflow(payload)
    # current_tenant_id is restored to its previous value here.
    # (Use the sync ``tenant_scope`` from synchronous code.)

Contract guarantees
-------------------
* ``current_tenant_id`` is a real ``contextvars.ContextVar`` \u2014 it
  propagates correctly across ``asyncio.create_task`` and into worker
  threads launched via ``loop.run_in_executor`` *only* when the caller
  carries the context (use ``contextvars.copy_context()`` for manual
  thread submission).
* ``set_tenant_context`` is **idempotent within a request** but bleeds
  across request boundaries if called outside a per-request scope.  Use
  ``tenant_scope`` (context manager) for any non-request work.
* When ``LOCKED_DEPLOYMENT_MODE == 'multi_tenant'`` and
  ``TUVL_REQUIRE_TENANT_CONTEXT`` is true (the default), opening a TUVL
  database session without setting the tenant raises
  :class:`tuvl.core.datasources.postgres.MissingTenantContextError`.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from tuvl.core.context import current_tenant_id
from tuvl.core.datasources.postgres import (
    _TENANT_ID_RE,
    MissingTenantContextError,
)

__all__ = [
    "MissingTenantContextError",
    "TENANT_ID_PATTERN",
    "async_tenant_scope",
    "bind_principal_context",
    "current_tenant_id",
    "current_user_id",
    "require_tenant_context",
    "set_tenant_context",
    "tenant_scope",
]


def __getattr__(name: str) -> Any:
    """Lazy re-export of auth helpers.

    ``bind_principal_context`` lives in :mod:`tuvl.core.auth.access`
    which pulls in the auth stack (FastAPI security, JWT, the key manager).
    Loading it lazily keeps ``import tuvl.tenancy`` cheap for the
    non-HTTP paths (CLI, tests, workers) that never need the dependency.
    """
    if name == "bind_principal_context":
        from tuvl.core.auth.access import bind_principal_context as _bpc

        return _bpc
    if name == "current_user_id":
        from tuvl.core.context import current_user_id as _cuid

        return _cuid
    raise AttributeError(f"module 'tuvl.tenancy' has no attribute {name!r}")


# Re-exported as a public, documented constant so host applications can
# validate tenant ids client-side using the same allowlist that TUVL
# enforces server-side.
TENANT_ID_PATTERN: re.Pattern[str] = _TENANT_ID_RE


def set_tenant_context(tenant_id: str) -> None:
    """Set the active tenant for the current async task.

    The value is validated against :data:`TENANT_ID_PATTERN` before it is
    bound to the ContextVar; an invalid id raises ``ValueError``.

    Notes
    -----
    Calling ``set_tenant_context`` outside of a per-request scope (for
    example at module import time, in a long-lived task) will permanently
    bind the value into that task's context.  Prefer :func:`tenant_scope`
    for any non-request work so the prior value is restored.
    """
    if not isinstance(tenant_id, str) or not TENANT_ID_PATTERN.fullmatch(tenant_id):
        raise ValueError(f"Tenant id {tenant_id!r} does not match {TENANT_ID_PATTERN.pattern}.")
    current_tenant_id.set(tenant_id)


@contextmanager
def tenant_scope(tenant_id: str) -> Iterator[None]:
    """Bind ``tenant_id`` for the duration of the ``with`` block.

    The previous value of ``current_tenant_id`` is restored on exit,
    including when the block raises.  Use this anywhere outside of a
    per-request lifecycle (background workers, CLI scripts, tests).

    Example
    -------
    >>> with tenant_scope("acme_corp"):
    ...     run_something_that_queries_the_db()
    """
    if not isinstance(tenant_id, str) or not TENANT_ID_PATTERN.fullmatch(tenant_id):
        raise ValueError(f"Tenant id {tenant_id!r} does not match {TENANT_ID_PATTERN.pattern}.")
    token = current_tenant_id.set(tenant_id)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


@asynccontextmanager
async def async_tenant_scope(tenant_id: str) -> AsyncIterator[None]:
    """Async-friendly variant of :func:`tenant_scope`.

    Functionally identical to the sync version (``ContextVar.set`` /
    ``reset`` work the same in async code), but exposed as an
    ``async with``-compatible context manager so it composes with other
    async resources.
    """
    with tenant_scope(tenant_id):
        yield


def require_tenant_context() -> str:
    """FastAPI-style dependency: return the active tenant or raise 400.

    Suitable for use as ``Depends(require_tenant_context)`` on host
    routes that must not run without a tenant.  TUVL's own session
    dependency enforces this at the database boundary; this helper lets
    host code fail earlier (before opening a session) with a clearer
    error.
    """
    from fastapi import HTTPException

    tid = current_tenant_id.get("")
    if not tid:
        raise HTTPException(
            status_code=400,
            detail=(
                "Tenant context is required for this request. The host "
                "application must set `current_tenant_id` before invoking "
                "this endpoint."
            ),
        )
    return tid
