"""The run journal (spec §14.2, Appendix C.3).

Events and checkpoints share one per-run sequence, allocated with an atomic
``UPDATE … RETURNING`` on the run row, so concurrent writers (the runner, a
supervisor, an operator request) can never interleave or collide. Values are
stored as JSON.

``secure: true`` model fields are redacted where data leaves the system:
event payloads (streamed to SSE and Insight) at write time, checkpoints on
export. Checkpoints themselves keep the real values — they are the state a
paused or crashed run resumes from, and the same values already live in the
model's own tables. A whole run exports to a JSON document — the format
pinned fixtures and replay use.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession

from tuvl.runtime import wakeup
from tuvl.runtime.models import SystemRun, SystemRunCheckpoint, SystemRunEvent

EVENT_TYPES: frozenset[str] = frozenset(
    {
        "run_queued",
        "run_started",
        "agent_started",
        "agent_completed",
        "signal",
        "llm_turn",
        "tool_call",
        "tool_result",
        "memory_recalled",
        "memory_written",
        "memory_compacted",
        "map_started",
        "map_item",
        "map_finished",
        "parallel_started",
        "parallel_branch",
        "parallel_finished",
        "decision",
        "judge_verdict",
        "supervisor",
        "approval_requested",
        "approval_decided",
        "paused",
        "resumed",
        "checkpoint",
        "compensation_started",
        "compensation_completed",
        "run_completed",
        "run_failed",
        "run_aborted",
    }
)

#: Journal events a declared webhook can subscribe to (see :mod:`tuvl.webhooks`).
WEBHOOK_EVENTS: frozenset[str] = frozenset(
    {"run_completed", "run_failed", "run_aborted", "approval_requested", "agent_completed"}
)

#: Event payloads larger than this are replaced by a size marker — the journal
#: is an audit trail, not a blob store. Checkpoints are never truncated (they
#: are the resume state).
MAX_EVENT_PAYLOAD_BYTES = 64 * 1024

EXPORT_FORMAT = "tuvl.journal/v1"


class JournalError(RuntimeError):
    pass


def to_json(value: Any) -> Any:
    """Pydantic models, dates, UUIDs, decimals … → JSON-compatible data."""
    return to_jsonable_python(value, fallback=str)


def redact(data: Mapping[str, Any]) -> dict[str, Any]:
    """Replace every ``secure: true`` model field (at any depth) with ``*****``.
    Expects JSON data (:func:`to_json` first) so fields inside models are seen."""
    from tuvl.core.engine.masking import mask_secure_data
    from tuvl.core.models.loader import SECURE_FIELDS

    return mask_secure_data(dict(data), SECURE_FIELDS) if SECURE_FIELDS else dict(data)


async def _execute(session: AsyncSession, statement: Any) -> Any:
    # SQLModel's AsyncSession.execute warns in favour of .exec(); the journal
    # issues Core statements (UPDATE … RETURNING), so call SQLAlchemy's directly.
    return await AsyncSession.execute(session, statement)


async def allocate_seqs(
    session: AsyncSession,
    run_id: uuid.UUID,
    count: int,
    *,
    where: Sequence[Any] = (),
    values: Mapping[str, Any] | None = None,
    returning: Sequence[Any] = (),
) -> tuple[int, tuple[Any, ...]] | None:
    """Allocate *count* consecutive sequence numbers in one ``UPDATE … RETURNING``
    that also sets *values* on the run row, only where *where* holds too.

    Returns the first number and the *returning* columns, or ``None`` when no row
    matched. The caller must use every number in the same transaction (or roll it
    back): an allocated number without its event or checkpoint is a gap."""
    table = SystemRun.__table__  # type: ignore[attr-defined]
    result = await _execute(
        session,
        sa.update(table)
        .where(table.c.id == run_id, *where)
        .values(next_seq=table.c.next_seq + count, **(values or {}))
        .returning(table.c.next_seq, *returning),
    )
    row = result.first()
    if row is None:
        return None
    return int(row[0]) - count, tuple(row[1:])


async def allocate_seq(session: AsyncSession, run_id: uuid.UUID) -> int:
    allocated = await allocate_seqs(session, run_id, 1)
    if allocated is None:
        raise JournalError(f"run {run_id} does not exist")
    return allocated[0]


async def append_event(
    session: AsyncSession,
    run_id: uuid.UUID,
    type: str,
    *,
    agent_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
    tokens: int = 0,
    latency_ms: float | None = None,
    seq: int | None = None,
    workflow: str | None = None,
) -> int:
    """Append one event and return its sequence number. The caller commits.

    *seq* is a number already taken with :func:`allocate_seqs` in this transaction.
    *workflow* is the run's workflow, when the caller knows it (saves a lookup)."""
    if type not in EVENT_TYPES:
        raise JournalError(f"unknown journal event type {type!r}")
    data = redact(to_json(payload or {}))
    size = len(json.dumps(data, separators=(",", ":")))
    if size > MAX_EVENT_PAYLOAD_BYTES:
        data = {"_truncated": True, "bytes": size}
    if seq is None:
        seq = await allocate_seq(session, run_id)
    session.add(
        SystemRunEvent(
            run_id=run_id,
            seq=seq,
            type=type,
            agent_id=agent_id,
            payload=data,
            tokens=tokens,
            latency_ms=latency_ms,
        )
    )
    wakeup.mark(session, run_id)
    if type in WEBHOOK_EVENTS:
        from tuvl import webhooks

        await webhooks.record(session, run_id, type, seq, agent_id, workflow=workflow)
    return seq


async def write_checkpoint(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    agent_id: str,
    signal: str,
    next: str,
    context: Mapping[str, Any],
    completed: Sequence[str],
    seq: int | None = None,
) -> int:
    """Record the run context after *agent_id* finished (unredacted: it is the
    resume state). The caller commits — together with the agent's database
    writes under ``per_agent`` transactions. *seq* as for :func:`append_event`."""
    if seq is None:
        seq = await allocate_seq(session, run_id)
    session.add(
        SystemRunCheckpoint(
            run_id=run_id,
            seq=seq,
            agent_id=agent_id,
            signal=signal,
            next=next,
            context=to_json(context),
            completed=list(completed),
        )
    )
    return seq


async def events(
    session: AsyncSession, run_id: uuid.UUID, *, from_seq: int = 0
) -> list[SystemRunEvent]:
    """Events with ``seq >= from_seq`` in order (SSE resume uses *from_seq*)."""
    result = await _execute(
        session,
        sa.select(SystemRunEvent)
        .where(SystemRunEvent.run_id == run_id, SystemRunEvent.seq >= from_seq)  # type: ignore[arg-type]
        .order_by(SystemRunEvent.seq),  # type: ignore[arg-type]
    )
    return list(result.scalars().all())


async def latest_checkpoint(session: AsyncSession, run_id: uuid.UUID) -> SystemRunCheckpoint | None:
    result = await _execute(
        session,
        sa.select(SystemRunCheckpoint)
        .where(SystemRunCheckpoint.run_id == run_id)  # type: ignore[arg-type]
        .order_by(SystemRunCheckpoint.seq.desc())  # type: ignore[attr-defined]
        .limit(1),
    )
    checkpoint: SystemRunCheckpoint | None = result.scalars().first()
    return checkpoint


# ── Export / import (fixtures, replay) ───────────────────────────────────────

_RUN_FIELDS = (
    "workflow",
    "workflow_hash",
    "status",
    "trigger",
    "end_name",
    "input",
    "output",
    "error",
    "tokens_used",
)


async def export_run(session: AsyncSession, run_id: uuid.UUID) -> dict[str, Any]:
    """The whole run as one JSON document (principal and leases left out)."""
    run = await session.get(SystemRun, run_id)
    if run is None:
        raise JournalError(f"run {run_id} does not exist")
    checkpoints = await _execute(
        session,
        sa.select(SystemRunCheckpoint)
        .where(SystemRunCheckpoint.run_id == run_id)  # type: ignore[arg-type]
        .order_by(SystemRunCheckpoint.seq),  # type: ignore[arg-type]
    )
    return {
        "format": EXPORT_FORMAT,
        "run": {"id": str(run.id), **{f: to_json(getattr(run, f)) for f in _RUN_FIELDS}},
        "events": [
            {
                "seq": e.seq,
                "type": e.type,
                "agent_id": e.agent_id,
                "payload": e.payload,
                "tokens": e.tokens,
                "latency_ms": e.latency_ms,
            }
            for e in await events(session, run_id)
        ],
        "checkpoints": [
            {
                "seq": c.seq,
                "agent_id": c.agent_id,
                "signal": c.signal,
                "next": c.next,
                "context": redact(c.context),
                "completed": c.completed,
            }
            for c in checkpoints.scalars().all()
        ],
    }


async def import_run(session: AsyncSession, document: Mapping[str, Any]) -> uuid.UUID:
    """Load an exported run under a fresh id (fixtures must not collide with
    live runs). The caller commits."""
    if document.get("format") != EXPORT_FORMAT:
        raise JournalError(f"not a {EXPORT_FORMAT} document")
    run_id = uuid.uuid4()
    src = document["run"]
    entries = [*document.get("events", []), *document.get("checkpoints", [])]
    next_seq = max((int(e["seq"]) for e in entries), default=0) + 1
    session.add(
        SystemRun(
            id=run_id,
            next_seq=next_seq,
            **{f: src.get(f) for f in _RUN_FIELDS if src.get(f) is not None},
        )
    )
    await session.flush()
    for e in document.get("events", []):
        session.add(SystemRunEvent(run_id=run_id, **e))
    for c in document.get("checkpoints", []):
        session.add(SystemRunCheckpoint(run_id=run_id, **c))
    return run_id
