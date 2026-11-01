"""Resilience (B4): a worker process is SIGKILLed in the middle of a parallel step.

The step was never checkpointed, so another worker runs all of it again: the run completes with the same
result, the step is completed once in the journal, every event keeps a unique sequence number, and no
branch is left half-done.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.resilience.conftest import PG_URL
from tuvl.contract.schema import WorkflowDocument
from tuvl.runtime import journal, queue
from tuvl.runtime.models import SystemRun
from tuvl.runtime.queue import Worker
from tuvl.runtime.runner import Runner, workflow_hash


class Lookups(BaseHTTPRequestHandler):
    """``/a``, ``/b`` answer at once; the first ``/slow`` hangs (the worker is killed meanwhile)."""

    seen: list[str] = []
    slow_calls = 0
    release = threading.Event()

    def do_GET(self) -> None:
        name = self.path.strip("/")
        Lookups.seen.append(name)
        if name == "slow":
            Lookups.slow_calls += 1
            if Lookups.slow_calls == 1:
                Lookups.release.wait(30)
        body = json.dumps({"value": len(name)}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def lookups() -> object:
    Lookups.seen, Lookups.slow_calls, Lookups.release = [], 0, threading.Event()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Lookups)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    Lookups.release.set()
    server.shutdown()


def _branch(name: str, port: int) -> dict[str, object]:
    return {
        "id": name,
        "engine": "tool",
        "outputs": {name: "int"},
        "tool": {
            "use": "http",
            "method": "GET",
            "url": f"http://127.0.0.1:{port}/{name}",
            "map": {name: "response.body.value"},
        },
    }


def _project(tmp_path: Path, port: int) -> tuple[Path, WorkflowDocument]:
    (tmp_path / "agents").mkdir()
    doc = {
        "kind": "Workflow",
        "version": "tuvl/v2",
        "metadata": {"name": "gather_flow"},
        "spec": {
            "agents": [
                {
                    "id": "gather",
                    "description": "look up",
                    "engine": "parallel",
                    "outputs": {"a": "int", "b": "int", "slow": "int"},
                    "parallel": {"branches": [_branch(n, port) for n in ("a", "b", "slow")]},
                    "routes": {"default": "END", "error": "END.failed"},
                }
            ],
            "outputs": {
                "default": {"body": {"a": "{{ a }}", "b": "{{ b }}", "slow": "{{ slow }}"}},
                "failed": {"status": 502},
            },
        },
    }
    (tmp_path / "workflow.yaml").write_text(yaml.safe_dump(doc))
    return tmp_path, WorkflowDocument.model_validate(doc)


async def test_sigkill_mid_fan_out_runs_the_step_again_and_finishes_once(
    pg_engine: AsyncEngine, lookups: object, tmp_path: Path
) -> None:
    project, doc = _project(tmp_path, lookups.server_address[1])  # type: ignore[attr-defined]
    async with AsyncSession(pg_engine) as s:
        run_id = await queue.enqueue(
            s, workflow="gather_flow", workflow_hash=workflow_hash(doc), trigger="test", input={}
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
        for _ in range(300):  # until the slow branch is in flight and the fast ones are done
            if Lookups.slow_calls and {"a", "b"} <= set(Lookups.seen):
                break
            await asyncio.sleep(0.1)
        assert Lookups.slow_calls, (
            proc.stderr.read().decode()[-2000:] if proc.poll() is not None else "no lookups"
        )
        proc.send_signal(signal.SIGKILL)
        proc.wait(10)
    finally:
        if proc.poll() is None:
            proc.kill()
    Lookups.release.set()
    await asyncio.sleep(1.2)  # the dead worker's lease expires

    survivor = Worker(pg_engine, Runner(pg_engine, {"gather_flow": doc}), owner="survivor")
    while await survivor.claim_some():
        await survivor.drain()

    async with AsyncSession(pg_engine) as s:
        final = await s.get(SystemRun, run_id)
        events = list(await journal.events(s, run_id))
    assert final is not None and final.status == "completed" and final.claims == 2
    assert final.output == {"status": 200, "body": {"a": 1, "b": 1, "slow": 4}}
    assert [e.type for e in events].count("agent_completed") == 1  # checkpointed once
    seqs = [e.seq for e in events]
    assert seqs == sorted(set(seqs)), seqs  # no clashes between the two workers' events
    finished = [e for e in events if e.type == "parallel_finished"]
    assert len(finished) == 1 and finished[0].payload["failed"] == []
    # the killed worker's reads were repeated, once more each, by the survivor
    assert Lookups.seen.count("a") == 2 and Lookups.seen.count("slow") == 2
