"""Memory rows: ordered by time, erased per owner, expired by age (C1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.runtime.test_builtins import vectors  # noqa: F401 — the pgvector fixture
from tuvl.core.models.system import SystemVectorStore
from tuvl.runtime import memory

pytestmark = pytest.mark.usefixtures("vectors")


def row(collection: str, key: str | None, text: str, age_hours: float = 0) -> SystemVectorStore:
    return SystemVectorStore(
        id=uuid.uuid4(),
        collection=collection,
        content=text,
        extra_metadata={"memory_key": key} if key else {"source": "kb"},
        created_at=datetime.now(UTC) - timedelta(hours=age_hours),
    )


async def contents(db: AsyncEngine, collection: str) -> list[str]:
    async with AsyncSession(db) as s:
        found = await s.execute(
            sa.text(
                "select content from tuvl_system_vector_store where collection = :c order by created_at"
            ),
            {"c": collection},
        )
        return [r[0] for r in found.all()]


async def test_rows_carry_the_time_they_were_written(pg_engine: AsyncEngine) -> None:
    async with AsyncSession(pg_engine) as s:
        s.add_all(
            [
                row("mem", "ada", "newest", 0),
                row("mem", "ada", "oldest", 48),
                row("mem", "ada", "middle", 5),
            ]
        )
        await s.commit()
    assert await contents(pg_engine, "mem") == ["oldest", "middle", "newest"]
    async with AsyncSession(
        pg_engine
    ) as s:  # a row written without a time gets one from the database
        await s.execute(
            sa.text(
                "insert into tuvl_system_vector_store (id, collection, content) values (:i, 'mem', 'bare')"
            ),
            {"i": uuid.uuid4()},
        )
        await s.commit()
        stamp = (
            await s.execute(
                sa.text("select created_at from tuvl_system_vector_store where content = 'bare'")
            )
        ).scalar_one()
    assert abs((datetime.now(UTC) - stamp).total_seconds()) < 60


async def test_forget_removes_one_owners_rows_in_one_collection_and_nothing_else(
    pg_engine: AsyncEngine,
) -> None:
    async with AsyncSession(pg_engine) as s:
        s.add_all(
            [
                row("mem", "ada", "ada one"),
                row("mem", "ada", "ada two"),
                row("mem", "grace", "grace one"),
                row("other", "ada", "ada elsewhere"),
                row("mem", None, "a knowledge-base row"),
            ]
        )
        await s.commit()
    async with AsyncSession(pg_engine) as s:
        assert await memory.forget(s, "mem", "ada") == 2
        await s.commit()
    assert sorted(await contents(pg_engine, "mem")) == ["a knowledge-base row", "grace one"]
    assert await contents(pg_engine, "other") == ["ada elsewhere"]
    async with AsyncSession(pg_engine) as s:
        assert await memory.forget(s, "mem", "nobody") == 0
        with pytest.raises(ValueError):
            await memory.forget(s, "mem", "")


async def test_expire_removes_old_memories_only(pg_engine: AsyncEngine) -> None:
    async with AsyncSession(pg_engine) as s:
        s.add_all(
            [
                row("mem", "ada", "fresh", 1),
                row("mem", "ada", "stale", 24 * 40),
                row("mem", None, "an old knowledge-base row", 24 * 400),
            ]
        )
        await s.commit()
    async with AsyncSession(pg_engine) as s:
        assert await memory.expire(s, "mem", timedelta(days=30)) == 1
        await s.commit()
        with pytest.raises(ValueError):
            await memory.expire(s, "mem", timedelta(0))
    assert sorted(await contents(pg_engine, "mem")) == ["an old knowledge-base row", "fresh"]


async def test_the_migration_adds_the_column_to_an_old_table(pg_engine: AsyncEngine) -> None:
    async with pg_engine.begin() as conn:
        await conn.execute(sa.text("alter table tuvl_system_vector_store drop column created_at"))
        await conn.execute(
            sa.text(
                "insert into tuvl_system_vector_store (id, collection, content) values (gen_random_uuid(), 'mem', 'old row')"
            )
        )
        await conn.execute(
            sa.text(
                "alter table tuvl_system_vector_store add column if not exists created_at timestamptz not null default now()"
            )
        )
        found: Any = await conn.execute(
            sa.text("select count(*) from tuvl_system_vector_store where created_at is not null")
        )
    assert found.scalar_one() == 1  # the existing row got a time too


def test_the_prune_command_wants_exactly_one_of_key_and_age() -> None:
    from typer.testing import CliRunner

    from tuvl.cli import app

    runner = CliRunner()
    both = runner.invoke(app, ["prune", "memory", "mem", "--key", "ada", "--older-than", "30d"])
    neither = runner.invoke(app, ["prune", "memory", "mem"])
    bad = runner.invoke(app, ["prune", "memory", "mem", "--older-than", "soon"])
    assert both.exit_code == 2 and neither.exit_code == 2 and bad.exit_code == 2
    assert "exactly one" in both.output and "invalid duration" in bad.output


async def test_the_retention_sweep_applies_each_collections_shortest_retention(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tuvl.contract.registry import WORKFLOWS
    from tuvl.contract.schema import WorkflowDocument

    def flow(name: str, collection: str, retention: str | None) -> WorkflowDocument:
        memory_block: dict[str, Any] = {"collection": collection}
        if retention:
            memory_block["retention"] = retention
        return WorkflowDocument.model_validate(
            {
                "kind": "Workflow",
                "version": "tuvl/v2",
                "metadata": {"name": name},
                "spec": {
                    "agents": [
                        {
                            "id": "a",
                            "description": "a",
                            "engine": "llm",
                            "llm": {"model": "m", "prompt": "p", "memory": memory_block},
                            "routes": {"default": "END"},
                        }
                    ]
                },
            }
        )

    monkeypatch.setitem(WORKFLOWS, "one", flow("one", "mem", "30d"))
    monkeypatch.setitem(WORKFLOWS, "two", flow("two", "mem", "7d"))  # the shorter one wins
    monkeypatch.setitem(WORKFLOWS, "three", flow("three", "forever", None))
    assert memory.retained_collections() == {"mem": timedelta(days=7)}
    async with AsyncSession(pg_engine) as s:
        s.add_all(
            [
                row("mem", "ada", "ten days old", 24 * 10),
                row("mem", "ada", "yesterday", 24),
                row("forever", "ada", "ancient but kept", 24 * 900),
            ]
        )
        await s.commit()
    monkeypatch.setattr(memory, "_last_retention", float("-inf"))
    async with AsyncSession(pg_engine) as s:
        assert await memory.retention_sweep(s) == 1
        await s.commit()
        assert await memory.retention_sweep(s) == 0  # not again within five minutes
    assert await contents(pg_engine, "mem") == ["yesterday"]
    assert await contents(pg_engine, "forever") == ["ancient but kept"]


def test_a_retention_must_be_a_positive_duration() -> None:
    from pydantic import ValidationError

    from tuvl.contract.schema import MemoryParams

    assert MemoryParams(collection="m", retention="30d").retention == "30d"
    for bad in ("soon", "0d"):
        with pytest.raises(ValidationError):
            MemoryParams(collection="m", retention=bad)


async def test_recall_query_uses_the_memory_key_index(pg_engine: AsyncEngine) -> None:
    async with AsyncSession(pg_engine) as s:
        await s.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_svs_memory_key ON tuvl_system_vector_store "
                "(collection, (metadata->>'memory_key'), created_at) "
                "WHERE metadata ? 'memory_key'"
            )
        )
        s.add_all([row("mem", f"owner{i % 50}", f"m{i}") for i in range(400)])
        s.add_all([row("kb", None, f"doc{i}") for i in range(2000)])
        await s.commit()
        await s.execute(sa.text("ANALYZE tuvl_system_vector_store"))
        await s.execute(sa.text("SET enable_seqscan = off"))
        plan = (
            await s.execute(
                sa.text("EXPLAIN " + memory.RECENT_SQL), {"c": "mem", "key": "owner1", "n": 5}
            )
        ).all()
    assert "ix_svs_memory_key" in "\n".join(r[0] for r in plan)
