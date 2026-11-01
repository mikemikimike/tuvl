"""Per-run and per-agent OTel spans (spec §19) and observe-only hooks."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

import tuvl.runtime.runner as runner_mod
from tuvl.contract.schema import WorkflowDocument
from tuvl.core.artifacts import registry as artifacts
from tuvl.core.artifacts.registry import ArtifactEntry, ArtifactVersion
from tuvl.core.engine import hooks as hooks_mod
from tuvl.runtime import queue
from tuvl.runtime.code import AGENT_REGISTRY
from tuvl.runtime.queue import Worker
from tuvl.runtime.runner import Runner, workflow_hash


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(runner_mod, "_tracer", provider.get_tracer("test"))
    return exporter


@pytest.fixture
def hook_log(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    for name, event in (
        ("on-start", "before_step"),
        ("on-end", "after_step"),
        ("on-fail", "on_error"),
    ):
        spec = {"type": "hook", "on": event, "action": "log"}
        monkeypatch.setitem(
            artifacts.ARTIFACT_REGISTRY,
            name,
            ArtifactEntry(
                name,
                "hook",
                versions={1: ArtifactVersion(content=spec, content_hash="x", source="file")},
            ),
        )
    log = MagicMock()
    monkeypatch.setattr(hooks_mod, "logger", log)
    return log


async def _ok(inp: Any, ctx: Any) -> dict[str, Any]:
    return {"n": 1}


async def _boom(inp: Any, ctx: Any) -> None:
    raise RuntimeError("boom")


async def test_spans_and_hooks(
    pg_engine: AsyncEngine,
    spans: InMemorySpanExporter,
    hook_log: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(AGENT_REGISTRY, "ok_agent", _ok)
    monkeypatch.setitem(AGENT_REGISTRY, "boom_agent", _boom)
    doc = WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "wf"},
            "spec": {
                "hooks": ["artifact://on-fail@1"],
                "agents": [
                    {
                        "id": "first",
                        "description": "d",
                        "engine": "code",
                        "code": {"run": "ok_agent"},
                        "outputs": {"n": "int"},
                        "hooks": ["artifact://on-start@1", "artifact://on-end@1"],
                        "routes": {"default": "second"},
                    },
                    {
                        "id": "second",
                        "description": "d",
                        "engine": "code",
                        "code": {"run": "boom_agent"},
                        "routes": {"default": "END", "error": "END.failed"},
                    },
                ],
                "outputs": {"default": {}, "failed": {"status": 500}},
            },
        }
    )
    async with AsyncSession(pg_engine) as s:
        await queue.enqueue(
            s, workflow="wf", workflow_hash=workflow_hash(doc), trigger="t", input={}
        )
        await s.commit()
    worker = Worker(pg_engine, Runner(pg_engine, {"wf": doc}), owner="w")
    await worker.claim_some()
    await worker.drain()

    finished = {s.name: s for s in spans.get_finished_spans()}
    assert set(finished) == {"tuvl.run", "tuvl.agent first", "tuvl.agent second"}
    first, second, run = (
        finished["tuvl.agent first"],
        finished["tuvl.agent second"],
        finished["tuvl.run"],
    )
    assert first.parent is not None and first.parent.span_id == run.context.span_id
    assert dict(first.attributes) == {
        "tuvl.workflow": "wf",
        "tuvl.agent": "first",
        "tuvl.engine": "code",
        "tuvl.determinism": "deterministic",
        "tuvl.signal": "default",
        "tuvl.tokens": 0,
        "tuvl.attempt": 1,
    }
    assert second.attributes["tuvl.error_type"] == "code_exception"
    assert second.status.status_code.name == "ERROR"

    fired = [
        (c.kwargs["hook"], c.kwargs["step_id"])
        for c in hook_log.info.call_args_list
        if c.args == ("workflow.hook",)
    ]
    assert fired == [("on-start", "first"), ("on-end", "first"), ("on-fail", "second")]
