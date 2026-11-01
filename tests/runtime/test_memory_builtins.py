"""``tuvl.memory_remember`` / ``tuvl.memory_recall`` (C2): per-owner, time-ordered, journaled, once per step."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.runtime import test_builtins
from tests.runtime.test_builtins import _doc
from tuvl.contract.schema import WorkflowDocument
from tuvl.runtime import journal, queue
from tuvl.runtime.builtins import memory_remember
from tuvl.runtime.models import SystemRun
from tuvl.runtime.queue import Worker
from tuvl.runtime.runner import Runner, workflow_hash

vectors = test_builtins.vectors  # the pgvector fixture

REMEMBER = {
    "id": "remember",
    "description": "store",
    "engine": "code",
    "code": {"run": "tuvl.memory_remember", "with": {"collection": "kb", "text": "{{ text }}"}},
    "inputs": {"text": "str"},
    "outputs": {"stored": "bool"},
    "routes": {"default": "END", "error": "END.failed"},
}


def _recall(**with_: Any) -> dict[str, Any]:
    return {
        "id": "recall",
        "description": "recall",
        "engine": "code",
        "effect": "read",
        "code": {
            "run": "tuvl.memory_recall",
            "with": {"collection": "kb", "query": "{{ question }}", **with_},
        },
        "inputs": {"question": "str"},
        "outputs": {"memories": "list[json]"},
        "routes": {"default": "END", "error": "END.failed"},
    }


def _remember_doc(**with_: Any) -> WorkflowDocument:
    agent = {
        **REMEMBER,
        "code": {**REMEMBER["code"], "with": {**REMEMBER["code"]["with"], **with_}},
    }  # type: ignore[dict-item]
    return _doc(
        agent,
        trigger={"text": "str"},
        ends={"default": {"body": "{{ stored }}"}, "failed": {"status": 500}},
    )


def _recall_doc(**with_: Any) -> WorkflowDocument:
    return _doc(
        _recall(**with_),
        trigger={"question": "str"},
        ends={"default": {"body": "{{ memories }}"}, "failed": {"status": 500}},
    )


async def run_as(
    db: AsyncEngine, doc: WorkflowDocument, payload: dict[str, Any], principal: str | None
) -> tuple[SystemRun, list[Any]]:
    async with AsyncSession(db) as s:
        run_id = await queue.enqueue(
            s,
            workflow="wf",
            workflow_hash=workflow_hash(doc),
            trigger="t",
            input=payload,
            principal=principal,
        )
        await s.commit()
    worker = Worker(db, Runner(db, {"wf": doc}), owner="w")
    await worker.claim_some()
    await worker.drain()
    async with AsyncSession(db) as s:
        run = await s.get(SystemRun, run_id)
        assert run is not None
        return run, list(await journal.events(s, run_id))


async def test_one_owner_recalls_what_they_stored_and_another_does_not(
    vectors: AsyncEngine,
) -> None:  # noqa: F811
    for text in ("my refund was for a damaged lamp", "my login page keeps failing"):
        run, _ = await run_as(vectors, _remember_doc(), {"text": text}, "ada")
        assert run.status == "completed", run.error
    await run_as(vectors, _remember_doc(), {"text": "grace asked about shipping"}, "grace")

    ada, events = await run_as(
        vectors, _recall_doc(window=2, top_k=0), {"question": "refund"}, "ada"
    )
    memories = ada.output["body"]  # type: ignore[index]
    assert [m["content"] for m in memories] == [
        "my refund was for a damaged lamp",
        "my login page keeps failing",
    ]
    assert all(m["source"] == "recent" for m in memories)  # oldest first, the order they were said

    grace, _ = await run_as(
        vectors, _recall_doc(window=5, top_k=5), {"question": "refund lamp"}, "grace"
    )
    assert [m["content"] for m in grace.output["body"]] == ["grace asked about shipping"]  # type: ignore[index]

    nobody_else, _ = await run_as(vectors, _recall_doc(), {"question": "refund"}, "mallory")
    assert nobody_else.output["body"] == []  # type: ignore[index]

    recalled = next(e for e in events if e.type == "memory_recalled")
    assert (
        recalled.payload["recent"] == 2
        and "my refund was for a damaged lamp" in recalled.payload["text"]
    )


async def test_related_older_memories_are_added_without_repeating_recent_ones(
    vectors: AsyncEngine,
) -> None:  # noqa: F811
    for text in (
        "the refund for the lamp",
        "password reset worked",
        "shipping to Lisbon",
        "delivery is late",
    ):
        await run_as(vectors, _remember_doc(), {"text": text}, "ada")
    run, _ = await run_as(vectors, _recall_doc(window=1, top_k=2), {"question": "refund"}, "ada")
    got = [(m["source"], m["content"]) for m in run.output["body"]]  # type: ignore[index]
    assert (
        got[0] == ("related", "the refund for the lamp")
        or ("related", "the refund for the lamp") in got
    )
    assert got[-1] == ("recent", "delivery is late")
    assert len({c for _, c in got}) == len(got)  # nothing twice


async def test_an_explicit_key_names_the_owner_and_no_owner_is_an_error(
    vectors: AsyncEngine,
) -> None:  # noqa: F811
    keyed = _remember_doc(key="customer-7")
    await run_as(vectors, keyed, {"text": "prefers email"}, None)  # no principal needed with a key
    run, _ = await run_as(vectors, _recall_doc(key="customer-7"), {"question": "email"}, "anyone")
    assert [m["content"] for m in run.output["body"]] == ["prefers email"]  # type: ignore[index]
    anonymous, _ = await run_as(vectors, _remember_doc(), {"text": "x"}, None)
    assert anonymous.end_name == "failed"


async def test_a_step_that_runs_again_stores_one_memory(vectors: AsyncEngine) -> None:
    async with AsyncSession(vectors) as s:
        agent = SimpleNamespace(id="remember", outputs={"stored": "bool"})
        engine_ctx = SimpleNamespace(
            session=s,
            idempotency_key="run-1:remember:0",
            workflow=SimpleNamespace(spec=SimpleNamespace(agents=[agent])),
        )
        ctx = SimpleNamespace(
            params={"collection": "kb", "text": "said once", "key": "ada"},
            _engine_ctx=engine_ctx,
            principal=None,
            run_id="run-1",
            agent_id="remember",
        )
        await memory_remember(None, ctx)  # type: ignore[arg-type]
        await memory_remember(None, ctx)  # type: ignore[arg-type]
        await s.commit()
        count = (
            await s.execute(
                sa.text("select count(*) from tuvl_system_vector_store where content = 'said once'")
            )
        ).scalar_one()
    assert count == 1


async def _owner_rows(db: AsyncEngine, key: str) -> list[tuple[str, str]]:
    async with AsyncSession(db) as s:
        found = await s.execute(
            sa.text(
                "select metadata->>'kind', content from tuvl_system_vector_store "
                "where metadata->>'memory_key' = :k order by created_at, content"
            ),
            {"k": key},
        )
        return [(r[0], r[1]) for r in found.all()]


async def test_compaction_folds_old_memories_into_one_summary(vectors: AsyncEngine) -> None:
    from datetime import UTC, datetime, timedelta

    from tuvl.core.models.system import SystemVectorStore
    from tuvl.runtime import memory

    async with AsyncSession(vectors) as s:
        for owner, n in (("ada", 8), ("grace", 3)):
            for i in range(n):
                s.add(
                    SystemVectorStore(
                        id=uuid.uuid4(),
                        collection="kb",
                        content=f"{owner} note {i}",
                        extra_metadata={"memory_key": owner, "kind": "turn"},
                        created_at=datetime.now(UTC) - timedelta(hours=100 - i),
                    )
                )
        await s.commit()
    seen: list[list[str]] = []

    async def summarise(notes: list[str]) -> str:
        seen.append(notes)
        return "ada likes email"

    async with AsyncSession(vectors) as s:
        done = await memory.compact(s, collection="kb", keep=3, min_rows=5, summarise=summarise)
        await s.commit()
    assert done == 1  # grace has too few memories to bother
    assert seen == [[f"ada note {i}" for i in range(5)]]  # the five oldest, oldest first
    rows = await _owner_rows(vectors, "ada")
    assert rows == [
        ("summary", "ada likes email"),
        ("turn", "ada note 5"),
        ("turn", "ada note 6"),
        ("turn", "ada note 7"),
    ]
    assert len(await _owner_rows(vectors, "grace")) == 3
    async with AsyncSession(vectors) as s:  # nothing left to fold: a second pass does no more
        assert (
            await memory.compact(s, collection="kb", keep=3, min_rows=3, summarise=summarise) == 0
        )


async def test_the_compact_builtin_asks_the_model_for_the_summary(
    vectors: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.runtime.test_llm_engine import FakeLLM
    from tuvl import llm as llm_client
    from tuvl.core.models import agent_models

    fake = FakeLLM("they prefer email")
    monkeypatch.setattr(llm_client, "acompletion", fake)
    monkeypatch.setattr(
        agent_models, "resolve_call_params", lambda cfg, agent: ("openai/test", 30, {})
    )
    agent = {
        "id": "compact",
        "description": "fold old memories",
        "engine": "code",
        "code": {
            "run": "tuvl.memory_compact",
            "with": {"collection": "kb", "model": "default", "keep": 1, "min_rows": 2},
        },
        "outputs": {"owners": "int"},
        "routes": {"default": "END", "error": "END.failed"},
    }
    for text in ("I like email", "no calls please", "latest"):
        await run_as(vectors, _remember_doc(), {"text": text}, "ada")
    doc = _doc(
        agent, trigger={}, ends={"default": {"body": "{{ owners }}"}, "failed": {"status": 500}}
    )
    run, events = await run_as(vectors, doc, {}, None)
    assert run.status == "completed" and run.output["body"] == 1, run.error  # type: ignore[index]
    prompt = fake.calls[0]["messages"][1]["content"]
    assert (
        "I like email" in prompt and "no calls please" in prompt and '<data name="notes">' in prompt
    )
    assert "latest" not in prompt  # the newest is kept as it is
    assert [e.payload["owners"] for e in events if e.type == "memory_compacted"] == [1]
    assert ("summary", "they prefer email") in await _owner_rows(vectors, "ada")
