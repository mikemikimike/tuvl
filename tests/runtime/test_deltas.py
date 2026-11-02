"""Live drafts: buffered writes, resets, cleanup and the sweep (SQLite and Postgres)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tuvl.runtime import deltas
from tuvl.runtime.models import SystemRunDelta

TABLE = SystemRunDelta.__table__  # type: ignore[attr-defined]


async def rows(engine: AsyncEngine, run_id: uuid.UUID) -> list[tuple[str, str, str]]:
    async with AsyncSession(engine) as s:
        found = await s.execute(
            sa.select(TABLE.c.agent_id, TABLE.c.kind, TABLE.c.text)
            .where(TABLE.c.run_id == run_id)
            .order_by(TABLE.c.id)
        )
        return [(a, k, t) for a, k, t in found.all()]


async def test_writes_are_held_back_and_merged(engine: AsyncEngine) -> None:
    run_id = uuid.uuid4()
    stream = deltas.DeltaStream(engine, run_id, "draft")
    for piece in ("Hel", "lo", ", ", "world"):
        await stream.write(piece)
    assert await rows(engine, run_id) == []  # nothing is written until the interval passes
    await stream.close()
    assert await rows(engine, run_id) == [("draft", "delta", "Hello, world")]
    assert stream.used


async def test_the_pump_flushes_without_a_close(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(deltas, "FLUSH_SECONDS", 0.02)
    run_id = uuid.uuid4()
    stream = deltas.DeltaStream(engine, run_id, "draft")
    await stream.write("first")
    import asyncio

    await asyncio.sleep(0.3)
    assert await rows(engine, run_id) == [("draft", "delta", "first")]
    await stream.write("second")
    await stream.close()
    assert [t for _, _, t in await rows(engine, run_id)] == ["first", "second"]


async def test_a_reset_discards_the_draft(engine: AsyncEngine) -> None:
    run_id = uuid.uuid4()
    stream = deltas.DeltaStream(engine, run_id, "draft")
    await stream.write("wrong")
    await stream.reset()
    await stream.write("right")
    await stream.close()
    assert await rows(engine, run_id) == [
        ("draft", "delta", "wrong"),
        ("draft", "reset", ""),
        ("draft", "delta", "right"),
    ]
    async with AsyncSession(engine) as s:
        assert await deltas.draft(s, run_id, "draft") == ("right", 3)


async def test_an_agent_that_runs_again_starts_with_a_reset(engine: AsyncEngine) -> None:
    run_id = uuid.uuid4()
    first = deltas.DeltaStream(engine, run_id, "draft")
    await first.write("from the worker that crashed")
    await first.close()
    second = deltas.DeltaStream(engine, run_id, "draft")
    await second.write("from the retry")
    await second.close()
    assert [k for _, k, _ in await rows(engine, run_id)] == ["delta", "reset", "delta"]
    async with AsyncSession(engine) as s:
        assert (await deltas.draft(s, run_id, "draft"))[0] == "from the retry"


async def test_the_draft_is_one_agents_and_the_cursor_is_the_runs(engine: AsyncEngine) -> None:
    run_id = uuid.uuid4()
    first, second = deltas.DeltaStream(engine, run_id, "a"), deltas.DeltaStream(engine, run_id, "b")
    await first.write("one")
    await second.write("two")
    await first.write(" more")
    await first.close()
    await second.close()
    async with AsyncSession(engine) as s:
        text, last = await deltas.draft(s, run_id, "a")
        assert text == "one more" and last == 2
        assert await deltas.draft(s, run_id, "b") == ("two", 2)
        assert await deltas.draft(s, run_id, "nobody") == ("", 2)
        assert [r.text for r in await deltas.after(s, run_id, 1)] == ["two"]


async def test_the_sweep_removes_old_rows_and_a_finished_runs_after_the_grace(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tuvl.runtime.models import SystemRun

    def row(run_id: uuid.UUID, agent: str, age: timedelta) -> SystemRunDelta:
        return SystemRunDelta(
            run_id=run_id, agent_id=agent, text="x", created_at=datetime.now(UTC) - age
        )

    ended, running, orphan = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine) as s:
        for run_id, status in ((ended, "completed"), (running, "running")):
            s.add(
                SystemRun(id=run_id, workflow="w", workflow_hash="h", status=status, trigger="test")
            )
        await s.flush()
        s.add_all(
            [
                row(
                    ended, "just-finished", timedelta(seconds=5)
                ),  # a client may still be reading it
                row(ended, "long-finished", timedelta(minutes=5)),
                row(
                    running, "still-writing", timedelta(minutes=5)
                ),  # a run that is still going keeps its draft
                row(orphan, "abandoned", timedelta(days=2)),
            ]
        )
        await s.commit()
    monkeypatch.setattr(deltas, "_last_sweep", float("-inf"))
    async with AsyncSession(engine) as s:
        assert await deltas.sweep(s) == 2
        await s.commit()
        assert await deltas.sweep(s) == 0  # not again within the minute
    left = {a for run_id in (ended, running, orphan) for a, _, _ in await rows(engine, run_id)}
    assert left == {"just-finished", "still-writing"}


async def test_a_draft_that_cannot_be_stored_never_fails_the_agent() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    broken = create_async_engine("sqlite+aiosqlite:///no/such/dir/x.db")
    stream = deltas.DeltaStream(broken, uuid.uuid4(), "draft")
    await stream.write("lost")
    await stream.close()  # logs and moves on
    await broken.dispose()
