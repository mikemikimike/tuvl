"""Live drafts: the text of an answer while the model is still writing it.

A worker writes pieces to ``tuvl_system_run_deltas`` in small batches; the run's event stream reads them
(any process can). They are not journal events: they are not replayed or exported, and the final
result is journaled as usual. A finished run's rows are removed a minute later by a sweep. A client that connects mid-agent gets the draft so far in one piece.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tuvl.runtime import queue, wakeup
from tuvl.runtime.models import SystemRun, SystemRunDelta

logger = structlog.get_logger(__name__)

#: How long a worker holds text back to write it in one insert.
FLUSH_SECONDS = 0.1
#: Rows older than this belong to a run that crashed or was deleted; the sweep removes them.
MAX_AGE = timedelta(hours=24)
#: How long a finished run's drafts stay, for a client still reading the last pieces.
GRACE = timedelta(seconds=60)
_SWEEP_EVERY = 60.0
_TABLE = SystemRunDelta.__table__  # type: ignore[attr-defined]
_RUNS = SystemRun.__table__  # type: ignore[attr-defined]


class DeltaStream:
    """What an engine writes a draft to: ``await stream.write(text)``, ``await stream.reset()``.

    Writes are buffered and flushed by a background task every ``FLUSH_SECONDS`` and on ``close()``.
    A failure to store a draft is logged and dropped: a draft is a convenience and must never fail
    the agent. The first write of an agent that already has a draft (it is running again after a
    crash or a retry) starts with a ``reset``.
    """

    def __init__(self, engine: AsyncEngine, run_id: uuid.UUID, agent_id: str) -> None:
        self.engine = engine
        self.run_id = run_id
        self.agent_id = agent_id
        self.used = False
        self._pending: list[tuple[str, str]] = []
        self._started = False
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    async def write(self, text: str) -> None:
        if text and not self._closed:
            self.used = True
            self._pending.append(("delta", text))
            self._ensure_pump()

    async def reset(self) -> None:
        """Discard the draft: the agent is starting its answer again."""
        if not self._closed:
            self.used = True
            self._pending.append(("reset", ""))
            self._ensure_pump()

    async def close(self) -> None:
        """Write what is still held back and stop. The rows stay for the sweep to remove."""
        self._closed = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self._flush()

    def _ensure_pump(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            await self._flush()

    async def _flush(self) -> None:
        if not self._pending:
            return
        batch, self._pending = self._pending, []
        merged: list[tuple[str, str]] = []
        for kind, text in batch:
            if kind == "delta" and merged and merged[-1][0] == "delta":
                merged[-1] = ("delta", merged[-1][1] + text)
            else:
                merged.append((kind, text))
        try:
            async with AsyncSession(self.engine) as s:
                if not self._started:
                    self._started = True
                    earlier = await s.execute(
                        sa.select(_TABLE.c.id)
                        .where(_TABLE.c.run_id == self.run_id, _TABLE.c.agent_id == self.agent_id)
                        .limit(1)
                    )
                    if earlier.first() is not None and merged[0][0] != "reset":
                        merged.insert(0, ("reset", ""))
                for kind, text in merged:
                    s.add(
                        SystemRunDelta(
                            run_id=self.run_id, agent_id=self.agent_id, kind=kind, text=text
                        )
                    )
                await s.commit()
            wakeup.notify(self.run_id)
        except Exception:
            logger.warning(
                "runtime.deltas.write_failed", run_id=str(self.run_id), agent=self.agent_id
            )


async def after(session: AsyncSession, run_id: uuid.UUID, cursor: int) -> list[Any]:
    """The rows of a run written after *cursor* (a delta id), oldest first."""
    result = await session.execute(
        sa.select(SystemRunDelta)
        .where(_TABLE.c.run_id == run_id, _TABLE.c.id > cursor)
        .order_by(_TABLE.c.id)
    )
    return list(result.scalars())


async def draft(session: AsyncSession, run_id: uuid.UUID, agent_id: str) -> tuple[str, int]:
    """One agent's draft so far (text since its last reset) and the id of the run's latest row."""
    result = await session.execute(
        sa.select(_TABLE.c.id, _TABLE.c.agent_id, _TABLE.c.kind, _TABLE.c.text)
        .where(_TABLE.c.run_id == run_id)
        .order_by(_TABLE.c.id)
    )
    parts: list[str] = []
    last = 0
    for row_id, owner, kind, text in result.all():
        last = int(row_id)
        if owner != agent_id:
            continue
        if kind == "reset":
            parts.clear()
        else:
            parts.append(text)
    return "".join(parts), last


async def running_agent(session: AsyncSession, run_id: uuid.UUID) -> str | None:
    """The agent a running run is inside: the last one started that has not completed."""
    from tuvl.runtime.models import SystemRunEvent

    table = SystemRunEvent.__table__  # type: ignore[attr-defined]
    result = await session.execute(
        sa.select(table.c.type, table.c.agent_id)
        .where(table.c.run_id == run_id, table.c.type.in_(("agent_started", "agent_completed")))
        .order_by(table.c.seq.desc())
        .limit(1)
    )
    row = result.first()
    return str(row[1]) if row is not None and row[0] == "agent_started" else None


_last_sweep = float("-inf")


async def sweep(session: AsyncSession) -> int:
    """Remove drafts nobody needs any more: a finished run's after a short grace (a client may still be
    reading the last pieces), and any older than a day (a run that never finished). Runs at most once a
    minute."""
    global _last_sweep
    now = time.monotonic()
    if now - _last_sweep < _SWEEP_EVERY:
        return 0
    _last_sweep = now
    stamp = datetime.now(UTC)
    ended = sa.select(_RUNS.c.id).where(_RUNS.c.status.in_(sorted(queue.TERMINAL_STATUSES)))
    result = await session.execute(
        sa.delete(_TABLE).where(
            sa.or_(
                _TABLE.c.created_at < stamp - MAX_AGE,
                sa.and_(_TABLE.c.created_at < stamp - GRACE, _TABLE.c.run_id.in_(ended)),
            )
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


queue.SWEEPS.append(sweep)
