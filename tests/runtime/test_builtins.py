"""Built-in tuvl.data_search / tuvl.data_ingest (P1.6e) on real pgvector,
with deterministic embeddings."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl import llm as llm_client
from tuvl.contract.schema import WorkflowDocument
from tuvl.core.config import settings
from tuvl.core.datasources import postgres
from tuvl.core.models import collections_loader
from tuvl.core.models.system import SystemVectorStore
from tuvl.runtime import queue
from tuvl.runtime.models import SystemRun
from tuvl.runtime.queue import Worker
from tuvl.runtime.runner import Runner, workflow_hash

DIMS = settings.tuvl_default_embedding_dimensions
WORDS = ["refund", "shipping", "password", "invoice", "delivery", "login"]


def _vector(text: str) -> list[float]:
    """Bag-of-known-words embedding: similar texts get close vectors."""
    lowered = text.lower()
    vec = [0.0] * DIMS
    for i, word in enumerate(WORDS):
        if word in lowered:
            vec[i] = 1.0
    vec[-1] = int(hashlib.sha256(text.encode()).hexdigest()[:4], 16) / 65535 / 100
    return vec


@pytest.fixture
async def vectors(pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> AsyncEngine:
    async with pg_engine.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(lambda c: SystemVectorStore.__table__.drop(c, checkfirst=True))  # type: ignore[attr-defined]
        await conn.run_sync(lambda c: SystemVectorStore.__table__.create(c))  # type: ignore[attr-defined]
    monkeypatch.setattr(postgres, "_VECTOR_STORE_READY", True)
    monkeypatch.setitem(collections_loader.COLLECTION_REGISTRY, "kb", {"name": "kb"})

    async def aembedding(*, model: str, input: list[str], dimensions: int, **_: Any) -> Any:
        assert dimensions == DIMS
        return SimpleNamespace(data=[{"embedding": _vector(input[0])}])

    monkeypatch.setattr(llm_client, "aembedding", aembedding)
    return pg_engine


def _doc(
    *agents: dict[str, Any], trigger: dict[str, str], ends: dict[str, Any]
) -> WorkflowDocument:
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "wf"},
            "spec": {"trigger": {"input": trigger}, "agents": list(agents), "outputs": ends},
        }
    )


INGEST = {
    "id": "remember",
    "description": "store",
    "engine": "code",
    "code": {
        "run": "tuvl.data_ingest",
        "with": {
            "collection": "kb",
            "document": "{{ text }}",
            "metadata": {"source": "{{ source }}"},
            "scope": "{{ scope }}",
        },
    },
    "inputs": {"text": "str", "source": "str", "scope": "str"},
    "outputs": {"doc_id": "uuid"},
    "routes": {"default": "END", "error": "END.failed"},
}


def _search(**with_: Any) -> dict[str, Any]:
    return {
        "id": "retrieve",
        "description": "search",
        "engine": "code",
        "effect": "read",
        "code": {
            "run": "tuvl.data_search",
            "with": {"collection": "kb", "query": "{{ question }}", **with_},
        },
        "inputs": {"question": "str"},
        "outputs": {"passages": "list[json]"},
        "routes": {"default": "END", "error": "END.failed"},
    }


async def _run(db: AsyncEngine, doc: WorkflowDocument, payload: dict[str, Any]) -> SystemRun:
    async with AsyncSession(db) as s:
        run_id = await queue.enqueue(
            s, workflow="wf", workflow_hash=workflow_hash(doc), trigger="t", input=payload
        )
        await s.commit()
    worker = Worker(db, Runner(db, {"wf": doc}), owner="w")
    await worker.claim_some()
    await worker.drain()
    async with AsyncSession(db) as s:
        run = await s.get(SystemRun, run_id)
        assert run is not None
        return run


async def _ingest(db: AsyncEngine, text: str, source: str, scope: str = "global") -> SystemRun:
    doc = _doc(
        INGEST,
        trigger={"text": "str", "source": "str", "scope": "str"},
        ends={"default": {"body": "{{ doc_id }}"}, "failed": {"status": 500}},
    )
    return await _run(db, doc, {"text": text, "source": source, "scope": scope})


SEARCH_ENDS = {"default": {"body": "{{ passages }}"}, "failed": {"status": 500}}


async def test_ingest_then_hybrid_search(vectors: AsyncEngine) -> None:
    stored = await _ingest(vectors, "How to request a refund for a damaged item", "faq")
    assert stored.status == "completed" and len(stored.output["body"]) == 36  # type: ignore[index]
    await _ingest(vectors, "Shipping and delivery times by region", "faq")
    await _ingest(vectors, "Resetting your password from the login page", "help")

    run = await _run(
        vectors,
        _doc(_search(top_k=2), trigger={"question": "str"}, ends=SEARCH_ENDS),
        {"question": "my refund for a damaged item"},
    )
    passages = run.output["body"]  # type: ignore[index]
    assert run.status == "completed" and len(passages) == 2
    assert passages[0]["content"].startswith("How to request a refund")
    assert (
        passages[0]["metadata"] == {"source": "faq"} and passages[0]["score"] > passages[1]["score"]
    )

    filtered = await _run(
        vectors,
        _doc(_search(filter={"source": "help"}), trigger={"question": "str"}, ends=SEARCH_ENDS),
        {"question": "refund"},
    )
    assert [p["metadata"]["source"] for p in filtered.output["body"]] == ["help"]  # type: ignore[index]


async def test_run_scoped_documents_stay_out_of_global_search(vectors: AsyncEngine) -> None:
    await _ingest(vectors, "invoice INV-7 was paid", "scratch", scope="run")
    found = await _run(
        vectors,
        _doc(_search(), trigger={"question": "str"}, ends=SEARCH_ENDS),
        {"question": "invoice"},
    )
    assert found.output["body"] == []  # type: ignore[index]


async def test_ingest_rolls_back_with_its_step(vectors: AsyncEngine) -> None:
    failing = dict(INGEST, outputs={"doc_id": "int"})  # contract violation after the write
    doc = _doc(
        failing,
        trigger={"text": "str", "source": "str", "scope": "str"},
        ends={"default": {}, "failed": {"status": 500}},
    )
    run = await _run(vectors, doc, {"text": "refund policy", "source": "x", "scope": "global"})
    assert run.end_name == "failed"
    async with AsyncSession(vectors) as s:
        count = (await s.exec(sa.select(sa.func.count()).select_from(SystemVectorStore))).one()  # type: ignore[call-overload]
    assert count[0] == 0


async def test_bad_params_are_errors(vectors: AsyncEngine) -> None:
    doc = _doc(_search(top_k=500), trigger={"question": "str"}, ends=SEARCH_ENDS)
    assert (await _run(vectors, doc, {"question": "x"})).end_name == "failed"
    unknown = _doc(_search(), trigger={"question": "str"}, ends=SEARCH_ENDS)
    unknown.spec.agents[0].code.with_["collection"] = "nope"
    assert (await _run(vectors, unknown, {"question": "x"})).end_name == "failed"


async def test_a_filter_rendered_from_a_uuid_input_is_encoded(vectors: AsyncEngine) -> None:
    search = _search(filter={"ref": "{{ ref }}"})
    search["inputs"] = {"question": "str", "ref": "uuid"}
    doc = _doc(search, trigger={"question": "str", "ref": "uuid"}, ends=SEARCH_ENDS)
    run = await _run(
        vectors, doc, {"question": "refund", "ref": "6f1c0a52-2a8e-4d0b-9a77-0b9d7c2f1e10"}
    )
    assert run.status == "completed" and run.end_name == "default", run.error


async def test_a_loop_searches_a_collection_as_a_tool(
    vectors: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.runtime.test_loop_engine import Script, call, start, workflows

    await _ingest(vectors, "How to request a refund for a damaged item", "faq")
    await _ingest(vectors, "Resetting your password from the login page", "help")
    script = Script(
        [call("search_kb", query="refund for a damaged item")],
        [call("finish", outcome="resolved", resolution="done")],
    )
    monkeypatch.setattr(llm_client, "acompletion", script)

    run = await start(vectors, workflows(tools=[{"collection": "kb", "top_k": 1}]))

    assert run.status == "completed", run.error
    names = [t["function"]["name"] for t in script.last_tools]
    assert "search_kb" in names
    reply = next(m for m in script.seen[1] if m["role"] == "tool")["content"]
    observed = json.loads(reply.split("\n", 1)[1].rsplit("\n", 1)[0])  # inside <data tool=…>
    assert [p["content"][:20] for p in observed["passages"]] == ["How to request a ref"]
    assert observed["passages"][0]["metadata"] == {"source": "faq"}
