"""The 2.0 runner (P1.4/P1.5) — driven through the real queue and worker
with scripted engines."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl.contract.schema import WorkflowDocument
from tuvl.runtime import deltas, engines, journal, queue
from tuvl.runtime.engines import AgentResult, EngineContext
from tuvl.runtime.models import SystemRun, SystemRunCheckpoint
from tuvl.runtime.queue import Worker
from tuvl.runtime.runner import Runner, workflow_hash

pytestmark = pytest.mark.asyncio

Script = Callable[[dict[str, Any], EngineContext], Awaitable[AgentResult]]
SCRIPTS: dict[str, Script] = {}
CALLS: Counter[str] = Counter()
KEYS: list[str] = []


class Ledger(SQLModel, table=True):
    """A table engines write to, to observe per-agent transactions."""

    __tablename__ = "test_runner_ledger"
    id: int | None = Field(default=None, primary_key=True)
    entry: str


async def scripted(agent: Any, view: dict[str, Any], ctx: EngineContext) -> AgentResult:
    name = agent.code.run
    CALLS[name] += 1
    KEYS.append(ctx.idempotency_key)
    return await SCRIPTS[name](view, ctx)


@pytest.fixture(autouse=True)
def _engine_registry(pg_engine: AsyncEngine):
    saved = dict(engines.ENGINES)
    engines.register_engine("code", scripted)
    SCRIPTS.clear()
    CALLS.clear()
    KEYS.clear()
    yield
    engines.ENGINES.clear()
    engines.ENGINES.update(saved)


@pytest.fixture
async def db(pg_engine: AsyncEngine) -> AsyncEngine:
    async with pg_engine.begin() as conn:
        await conn.run_sync(lambda c: Ledger.__table__.drop(c, checkfirst=True))  # type: ignore[attr-defined]
        await conn.run_sync(lambda c: Ledger.__table__.create(c))  # type: ignore[attr-defined]
    return pg_engine


def script(name: str) -> Callable[[Script], Script]:
    def deco(fn: Script) -> Script:
        SCRIPTS[name] = fn
        return fn

    return deco


def ok(signal: str = "default", **outputs: Any) -> AgentResult:
    return AgentResult(signal, outputs=outputs)


def code(agent_id: str, routes: dict[str, str], **extra: Any) -> dict[str, Any]:
    return {
        "id": agent_id,
        "description": agent_id,
        "engine": "code",
        "code": {"run": agent_id},
        "routes": routes,
        **extra,
    }


def workflow(*agents: dict[str, Any], **spec: Any) -> WorkflowDocument:
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "wf"},
            "spec": {"agents": list(agents), **spec},
        }
    )


async def start(
    db: AsyncEngine, doc: WorkflowDocument, payload: dict[str, Any] | None = None
) -> uuid.UUID:
    async with AsyncSession(db) as s:
        run_id = await queue.enqueue(
            s, workflow="wf", workflow_hash=workflow_hash(doc), trigger="test", input=payload or {}
        )
        await s.commit()
    return run_id


async def drive(
    db: AsyncEngine, doc: WorkflowDocument, owner: str = "w1", **worker_kw: Any
) -> None:
    worker = Worker(db, Runner(db, {"wf": doc}), owner=owner, **worker_kw)
    while await worker.claim_some():
        await worker.drain()


async def run(
    db: AsyncEngine, doc: WorkflowDocument, payload: dict[str, Any] | None = None
) -> SystemRun:
    run_id = await start(db, doc, payload)
    await drive(db, doc)
    return await get(db, run_id)


async def get(db: AsyncEngine, run_id: uuid.UUID) -> SystemRun:
    async with AsyncSession(db) as s:
        found = await s.get(SystemRun, run_id)
        assert found is not None
        return found


async def event_types(db: AsyncEngine, run_id: uuid.UUID) -> list[str]:
    async with AsyncSession(db) as s:
        return [e.type for e in await journal.events(s, run_id)]


async def ledger(db: AsyncEngine) -> list[str]:
    async with AsyncSession(db) as s:
        rows = await s.exec(sa.select(Ledger.entry).order_by(Ledger.id))  # type: ignore[call-overload,arg-type]
        return [r[0] for r in rows.all()]


@pytest.fixture(params=[True, False], ids=["dev", "prod"])
def dev_mode(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> bool:
    """Outside dev mode the control read is folded into ``agent_started``."""
    from tuvl.core.config import settings

    monkeypatch.setattr(settings, "tuvl_dev_mode", request.param)
    return bool(request.param)


async def assert_gap_free(db: AsyncEngine, run_id: uuid.UUID) -> None:
    """Events and checkpoints together use every sequence number below ``next_seq`` once."""
    async with AsyncSession(db) as s:
        seqs = [e.seq for e in await journal.events(s, run_id)]
        rows = await s.exec(
            sa.select(SystemRunCheckpoint.seq).where(SystemRunCheckpoint.run_id == run_id)  # type: ignore[call-overload,arg-type]
        )
        seqs += [r[0] for r in rows.all()]
        run = await s.get(SystemRun, run_id)
        assert run is not None
        assert sorted(seqs) == list(range(1, run.next_seq))


# ── Happy path ──────────────────────────────────────────────────────────────


async def test_linear_run_renders_the_named_end(db: AsyncEngine) -> None:
    @script("double")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return ok(doubled=view["n"] * 2)

    @script("label")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return ok(text=f"n*2={view['doubled']}")

    doc = workflow(
        code(
            "double",
            {"default": "label", "error": "END.failed"},
            inputs={"n": "int"},
            outputs={"doubled": "int"},
        ),
        code(
            "label",
            {"default": "END", "error": "END.failed"},
            inputs={"doubled": "int"},
            outputs={"text": "str"},
        ),
        trigger={"input": {"n": "int"}},
        outputs={
            "default": {"body": {"result": "{{ text }}", "raw": "{{ doubled }}"}},
            "failed": {"status": 500},
        },
    )
    result = await run(db, doc, {"n": 21})
    assert result.status == "completed" and result.end_name == "default"
    assert result.output == {"status": 200, "body": {"result": "n*2=42", "raw": 42}}
    assert await event_types(db, result.id) == [
        "run_queued",
        "run_started",
        "agent_started",
        "agent_completed",
        "agent_started",
        "agent_completed",
        "run_completed",
    ]


async def test_custom_signals_route_and_carry_their_outputs(db: AsyncEngine) -> None:
    @script("classify")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return ok("big" if view["amount"] > 100 else "small", note=f"amount {view['amount']}")

    doc = workflow(
        code(
            "classify",
            {"big": "END.big", "small": "END", "error": "END"},
            inputs={"amount": "int"},
            outputs={"big": {"note": "str"}, "small": {}},
        ),
        trigger={"input": {"amount": "int"}},
        outputs={"default": {"body": "small"}, "big": {"body": "{{ note }}"}},
    )
    assert (await run(db, doc, {"amount": 500})).output == {"status": 200, "body": "amount 500"}
    assert (await run(db, doc, {"amount": 5})).output == {"status": 200, "body": "small"}


# ── Contracts and routing ───────────────────────────────────────────────────


async def test_output_contract_violation_takes_the_error_route(db: AsyncEngine) -> None:
    @script("bad")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return ok(count="many", extra=1)

    doc = workflow(
        code("bad", {"default": "END", "error": "END.failed"}, outputs={"count": "int"}),
        outputs={"default": {}, "failed": {"status": 422, "body": "bad output"}},
    )
    result = await run(db, doc)
    assert result.status == "completed" and result.end_name == "failed"
    async with AsyncSession(db) as s:
        completed = [e for e in await journal.events(s, result.id) if e.type == "agent_completed"][
            0
        ]
    assert completed.payload["error_type"] == "contract_violation"
    assert "count" in completed.payload["message"] and "extra" in completed.payload["message"]


async def test_unrouted_signal_fails_the_run(db: AsyncEngine) -> None:
    @script("odd")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return ok("surprise")

    result = await run(db, workflow(code("odd", {"default": "END"})))
    assert result.status == "failed"
    assert result.error == {
        "error_type": "unrouted_signal",
        "message": "'odd' emitted 'surprise', which is not routed",
        "agent_id": "odd",
    }
    assert (await event_types(db, result.id))[-1] == "run_failed"


async def test_unrouted_error_fails_the_run_with_the_engine_error(db: AsyncEngine) -> None:
    @script("crash")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        raise ValueError("division by zero")

    result = await run(db, workflow(code("crash", {"default": "END"})))
    assert result.status == "failed"
    assert result.error is not None and result.error["error_type"] == "code_exception"
    assert "ValueError: division by zero" in result.error["message"]


async def test_input_contract_violation(db: AsyncEngine) -> None:
    @script("use")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return ok()

    doc = workflow(
        code("use", {"default": "END", "error": "END.failed"}, inputs={"n": "int"}),
        trigger={"input": {"n": "str"}},
        outputs={"default": {}, "failed": {"status": 422}},
    )
    result = await run(db, doc, {"n": "not a number"})
    assert result.end_name == "failed" and CALLS["use"] == 0


# ── Budgets ─────────────────────────────────────────────────────────────────


async def test_timeout(db: AsyncEngine) -> None:
    @script("slow")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        await asyncio.sleep(2)
        return ok()

    doc = workflow(
        code("slow", {"default": "END", "error": "END.failed"}, budget={"timeout": "100ms"}),
        outputs={"default": {}, "failed": {"status": 504}},
    )
    result = await run(db, doc)
    assert result.end_name == "failed"


async def test_retry_on_transient_errors(db: AsyncEngine) -> None:
    @script("flaky")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        if CALLS["flaky"] < 3:
            return AgentResult("error", error_type="transient", message="503")
        return ok()

    doc = workflow(
        code(
            "flaky",
            {"default": "END", "error": "END.failed"},
            budget={"retry": {"attempts": 3, "errors": ["transient"], "backoff": 1.0}},
        ),
        outputs={"default": {}, "failed": {"status": 503}},
    )
    import tuvl.runtime.runner as runner_mod

    runner_mod._BACKOFF_BASE_SECONDS = 0.01
    result = await run(db, doc)
    assert CALLS["flaky"] == 3 and result.end_name == "default"
    assert len(set(KEYS)) == 1  # retries share the idempotency key


async def test_policy_token_limit(db: AsyncEngine) -> None:
    @script("spend")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return AgentResult("default", tokens=600)

    doc = workflow(
        code("spend", {"default": "again", "error": "END"}),
        code("again", {"default": "END", "error": "END"}),
        policy={"max_tokens_per_run": 1000},
    )
    SCRIPTS["again"] = SCRIPTS["spend"]
    result = await run(db, doc)
    assert result.status == "failed" and result.error is not None
    assert result.error["error_type"] == "policy_violation" and result.tokens_used == 1200


# ── Transactions ────────────────────────────────────────────────────────────


async def test_agent_writes_commit_only_with_a_normal_outcome(db: AsyncEngine) -> None:
    @script("write_ok")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        ctx.session.add(Ledger(entry="kept"))
        return ok()

    @script("write_fail")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        ctx.session.add(Ledger(entry="discarded"))
        return AgentResult("error", error_type="db_error", message="constraint")

    doc = workflow(
        code("write_ok", {"default": "write_fail", "error": "END"}),
        code("write_fail", {"default": "END", "error": "END"}),
    )
    await run(db, doc)
    assert await ledger(db) == ["kept"]


async def test_lost_lease_commits_nothing(db: AsyncEngine, dev_mode: bool) -> None:
    @script("steal")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        ctx.session.add(Ledger(entry="after lease loss"))
        async with AsyncSession(db) as s:  # another worker takes the run
            await s.exec(
                sa.update(SystemRun).where(SystemRun.id == ctx.run_id).values(lease_owner="thief")
            )  # type: ignore[call-overload,arg-type]
            await s.commit()
        return ok()

    run_id = await start(db, workflow(code("steal", {"default": "END"})))
    await drive(db, workflow(code("steal", {"default": "END"})))
    assert await ledger(db) == []
    assert (await get(db, run_id)).lease_owner == "thief"
    assert "agent_completed" not in await event_types(db, run_id)
    await assert_gap_free(db, run_id)


async def test_lost_lease_under_per_run_journals_no_completion(
    db: AsyncEngine, dev_mode: bool
) -> None:
    @script("steal")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        ctx.session.add(Ledger(entry="after lease loss"))
        async with AsyncSession(db) as s:
            await s.exec(
                sa.update(SystemRun).where(SystemRun.id == ctx.run_id).values(lease_owner="thief")
            )  # type: ignore[call-overload,arg-type]
            await s.commit()
        return ok()

    doc = workflow(code("steal", {"default": "END"}), transaction="per_run")
    run_id = await start(db, doc)
    await drive(db, doc)
    assert await ledger(db) == []
    assert (await get(db, run_id)).lease_owner == "thief"
    assert "agent_completed" not in await event_types(db, run_id)
    await assert_gap_free(db, run_id)


# ── Suspend / resume / crash ────────────────────────────────────────────────


async def test_suspend_and_resume_does_not_rerun_finished_agents(
    db: AsyncEngine, dev_mode: bool
) -> None:
    decisions: dict[str, bool] = {}

    @script("prepare")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return ok(amount=900)

    @script("approve")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        if "approved" not in decisions:
            return AgentResult("default", suspend="waiting_human")
        return ok("true" if decisions["approved"] else "false", approved=decisions["approved"])

    doc = workflow(
        code("prepare", {"default": "approve", "error": "END"}, outputs={"amount": "int"}),
        code(
            "approve",
            {"true": "END", "false": "END.rejected", "error": "END"},
            inputs={"amount": "int"},
            outputs={"true": {"approved": "bool"}, "false": {"approved": "bool"}},
        ),
        outputs={"default": {"body": "approved {{ amount }}"}, "rejected": {"body": "rejected"}},
    )
    result = await run(db, doc)
    assert (
        result.status == "waiting_human"
        and result.current_agent == "approve"
        and result.lease_owner is None
    )

    decisions["approved"] = True
    async with AsyncSession(db) as s:
        assert await queue.requeue(s, result.id)
        await s.commit()
    await drive(db, doc, owner="w2")
    resumed = await get(db, result.id)
    assert resumed.status == "completed" and resumed.output == {
        "status": 200,
        "body": "approved 900",
    }
    assert Counter({"prepare": 1, "approve": 2}) == CALLS
    assert "resumed" in await event_types(db, result.id)


async def test_crash_mid_run_resumes_from_the_last_checkpoint(
    db: AsyncEngine, dev_mode: bool
) -> None:
    gate = asyncio.Event()

    @script("first")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        ctx.session.add(Ledger(entry="first"))
        return ok(x=1)

    @script("second")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        if CALLS["second"] == 1:
            await gate.wait()  # the first worker "dies" here
        return ok()

    doc = workflow(
        code("first", {"default": "second", "error": "END"}, outputs={"x": "int"}),
        code("second", {"default": "END", "error": "END"}, inputs={"x": "int"}),
    )
    run_id = await start(db, doc)
    doomed = Worker(
        db, Runner(db, {"wf": doc}), owner="doomed", lease_seconds=0.3, heartbeat_seconds=10
    )
    await doomed.claim_some()
    while CALLS["second"] < 1:
        await asyncio.sleep(0.02)
    for task in list(doomed._active.values()):
        task.cancel()  # process death: no release, no heartbeat
    await asyncio.sleep(0.4)  # lease expires

    await drive(db, doc, owner="survivor")
    final = await get(db, run_id)
    assert final.status == "completed" and final.claims == 2
    assert Counter({"first": 1, "second": 2}) == CALLS  # 'first' was not re-executed
    assert await ledger(db) == ["first"]  # its write committed exactly once
    second_keys = [k for k in KEYS if ":second:" in k]
    assert len(set(second_keys)) == 1  # re-execution reuses the idempotency key
    await assert_gap_free(db, run_id)


# ── Compensation ────────────────────────────────────────────────────────────


def _saga(fail_comp: bool = False) -> WorkflowDocument:
    for name in ("charge", "ship"):

        async def step(view: dict, ctx: EngineContext, n: str = name) -> AgentResult:
            ctx.session.add(Ledger(entry=n))
            return ok(**{f"{n}_ref": f"{n}-1"})

        SCRIPTS[name] = step
    for name in ("refund", "unship"):

        async def undo(view: dict, ctx: EngineContext, n: str = name) -> AgentResult:
            if fail_comp and n == "unship":
                return AgentResult("error", error_type="http_error", message="carrier down")
            ctx.session.add(Ledger(entry=n))
            return ok()

        SCRIPTS[name] = undo

    @script("notify")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return AgentResult("error", error_type="http_error", message="mail down")

    return workflow(
        code(
            "charge",
            {"default": "ship", "error": "END.failed"},
            outputs={"charge_ref": "str"},
            compensate="refund",
        ),
        code(
            "ship",
            {"default": "notify", "error": "END.failed"},
            outputs={"ship_ref": "str"},
            compensate="unship",
        ),
        code("notify", {"default": "END", "error": "END.failed"}),
        code("refund", {"default": "END"}, inputs={"charge_ref": "str"}),
        code("unship", {"default": "END"}, inputs={"ship_ref": "str"}),
        outputs={"default": {}, "failed": {"status": 502, "rollback": True, "body": "rolled back"}},
    )


async def test_rollback_end_compensates_newest_first(db: AsyncEngine) -> None:
    result = await run(db, _saga())
    assert result.status == "compensated" and result.output == {
        "status": 502,
        "body": "rolled back",
    }
    assert await ledger(db) == ["charge", "ship", "unship", "refund"]
    types = await event_types(db, result.id)
    assert types.count("compensation_started") == 2 and types[-1] == "run_completed"


async def test_failed_compensation_fails_the_run_but_still_runs_the_rest(db: AsyncEngine) -> None:
    result = await run(db, _saga(fail_comp=True))
    assert result.status == "failed"
    assert await ledger(db) == ["charge", "ship", "refund"]


async def test_unhandled_error_compensates(db: AsyncEngine) -> None:
    doc = _saga()
    doc.spec.agents[2].routes.pop("error")  # notify's error is now unrouted
    result = await run(db, doc)
    assert result.status == "compensated"
    assert result.error is not None and result.error["error_type"] == "http_error"
    assert await ledger(db) == ["charge", "ship", "unship", "refund"]


# ── Control and integrity ───────────────────────────────────────────────────


async def test_abort_and_pause_requests(db: AsyncEngine, dev_mode: bool) -> None:
    @script("one")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        async with AsyncSession(db) as s:
            await s.exec(
                sa.update(SystemRun)
                .where(SystemRun.id == ctx.run_id)
                .values(control={"action": action})
            )  # type: ignore[call-overload,arg-type]
            await s.commit()
        return ok()

    @script("two")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return ok()

    doc = workflow(code("one", {"default": "two"}), code("two", {"default": "END"}))
    action = "pause"
    paused = await run(db, doc)
    assert paused.status == "paused" and paused.current_agent == "two" and CALLS["two"] == 0
    action = "abort"
    aborted = await run(db, doc)
    assert (
        aborted.status == "aborted"
        and aborted.error is not None
        and aborted.error["error_type"] == "aborted"
    )


async def test_journal_stays_gap_free_across_errors_pauses_and_resume(
    db: AsyncEngine, dev_mode: bool
) -> None:
    @script("one")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        ctx.session.add(Ledger(entry="one"))
        return ok(n="not an int")  # contract violation: its writes roll back

    @script("two")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        async with AsyncSession(db) as s:
            await s.exec(
                sa.update(SystemRun)
                .where(SystemRun.id == ctx.run_id)
                .values(control={"action": "pause"})
            )  # type: ignore[call-overload,arg-type]
            await s.commit()
        return ok()

    @script("three")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return ok()

    doc = workflow(
        code("one", {"default": "END", "error": "two"}, outputs={"n": "int"}),
        code("two", {"default": "three"}),
        code("three", {"default": "END"}),
    )
    paused = await run(db, doc)
    assert paused.status == "paused" and paused.current_agent == "three" and CALLS["three"] == 0
    assert paused.control is None and await ledger(db) == []
    await assert_gap_free(db, paused.id)
    async with AsyncSession(db) as s:
        assert await queue.requeue(s, paused.id)
        await s.commit()
    await drive(db, doc, owner="w2")
    final = await get(db, paused.id)
    assert final.status == "completed" and Counter({"one": 1, "two": 1, "three": 1}) == CALLS
    types = await event_types(db, final.id)
    assert types.count("agent_started") == 3 == types.count("agent_completed")
    await assert_gap_free(db, final.id)


async def test_a_pending_steer_does_not_stop_the_run(db: AsyncEngine, dev_mode: bool) -> None:
    @script("one")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return ok()

    doc = workflow(code("one", {"default": "END"}))
    run_id = await start(db, doc)
    async with AsyncSession(db) as s:
        await s.exec(
            sa.update(SystemRun)
            .where(SystemRun.id == run_id)
            .values(control={"action": "steer", "message": "be brief"})
        )  # type: ignore[call-overload,arg-type]
        await s.commit()
    await drive(db, doc)
    final = await get(db, run_id)
    assert final.status == "completed" and final.control == {
        "action": "steer",
        "message": "be brief",
    }
    await assert_gap_free(db, run_id)


async def test_an_abort_queued_before_the_first_agent_runs_nothing(
    db: AsyncEngine, dev_mode: bool
) -> None:
    @script("one")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return ok()

    doc = workflow(code("one", {"default": "END"}))
    run_id = await start(db, doc)
    async with AsyncSession(db) as s:
        await s.exec(
            sa.update(SystemRun).where(SystemRun.id == run_id).values(control={"action": "abort"})
        )  # type: ignore[call-overload,arg-type]
        await s.commit()
    await drive(db, doc)
    final = await get(db, run_id)
    assert final.status == "aborted" and CALLS["one"] == 0
    assert "agent_started" not in await event_types(db, run_id)
    await assert_gap_free(db, run_id)


async def test_changed_workflow_fails_instead_of_running_a_different_graph(db: AsyncEngine) -> None:
    doc = workflow(code("x", {"default": "END"}))
    run_id = await start(db, doc)
    changed = workflow(code("x", {"default": "END", "error": "END"}))
    await drive(db, changed)
    result = await get(db, run_id)
    assert (
        result.status == "failed"
        and result.error is not None
        and result.error["error_type"] == "workflow_changed"
    )


async def test_pending_agents_return_typed_stubs(db: AsyncEngine) -> None:
    @script("consume")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return ok(seen=f"{view['team']}|{view['score']}|{view['tags']}")

    doc = workflow(
        {
            "id": "plan",
            "description": "contract only",
            "engine": "pending",
            "outputs": {"team": "enum[billing, tech]", "score": "float", "tags": "list[str]"},
            "routes": {"default": "consume"},
        },
        code(
            "consume",
            {"default": "END", "error": "END"},
            inputs={"team": "enum[billing, tech]", "score": "float", "tags": "list[str]"},
            outputs={"seen": "str"},
        ),
        outputs={"default": {"body": "{{ seen }}"}},
    )
    assert (await run(db, doc)).output == {"status": 200, "body": "billing|0.0|[]"}


# ── transaction: per_run ────────────────────────────────────────────────────


def _writer(name: str, signal: str = "default") -> None:
    async def write(view: dict, ctx: EngineContext) -> AgentResult:
        ctx.session.add(Ledger(entry=name))
        if signal == "error":
            return AgentResult("error", error_type="db_error", message="nope")
        return ok(signal)

    SCRIPTS[name] = write


async def test_per_run_commits_every_write_at_the_end(db: AsyncEngine) -> None:
    _writer("a")
    _writer("b")
    doc = workflow(
        code("a", {"default": "b"}), code("b", {"default": "END"}), transaction="per_run"
    )
    result = await run(db, doc)
    assert result.status == "completed" and await ledger(db) == ["a", "b"]
    async with AsyncSession(db) as s:
        assert await journal.latest_checkpoint(s, result.id) is None  # nothing to resume from


async def test_per_run_failure_discards_everything_without_compensators(db: AsyncEngine) -> None:
    _writer("a")
    _writer("undo_a")
    _writer("b", signal="error")
    doc = workflow(
        code("a", {"default": "b"}, compensate="undo_a"),
        code("b", {"default": "END"}),
        code("undo_a", {"default": "END"}),
        transaction="per_run",
    )
    result = await run(db, doc)
    assert (
        result.status == "failed"
        and result.error is not None
        and result.error["error_type"] == "db_error"
    )
    assert await ledger(db) == []
    assert "compensation_started" not in await event_types(db, result.id)


async def test_per_run_rollback_end_discards_the_writes(db: AsyncEngine) -> None:
    _writer("a")
    doc = workflow(
        code("a", {"default": "END.undo"}),
        transaction="per_run",
        outputs={"default": {}, "undo": {"status": 409, "rollback": True, "body": "rolled back"}},
    )
    result = await run(db, doc)
    assert result.status == "compensated" and result.end_name == "undo"
    assert await ledger(db) == []


async def test_per_run_drops_only_a_failed_steps_writes(db: AsyncEngine) -> None:
    _writer("a", signal="error")  # routed error: its own write is discarded
    _writer("b")
    doc = workflow(
        code("a", {"default": "END", "error": "b"}),
        code("b", {"default": "END"}),
        transaction="per_run",
    )
    result = await run(db, doc)
    assert result.status == "completed" and await ledger(db) == ["b"]


async def test_per_run_retries_do_not_duplicate_writes(db: AsyncEngine) -> None:
    @script("flaky_writer")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        ctx.session.add(Ledger(entry=f"attempt-{CALLS['flaky_writer']}"))
        if CALLS["flaky_writer"] < 3:
            return AgentResult("error", error_type="transient", message="503")
        return ok()

    import tuvl.runtime.runner as runner_mod

    runner_mod._BACKOFF_BASE_SECONDS = 0.01
    doc = workflow(
        code(
            "flaky_writer",
            {"default": "END", "error": "END"},
            budget={"retry": {"attempts": 3, "errors": ["transient"]}},
        ),
        transaction="per_run",
    )
    assert (await run(db, doc)).status == "completed"
    assert await ledger(db) == ["attempt-3"]


async def test_per_run_crash_commits_nothing_and_reruns_from_the_start(
    db: AsyncEngine, dev_mode: bool
) -> None:
    gate = asyncio.Event()

    @script("first")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        ctx.session.add(Ledger(entry="first"))
        return ok()

    @script("second")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        if CALLS["second"] == 1:
            await gate.wait()  # the first worker dies here
        ctx.session.add(Ledger(entry="second"))
        return ok()

    doc = workflow(
        code("first", {"default": "second"}),
        code("second", {"default": "END"}),
        transaction="per_run",
    )
    run_id = await start(db, doc)
    doomed = Worker(
        db, Runner(db, {"wf": doc}), owner="doomed", lease_seconds=0.3, heartbeat_seconds=10
    )
    await doomed.claim_some()
    while CALLS["second"] < 1:
        await asyncio.sleep(0.02)
    assert await ledger(db) == []  # nothing visible mid-run
    for task in list(doomed._active.values()):
        task.cancel()
    await asyncio.sleep(0.4)
    await drive(db, doc, owner="survivor")
    final = await get(db, run_id)
    assert final.status == "completed" and await ledger(db) == ["first", "second"]
    assert Counter({"first": 2, "second": 2}) == CALLS  # per_run reruns everything


# ── Per-run work happens once per load, not per step ────────────────────────


async def test_a_step_costs_five_statements(
    db: AsyncEngine, dev_mode: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``agent_started`` (with the control read) is one UPDATE and one INSERT; completion
    is one fenced UPDATE taking both sequence numbers, then the event and checkpoint.
    Dev mode reads ``control`` on its own first (breakpoints are checked after it)."""
    for name in ("a", "b", "c"):

        @script(name)
        async def _(view: dict, ctx: EngineContext) -> AgentResult:
            return ok()

    seen: list[str] = []

    def count(conn: Any, cursor: Any, statement: str, *_: Any) -> None:
        seen.append(statement)

    async def statements(doc: WorkflowDocument) -> int:
        await start(db, doc)
        # the draft sweep runs once a minute per process; its DELETE is not part of a step
        monkeypatch.setattr(deltas, "_last_sweep", time.monotonic())
        seen.clear()
        sa.event.listen(db.sync_engine, "before_cursor_execute", count)
        try:
            await drive(db, doc)
        finally:
            sa.event.remove(db.sync_engine, "before_cursor_execute", count)
        return len(seen)

    one = await statements(workflow(code("a", {"default": "END"})))
    three = await statements(
        workflow(
            code("a", {"default": "b"}), code("b", {"default": "c"}), code("c", {"default": "END"})
        )
    )
    assert (three - one) / 2 == (6 if dev_mode else 5)


async def test_hash_and_depth_are_computed_once_per_load(
    db: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tuvl.runtime import runner as runner_mod

    depths: list[int] = []

    for name in ("a", "b", "c"):

        @script(name)
        async def _(view: dict, ctx: EngineContext) -> AgentResult:
            depths.append(ctx.depth)
            return ok(n=view["n"] + 1)

    doc = workflow(
        code("a", {"default": "b"}, inputs={"n": "int"}, outputs={"n": "int"}),
        code("b", {"default": "c"}, inputs={"n": "int"}, outputs={"n": "int"}),
        code("c", {"default": "END"}, inputs={"n": "int"}, outputs={"n": "int"}),
        trigger={"input": {"n": "int"}},
        outputs={"default": {"body": {"n": "{{ n }}"}}},
    )
    digest = workflow_hash(doc)
    grandparent, parent = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(db) as s:
        s.add(
            SystemRun(
                id=grandparent, workflow="wf", workflow_hash=digest, trigger="t", status="running"
            )
        )
        s.add(
            SystemRun(
                id=parent,
                workflow="wf",
                workflow_hash=digest,
                trigger="t",
                status="running",
                parent_run_id=grandparent,
            )
        )
        await s.commit()
        run_id = await queue.enqueue(
            s,
            workflow="wf",
            workflow_hash=digest,
            trigger="t",
            input={"n": 0},
            parent_run_id=parent,
        )
        await s.commit()

    hashes = Counter[int]()
    real_hash = runner_mod.workflow_hash

    def counted(d: WorkflowDocument) -> str:
        hashes[id(d)] += 1
        return real_hash(d)

    monkeypatch.setattr(runner_mod, "workflow_hash", counted)
    real_depth = Runner.depth_of
    depth_calls = [0]

    async def counted_depth(self: Runner, run: SystemRun, s: Any) -> int:
        depth_calls[0] += 1
        return await real_depth(self, run, s)

    monkeypatch.setattr(Runner, "depth_of", counted_depth)
    await drive(db, doc)
    final = await get(db, run_id)
    assert final.status == "completed" and final.output["body"] == {"n": 3}
    assert depths == [2, 2, 2]
    assert sum(hashes.values()) == 1  # the load check; contract models reuse it
    assert depth_calls == [1]


async def test_a_changed_workflow_gets_fresh_contract_models(db: AsyncEngine) -> None:
    @script("a")
    async def _(view: dict, ctx: EngineContext) -> AgentResult:
        return ok(n=view["n"])

    def doc_with(out: str) -> WorkflowDocument:
        return workflow(
            code(
                "a",
                {"default": "END", "error": "END.failed"},
                inputs={"n": "int"},
                outputs={"n": out},
            ),
            trigger={"input": {"n": "int"}},
            outputs={"default": {"body": {"n": "{{ n }}"}}, "failed": {"status": 500}},
        )

    runner = Runner(db, {})
    for out, end in (("int", "default"), ("str", "failed")):
        doc = doc_with(out)
        runner.workflows = {"wf": doc}
        run_id = await start(db, doc, {"n": 5})
        worker = Worker(db, runner, owner="w1")
        while await worker.claim_some():
            await worker.drain()
        assert (await get(db, run_id)).end_name == end
