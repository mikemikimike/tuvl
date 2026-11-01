"""Judges (P2.8): typed verdicts, deterministic cache, calibration, and the
fail-closed guardrail and supervisor uses."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl import llm as llm_client
from tuvl.contract.schema import WorkflowDocument
from tuvl.core.artifacts import registry as artifacts
from tuvl.core.artifacts.registry import ArtifactEntry, ArtifactVersion
from tuvl.runtime import journal, judges, queue
from tuvl.runtime.models import SystemRun
from tuvl.runtime.queue import Worker
from tuvl.runtime.runner import Runner, workflow_hash

RUBRIC = {  # as the registry stores it — the type lives on the entry
    "model": "openai/judge-1",
    "rubric": "The reply states the refund amount.",
    "verdict": ["pass", "fail", "uncertain"],
    "min_score": 0.8,
}


class Models:
    """Judge calls answer from ``verdicts`` (by subject text); agent calls from ``agent``."""

    def __init__(self) -> None:
        self.judge_calls = 0
        self.verdicts: dict[str, tuple[str, float]] = {}
        self.default = ("pass", 0.95)
        self.down = False
        self.agent: list[Any] = []

    async def __call__(self, **kwargs: Any) -> Any:
        system = kwargs["messages"][0]["content"]
        usage = SimpleNamespace(total_tokens=50)
        if "RUBRIC" in system:
            self.judge_calls += 1
            if self.down:
                raise llm_client.APIConnectionError("down")
            subject = kwargs["messages"][1]["content"]
            verdict, score = next(
                (v for k, v in self.verdicts.items() if k in subject), self.default
            )
            content = json.dumps(
                {"verdict": verdict, "score": score, "reasons": [f"{verdict} because"]}
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=usage
            )
        reply = self.agent.pop(0)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(reply)), finish_reason="stop"
                )
            ],
            usage=usage,
        )


@pytest.fixture
def models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Models:
    fake = Models()
    monkeypatch.setattr(llm_client, "acompletion", fake)
    monkeypatch.setattr(judges, "_cache_dir", lambda: tmp_path / ".tuvl" / "judge-cache")
    judge_artifact(monkeypatch, RUBRIC, version=2)
    return fake


def judge_artifact(
    monkeypatch: pytest.MonkeyPatch, spec: dict[str, Any], version: int, digest: str = "h2"
) -> None:
    monkeypatch.setitem(
        artifacts.ARTIFACT_REGISTRY,
        "reply-quality",
        ArtifactEntry(
            "reply-quality",
            "judge",
            versions={version: ArtifactVersion(content=spec, content_hash=digest, source="file")},
        ),
    )


async def test_verdicts_score_threshold_and_cache(
    models: Models, monkeypatch: pytest.MonkeyPatch
) -> None:
    models.verdicts = {
        "forty": ("pass", 0.95),
        "vague": ("pass", 0.5),
        "nothing": ("uncertain", 0.2),
    }
    first = await judges.judge("artifact://reply-quality@2", "Refund of forty euros")
    again = await judges.judge("artifact://reply-quality@2", "Refund of forty euros")
    assert (first.verdict, first.cached, again.verdict, again.cached) == (
        "pass",
        False,
        "pass",
        True,
    )
    assert models.judge_calls == 1  # the second run is free
    low = await judges.judge("artifact://reply-quality@2", "a vague reply")
    assert low.verdict == "fail" and "below min_score" in low.reasons[-1]
    assert (await judges.judge("artifact://reply-quality@2", "nothing here")).verdict == "uncertain"

    # A changed rubric (new content hash) is a new cache key: judged again.
    judge_artifact(monkeypatch, {**RUBRIC, "rubric": "Stricter."}, version=2, digest="h3")
    await judges.judge("artifact://reply-quality@2", "Refund of forty euros")
    assert models.judge_calls == 4
    assert len(list(judges._cache_dir().glob("*.json"))) == 4


async def test_the_verdict_cache_is_read_and_written_off_the_event_loop(
    models: Models, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    loop_thread = threading.get_ident()
    threads: list[int] = []
    read, write = judges._read_cache, judges._write_cache

    def track(fn: Any) -> Any:
        def wrapped(*args: Any) -> Any:
            threads.append(threading.get_ident())
            return fn(*args)

        return wrapped

    monkeypatch.setattr(judges, "_read_cache", track(read))
    monkeypatch.setattr(judges, "_write_cache", track(write))
    await judges.judge("artifact://reply-quality@2", "Refund of forty euros")
    assert (await judges.judge("artifact://reply-quality@2", "Refund of forty euros")).cached
    assert len(threads) == 3 and loop_thread not in threads


async def test_unavailable_judge_raises(models: Models) -> None:
    models.down = True
    with pytest.raises(judges.JudgeUnavailableError):
        await judges.judge("artifact://reply-quality@2", "x")


async def test_calibration_agreement(
    models: Models, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "ok.json").write_text(json.dumps({"reply": "refund forty"}))
    (tmp_path / "bad.json").write_text(json.dumps({"reply": "we promise a free car"}))
    calibrated = {
        **RUBRIC,
        "min_agreement": 0.9,
        "calibration": [
            {"input": "ok.json", "expect": "pass"},
            {"input": "bad.json", "expect": "fail"},
        ],
    }
    judge_artifact(monkeypatch, calibrated, version=2)
    models.verdicts = {
        "forty": ("pass", 0.9),
        "free car": ("pass", 0.9),
    }  # the judge misses the bad one
    result = await judges.calibrate("artifact://reply-quality@2", tmp_path)
    assert result.agreement == 0.5 and not result.trusted
    assert [r["agree"] for r in result.results] == [True, False]


# ── fail-closed guardrail on an llm agent ───────────────────────────────────


def llm_doc() -> WorkflowDocument:
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "wf"},
            "spec": {
                "agents": [
                    {
                        "id": "reply",
                        "description": "write the reply",
                        "engine": "llm",
                        "outputs": {"text": "str"},
                        "llm": {"model": "openai/gpt-test", "prompt": "Reply."},
                        "guardrails": {"output": ["artifact://reply-quality@2"]},
                        "routes": {
                            "default": "END",
                            "guardrail_violation": "END.blocked",
                            "error": "END.failed",
                            "parse_error": "END.failed",
                            "timeout": "END.failed",
                        },
                    }
                ],
                "outputs": {"default": {}, "blocked": {"status": 422}, "failed": {"status": 502}},
            },
        }
    )


async def run(db: AsyncEngine, doc: WorkflowDocument) -> tuple[SystemRun, dict[str, Any]]:
    async with AsyncSession(db) as s:
        run_id = await queue.enqueue(
            s, workflow="wf", workflow_hash=workflow_hash(doc), trigger="t", input={}
        )
        await s.commit()
    worker = Worker(db, Runner(db, {"wf": doc}), owner="w")
    while await worker.claim_some():
        await worker.drain()
    async with AsyncSession(db) as s:
        result = await s.get(SystemRun, run_id)
        done = [e.payload for e in await journal.events(s, run_id) if e.type == "agent_completed"]
    assert result is not None
    return result, done[0]


@pytest.mark.parametrize(
    ("verdict", "down", "end", "error_type"),
    [
        ("pass", False, "default", None),
        ("fail", False, "blocked", None),
        ("uncertain", False, "failed", "judge_uncertain"),
        ("pass", True, "failed", "judge_unavailable"),
    ],
)
async def test_judge_guardrail_fails_closed(
    pg_engine: AsyncEngine,
    models: Models,
    verdict: str,
    down: bool,
    end: str,
    error_type: str | None,
) -> None:
    models.default, models.down = (verdict, 0.95), down
    models.agent = [{"text": "Your refund of 40 EUR is on its way."}]
    result, done = await run(pg_engine, llm_doc())
    assert result.end_name == end and done["error_type"] == error_type
    if end == "default":
        assert result.tokens_used == 100  # the agent turn plus the judge call


# ── the supervisor's judge ──────────────────────────────────────────────────


async def test_supervisor_judge_aborts_a_loop(
    pg_engine: AsyncEngine, models: Models, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tuvl.runtime.code import AGENT_REGISTRY

    async def lookup(inp: Any, ctx: Any) -> dict[str, Any]:
        return {"balance": 1}

    monkeypatch.setitem(AGENT_REGISTRY, "lookup", lookup)
    models.default = ("fail", 0.1)
    turn = {"tool_calls": [{"name": "lookup_order", "args": {"order_id": "o-1"}}]}

    original = models.__call__

    async def loop_aware(**kwargs: Any) -> Any:
        if "RUBRIC" in kwargs["messages"][0]["content"]:
            return await original(**kwargs)
        calls = [
            SimpleNamespace(
                id=f"c{i}",
                function=SimpleNamespace(name=c["name"], arguments=json.dumps(c["args"])),
            )
            for i, c in enumerate(turn["tool_calls"])
        ]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=calls))],
            usage=SimpleNamespace(total_tokens=10),
        )

    monkeypatch.setattr(llm_client, "acompletion", loop_aware)
    doc = WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "wf"},
            "spec": {
                "agents": [
                    {
                        "id": "resolve",
                        "description": "resolve",
                        "engine": "loop",
                        "outputs": {"note": "str"},
                        "budget": {
                            "max_iterations": 5,
                            "max_tokens": 5000,
                            "max_tool_calls": 5,
                            "timeout": "30s",
                        },
                        "loop": {
                            "model": "openai/gpt-test",
                            "steering": "Resolve.",
                            "tools": [{"agent": "lookup_order"}],
                            "supervisor": {
                                "judge": "artifact://reply-quality@2",
                                "on_violation": "abort",
                            },
                        },
                        "routes": {
                            "default": "END",
                            "error": "END.failed",
                            "max_iterations": "END.failed",
                            "budget_exceeded": "END.failed",
                            "timeout": "END.failed",
                            "aborted": "END.stopped",
                        },
                    },
                    {
                        "id": "lookup_order",
                        "description": "look up",
                        "engine": "code",
                        "code": {"run": "lookup"},
                        "effect": "read",
                        "inputs": {"order_id": "str"},
                        "outputs": {"balance": "int"},
                        "routes": {"default": "END"},
                    },
                ],
                "outputs": {"default": {}, "stopped": {"status": 409}, "failed": {"status": 502}},
            },
        }
    )
    result, done = await run(pg_engine, doc)
    assert result.end_name == "stopped" and done["signal"] == "aborted"
    async with AsyncSession(pg_engine) as s:
        verdicts = [
            e.payload for e in await journal.events(s, result.id) if e.type == "judge_verdict"
        ]
    assert verdicts and verdicts[0]["verdict"] == "fail"
