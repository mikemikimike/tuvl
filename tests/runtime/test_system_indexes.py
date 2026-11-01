"""System indexes on large tables: built concurrently at boot, used by the queries they serve."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.runtime.test_builtins import vectors  # noqa: F401 — the pgvector fixture
from tuvl.core.datasources import postgres
from tuvl.core.models.system import SystemVectorStore
from tuvl.runtime import memory

DELTAS_INDEX = "ix_tuvl_run_deltas_created"


async def _valid(engine: AsyncEngine, name: str) -> bool | None:
    async with engine.connect() as conn:
        found = await conn.execute(
            sa.text("SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:n)"),
            {"n": name},
        )
        return found.scalar_one_or_none()


async def _drop(engine: AsyncEngine, name: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))


async def test_a_fresh_database_gets_the_deltas_index(pg_engine: AsyncEngine) -> None:
    assert await _valid(pg_engine, DELTAS_INDEX) is True


async def test_an_existing_table_gets_the_index_built_concurrently(pg_engine: AsyncEngine) -> None:
    await _drop(pg_engine, DELTAS_INDEX)
    async with pg_engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO tuvl_system_run_deltas (run_id, agent_id, kind, text, created_at) "
                "SELECT gen_random_uuid(), 'a', 'delta', 'x', now() FROM generate_series(1, 50)"
            )
        )
    # CONCURRENTLY refuses to run inside a transaction block: this passing proves it ran outside one
    await postgres.ensure_indexes(pg_engine, postgres.RUNTIME_INDEXES)
    assert await _valid(pg_engine, DELTAS_INDEX) is True
    await postgres.ensure_indexes(pg_engine, postgres.RUNTIME_INDEXES)  # idempotent
    assert await _valid(pg_engine, DELTAS_INDEX) is True


async def test_an_index_left_invalid_by_a_dead_build_is_rebuilt(pg_engine: AsyncEngine) -> None:
    try:
        async with pg_engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE pg_index SET indisvalid = false WHERE indexrelid = to_regclass(:n)"
                ),
                {"n": DELTAS_INDEX},
            )
    except sa.exc.DBAPIError:
        pytest.skip("needs a superuser to mark an index invalid")
    assert await _valid(pg_engine, DELTAS_INDEX) is False
    await postgres.ensure_indexes(pg_engine, postgres.RUNTIME_INDEXES)
    assert await _valid(pg_engine, DELTAS_INDEX) is True


async def test_a_process_finding_the_lock_taken_leaves_the_indexes_alone(
    pg_engine: AsyncEngine,
) -> None:
    await _drop(pg_engine, DELTAS_INDEX)
    async with pg_engine.connect() as holder:
        await holder.execute(sa.text("SELECT pg_advisory_lock(:k)"), {"k": postgres._INDEX_LOCK})
        await postgres.ensure_indexes(pg_engine, postgres.RUNTIME_INDEXES)
        assert await _valid(pg_engine, DELTAS_INDEX) is None
        await holder.execute(sa.text("SELECT pg_advisory_unlock(:k)"), {"k": postgres._INDEX_LOCK})
    await postgres.ensure_indexes(pg_engine, postgres.RUNTIME_INDEXES)
    assert await _valid(pg_engine, DELTAS_INDEX) is True


@pytest.mark.usefixtures("vectors")
async def test_the_step_lookup_in_remember_uses_its_partial_index(pg_engine: AsyncEngine) -> None:
    await postgres.ensure_indexes(pg_engine, postgres.VECTOR_INDEXES)
    assert await _valid(pg_engine, "ix_svs_memory_step") is True
    async with AsyncSession(pg_engine) as s:
        s.add_all(
            [
                SystemVectorStore(
                    id=uuid.uuid4(),
                    collection="mem",
                    content=f"turn {i}",
                    extra_metadata={"memory_key": "ada", "step": f"run:a:{i}"},
                )
                for i in range(300)
            ]
            + [
                SystemVectorStore(
                    id=uuid.uuid4(), collection="mem", content="kb", extra_metadata={"source": "kb"}
                )
            ]
        )
        await s.commit()
    seen: list[tuple[Any, Any]] = []

    async with AsyncSession(pg_engine) as s:

        @event.listens_for(s.sync_session, "do_orm_execute")
        def capture(state: Any) -> None:
            if "metadata->>'step'" in str(state.statement):
                seen.append((state.statement, state.parameters))

        stored = await memory.remember(
            s, collection="mem", text="again", key="ada", run_id="r", agent="a", step="run:a:7"
        )
        assert stored is False  # the step already ran
        assert seen
        statement, params = seen[0]
        await s.execute(sa.text("ANALYZE tuvl_system_vector_store"))
        await s.execute(sa.text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0] for row in (await s.execute(sa.text(f"EXPLAIN {statement}"), params)).all()
        )
    assert "ix_svs_memory_step" in plan, plan
