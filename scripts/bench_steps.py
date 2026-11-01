"""Step-throughput benchmark for the runner, with a stubbed model and no outside network.

Runs a six-agent workflow (llm → decide → code → llm → code → llm) many times through the real
queue, worker and runner against Postgres, and reports runs/s, agent steps/s, p50/p95 step latency
and SQL statements per step (counted with a ``before_cursor_execute`` listener).

The model is one of:

* ``--llm http`` (default) — a local OpenAI-compatible server on 127.0.0.1 with keep-alive, so the
  real ``tuvl.llm`` HTTP path is measured (connection setup included);
* ``--llm stub`` — ``tuvl.llm.acompletion`` replaced in process (engine and runner cost only).

The database must be disposable: the runtime tables are dropped and recreated::

    TUVL_TEST_PG_URL=postgresql+asyncpg://tuvl:tuvl@localhost:5434/tuvl_bench \\
        uv run python scripts/bench_steps.py --runs 200

Numbers vary with the machine; compare before/after on the same one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import time
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlmodel import SQLModel

from tuvl.contract.schema import WorkflowDocument
from tuvl.runtime import queue
from tuvl.runtime.code import AGENT_REGISTRY
from tuvl.runtime.models import RUNTIME_TABLES
from tuvl.runtime.queue import Worker
from tuvl.runtime.runner import Runner, workflow_hash

REPLIES = {
    "classify": {"label": "billing", "score": 0.9},
    "draft": {"text": "Thanks, we are on it."},
    "polish": {"text": "Thanks, we are on it.", "outcome": "send"},
}


def _llm(agent_id: str, outputs: dict[str, str], prompt: str, routes: dict[str, str]) -> Any:
    return {
        "id": agent_id,
        "description": agent_id,
        "engine": "llm",
        "llm": {"model": "ollama/bench", "prompt": prompt},
        "outputs": outputs,
        "routes": {**routes, "error": "END.failed", "parse_error": "END.failed"},
    }


def _code(agent_id: str, inputs: dict[str, str], outputs: dict[str, str], to: str) -> Any:
    return {
        "id": agent_id,
        "description": agent_id,
        "engine": "code",
        "code": {"run": f"bench_{agent_id}"},
        "inputs": inputs,
        "outputs": outputs,
        "routes": {"default": to, "error": "END.failed"},
    }


def workflow() -> WorkflowDocument:
    agents = [
        {
            **_llm(
                "classify",
                {"label": "enum[billing, outage, other]", "score": "float"},
                "Classify ticket {{ ticket.id }}: {{ ticket.subject }}",
                {"default": "triage"},
            ),
            "inputs": {"ticket": "Ticket"},
        },
        {
            "id": "triage",
            "description": "triage",
            "engine": "decide",
            "inputs": {"label": "str", "score": "float"},
            "outputs": {"route": "enum[urgent, normal]"},
            "decide": {
                "rules": [
                    {"when": 'label == "outage" or score > 0.95', "then": "urgent"},
                    {"when": "score <= 0.95", "then": "normal"},
                ]
            },
            "routes": {"urgent": "enrich", "normal": "enrich", "error": "END.failed"},
        },
        _code("enrich", {"label": "str"}, {"queue": "str", "priority": "int"}, "draft"),
        {
            **_llm(
                "draft",
                {"text": "str"},
                "Write a reply for queue {{ queue }} (priority {{ priority }}).",
                {"default": "audit"},
            ),
            "inputs": {"queue": "str", "priority": "int"},
        },
        _code("audit", {"text": "str", "priority": "int"}, {"length": "int"}, "polish"),
        {
            **_llm(
                "polish",
                {"text": "str"},
                "Polish: {{ text }} ({{ length }} chars)",
                {"send": "END", "hold": "END.held"},
            ),
            "inputs": {"text": "str", "length": "int"},
        },
    ]
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "bench"},
            "spec": {
                "trigger": {"input": {"ticket": "Ticket"}},
                "agents": agents,
                "outputs": {"default": {}, "held": {}, "failed": {"status": 500}},
            },
        }
    )


async def _enrich(inp: Any, ctx: Any) -> dict[str, Any]:
    return {"queue": f"q-{inp.label}", "priority": 2}


async def _audit(inp: Any, ctx: Any) -> dict[str, Any]:
    return {"length": len(inp.text)}


def _reply_for(response_format: dict[str, Any]) -> dict[str, Any]:
    return REPLIES[response_format["json_schema"]["name"]]


def _completion_json(reply: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": "bench",
        "choices": [
            {
                "message": {"role": "assistant", "content": json.dumps(reply)},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class _Server:
    """An OpenAI-compatible chat endpoint on loopback that keeps connections alive."""

    connections = 0

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return int(self.server.sockets[0].getsockname()[1])

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            while True:
                head = (await reader.readuntil(b"\r\n\r\n")).decode()
                headers = {
                    k.lower(): v
                    for k, _, v in (ln.partition(": ") for ln in head.split("\r\n")[1:] if ln)
                }
                body = json.loads(await reader.readexactly(int(headers["content-length"])))
                payload = json.dumps(_completion_json(_reply_for(body["response_format"]))).encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n"
                    + f"content-length: {len(payload)}\r\n\r\n".encode()
                    + payload
                )
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    async def stop(self) -> None:
        self.server.close()
        await self.server.wait_closed()


class _Timed(Runner):
    durations: list[float]

    async def step(self, state: Any, lease: Any, agent: Any) -> str:
        started = time.perf_counter()
        try:
            return await super().step(state, lease, agent)
        finally:
            self.durations.append(time.perf_counter() - started)


def _ticket_model() -> None:
    from pydantic import BaseModel

    from tuvl.core.models.schemas import SCHEMA_REGISTRY

    class Ticket(BaseModel):
        id: int
        subject: str

    SCHEMA_REGISTRY["Ticket"] = {"read": Ticket}


async def _reset(engine: AsyncEngine) -> None:
    tables = [m.__table__ for m in RUNTIME_TABLES]  # type: ignore[attr-defined]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: SQLModel.metadata.drop_all(c, tables=tables))
        await conn.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=tables))


async def bench(url: str, runs: int, warmup: int, mode: str) -> dict[str, Any]:
    from tuvl import llm

    _ticket_model()
    AGENT_REGISTRY["bench_enrich"] = _enrich
    AGENT_REGISTRY["bench_audit"] = _audit
    server = _Server()
    if mode == "http":
        port = await server.start()
        os.environ["OLLAMA_API_BASE"] = f"http://127.0.0.1:{port}"
        from tuvl.core.models import agent_models

        agent_models.AGENT_MODEL_REGISTRY["bench"] = {
            "model": "ollama/bench",
            "api_base": f"http://127.0.0.1:{port}",
        }
    else:

        async def stub(**kw: Any) -> Any:
            return llm.openai_wire.parse_chat(
                _completion_json(_reply_for(kw["response_format"])), "bench"
            )

        llm.acompletion = stub  # type: ignore[assignment]

    doc = workflow()
    if mode == "http":
        for a in doc.spec.agents:
            if a.engine == "llm":
                a.llm.model = "bench"  # type: ignore[attr-defined]
    # pooled and pre-pinged like the server's primary datasource
    engine = create_async_engine(url, pool_pre_ping=True)
    await _reset(engine)
    statements = [0]
    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        lambda *a: statements.__setitem__(0, statements[0] + 1),
    )
    runner = _Timed(engine, {"bench": doc})
    runner.durations = []
    worker = Worker(engine, runner, owner="bench", concurrency=1)
    digest = workflow_hash(doc)

    async def once() -> None:
        async with AsyncSession(engine) as s:
            await queue.enqueue(
                s,
                workflow="bench",
                workflow_hash=digest,
                trigger="bench",
                input={"ticket": {"id": 7, "subject": "Card charged twice"}},
            )
            await s.commit()
        while await worker.claim_some():
            await worker.drain()

    for _ in range(warmup):
        await once()
    runner.durations = []
    statements[0] = 0
    started = time.perf_counter()
    for _ in range(runs):
        await once()
    elapsed = time.perf_counter() - started
    steps = len(runner.durations)
    sql = statements[0]
    await engine.dispose()
    if mode == "http":
        if hasattr(llm, "aclose"):
            await llm.aclose()
        await server.stop()
    expected = runs * len(doc.spec.agents)
    if steps != expected:
        raise SystemExit(f"expected {expected} steps, ran {steps}: a run failed")
    ms = sorted(d * 1000 for d in runner.durations)
    return {
        "mode": mode,
        "runs": runs,
        "steps": steps,
        "runs_per_s": round(runs / elapsed, 1),
        "steps_per_s": round(steps / elapsed, 1),
        "p50_step_ms": round(statistics.median(ms), 2),
        "p95_step_ms": round(ms[int(len(ms) * 0.95) - 1], 2),
        "sql_per_step": round(sql / steps, 2),
        "sql_per_run": round(sql / runs, 1),
        "model_connections": server.connections if mode == "http" else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", default=os.environ.get("TUVL_TEST_PG_URL"))
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--llm", choices=("http", "stub"), default="http")
    args = parser.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not args.db:
        raise SystemExit("set --db or TUVL_TEST_PG_URL to a disposable Postgres database")
    result = asyncio.run(bench(args.db, args.runs, args.warmup, args.llm))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
