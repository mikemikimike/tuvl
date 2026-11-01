"""Durable run storage (P1.1, spec §14.2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl.runtime.models import (
    RUN_STATUSES,
    TERMINAL_STATUSES,
    SystemApproval,
    SystemRun,
    SystemRunCheckpoint,
    SystemRunEvent,
)

pytestmark = pytest.mark.asyncio


async def _round_trip(engine: AsyncEngine) -> None:
    run_id = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        s.add(
            SystemRun(
                id=run_id,
                workflow="refund_flow",
                workflow_hash="abc",
                trigger="http",
                principal="u1",
                input={"order_id": "o1", "nested": {"k": [1, 2]}},
            )
        )
        s.add(SystemRunEvent(run_id=run_id, seq=1, type="run_queued", payload={"trigger": "http"}))
        s.add(SystemRunEvent(run_id=run_id, seq=2, type="agent_started", agent_id="load_order"))
        s.add(
            SystemRunCheckpoint(
                run_id=run_id,
                seq=3,
                agent_id="load_order",
                signal="default",
                next="triage_refund",
                context={"order_id": "o1", "order": {"total": 40}},
                completed=["load_order"],
            )
        )
        s.add(
            SystemApproval(
                run_id=run_id,
                agent_id="approval",
                kind="human",
                payload={"title": "Refund o1"},
                required_group="support_manager",
                expires_at=datetime.now(UTC) + timedelta(hours=48),
            )
        )
        await s.commit()

    async with AsyncSession(engine) as s:
        run = await s.get(SystemRun, run_id)
        assert run is not None
        assert run.status == "queued" and run.next_seq == 1 and run.claims == 0
        assert run.input["nested"] == {"k": [1, 2]}
        events = (
            await s.exec(
                sa.select(SystemRunEvent)
                .where(SystemRunEvent.run_id == run_id)
                .order_by(SystemRunEvent.seq)
            )  # type: ignore[call-overload]
        ).all()
        assert [e[0].type for e in events] == ["run_queued", "agent_started"]
        cp = await s.get(SystemRunCheckpoint, (run_id, 3))
        assert (
            cp is not None and cp.completed == ["load_order"] and cp.context["order"]["total"] == 40
        )
        approval = (await s.exec(sa.select(SystemApproval))).one()[0]  # type: ignore[call-overload]
        assert approval.status == "pending" and approval.kind == "human"


async def test_round_trip_sqlite(sqlite_engine: AsyncEngine) -> None:
    await _round_trip(sqlite_engine)


async def test_round_trip_postgres(pg_engine: AsyncEngine) -> None:
    await _round_trip(pg_engine)


async def test_postgres_uses_jsonb_and_claim_index(pg_engine: AsyncEngine) -> None:
    async with pg_engine.connect() as conn:
        types = dict(
            (
                await conn.execute(
                    sa.text(
                        "select column_name, data_type from information_schema.columns "
                        "where table_name = 'tuvl_system_runs'"
                    )
                )
            ).all()
        )
        indexes = {
            r[0]
            for r in (
                await conn.execute(
                    sa.text("select indexname from pg_indexes where tablename = 'tuvl_system_runs'")
                )
            ).all()
        }
    assert types["input"] == "jsonb"
    assert types["lease_expires_at"] == "timestamp with time zone"
    assert "ix_tuvl_runs_claim" in indexes


async def test_event_sequence_is_unique_per_run(pg_engine: AsyncEngine) -> None:
    run_id = uuid.uuid4()
    async with AsyncSession(pg_engine) as s:
        s.add(SystemRunEvent(run_id=run_id, seq=1, type="run_queued"))
        await s.commit()
    with pytest.raises(sa.exc.IntegrityError):
        async with AsyncSession(pg_engine) as s:
            s.add(SystemRunEvent(run_id=run_id, seq=1, type="run_started"))
            await s.commit()


async def test_status_vocabulary() -> None:
    assert set(RUN_STATUSES) >= TERMINAL_STATUSES
    assert "queued" not in TERMINAL_STATUSES and "waiting_human" not in TERMINAL_STATUSES
