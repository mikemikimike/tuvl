"""Regression tests for SQLAlchemy session cleanup under cancellation.

In 2026.2.3b1/b2, all three FastAPI session dependencies
(``SessionRouter.__call__``, ``model_session(...)`` and
``get_primary_rw_session``) used the pattern::

    async with factory() as session:
        yield session

This fails when the consumer is cancelled mid-yield: the session is
typically in ``PROVISIONING_CONNECTION`` state, and the ``async with``
``__aexit__`` invokes ``session.close()`` which raises
``IllegalStateChangeError`` because the state machine is mid-transition.
Symptoms observed in the wild (during ``tuvl dev`` hot-reload):

  ERROR  Task exception was never retrieved
  ...
  IllegalStateChangeError: Method 'close()' can't be called here;
  method '_connection_for_bind()' is already in progress
  ...
  WARNING  The garbage collector is trying to clean up non-checked-in
  connection — please ensure SQLAlchemy pooled connections are returned
  to the pool explicitly.

Fixed in 2026.2.3b3 by switching to a manual try/finally lifecycle with
``_close_session_safely`` as the finalizer.  These tests pin the
contract so the pattern can't regress to the buggy ``async with`` form.
"""

from __future__ import annotations

import inspect

from sqlalchemy.exc import IllegalStateChangeError


def test_close_session_safely_swallows_illegal_state_change() -> None:
    """The helper must catch IllegalStateChangeError + try to rollback."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from tuvl.core.datasources.postgres import _close_session_safely

    session = MagicMock()
    session.close = AsyncMock(
        side_effect=IllegalStateChangeError(
            "Method 'close()' can't be called here; "
            "method '_connection_for_bind()' is already in progress"
        )
    )
    session.rollback = AsyncMock()

    # Must NOT raise even though close() did.
    asyncio.run(_close_session_safely(session))

    session.close.assert_awaited_once()
    session.rollback.assert_awaited_once()


def test_close_session_safely_swallows_arbitrary_exceptions() -> None:
    """Any other close() exception is also swallowed (best-effort finaliser)."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from tuvl.core.datasources.postgres import _close_session_safely

    session = MagicMock()
    session.close = AsyncMock(side_effect=OSError("network down"))

    # Must NOT raise.
    asyncio.run(_close_session_safely(session))


def test_close_session_safely_returns_cleanly_on_success() -> None:
    """Happy path: close() succeeds, helper returns None without rollback."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from tuvl.core.datasources.postgres import _close_session_safely

    session = MagicMock()
    session.close = AsyncMock()
    session.rollback = AsyncMock()

    asyncio.run(_close_session_safely(session))

    session.close.assert_awaited_once()
    session.rollback.assert_not_called()


# ── Source-level pins so the FastAPI dependency pattern can't regress ────────


def _source(obj) -> str:
    return inspect.getsource(obj)


def test_session_router_uses_manual_lifecycle() -> None:
    """``SessionRouter.__call__`` must not use ``async with factory()`` —
    that pattern leaks ``IllegalStateChangeError`` on cancellation."""
    from tuvl.core.datasources.postgres import SessionRouter

    src = _source(SessionRouter)
    assert "async with factory()" not in src, (
        "SessionRouter regressed to `async with factory() as session:` — "
        "this pattern leaks IllegalStateChangeError when the consumer is "
        "cancelled mid-yield.  Use manual try/finally with "
        "_close_session_safely instead."
    )
    assert "_close_session_safely(session)" in src, (
        "SessionRouter must call _close_session_safely in its finally block."
    )


def test_model_session_dep_uses_manual_lifecycle() -> None:
    """The per-model session dependency must use the same safe pattern."""
    from tuvl.core.datasources.postgres import model_session

    # model_session is a factory — capture the inner _dep function.
    src = _source(model_session)
    assert "async with factory()" not in src
    assert "_close_session_safely(session)" in src


def test_get_primary_rw_session_uses_manual_lifecycle() -> None:
    """The IAM-write session must use the same safe pattern."""
    from tuvl.core.datasources.postgres import get_primary_rw_session

    src = _source(get_primary_rw_session)
    assert "async with _sessions_rw" not in src, (
        "get_primary_rw_session regressed to the buggy `async with` pattern."
    )
    assert "_close_session_safely(session)" in src
