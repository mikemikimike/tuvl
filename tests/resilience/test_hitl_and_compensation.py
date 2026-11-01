"""Resilience (P1.11): a human decision made while the worker that asked is
gone is picked up by another worker process; and a failing run compensates
end to end over HTTP."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
import yaml
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.resilience.conftest import PG_URL
from tuvl.api.runs import router
from tuvl.api.triggers import mount_triggers
from tuvl.contract.schema import WorkflowDocument
from tuvl.core.auth.token import mint_token
from tuvl.core.config import settings
from tuvl.runtime import human, queue
from tuvl.runtime.code import AGENT_REGISTRY
from tuvl.runtime.host import RuntimeHost, set_host
from tuvl.runtime.models import SystemRun
from tuvl.runtime.queue import Worker
from tuvl.runtime.runner import Runner, workflow_hash

APPROVAL = {
    "kind": "Workflow",
    "version": "tuvl/v2",
    "metadata": {"name": "approve_flow"},
    "spec": {
        "trigger": {"input": {"amount": "int"}},
        "agents": [
            {
                "id": "approval",
                "description": "lead approves",
                "engine": "human",
                "inputs": {"amount": "int"},
                "outputs": {"ok": "bool"},
                "human": {
                    "title": "Approve {{ amount }}",
                    "required_group": "leads",
                    "route_on": "ok",
                },
                "routes": {"true": "END", "false": "END.no", "error": "END.no"},
            },
        ],
        "outputs": {"default": {"body": "approved {{ amount }}"}, "no": {"status": 409}},
    },
}


async def _wait_for(
    engine: AsyncEngine, run_id: Any, status: str, seconds: float = 30
) -> SystemRun:
    for _ in range(int(seconds * 10)):
        async with AsyncSession(engine) as s:
            run = await s.get(SystemRun, run_id)
        if run is not None and run.status == status:
            return run
        await asyncio.sleep(0.1)
    raise AssertionError(f"run never reached {status!r} (last: {run.status if run else None})")


async def test_human_decision_resumes_on_another_worker_process(
    pg_engine: AsyncEngine, tmp_path: Path
) -> None:
    (tmp_path / "agents").mkdir()
    (tmp_path / "workflow.yaml").write_text(yaml.safe_dump(APPROVAL))
    doc = WorkflowDocument.model_validate(APPROVAL)
    async with AsyncSession(pg_engine) as s:
        run_id = await queue.enqueue(
            s,
            workflow="approve_flow",
            workflow_hash=workflow_hash(doc),
            trigger="test",
            input={"amount": 70},
            principal="requester",
        )
        await s.commit()

    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(Path.cwd()), str(Path.cwd() / "src")])}
    worker_a = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).with_name("worker_proc.py")),
            PG_URL,
            str(tmp_path),
            "worker-a",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        waiting = await _wait_for(pg_engine, run_id, "waiting_human")
        assert waiting.lease_owner is None and waiting.claims == 1
    finally:
        worker_a.send_signal(signal.SIGKILL)  # A is gone before anyone decides
        worker_a.wait(10)

    async with AsyncSession(pg_engine) as s:
        lead = human.Reviewer("lead-1", frozenset({"leads"}), frozenset({"approvals:decide"}))
        await human.decide(
            s, run_id, "approval", {"ok": True}, lead, workflows={"approve_flow": doc}
        )
        await s.commit()

    worker_b = Worker(pg_engine, Runner(pg_engine, {"approve_flow": doc}), owner="worker-b")
    while await worker_b.claim_some():
        await worker_b.drain()
    final = await _wait_for(pg_engine, run_id, "completed")
    assert final.output == {"status": 200, "body": "approved 70"} and final.claims == 2


async def _charge(inp: Any, ctx: Any) -> dict[str, Any]:
    await ctx._engine_ctx.session.execute(
        sa.text("insert into resilience_ledger(entry) values ('charged')")
    )
    return {}


async def _refund(inp: Any, ctx: Any) -> dict[str, Any]:
    await ctx._engine_ctx.session.execute(
        sa.text("insert into resilience_ledger(entry) values ('refunded')")
    )
    return {}


async def _ship(inp: Any, ctx: Any) -> None:
    raise RuntimeError("carrier unavailable")


async def test_failed_run_compensates_end_to_end_over_http(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with pg_engine.begin() as conn:
        await conn.execute(sa.text("drop table if exists resilience_ledger"))
        await conn.execute(
            sa.text("create table resilience_ledger (id serial primary key, entry text)")
        )
    for name, fn in {"charge": _charge, "refund": _refund, "ship": _ship}.items():
        monkeypatch.setitem(AGENT_REGISTRY, name, fn)
    token = mint_token("buyer", [], ["orders:place", "runs:read"], ttl_seconds=60)
    monkeypatch.setattr(settings, "tuvl_dev_mode", False)  # the trigger needs the token
    doc = WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "order", "required_scope": "orders:place"},
            "spec": {
                "trigger": {"http": {"path": "/orders", "method": "POST"}},
                "agents": [
                    {
                        "id": "charge",
                        "description": "take payment",
                        "engine": "code",
                        "code": {"run": "charge"},
                        "compensate": "refund",
                        "routes": {"default": "ship"},
                    },
                    {
                        "id": "ship",
                        "description": "book carrier",
                        "engine": "code",
                        "code": {"run": "ship"},
                        "routes": {"default": "END", "error": "END.failed"},
                    },
                    {
                        "id": "refund",
                        "description": "undo payment",
                        "engine": "code",
                        "code": {"run": "refund"},
                        "routes": {"default": "END"},
                    },
                ],
                "outputs": {
                    "default": {},
                    "failed": {"status": 502, "rollback": True, "body": "order cancelled"},
                },
            },
        }
    )
    host = RuntimeHost(pg_engine, workflows={"order": doc}, role="api")
    set_host(host)
    app = FastAPI()
    app.include_router(router)
    mount_triggers(app, {"order": doc})
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            resp = await client.post("/orders", headers=headers)
            assert resp.status_code == 502 and resp.json() == "order cancelled"
            run = (
                await client.get(f"/api/runs/{resp.headers['x-tuvl-run-id']}", headers=headers)
            ).json()
            events = (await client.get(f"/api/runs/{run['run_id']}/events", headers=headers)).text
    finally:
        await host.stop()
        set_host(None)
    assert run["status"] == "compensated" and run["end"] == "failed"
    assert "event: compensation_started" in events and "event: compensation_completed" in events
    async with AsyncSession(pg_engine) as s:
        rows = (await s.exec(sa.text("select entry from resilience_ledger order by id"))).all()  # type: ignore[call-overload]
    assert [r[0] for r in rows] == ["charged", "refunded"]
