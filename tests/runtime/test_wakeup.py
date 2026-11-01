"""In-process wakeups for run event streams: fired after commit, never before, never leaked."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl.runtime import journal, wakeup
from tuvl.runtime.models import SystemRun


async def _run(engine: AsyncEngine) -> uuid.UUID:
    run = SystemRun(workflow="w", workflow_hash="h", status="running", trigger="api", input={})
    async with AsyncSession(engine) as s:
        s.add(run)
        run_id = run.id
        await s.commit()
    return run_id


async def test_a_journal_event_wakes_listeners_only_once_committed(
    sqlite_engine: AsyncEngine,
) -> None:
    run_id = await _run(sqlite_engine)
    with wakeup.listen(run_id) as woken:
        async with AsyncSession(sqlite_engine) as s:
            await journal.append_event(s, run_id, "run_started")
            await s.flush()
            assert not woken.is_set()  # flushed is not committed: a reader would see nothing
            await s.commit()
        assert woken.is_set()


async def test_a_rolled_back_event_wakes_nobody(sqlite_engine: AsyncEngine) -> None:
    run_id = await _run(sqlite_engine)
    with wakeup.listen(run_id) as woken:
        async with AsyncSession(sqlite_engine) as s:
            await journal.append_event(s, run_id, "run_started")
            await s.rollback()
            await s.commit()
        assert not woken.is_set()


async def test_listeners_are_per_run_and_removed_on_exit() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    with wakeup.listen(a) as on_a, wakeup.listen(a) as on_a2, wakeup.listen(b) as on_b:
        wakeup.notify(a)
        assert on_a.is_set() and on_a2.is_set() and not on_b.is_set()
    assert a not in wakeup._listeners and b not in wakeup._listeners
    wakeup.notify(a)  # nobody listening: a no-op


async def test_a_notify_from_another_thread_reaches_the_loop() -> None:
    run_id = uuid.uuid4()
    with wakeup.listen(run_id) as woken:
        await asyncio.to_thread(wakeup.notify, run_id)
        async with asyncio.timeout(1):
            await woken.wait()
