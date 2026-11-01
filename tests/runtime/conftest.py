"""Database fixtures for the 2.0 runtime.

``pg_engine`` is a real Postgres (row locks, SKIP LOCKED, JSONB) — CI provides
one; locally point ``TUVL_TEST_PG_URL`` at any disposable database. Tests that
need it are skipped when it is unreachable. ``sqlite_engine`` covers the
dialect-neutral parts.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool
from sqlmodel import SQLModel

from tuvl.runtime.models import RUNTIME_TABLES

PG_URL = os.environ.get(
    "TUVL_TEST_PG_URL", "postgresql+asyncpg://tuvl:tuvl@localhost:5432/tuvl_test"
)
_TABLES = [m.__table__ for m in RUNTIME_TABLES]


async def _reset(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: SQLModel.metadata.drop_all(c, tables=_TABLES))
        await conn.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=_TABLES))


async def _pg() -> AsyncEngine:
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        await _reset(engine)
    except Exception as exc:  # unreachable / no such database
        await engine.dispose()
        pytest.skip(f"Postgres not available at TUVL_TEST_PG_URL ({type(exc).__name__})")
    return engine


async def _sqlite() -> AsyncEngine:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    await _reset(engine)
    return engine


@pytest.fixture
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    engine = await _pg()
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def sqlite_engine() -> AsyncIterator[AsyncEngine]:
    engine = await _sqlite()
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(params=["sqlite", "postgres"])
async def engine(request: pytest.FixtureRequest) -> AsyncIterator[AsyncEngine]:
    """Runs a test on both SQLite and Postgres."""
    eng = await (_sqlite() if request.param == "sqlite" else _pg())
    try:
        yield eng
    finally:
        await eng.dispose()
