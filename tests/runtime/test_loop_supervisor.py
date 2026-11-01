# ruff: noqa: F811 — fixtures are imported by name from test_loop_engine
"""Supervisor rules and live operator control inside loops (P2.7)."""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.runtime.test_loop_engine import (  # noqa: F401 — fixtures
    Script,
    agents,
    call,
    drive,
    events,
    get,
    ledger,
    model,
    start,
    workflows,
)
from tuvl.contract.schema import WorkflowDocument
from tuvl.runtime import queue
from tuvl.runtime.loop import resume_paused
from tuvl.runtime.models import SystemRun

BUDGET = {"max_iterations": 8, "max_tokens": 10_000, "max_tool_calls": 8, "timeout": "30s"}


def supervised(*rules: dict[str, Any], **extra: Any) -> dict[str, WorkflowDocument]:
    wfs = workflows(tools=[{"agent": "lookup_order"}, {"agent": "issue_refund"}], budget=BUDGET)
    doc = wfs["wf"].model_dump(mode="json", exclude_none=True)
    doc["spec"]["agents"][0]["loop"]["supervisor"] = {"rules": list(rules), **extra}
    return {"wf": WorkflowDocument.model_validate(doc)}


def finish(note: str = "done") -> list[Any]:
    return [call("finish", outcome="resolved", resolution=note)]


async def test_tool_repeated_aborts(pg_engine: AsyncEngine, model: Any) -> None:
    model(*[[call("lookup_order", order_id="o-1")]] * 4)
    run = await start(pg_engine, supervised({"when": "tool_repeated", "count": 2, "then": "abort"}))
    assert run.end_name == "failed"
    done = (await events(pg_engine, run.id, "agent_completed"))[0]
    assert done["signal"] == "aborted" and "lookup_order called 2×" in done["message"]
    sup = await events(pg_engine, run.id, "supervisor")
    assert sup[0]["rule"] == "tool_repeated" and sup[0]["action"] == "abort"


async def test_steer_injects_a_message(pg_engine: AsyncEngine, model: Any) -> None:
    script = model(
        [call("lookup_order", order_id="o-1")], [call("lookup_order", order_id="o-2")], finish()
    )
    run = await start(
        pg_engine,
        supervised(
            {"when": "iteration_reached", "gte": 2, "then": "steer"}, steer_message="Wrap up now."
        ),
    )
    assert run.status == "completed"
    assert {"role": "user", "content": "Wrap up now."} in script.seen[-1]


async def test_effect_count_and_pause_resume(pg_engine: AsyncEngine, model: Any) -> None:
    script = model(
        [call("issue_refund", amount=10)], [call("issue_refund", amount=20)], finish("two refunds")
    )
    wfs = supervised({"when": "effect_count", "effect": "write", "count": 2, "then": "pause"})
    run = await start(pg_engine, wfs)
    assert run.status == "paused" and await ledger(pg_engine) == ["refund:10", "refund:20"]
    async with AsyncSession(pg_engine) as s:
        assert await resume_paused(s, run.id) == 1
        assert await queue.requeue(s, run.id)
        await s.commit()
    await drive(pg_engine, wfs, owner="w2")
    final = await get(pg_engine, run.id)
    assert final.status == "completed" and final.output["body"] == "two refunds"  # type: ignore[index]
    assert len(script.seen) == 3  # the loop continued; earlier turns were not replayed
    assert final.tokens_used == 300


async def _control(db: AsyncEngine, run_id: Any, control: dict[str, Any]) -> None:
    async with AsyncSession(db) as s:
        await s.exec(sa.update(SystemRun).where(SystemRun.id == run_id).values(control=control))  # type: ignore[call-overload,arg-type]
        await s.commit()


class Operator(Script):
    """Leaves an operator request on the run during the first model turn."""

    db: AsyncEngine
    request: dict[str, Any]

    async def __call__(self, **kwargs: Any) -> Any:
        if not self.seen:
            async with AsyncSession(self.db) as s:
                run_id = (
                    await s.exec(sa.select(SystemRun.id).order_by(SystemRun.created_at.desc()))
                ).first()  # type: ignore[call-overload,arg-type]
            await _control(self.db, run_id[0], self.request)
        return await super().__call__(**kwargs)


@pytest.mark.parametrize(
    ("request_", "status", "end"),
    [
        ({"action": "steer", "message": "check o-2 instead"}, "completed", "default"),
        ({"action": "pause"}, "paused", None),
        ({"action": "abort"}, "completed", "failed"),
    ],
)
async def test_operator_control_mid_loop(
    pg_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    request_: dict[str, Any],
    status: str,
    end: str | None,
) -> None:
    from tuvl import llm as llm_client

    op = Operator([call("lookup_order", order_id="o-1")], finish())
    op.db, op.request = pg_engine, request_
    monkeypatch.setattr(llm_client, "acompletion", op)
    run = await start(pg_engine, workflows(tools=[{"agent": "lookup_order"}], budget=BUDGET))
    assert run.status == status and run.end_name == end
    if request_["action"] == "steer":
        assert {"role": "user", "content": "[operator] check o-2 instead"} in op.seen[-1]
    if request_["action"] == "abort":
        assert (await events(pg_engine, run.id, "agent_completed"))[0]["signal"] == "aborted"
