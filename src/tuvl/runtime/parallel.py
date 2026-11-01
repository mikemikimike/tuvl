"""The ``parallel`` engine: run several different read-only agents at the same time and join them.

Each branch runs its own engine in a session of its own (the step's session is not safe to share),
with the idempotency key ``<step key>:<branch id>``. A branch succeeds when it ends on ``default``;
anything else (an error, a timeout, another signal) is a failure. ``on_error: fail`` stops the
branches still running at the first failure and fails the agent; ``collect`` lets every branch finish
and reports ``partial`` (when routed) with the failed branches' outputs left out. The agent's outputs
are those of all branches together. The step's own timeout (``budget.timeout``) cancels every branch.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from tuvl.contract.signals import is_reserved
from tuvl.runtime.engines import (
    ENGINES,
    AgentResult,
    EngineContext,
    EngineError,
    register_engine,
)


@dataclass
class _Branch:
    ok: bool = False
    outputs: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    tokens: int = 0
    started: bool = False
    ms: int = 0


async def parallel_engine(agent: Any, view: dict[str, Any], ctx: EngineContext) -> AgentResult:
    p = agent.parallel
    bind = ctx.session.bind
    if bind is None:
        raise EngineError("contract_violation", "a parallel step needs a database connection")
    branches = list(p.branches)
    slots = {b.id: _Branch() for b in branches}
    gate = asyncio.Semaphore(p.concurrency or len(branches))
    stop = asyncio.Event()
    await ctx.emit(
        "parallel_started",
        payload={"branches": [b.id for b in branches], "on_error": p.on_error},
    )

    async def run_branch(branch: Any) -> None:
        slot = slots[branch.id]
        async with gate:
            if stop.is_set():
                return
            slot.started = True
            began = time.monotonic()
            async with AsyncSession(bind, expire_on_commit=False) as session:
                sub = EngineContext(
                    run_id=ctx.run_id,
                    workflow=ctx.workflow,
                    session=session,
                    principal=ctx.principal,
                    idempotency_key=f"{ctx.idempotency_key}:{branch.id}",
                    resolver=ctx.resolver,
                    emit=_tagged(ctx, branch.id),
                    run_child=ctx.run_child,
                    depth=ctx.depth,
                    workflows=ctx.workflows,
                )
                try:
                    engine = ENGINES.get(branch.engine)
                    if engine is None:
                        raise EngineError(
                            "engine_unavailable", f"no '{branch.engine}' engine is installed"
                        )
                    branch_view = {k: view.get(k) for k in branch.inputs}
                    result = await engine(branch, branch_view, sub)
                except EngineError as exc:
                    slot.reason = f"{exc.error_type}: {exc}"
                except Exception as exc:
                    slot.reason = f"{type(exc).__name__}: {exc}"
                else:
                    slot.tokens = result.tokens
                    if result.signal == "default":
                        slot.ok, slot.outputs = True, result.outputs
                    elif is_reserved(result.signal):
                        slot.reason = (
                            f"{result.error_type or result.signal}: {result.message or ''}".strip(
                                ": "
                            )
                        )
                    else:
                        slot.reason = f"emitted '{result.signal}'; a branch can only end on default"
            slot.ms = int((time.monotonic() - began) * 1000)
            if not slot.ok and p.on_error == "fail":
                stop.set()
                for task in tasks:
                    if task is not asyncio.current_task():
                        task.cancel()
        await ctx.emit(
            "parallel_branch",
            payload={
                "branch": branch.id,
                "ok": slot.ok,
                "ms": slot.ms,
                "tokens": slot.tokens,
                "reason": slot.reason,
            },
        )

    tasks = [asyncio.ensure_future(run_branch(b)) for b in branches]
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:  # the step's own timeout: take every branch down with it
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    tokens = sum(s.tokens for s in slots.values())
    failed = [b.id for b in branches if not slots[b.id].ok]
    detail = {
        "branches": {
            b.id: {"ok": s.ok, "ms": s.ms, "tokens": s.tokens, "reason": s.reason}
            for b in branches
            for s in (slots[b.id],)
        }
    }
    await ctx.emit("parallel_finished", payload={"failed": failed, "branches": len(branches)})
    if failed and p.on_error == "fail":
        first = failed[0]
        started = slots[first].started
        return AgentResult(
            "error",
            error_type="parallel_branch_failed",
            message=f"branch '{first}' {'failed' if started else 'did not run'}: "
            f"{slots[first].reason or 'cancelled'} ({len(failed)} of {len(branches)} failed)",
            tokens=tokens,
            detail=detail,
        )
    signal = "partial" if failed and "partial" in agent.routes else "default"
    outputs: dict[str, Any] = {}
    for b in branches:
        outputs.update(slots[b.id].outputs)
    wanted = set(agent.outputs_for(signal))
    for name in wanted:
        outputs.setdefault(name, None)
    return AgentResult(
        signal,
        outputs={k: v for k, v in outputs.items() if k in wanted},
        tokens=tokens,
        detail=detail,
    )


def _tagged(ctx: EngineContext, branch: str) -> Any:
    async def emit(type: str, **kw: Any) -> int:
        payload = {**(kw.pop("payload", None) or {}), "branch": branch}
        return await ctx.emit(type, payload=payload, **kw)

    return emit


register_engine("parallel", parallel_engine)
