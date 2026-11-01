"""Resilience (P1.11): a worker process is SIGKILLed mid-run.

The run resumes on another worker from its last checkpoint: the finished
step's database write happened exactly once, and the in-flight http step is
re-executed with the same Idempotency-Key.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.resilience.conftest import PG_URL
from tuvl.contract.schema import WorkflowDocument
from tuvl.runtime import queue
from tuvl.runtime.code import AGENT_REGISTRY, load_agents
from tuvl.runtime.models import SystemRun
from tuvl.runtime.queue import Worker
from tuvl.runtime.runner import Runner, workflow_hash


class Recorder(BaseHTTPRequestHandler):
    """Records every POST; the first one hangs (the worker is killed meanwhile)."""

    seen: list[dict[str, str]] = []
    release = threading.Event()

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("content-length") or 0))
        Recorder.seen.append(dict(self.headers))
        if len(Recorder.seen) == 1:
            Recorder.release.wait(30)
        body = json.dumps({"charge_id": "ch_1"}).encode()
        self.send_response(201)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def recorder() -> object:
    Recorder.seen, Recorder.release = [], threading.Event()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    Recorder.release.set()
    server.shutdown()


def _project(tmp_path: Path, port: int) -> Path:
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "write_once.py").write_text(
        textwrap.dedent("""
        from sqlalchemy import text
        from tuvl import agent

        @agent("write_once")
        async def write_once(inp, ctx):
            await ctx._engine_ctx.session.execute(
                text("insert into resilience_ledger(entry) values ('once')"))
            return {}
    """)
    )
    doc = {
        "kind": "Workflow",
        "version": "tuvl/v2",
        "metadata": {"name": "charge_flow"},
        "spec": {
            "agents": [
                {
                    "id": "record",
                    "description": "write",
                    "engine": "code",
                    "code": {"run": "write_once"},
                    "routes": {"default": "charge"},
                },
                {
                    "id": "charge",
                    "description": "pay",
                    "engine": "tool",
                    "effect": "write",
                    "tool": {
                        "use": "http",
                        "method": "POST",
                        "url": f"http://127.0.0.1:{port}/charge",
                        "idempotency": "auto",
                        "map": {"charge_id": "response.body.charge_id"},
                    },
                    "outputs": {"charge_id": "str"},
                    "routes": {"default": "END", "error": "END.failed"},
                },
            ],
            "outputs": {"default": {"body": "{{ charge_id }}"}, "failed": {"status": 502}},
        },
    }
    (tmp_path / "workflow.yaml").write_text(yaml.safe_dump(doc))
    return tmp_path


async def test_sigkill_mid_run_resumes_exactly_once(
    pg_engine: AsyncEngine, recorder: object, tmp_path: Path
) -> None:
    async with pg_engine.begin() as conn:
        await conn.execute(sa.text("drop table if exists resilience_ledger"))
        await conn.execute(
            sa.text("create table resilience_ledger (id serial primary key, entry text)")
        )
    project = _project(tmp_path, recorder.server_address[1])  # type: ignore[attr-defined]
    doc = WorkflowDocument.model_validate(yaml.safe_load((project / "workflow.yaml").read_text()))
    async with AsyncSession(pg_engine) as s:
        run_id = await queue.enqueue(
            s, workflow="charge_flow", workflow_hash=workflow_hash(doc), trigger="test", input={}
        )
        await s.commit()

    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(Path.cwd()), str(Path.cwd() / "src")])}
    proc = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).with_name("worker_proc.py")),
            PG_URL,
            str(project),
            "doomed",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(300):  # until the charge call is in flight
            if Recorder.seen:
                break
            await asyncio.sleep(0.1)
        assert Recorder.seen, (
            proc.stderr.read().decode()[-2000:] if proc.poll() is not None else "no charge call"
        )
        proc.send_signal(signal.SIGKILL)  # no cleanup, no lease release
        proc.wait(10)
    finally:
        if proc.poll() is None:
            proc.kill()
    Recorder.release.set()

    async with AsyncSession(pg_engine) as s:
        crashed = await s.get(SystemRun, run_id)
        assert (
            crashed is not None and crashed.status == "running" and crashed.lease_owner == "doomed"
        )
    await asyncio.sleep(1.2)  # the dead worker's lease expires

    saved = dict(AGENT_REGISTRY)
    try:
        load_agents(project / "agents")
        survivor = Worker(pg_engine, Runner(pg_engine, {"charge_flow": doc}), owner="survivor")
        while await survivor.claim_some():
            await survivor.drain()
    finally:
        AGENT_REGISTRY.clear()
        AGENT_REGISTRY.update(saved)
        for name in [m for m in sys.modules if m == "agents" or m.startswith("agents.")]:
            del sys.modules[name]

    async with AsyncSession(pg_engine) as s:
        final = await s.get(SystemRun, run_id)
        rows = (await s.exec(sa.text("select entry from resilience_ledger"))).all()  # type: ignore[call-overload]
    assert final is not None and final.status == "completed" and final.claims == 2
    assert final.output == {"status": 200, "body": "ch_1"}
    assert [r[0] for r in rows] == ["once"]  # the finished step was not re-executed
    keys = [h.get("Idempotency-Key") for h in Recorder.seen]
    assert len(keys) == 2 and keys[0] == keys[1] and keys[0].startswith(f"{run_id}:charge:")
