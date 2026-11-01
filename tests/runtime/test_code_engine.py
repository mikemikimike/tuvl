"""The code engine (P1.6a): @agent functions run by the real runner."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl.contract.schema import WorkflowDocument
from tuvl.core.models import loader as model_loader
from tuvl.runtime import queue
from tuvl.runtime.code import AGENT_REGISTRY, agent, load_agents
from tuvl.runtime.models import SystemRun
from tuvl.runtime.queue import Worker
from tuvl.runtime.runner import Runner, workflow_hash


class Note(SQLModel, table=True):
    __tablename__ = "test_code_notes"
    id: int | None = Field(default=None, primary_key=True)
    text: str


@pytest.fixture
async def db(pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> AsyncEngine:
    async with pg_engine.begin() as conn:
        await conn.run_sync(lambda c: Note.__table__.drop(c, checkfirst=True))  # type: ignore[attr-defined]
        await conn.run_sync(lambda c: Note.__table__.create(c))  # type: ignore[attr-defined]
    monkeypatch.setitem(model_loader.MODEL_REGISTRY, "Note", Note)
    return pg_engine


@pytest.fixture(autouse=True)
def _clean_agents():
    saved = dict(AGENT_REGISTRY)
    yield
    AGENT_REGISTRY.clear()
    AGENT_REGISTRY.update(saved)
    for name in [m for m in sys.modules if m == "agents" or m.startswith("agents.")]:
        del sys.modules[name]


def doc(effect: str = "write", models: list[str] | None = None) -> WorkflowDocument:
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "wf"},
            "spec": {
                "models": ["Note"] if models is None else models,
                "trigger": {"input": {"text": "str"}},
                "agents": [
                    {
                        "id": "remember",
                        "description": "store a note",
                        "engine": "code",
                        "code": {"run": "remember"},
                        "effect": effect,
                        "inputs": {"text": "str"},
                        "outputs": {"saved": {"note": "json"}, "skipped": {}},
                        "routes": {"saved": "END", "skipped": "END.skipped", "error": "END.failed"},
                    }
                ],
                "outputs": {
                    "default": {"body": "{{ note.text }}"},
                    "skipped": {"body": "skipped"},
                    "failed": {"status": 500},
                },
            },
        }
    )


async def execute(db: AsyncEngine, workflow: WorkflowDocument, text: str) -> SystemRun:
    async with AsyncSession(db) as s:
        run_id = await queue.enqueue(
            s,
            workflow="wf",
            workflow_hash=workflow_hash(workflow),
            trigger="test",
            input={"text": text},
        )
        await s.commit()
    worker = Worker(db, Runner(db, {"wf": workflow}), owner="w")
    await worker.claim_some()
    await worker.drain()
    async with AsyncSession(db) as s:
        run = await s.get(SystemRun, run_id)
        assert run is not None
        return run


async def notes(db: AsyncEngine) -> list[str]:
    async with AsyncSession(db) as s:
        return [
            n.text
            for n in (await s.exec(SQLModel.metadata.tables["test_code_notes"].select())).all()
        ]  # type: ignore[call-overload,attr-defined]


def project(tmp: Path, body: str) -> Path:
    (tmp / "agents" / "_generated").mkdir(parents=True)
    (tmp / "agents" / "_generated" / "schemas.py").write_text(
        "from pydantic import BaseModel\n\n\nclass RememberIn(BaseModel):\n    text: str\n"
    )
    (tmp / "agents" / "remember.py").write_text(textwrap.dedent(body))
    return tmp / "agents"


async def test_loaded_agent_writes_through_ctx_db(db: AsyncEngine, tmp_path: Path) -> None:
    loaded = load_agents(
        project(
            tmp_path,
            """
            from tuvl import agent, Ctx
            from agents._generated.schemas import RememberIn

            @agent("remember")
            async def remember(inp: RememberIn, ctx: Ctx):
                assert isinstance(inp, RememberIn)  # the annotated class is honoured
                if not inp.text:
                    return "skipped"
                note = await ctx.db.create("Note", text=inp.text.upper())
                return {"note": note}, "saved"
            """,
        )
    )
    assert loaded == ["remember"]
    run = await execute(db, doc(), "hello")
    assert run.status == "completed" and run.output == {"status": 200, "body": "HELLO"}
    assert await notes(db) == ["HELLO"]
    skipped = await execute(db, doc(), "")
    assert skipped.end_name == "skipped"


async def _remember(inp, ctx):
    await ctx.db.create("Note", text=inp.text)
    return {"note": {"text": inp.text}}, "saved"


async def test_effect_read_refuses_writes(db: AsyncEngine) -> None:
    AGENT_REGISTRY["remember"] = _remember
    run = await execute(db, doc(effect="read"), "x")
    assert run.end_name == "failed" and await notes(db) == []


async def test_models_outside_the_allow_list_are_refused(db: AsyncEngine) -> None:
    AGENT_REGISTRY["remember"] = _remember
    run = await execute(db, doc(models=[]), "x")
    assert run.end_name == "failed" and await notes(db) == []


async def test_unknown_runner_is_an_error(db: AsyncEngine) -> None:
    AGENT_REGISTRY.pop("remember", None)
    assert (await execute(db, doc(), "x")).end_name == "failed"


def test_decorator_rules() -> None:
    with pytest.raises(TypeError, match="must decorate an async function"):
        agent("sync_one")(lambda inp, ctx: None)  # type: ignore[arg-type,return-value]

    @agent("unique_x")
    async def first(inp, ctx):
        return None

    with pytest.raises(ValueError, match="already registered"):

        @agent("unique_x")
        async def second(inp, ctx):
            return None


def test_load_agents_skips_private_files(tmp_path: Path) -> None:
    agents_dir = project(
        tmp_path,
        "from tuvl import agent\n\n@agent('remember')\nasync def r(inp, ctx):\n    return None\n",
    )
    (agents_dir / "_helpers.py").write_text("raise RuntimeError('must not be imported')\n")
    assert load_agents(agents_dir) == ["remember"]
    assert load_agents(tmp_path / "missing") == []


async def test_returning_the_wrong_shape_is_a_contract_violation(db: AsyncEngine) -> None:
    @agent("remember_bad")
    async def bad(inp, ctx):
        return 42

    AGENT_REGISTRY["remember"] = bad
    assert (await execute(db, doc(), "x")).end_name == "failed"
