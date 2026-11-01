"""The ``parallel`` engine: different read-only agents at the same time, joined into one step."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl.contract.schema import WorkflowDocument
from tuvl.runtime import journal, queue
from tuvl.runtime.models import SystemRun
from tuvl.runtime.queue import Worker
from tuvl.runtime.runner import Runner, workflow_hash


def branch(name: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": name,
        "engine": "tool",
        "inputs": {"key": "str"},
        "outputs": {name: "int"},
        "tool": {
            "use": "http",
            "method": "GET",
            "url": f"https://api.test/{name}/{{{{ key }}}}",
            "map": {name: "response.body.value"},
        },
        **extra,
    }


def doc(
    *names: str, on_error: str = "fail", routes: dict[str, str] | None = None, **agent: Any
) -> WorkflowDocument:
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "gather_all"},
            "spec": {
                "trigger": {"input": {"key": "str"}},
                "agents": [
                    {
                        "id": "gather",
                        "description": "Look everything up at once",
                        "engine": "parallel",
                        "inputs": {"key": "str"},
                        "outputs": dict.fromkeys(names, "int"),
                        "parallel": {"branches": [branch(n) for n in names], "on_error": on_error},
                        "routes": {"default": "END", "error": "END.failed", **(routes or {})},
                        **agent,
                    }
                ],
                "outputs": {
                    "default": {"body": {n: "{{ " + n + " }}" for n in names}},
                    "partial": {"status": 207, "body": {n: "{{ " + n + " }}" for n in names}},
                    "failed": {"status": 500},
                },
            },
        }
    )


class Api:
    """``/<name>/<key>`` answers ``len(name)``; ``bad`` fails fast, ``slow`` takes a second."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.peak = 0
        self.finished: list[str] = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.split("/")[1]
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(1.0 if name == "slow" else 0.2)
            if name == "bad":
                return httpx.Response(500)
            self.finished.append(name)
            return httpx.Response(200, json={"value": len(name)})
        finally:
            self.in_flight -= 1


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Api:
    fake = Api()
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    monkeypatch.setattr("tuvl.core.infra.http_client.get_http_client", lambda timeout=30.0: client)
    return fake


async def run_it(db: AsyncEngine, workflow: WorkflowDocument) -> tuple[SystemRun, list[Any]]:
    runner = Runner(db, {"gather_all": workflow})
    async with AsyncSession(db) as s:
        run_id = await queue.enqueue(
            s,
            workflow="gather_all",
            workflow_hash=workflow_hash(workflow),
            trigger="test",
            input={"key": "k"},
        )
        await s.commit()
    worker = Worker(db, runner, owner="w")
    await worker.claim_some()
    await worker.drain()
    async with AsyncSession(db) as s:
        run = await s.get(SystemRun, run_id)
        assert run is not None
        return run, list(await journal.events(s, run_id))


async def test_branches_run_at_the_same_time_and_their_outputs_join(
    pg_engine: AsyncEngine, api: Api
) -> None:
    run, events = await run_it(pg_engine, doc("crm", "sanctions", "kb"))
    assert run.status == "completed", run.error
    assert run.output == {"status": 200, "body": {"crm": 3, "sanctions": 9, "kb": 2}}
    assert api.peak == 3  # all three in flight together
    types = [e.type for e in events]
    assert types.count("parallel_branch") == 3
    assert types.index("parallel_started") < types.index("parallel_finished")
    started = next(e for e in events if e.type == "parallel_started")
    assert started.payload["branches"] == ["crm", "sanctions", "kb"]
    tagged = {e.payload["branch"] for e in events if e.type == "tool_call"}
    assert tagged == {"crm", "sanctions", "kb"}  # each branch's own events say which branch
    seqs = [e.seq for e in events]
    assert seqs == sorted(set(seqs))  # interleaved, yet numbered once each


async def test_concurrency_limits_branches_in_flight(pg_engine: AsyncEngine, api: Api) -> None:
    workflow = doc("crm", "sanctions", "kb")
    workflow.spec.agents[0].parallel.concurrency = 2  # type: ignore[union-attr]
    run, _ = await run_it(pg_engine, workflow)
    assert run.status == "completed"
    assert api.peak == 2


async def test_a_failed_branch_fails_the_step_and_stops_the_others(
    pg_engine: AsyncEngine, api: Api
) -> None:
    run, events = await run_it(pg_engine, doc("bad", "slow", "crm"))
    assert run.end_name == "failed"
    done = next(e for e in events if e.type == "agent_completed")
    assert done.payload["error_type"] == "parallel_branch_failed"
    assert "branch 'bad'" in done.payload["message"]
    await asyncio.sleep(0.1)
    assert "slow" not in api.finished  # cancelled before its second was up


async def test_collect_reports_partial_and_leaves_the_failed_outputs_null(
    pg_engine: AsyncEngine, api: Api
) -> None:
    workflow = doc("crm", "bad", "kb", on_error="collect", routes={"partial": "END.partial"})
    for agent in (workflow.spec.agents[0],):
        agent.outputs = {"crm": "int", "bad": "int?", "kb": "int"}  # type: ignore[assignment]
    run, events = await run_it(pg_engine, workflow)
    assert run.status == "completed" and run.end_name == "partial", run.error
    assert run.output == {"status": 207, "body": {"crm": 3, "bad": None, "kb": 2}}
    branches = {e.payload["branch"]: e.payload for e in events if e.type == "parallel_branch"}
    assert branches["bad"]["ok"] is False and branches["crm"]["ok"] is True
    assert "returned 500" in branches["bad"]["reason"]


async def test_the_steps_timeout_takes_every_branch_down(pg_engine: AsyncEngine, api: Api) -> None:
    workflow = doc("slow", "crm", routes={"timeout": "END.failed"}, budget={"timeout": "300ms"})
    run, events = await run_it(pg_engine, workflow)
    assert run.end_name == "failed"
    done = next(e for e in events if e.type == "agent_completed")
    assert done.payload["signal"] == "timeout"
    await asyncio.sleep(1.3)
    assert "slow" not in api.finished and api.in_flight == 0  # nothing left running


async def test_many_runs_at_once_finish_and_leak_nothing(pg_engine: AsyncEngine, api: Api) -> None:
    workflow = doc("crm", "sanctions", "kb")
    runner = Runner(pg_engine, {"gather_all": workflow})
    ids = []
    async with AsyncSession(pg_engine) as s:
        for _ in range(30):
            ids.append(
                await queue.enqueue(
                    s,
                    workflow="gather_all",
                    workflow_hash=workflow_hash(workflow),
                    trigger="test",
                    input={"key": "k"},
                )
            )
        await s.commit()
    worker = Worker(pg_engine, runner, owner="w", concurrency=10)
    while await worker.claim_some():
        await worker.drain()
    async with AsyncSession(pg_engine) as s:
        runs = [await s.get(SystemRun, i) for i in ids]
        batches = [list(await journal.events(s, i)) for i in ids]
    assert all(r is not None and r.status == "completed" for r in runs)
    for events in batches:
        seqs = [e.seq for e in events]
        assert seqs == sorted(set(seqs))
        assert [e.type for e in events].count("parallel_branch") == 3
    assert api.peak > 3  # runs overlapped with each other as well as inside the step
    assert api.in_flight == 0
    async with pg_engine.connect() as conn:  # every branch session was closed
        busy = (
            await conn.execute(
                sa.text(
                    "select count(*) from pg_stat_activity where datname = current_database() "
                    "and pid <> pg_backend_pid() and state like 'idle in transaction%'"
                )
            )
        ).scalar_one()
    assert busy == 0
    stray = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    assert not [t for t in stray if "run_branch" in repr(t)]
