"""Regression tests for TD-11 (leaked secondary sessions on first commit
failure) and TD-39 (non-DB exceptions mislabeled as 'Unexpected DB error')."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from tuvl.core.datasources import postgres
from tuvl.core.repositories.uow import WorkflowUoW

# ── TD-11: commit_secondary must close every session and re-raise the first
# error, even when an earlier session's commit fails ────────────────────────


class _FakeSecondarySession:
    def __init__(self, *, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.committed = False
        self.closed = False

    async def commit(self) -> None:
        self.committed = True
        if self.fail_commit:
            raise RuntimeError("commit boom")

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_commit_secondary_closes_all_sessions_after_first_failure() -> None:
    uow = WorkflowUoW(primary_session=object(), allowed_models=frozenset())
    failing = _FakeSecondarySession(fail_commit=True)
    healthy = _FakeSecondarySession()
    uow._secondary_sessions = {"ds_a": failing, "ds_b": healthy}

    with pytest.raises(RuntimeError, match="commit boom"):
        await uow.commit_secondary()

    assert failing.closed, "the failing session must still be closed"
    assert healthy.closed, "sessions after the failing one must not leak"
    assert uow._secondary_sessions == {}


@pytest.mark.asyncio
async def test_commit_secondary_reraises_only_the_first_error() -> None:
    uow = WorkflowUoW(primary_session=object(), allowed_models=frozenset())
    first = _FakeSecondarySession(fail_commit=True)
    second = _FakeSecondarySession(fail_commit=True)
    uow._secondary_sessions = {"ds_a": first, "ds_b": second}

    with pytest.raises(RuntimeError):
        await uow.commit_secondary()

    assert first.closed
    assert second.closed


@pytest.mark.asyncio
async def test_commit_secondary_happy_path_commits_and_closes() -> None:
    uow = WorkflowUoW(primary_session=object(), allowed_models=frozenset())
    a, b = _FakeSecondarySession(), _FakeSecondarySession()
    uow._secondary_sessions = {"ds_a": a, "ds_b": b}

    await uow.commit_secondary()

    assert a.committed and a.closed
    assert b.committed and b.closed
    assert uow._secondary_sessions == {}


# ── TD-39: only genuine SQLAlchemyError gets logged as "Unexpected DB error" ─


class _YieldingSession:
    async def close(self) -> None:
        pass


class _FakeRequest:
    def __init__(self, method: str = "POST") -> None:
        self.method = method


class _NotADbError(Exception):
    """Stand-in for a client-side error (e.g. pydantic ValidationError)."""


@pytest.mark.asyncio
async def test_get_session_does_not_log_db_error_for_non_db_exception(monkeypatch) -> None:
    session = _YieldingSession()
    monkeypatch.setattr(postgres, "_PRIMARY_DS", "primary_test")
    monkeypatch.setattr(postgres, "_sessions_rw", {"primary_test": lambda: session})

    logged: list[tuple[str, dict]] = []
    monkeypatch.setattr(postgres.logger, "error", lambda msg, *a, **kw: logged.append((msg, kw)))

    agen = postgres.get_session(_FakeRequest())
    got = await agen.__anext__()
    assert got is session

    with pytest.raises(_NotADbError):
        await agen.athrow(_NotADbError("client sent bad enum value"))

    assert not any(msg == "Unexpected DB error on session" for msg, _ in logged)


@pytest.mark.asyncio
async def test_get_session_logs_db_error_for_sqlalchemy_error(monkeypatch) -> None:
    session = _YieldingSession()
    monkeypatch.setattr(postgres, "_PRIMARY_DS", "primary_test")
    monkeypatch.setattr(postgres, "_sessions_rw", {"primary_test": lambda: session})

    logged: list[tuple[str, dict]] = []
    monkeypatch.setattr(postgres.logger, "error", lambda msg, *a, **kw: logged.append((msg, kw)))

    agen = postgres.get_session(_FakeRequest())
    await agen.__anext__()

    with pytest.raises(SQLAlchemyError):
        await agen.athrow(SQLAlchemyError("db exploded"))

    assert any(msg == "Unexpected DB error on session" for msg, _ in logged)


@pytest.mark.asyncio
async def test_model_session_does_not_log_db_error_for_non_db_exception(monkeypatch) -> None:
    session = _YieldingSession()
    monkeypatch.setattr(postgres, "_PRIMARY_DS", "primary_test")
    monkeypatch.setattr(postgres, "get_session_factory", lambda ds, is_write: lambda: session)

    logged: list[tuple[str, dict]] = []
    monkeypatch.setattr(postgres.logger, "error", lambda msg, *a, **kw: logged.append((msg, kw)))

    dep = postgres.model_session("NotInDatasourceMap")
    agen = dep(_FakeRequest())
    await agen.__anext__()

    with pytest.raises(_NotADbError):
        await agen.athrow(_NotADbError("bad input"))

    assert not any(msg == "Unexpected DB error on session" for msg, _ in logged)


@pytest.mark.asyncio
async def test_model_session_logs_db_error_for_sqlalchemy_error(monkeypatch) -> None:
    session = _YieldingSession()
    monkeypatch.setattr(postgres, "_PRIMARY_DS", "primary_test")
    monkeypatch.setattr(postgres, "get_session_factory", lambda ds, is_write: lambda: session)

    logged: list[tuple[str, dict]] = []
    monkeypatch.setattr(postgres.logger, "error", lambda msg, *a, **kw: logged.append((msg, kw)))

    dep = postgres.model_session("NotInDatasourceMap")
    agen = dep(_FakeRequest())
    await agen.__anext__()

    with pytest.raises(SQLAlchemyError):
        await agen.athrow(SQLAlchemyError("db exploded"))

    assert any(msg == "Unexpected DB error on session" for msg, _ in logged)
