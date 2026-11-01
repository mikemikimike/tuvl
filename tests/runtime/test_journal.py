"""The run journal (P1.2)."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl.runtime import journal
from tuvl.runtime.journal import JournalError
from tuvl.runtime.models import SystemRun

pytestmark = pytest.mark.asyncio


class Customer(BaseModel):
    name: str
    ssn: str


async def new_run(engine: AsyncEngine) -> uuid.UUID:
    run_id = uuid.uuid4()
    async with AsyncSession(engine) as s:
        s.add(SystemRun(id=run_id, workflow="wf", workflow_hash="h", trigger="api"))
        await s.commit()
    return run_id


async def test_events_and_checkpoints_share_one_sequence(engine: AsyncEngine) -> None:
    run_id = await new_run(engine)
    async with AsyncSession(engine) as s:
        assert await journal.append_event(s, run_id, "run_started") == 1
        assert await journal.append_event(s, run_id, "agent_started", agent_id="a") == 2
        cp = await journal.write_checkpoint(
            s, run_id, agent_id="a", signal="default", next="b", context={"x": 1}, completed=["a"]
        )
        assert cp == 3
        assert (
            await journal.append_event(
                s, run_id, "agent_completed", agent_id="a", tokens=12, latency_ms=4.5
            )
            == 4
        )
        await s.commit()
    async with AsyncSession(engine) as s:
        evs = await journal.events(s, run_id)
        assert [(e.seq, e.type) for e in evs] == [
            (1, "run_started"),
            (2, "agent_started"),
            (4, "agent_completed"),
        ]
        assert [e.seq for e in await journal.events(s, run_id, from_seq=3)] == [4]
        latest = await journal.latest_checkpoint(s, run_id)
        assert latest is not None and latest.next == "b" and latest.completed == ["a"]
        run = await s.get(SystemRun, run_id)
        assert run is not None and run.next_seq == 5


async def test_allocate_seqs_takes_a_contiguous_block_or_nothing(engine: AsyncEngine) -> None:
    runs = SystemRun.__table__  # type: ignore[attr-defined]
    run_id = await new_run(engine)
    async with AsyncSession(engine) as s:
        assert await journal.append_event(s, run_id, "run_started") == 1
        allocated = await journal.allocate_seqs(
            s, run_id, 2, values={"tokens_used": 7}, returning=(runs.c.workflow,)
        )
        assert allocated == (2, ("wf",))
        await journal.append_event(s, run_id, "agent_completed", agent_id="a", seq=2)
        await journal.write_checkpoint(
            s, run_id, agent_id="a", signal="default", next="b", context={}, completed=["a"], seq=3
        )
        unmatched = await journal.allocate_seqs(
            s, run_id, 2, where=(runs.c.lease_owner == "nobody",)
        )
        assert unmatched is None
        assert await journal.append_event(s, run_id, "llm_turn") == 4
        await s.commit()
    async with AsyncSession(engine) as s:
        assert await journal.allocate_seqs(s, run_id, 3) == (5, ())
        await s.rollback()  # an allocation rolled back leaves no gap
    async with AsyncSession(engine) as s:
        assert await journal.append_event(s, run_id, "llm_turn") == 5
        await s.commit()
        run = await s.get(SystemRun, run_id)
        assert run is not None and run.next_seq == 6 and run.tokens_used == 7
        assert [e.seq for e in await journal.events(s, run_id)] == [1, 2, 4, 5]


async def test_values_are_stored_as_json_and_secure_fields_redacted(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tuvl.core.models import loader

    monkeypatch.setattr(loader, "SECURE_FIELDS", {"ssn"})
    run_id = await new_run(engine)
    ctx = {
        "customer": Customer(name="Ada", ssn="123"),
        "when": dt.date(2026, 10, 8),
        "ref": uuid.UUID(int=1),
    }
    async with AsyncSession(engine) as s:
        await journal.append_event(s, run_id, "tool_result", payload={"result": ctx})
        await journal.write_checkpoint(
            s, run_id, agent_id="a", signal="default", next="END", context=ctx, completed=["a"]
        )
        await s.commit()
    async with AsyncSession(engine) as s:
        (event,) = await journal.events(s, run_id)
        cp = await journal.latest_checkpoint(s, run_id)
    assert event.payload["result"]["customer"] == {"name": "Ada", "ssn": "*****"}
    # Checkpoints keep real values (resume state) and redact on export.
    assert cp is not None and cp.context["customer"]["ssn"] == "123"
    async with AsyncSession(engine) as s:
        exported = await journal.export_run(s, run_id)
    assert exported["checkpoints"][0]["context"]["customer"]["ssn"] == "*****"
    assert cp.context["when"] == "2026-10-08"
    assert cp.context["ref"] == "00000000-0000-0000-0000-000000000001"


async def test_large_payloads_are_truncated(engine: AsyncEngine) -> None:
    run_id = await new_run(engine)
    async with AsyncSession(engine) as s:
        await journal.append_event(
            s, run_id, "tool_result", payload={"blob": "x" * (journal.MAX_EVENT_PAYLOAD_BYTES + 10)}
        )
        await s.commit()
        (event,) = await journal.events(s, run_id)
    assert (
        event.payload["_truncated"] is True
        and event.payload["bytes"] > journal.MAX_EVENT_PAYLOAD_BYTES
    )


async def test_rejects_unknown_types_and_runs(sqlite_engine: AsyncEngine) -> None:
    run_id = await new_run(sqlite_engine)
    async with AsyncSession(sqlite_engine) as s:
        with pytest.raises(JournalError, match="unknown journal event type 'step'"):
            await journal.append_event(s, run_id, "step")
        with pytest.raises(JournalError, match="does not exist"):
            await journal.append_event(s, uuid.uuid4(), "run_started")


async def test_concurrent_writers_get_unique_contiguous_sequence(pg_engine: AsyncEngine) -> None:
    run_id = await new_run(pg_engine)

    async def write(i: int) -> int:
        async with AsyncSession(pg_engine) as s:
            seq = await journal.append_event(s, run_id, "llm_turn", payload={"i": i})
            await s.commit()
            return seq

    seqs = await asyncio.gather(*(write(i) for i in range(40)))
    assert sorted(seqs) == list(range(1, 41))


async def test_export_import_round_trip(engine: AsyncEngine) -> None:
    run_id = await new_run(engine)
    async with AsyncSession(engine) as s:
        await journal.append_event(s, run_id, "run_started", payload={"input": {"a": 1}})
        await journal.write_checkpoint(
            s, run_id, agent_id="a", signal="ok", next="END.done", context={"a": 1}, completed=["a"]
        )
        await journal.append_event(s, run_id, "run_completed", payload={"end": "done"})
        await s.commit()
    async with AsyncSession(engine) as s:
        exported = await journal.export_run(s, run_id)
        new_id = await journal.import_run(s, exported)
        await s.commit()
    async with AsyncSession(engine) as s:
        again = await journal.export_run(s, new_id)
        # Imported runs continue the sequence after the recorded entries.
        assert await journal.append_event(s, new_id, "resumed") == 4
    assert new_id != run_id
    assert again["run"].pop("id") != exported["run"].pop("id")
    assert again == exported
    assert [e["type"] for e in exported["events"]] == ["run_started", "run_completed"]


async def test_import_rejects_foreign_documents(sqlite_engine: AsyncEngine) -> None:
    async with AsyncSession(sqlite_engine) as s:
        with pytest.raises(JournalError, match="not a tuvl.journal/v1 document"):
            await journal.import_run(s, {"format": "other"})
