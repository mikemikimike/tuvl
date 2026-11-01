"""The decide engine (P2.1–P2.3): one test per row of the spec §10.2 table,
with fake decision providers, through the real runner on Postgres."""

from __future__ import annotations

import asyncio
import json
import math
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl.contract.schema import WorkflowDocument
from tuvl.core.artifacts import registry as artifacts
from tuvl.core.artifacts.registry import ArtifactEntry, ArtifactVersion
from tuvl.core.models import agent_models
from tuvl.runtime import decision, journal, queue
from tuvl.runtime.models import SystemRun
from tuvl.runtime.queue import Worker
from tuvl.runtime.runner import Runner, workflow_hash

CALLS: list[dict[str, Any]] = []


class Fake:
    """A fake provider whose behaviour each test sets."""

    mode = "ok"
    value = "auto_refund"
    confidence = 0.95

    @classmethod
    async def __call__(cls, request: decision.DecisionRequest) -> decision.Decision:
        CALLS.append(dict(request.inputs))
        if cls.mode == "down":
            raise decision.ProviderUnavailableError("connection refused")
        if cls.mode == "slow":
            await asyncio.sleep(5)
        return decision.Decision(cls.value, cls.confidence)


@pytest.fixture(autouse=True)
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    CALLS.clear()
    Fake.mode, Fake.value, Fake.confidence = "ok", "auto_refund", 0.95
    monkeypatch.setitem(decision.PROVIDERS, "fake", Fake())
    monkeypatch.setitem(
        agent_models.AGENT_MODEL_REGISTRY,
        "classifier",
        {"type": "decision", "provider": "fake", "model": "fake-1"},
    )
    decision.STATUS.pop("classifier", None)


def doc(
    *, rules: Any = None, model: bool = True, shadow: bool = False, **budget: Any
) -> WorkflowDocument:
    decide: dict[str, Any] = {
        "rules": rules
        if rules is not None
        else [
            {"when": "amount > 500", "then": "manager_review"},
            {"when": 'reason == "fraud_flag"', "then": "reject"},
        ]
    }
    if model:
        decide["model"] = {"ref": "classifier", "min_confidence": 0.8}
    if shadow:
        decide["shadow"] = True
    routes = {
        "auto_refund": "END.auto",
        "manager_review": "END.review",
        "reject": "END.rejected",
        "error": "END.failed",
    }
    if model and not shadow:
        routes["low_confidence"] = "END.unsure"
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "wf"},
            "spec": {
                "trigger": {"input": {"amount": "int", "reason": "str"}},
                "agents": [
                    {
                        "id": "triage",
                        "description": "Decide how a refund is handled",
                        "engine": "decide",
                        "inputs": {"amount": "int", "reason": "str"},
                        "outputs": {"route": "enum[auto_refund, manager_review, reject]"},
                        "budget": budget,
                        "decide": decide,
                        "routes": routes,
                    }
                ],
                "outputs": {
                    name: {}
                    for name in ("default", "auto", "review", "rejected", "failed", "unsure")
                },
            },
        }
    )


async def run(
    db: AsyncEngine, workflow: WorkflowDocument, amount: int, reason: str = ""
) -> tuple[SystemRun, dict[str, Any]]:
    async with AsyncSession(db) as s:
        run_id = await queue.enqueue(
            s,
            workflow="wf",
            workflow_hash=workflow_hash(workflow),
            trigger="t",
            input={"amount": amount, "reason": reason},
        )
        await s.commit()
    worker = Worker(db, Runner(db, {"wf": workflow}), owner="w")
    await worker.claim_some()
    await worker.drain()
    async with AsyncSession(db) as s:
        result = await s.get(SystemRun, run_id)
        record = [e.payload for e in await journal.events(s, run_id) if e.type == "decision"]
        done = [e.payload for e in await journal.events(s, run_id) if e.type == "agent_completed"]
    assert result is not None and len(record) == 1
    return result, {**record[0], "completed": done[0]}


async def test_rule_match_wins_and_model_is_not_called(pg_engine: AsyncEngine) -> None:
    result, rec = await run(pg_engine, doc(), 900)
    assert (
        result.end_name == "review"
        and rec["source"] == "rule#1"
        and rec["decision"] == "manager_review"
    )
    result, rec = await run(pg_engine, doc(), 10, "fraud_flag")
    assert result.end_name == "rejected" and rec["source"] == "rule#2"
    assert CALLS == []


async def test_no_rule_and_no_model_is_no_rule_matched(pg_engine: AsyncEngine) -> None:
    result, rec = await run(pg_engine, doc(model=False), 10)
    assert result.end_name == "failed" and rec["source"] == "rules"
    assert rec["completed"]["error_type"] == "no_rule_matched"


async def test_confident_model_decides(pg_engine: AsyncEngine) -> None:
    result, rec = await run(pg_engine, doc(), 10, "late delivery")
    assert result.end_name == "auto" and rec["source"] == "model" and rec["confidence"] == 0.95
    assert CALLS == [{"amount": 10, "reason": "late delivery"}]  # exactly the inputs


async def test_low_confidence_is_its_own_signal(pg_engine: AsyncEngine) -> None:
    Fake.confidence = 0.42
    result, rec = await run(pg_engine, doc(), 10)
    assert result.end_name == "unsure" and rec["decision"] is None
    assert rec["value"] == "auto_refund" and rec["confidence"] == 0.42  # the proposal is journaled


async def test_unavailable_model_is_an_error_with_no_fallback(pg_engine: AsyncEngine) -> None:
    Fake.mode = "down"
    result, rec = await run(pg_engine, doc(), 10)
    assert result.end_name == "failed"
    assert rec["completed"]["error_type"] == "decision_model_unavailable"
    assert decision.health()["classifier"]["error"] == "connection refused"


async def test_slow_model_times_out_after_retries_as_unavailable(pg_engine: AsyncEngine) -> None:
    Fake.mode = "slow"
    workflow = doc(timeout="100ms", retry={"attempts": 2, "errors": ["timeout"], "backoff": 1.0})
    result, rec = await run(pg_engine, workflow, 10)
    assert result.end_name == "failed" and len(CALLS) == 2
    assert rec["completed"]["error_type"] == "decision_model_unavailable"
    assert "timed out" in rec["completed"]["message"]


async def test_shadow_mode_rules_decide_and_model_is_only_journaled(pg_engine: AsyncEngine) -> None:
    Fake.value = "reject"
    result, rec = await run(pg_engine, doc(shadow=True), 900)
    assert result.end_name == "review" and rec["source"] == "rule#1"
    assert rec["shadow"]["value"] == "reject"
    Fake.mode = "down"
    result, rec = await run(pg_engine, doc(shadow=True), 900)
    assert (
        result.end_name == "review" and "error" in rec["shadow"]
    )  # a shadow failure is not an error
    result, rec = await run(pg_engine, doc(shadow=True), 10)
    assert result.end_name == "failed" and rec["completed"]["error_type"] == "no_rule_matched"


async def test_rules_from_an_artifact(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = {"type": "rules", "rules": [{"when": "amount < 50", "then": "auto_refund"}]}
    monkeypatch.setitem(
        artifacts.ARTIFACT_REGISTRY,
        "refund-rules",
        ArtifactEntry(
            "refund-rules",
            "rules",
            versions={4: ArtifactVersion(content=spec, content_hash="x", source="file")},
        ),
    )
    result, rec = await run(pg_engine, doc(rules="artifact://refund-rules@4", model=False), 20)
    assert result.end_name == "auto" and rec["source"] == "rule#1"


def test_logprob_confidence_covers_the_value_tokens() -> None:
    import math

    content = '{"decision": "reject"}'
    tokens = [
        SimpleNamespace(token=t, logprob=lp)
        for t, lp in [
            ('{"', 0.0),
            ("decision", 0.0),
            ('": "', 0.0),
            ("rej", -0.1),
            ("ect", -0.2),
            ('"}', 0.0),
        ]
    ]
    conf = decision._value_confidence(content, "reject", SimpleNamespace(content=tokens))
    assert conf == pytest.approx(math.exp(-0.3))
    assert decision._value_confidence(content, "reject", None) is None


async def test_unknown_provider_is_unavailable(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        agent_models.AGENT_MODEL_REGISTRY,
        "classifier",
        {"type": "decision", "provider": "acme", "model": "acme-1"},
    )
    result, rec = await run(pg_engine, doc(), 10)
    assert rec["completed"]["error_type"] == "decision_model_unavailable"
    assert "'acme' is not installed" in rec["completed"]["message"]


async def test_llm_adapter_retries_without_logprobs(monkeypatch: pytest.MonkeyPatch) -> None:
    from tuvl import llm as llm_client

    seen: list[bool] = []

    async def acompletion(**kwargs: Any) -> Any:
        seen.append("logprobs" in kwargs)
        if "logprobs" in kwargs:
            raise llm_client.BadRequestError("Logprobs is not enabled for this model")
        message = SimpleNamespace(content='{"decision": "reject", "confidence": 0.82}')
        return SimpleNamespace(choices=[SimpleNamespace(message=message, logprobs=None)])

    monkeypatch.setattr(llm_client, "acompletion", acompletion)
    monkeypatch.setitem(
        agent_models.AGENT_MODEL_REGISTRY,
        "clf",
        {"type": "decision", "provider": "llm", "model": "gemini/x-1"},
    )
    request = decision.DecisionRequest(
        "clf", decision.resolve_model("clf"), {"t": "x"}, ["reject", "ok"], "d"
    )
    first = await decision.decide(request)
    second = await decision.decide(request)
    assert (first.value, first.confidence) == ("reject", 0.82) and second.value == "reject"
    assert seen == [True, False, False]  # the refusal is remembered per model


def _llm_answer(
    monkeypatch: pytest.MonkeyPatch, content: str, logprob: float | None, seen: list[dict[str, Any]]
) -> None:
    from tuvl import llm as llm_client

    async def acompletion(**kwargs: Any) -> Any:
        seen.append(kwargs)
        logprobs = (
            SimpleNamespace(content=[SimpleNamespace(token=content, logprob=math.log(logprob))])
            if logprob is not None
            else None
        )
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, logprobs=logprobs)])

    monkeypatch.setattr(llm_client, "acompletion", acompletion)


def _request(name: str) -> decision.DecisionRequest:
    return decision.DecisionRequest(
        name, decision.resolve_model(name), {"t": "x"}, ["reject", "ok"], "d"
    )


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ({"type": "decision", "provider": "llm", "model": "openai/laya-x"}, 0.9),
        ({"model": "openai/gpt-x"}, 0.5),
    ],
    ids=["decision-model-reports-first", "llm-logprobs-first"],
)
async def test_confidence_source_depends_on_the_model_type(
    monkeypatch: pytest.MonkeyPatch, entry: dict[str, Any], expected: float
) -> None:
    _llm_answer(monkeypatch, '{"decision": "ok", "confidence": 0.9}', 0.5, [])
    monkeypatch.setitem(agent_models.AGENT_MODEL_REGISTRY, "clf", entry)
    answer = await decision.decide(_request("clf"))
    assert (answer.value, answer.confidence) == ("ok", expected)


@pytest.mark.parametrize("reported", ["", ', "confidence": 1.7', ', "confidence": true'])
async def test_no_usable_confidence_is_unavailable_not_certain(
    monkeypatch: pytest.MonkeyPatch, reported: str
) -> None:
    _llm_answer(monkeypatch, '{"decision": "ok"' + reported + "}", None, [])
    monkeypatch.setitem(
        agent_models.AGENT_MODEL_REGISTRY,
        "clf",
        {"type": "decision", "provider": "llm", "model": "openai/laya-x"},
    )
    with pytest.raises(decision.ProviderUnavailableError, match="no confidence"):
        await decision.decide(_request("clf"))


async def test_decision_model_endpoint_and_key_reach_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, Any]] = []
    _llm_answer(monkeypatch, '{"decision": "ok", "confidence": 0.7}', None, seen)
    monkeypatch.setenv("LAYA_TEST_KEY", "k-123")
    monkeypatch.setitem(
        agent_models.AGENT_MODEL_REGISTRY,
        "laya",
        {
            "type": "decision",
            "provider": "llm",
            "model": "openai/laya-x",
            "api_base": "http://laya.internal/v1",
            "api_key": "${LAYA_TEST_KEY}",
        },
    )
    await decision.decide(_request("laya"))
    assert seen[0]["model"] == "openai/laya-x"
    assert (seen[0]["api_base"], seen[0]["api_key"]) == ("http://laya.internal/v1", "k-123")
    schema = seen[0]["response_format"]["json_schema"]["schema"]
    assert schema["required"] == ["decision", "confidence"]


def _systemone(
    monkeypatch: pytest.MonkeyPatch, reply: Any, seen: list[httpx.Request], status: int = 200
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=reply)

    real = httpx.AsyncClient

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)


def _laya(monkeypatch: pytest.MonkeyPatch, **spec: Any) -> None:
    monkeypatch.setitem(
        agent_models.AGENT_MODEL_REGISTRY,
        "laya",
        {"type": "decision", "provider": "laya", "api_base": "http://laya:8000", **spec},
    )


async def test_laya_asks_one_choice_question_and_uses_calibrated_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []
    answer = {
        "type": "choice",
        "choice": "ok",
        "probabilities": {"ok": 0.97, "reject": 0.03},
        "confidence": 0.81,
        "answer_confidence": 0.97,
    }
    _systemone(monkeypatch, {"model": "laya-rl-agent", "answers": {"decision": answer}}, seen)
    monkeypatch.setenv("LAYA_TEST_KEY", "k-1")
    _laya(monkeypatch, model="auto", api_key="${LAYA_TEST_KEY}")
    result = await decision.decide(_request("laya"))
    assert (result.value, result.confidence) == ("ok", 0.97)
    assert result.probabilities == {"ok": 0.97, "reject": 0.03}
    sent = json.loads(seen[0].content)
    assert str(seen[0].url) == "http://laya:8000/v1/systemone"
    assert seen[0].headers["authorization"] == "Bearer k-1"
    assert sent == {
        "state": {"t": "x"},
        "questions": {
            "decision": {
                "type": "choice",
                "instructions": "d",
                "criteria": {"reject": "reject", "ok": "ok"},
            }
        },
    }  # "auto" leaves the checkpoint to laya's router


async def test_strict_jev_answer_uses_confidence_and_names_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []
    answer = {"type": "choice", "choice": "reject", "probabilities": {}, "confidence": 0.6}
    _systemone(monkeypatch, {"model": "jev-1.13.0", "answers": {"decision": answer}}, seen)
    monkeypatch.setitem(
        agent_models.AGENT_MODEL_REGISTRY,
        "jev",
        {"type": "decision", "provider": "jev", "model": "jev-1.13.0", "api_base": "https://j/"},
    )
    result = await decision.decide(_request("jev"))
    assert (result.value, result.confidence) == ("reject", 0.6)
    assert json.loads(seen[0].content)["model"] == "jev-1.13.0"
    assert "authorization" not in seen[0].headers


@pytest.mark.parametrize(
    ("status", "reply", "message"),
    [
        (503, {"detail": "server busy"}, "server busy"),
        (200, {"answers": {}}, "KeyError"),
        (200, {"answers": {"decision": {"choice": "ok"}}}, "no confidence"),
    ],
)
async def test_systemone_failures_are_unavailable(
    monkeypatch: pytest.MonkeyPatch, status: int, reply: Any, message: str
) -> None:
    _systemone(monkeypatch, reply, [], status=status)
    _laya(monkeypatch, model="english")
    with pytest.raises(decision.ProviderUnavailableError, match=message):
        await decision.decide(_request("laya"))


async def test_systemone_undefined_key_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LAYA_TEST_MISSING", raising=False)
    _laya(monkeypatch, model="auto", api_key="${LAYA_TEST_MISSING}")
    with pytest.raises(decision.ProviderUnavailableError, match="LAYA_TEST_MISSING"):
        await decision.decide(_request("laya"))
