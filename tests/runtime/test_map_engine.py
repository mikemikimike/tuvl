"""The ``map`` engine (TD-52): a child workflow per list item, bounded concurrency, per-item runs."""

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


def child_doc(
    name: str = "score_item", agents: list[dict[str, Any]] | None = None, item_type: str = "str"
) -> WorkflowDocument:
    fetch = {
        "id": "fetch",
        "description": "Fetch the item's score",
        "engine": "tool",
        "inputs": {"item": item_type},
        "outputs": {"score": "int"},
        "tool": {
            "use": "http",
            "method": "GET",
            "url": "https://api.test/items/{{ item }}",
            "map": {"score": "response.body.score"},
        },
        "routes": {"default": "END", "error": "END.failed"},
    }
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": name},
            "spec": {
                "trigger": {"input": {"item": item_type}},
                "agents": agents or [fetch],
                "outputs": {"default": {"body": "{{ score }}"}, "failed": {"status": 502}},
            },
        }
    )


def parent_doc(**map_params: Any) -> WorkflowDocument:
    routes = {"default": "END", "error": "END.failed", **map_params.pop("routes", {})}
    params = {"over": "ids", "workflow": "score_item", "as": "item", **map_params}
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "score_all"},
            "spec": {
                "trigger": {"input": {"ids": "list[str]"}},
                "agents": [
                    {
                        "id": "score_each",
                        "description": "Score every item",
                        "engine": "map",
                        "inputs": {"ids": "list[str]"},
                        "outputs": {"scores": "list[json]"},
                        "map": params,
                        "routes": routes,
                    }
                ],
                "outputs": {
                    "default": {"body": "{{ scores }}"},
                    "partial": {"status": 207, "body": "{{ scores }}"},
                    "failed": {"status": 500},
                },
            },
        }
    )


class Api:
    """A fake scoring API: ``/items/<n>`` scores n*10, ``/items/bad`` fails; tracks concurrency."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.in_flight = 0
        self.peak = 0

    async def handle(self, request: httpx.Request) -> httpx.Response:
        item = request.url.path.rsplit("/", 1)[-1]
        self.calls.append(item)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(0.05)
        finally:
            self.in_flight -= 1
        if item == "bad":
            return httpx.Response(500)
        return httpx.Response(200, json={"score": int(item) * 10})


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Api:
    fake = Api()
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    monkeypatch.setattr("tuvl.core.infra.http_client.get_http_client", lambda timeout=30.0: client)
    return fake


async def run_parent(
    db: AsyncEngine,
    parent: WorkflowDocument,
    ids: list[str],
    children: list[WorkflowDocument] | None = None,
) -> tuple[SystemRun, Runner]:
    registry = {"score_all": parent, **{c.metadata.name: c for c in children or [child_doc()]}}
    runner = Runner(db, registry)
    async with AsyncSession(db) as s:
        run_id = await queue.enqueue(
            s,
            workflow="score_all",
            workflow_hash=workflow_hash(parent),
            trigger="test",
            input={"ids": ids},
        )
        await s.commit()
    worker = Worker(db, runner, owner="w")
    await worker.claim_some()
    await worker.drain()
    async with AsyncSession(db) as s:
        run = await s.get(SystemRun, run_id)
        assert run is not None
        return run, runner


async def children_of(db: AsyncEngine, run: SystemRun) -> list[SystemRun]:
    async with AsyncSession(db) as s:
        rows = await s.exec(  # type: ignore[call-overload]
            sa.select(SystemRun)
            .where(SystemRun.parent_run_id == run.id)
            .order_by(SystemRun.trigger)
        )
        return list(rows.scalars().all())


async def event_types(db: AsyncEngine, run: SystemRun) -> list[str]:
    async with AsyncSession(db) as s:
        return [e.type for e in await journal.events(s, run.id)]


async def test_maps_a_child_over_every_item(pg_engine: AsyncEngine, api: Api) -> None:
    run, _ = await run_parent(pg_engine, parent_doc(), ["1", "2", "3"])
    assert run.status == "completed", run.error
    assert run.output == {"status": 200, "body": [10, 20, 30]}  # in input order
    kids = await children_of(pg_engine, run)
    assert [k.trigger for k in kids] == [f"child:score_each:{i}" for i in range(3)]
    assert all(k.status == "completed" and k.workflow == "score_item" for k in kids)
    types = await event_types(pg_engine, run)
    assert types.count("map_item") == 3 and "map_started" in types and "map_finished" in types


async def test_concurrency_is_bounded(pg_engine: AsyncEngine, api: Api) -> None:
    run, _ = await run_parent(pg_engine, parent_doc(concurrency=2), [str(i) for i in range(1, 7)])
    assert run.status == "completed"
    assert run.output is not None and run.output["body"] == [10, 20, 30, 40, 50, 60]
    assert api.peak == 2  # in parallel, but never more than asked


async def test_the_first_failure_stops_new_items(pg_engine: AsyncEngine, api: Api) -> None:
    run, _ = await run_parent(pg_engine, parent_doc(concurrency=1), ["1", "bad", "3", "4", "5"])
    assert run.end_name == "failed"
    done = await completion(pg_engine, run)
    assert done["error_type"] == "map_item_failed"
    assert "item 1 failed" in done["message"] and "3 not started" in done["message"]
    assert api.calls == ["1", "bad"]  # items 3-5 never started
    assert len(await children_of(pg_engine, run)) == 2


async def test_collect_reports_partial_with_nulls(pg_engine: AsyncEngine, api: Api) -> None:
    run, _ = await run_parent(
        pg_engine,
        parent_doc(on_error="collect", routes={"partial": "END.partial"}),
        ["1", "bad", "3"],
    )
    assert run.status == "completed" and run.end_name == "partial"
    assert run.output == {"status": 207, "body": [10, None, 30]}
    assert sorted(api.calls) == ["1", "3", "bad"]  # every item ran
    reasons = [e.payload["reason"] for e in await _events(pg_engine, run) if e.type == "map_item"]
    failed = next(r for r in reasons if r)
    assert (
        "status 502" in failed and "returned 500" in failed
    )  # the child's own error, not just its end


async def test_collect_without_a_partial_route_still_completes(
    pg_engine: AsyncEngine, api: Api
) -> None:
    run, _ = await run_parent(pg_engine, parent_doc(on_error="collect"), ["bad", "2"])
    assert run.end_name == "default"
    assert run.output is not None and run.output["body"] == [None, 20]


async def test_a_list_over_max_items_fails_before_any_item(
    pg_engine: AsyncEngine, api: Api
) -> None:
    run, _ = await run_parent(pg_engine, parent_doc(max_items=2), ["1", "2", "3"])
    assert run.end_name == "failed"
    assert (await completion(pg_engine, run))["error_type"] == "map_too_many_items"
    assert api.calls == []


async def test_an_empty_list_completes_with_an_empty_result(
    pg_engine: AsyncEngine, api: Api
) -> None:
    run, _ = await run_parent(pg_engine, parent_doc(), [])
    assert run.output == {"status": 200, "body": []}


async def test_an_item_the_child_rejects_is_a_failed_item(pg_engine: AsyncEngine, api: Api) -> None:
    # the child takes an int; "oops" cannot be one, so that item fails and the others still run
    parent = parent_doc(on_error="collect")
    parent.spec.trigger.input = {"ids": "list[json]"}  # type: ignore[assignment]
    parent.spec.agents[0].inputs = {"ids": "list[json]"}  # type: ignore[assignment]
    run, _ = await run_parent(
        pg_engine,
        parent,
        [1, "oops", 3],
        children=[child_doc(item_type="int")],  # type: ignore[list-item]
    )
    assert run.output is not None and run.output["body"] == [10, None, 30]
    reasons = [e.payload["reason"] for e in await _events(pg_engine, run) if e.type == "map_item"]
    assert any("input" in r.lower() or "valid" in r.lower() for r in reasons if r)


async def test_a_workflow_that_maps_itself_is_stopped_by_the_depth_limit(
    pg_engine: AsyncEngine, api: Api
) -> None:
    recur = WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "score_all"},
            "spec": {
                "trigger": {"input": {"ids": "list[json]"}},
                "agents": [
                    {
                        "id": "score_each",
                        "description": "Recurse into every item",
                        "engine": "map",
                        "inputs": {"ids": "list[json]"},
                        "outputs": {"scores": "list[json]"},
                        "map": {"over": "ids", "workflow": "score_all", "as": "ids"},
                        "routes": {"default": "END", "error": "END.failed"},
                    }
                ],
                "outputs": {"default": {"body": "{{ scores }}"}, "failed": {"status": 500}},
            },
        }
    )
    run, _ = await run_parent(pg_engine, recur, [[[[[]]]]], children=[])  # type: ignore[list-item]
    assert run.end_name == "failed"  # the recursion is cut, not followed forever
    async with AsyncSession(pg_engine) as s:
        total = (await s.exec(sa.select(sa.func.count()).select_from(SystemRun))).one()[0]
    assert total <= 4  # the top run plus at most the levels policy.max_depth allows


async def test_a_rerun_parent_follows_its_children_instead_of_starting_new_ones(
    pg_engine: AsyncEngine, api: Api
) -> None:
    run, runner = await run_parent(pg_engine, parent_doc(), ["1", "2"])
    before = list(api.calls)
    again = await runner.run_child(run.id, "score_item", {"item": "1"}, None, key="score_each:0")
    other = await runner.run_child(run.id, "score_item", {"item": "9"}, None, key="score_each:9")
    kids = await children_of(pg_engine, run)
    assert again.id == kids[0].id  # the same child, not a second one
    assert api.calls == [*before, "9"]  # only the genuinely new key ran
    assert other.id not in {k.id for k in kids[:2]}
    assert len(await children_of(pg_engine, run)) == 3


async def test_a_child_that_waits_for_a_person_is_a_failed_item(
    pg_engine: AsyncEngine, api: Api
) -> None:
    waiting = child_doc(
        "score_item",
        [
            {
                "id": "ask",
                "description": "Ask a person",
                "engine": "human",
                "inputs": {"item": "str"},
                "outputs": {"score": "int"},
                "human": {"title": "Score {{ item }}", "form": {"score": {}}},
                "routes": {"default": "END"},
            }
        ],
    )
    run, _ = await run_parent(pg_engine, parent_doc(on_error="collect"), ["1"], children=[waiting])
    assert run.status == "completed" and run.output is not None
    assert run.output["body"] == [None]
    events = [e for e in await _events(pg_engine, run) if e.type == "map_item"]
    assert "must finish on its own" in events[0].payload["reason"]


async def completion(db: AsyncEngine, run: SystemRun) -> dict[str, Any]:
    """What the map agent reported when it finished: its signal, and the error if it failed."""
    done = [e for e in await _events(db, run) if e.type == "agent_completed"]
    return dict(done[-1].payload)


async def _events(db: AsyncEngine, run: SystemRun) -> list[Any]:
    async with AsyncSession(db) as s:
        return list(await journal.events(s, run.id))
