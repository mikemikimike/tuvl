"""The ``map`` engine: run a child workflow once per item of a list, with bounded concurrency.

Each item is a child run (``parent_run_id`` = this run) keyed ``<agent>:<index>``, so it is
journaled and replayable on its own, and an agent that runs again after a crash follows the
children it already started instead of starting new ones. ``on_error: fail`` stops starting
items at the first failure and fails the agent; ``collect`` runs every item and reports
``partial`` when some failed. An item succeeds when its child run completes on an end whose
status is below 400; its result is that end's ``body``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from tuvl.runtime.engines import (
    AgentResult,
    EngineContext,
    EngineError,
    register_engine,
    render_params,
)


@dataclass
class _Item:
    ok: bool = False
    body: Any = None
    run_id: str | None = None
    reason: str = ""
    tokens: int = 0
    started: bool = False


def _outcome(child: Any) -> tuple[bool, str]:
    """Whether the child run counts as a success, and why not."""
    if child.status != "completed":
        if child.status.startswith("waiting_") or child.status == "paused":
            return (
                False,
                f"the child run is {child.status}; a mapped workflow must finish on its own",
            )
        error = child.error if isinstance(child.error, dict) else {}
        return False, str(error.get("message") or error.get("error_type") or child.status)
    status = (child.output or {}).get("status", 200)
    if isinstance(status, int) and status >= 400:
        return False, f"the child run ended with status {status}"
    return True, ""


async def _cause(ctx: EngineContext, child: Any) -> str:
    """The error the child's own journal recorded, for a child that ended on a failure end."""
    from tuvl.runtime import journal

    try:
        events = await journal.events(ctx.session, child.id)
    except Exception:  # the reason is a courtesy; never let it fail the item
        return ""
    for event in reversed(events):
        payload = event.payload or {}
        if event.type == "agent_completed" and payload.get("signal") == "error":
            where = f"{event.agent_id}: " if event.agent_id else ""
            return (
                f"{where}{payload.get('error_type', 'error')}: {payload.get('message', '')}".strip(
                    ": "
                )
            )
    return ""


async def map_engine(agent: Any, view: dict[str, Any], ctx: EngineContext) -> AgentResult:
    p = agent.map
    items = view.get(p.over)
    if not isinstance(items, list):
        raise EngineError("tool_args_invalid", f"'{p.over}' is not a list")
    if len(items) > p.max_items:
        raise EngineError(
            "map_too_many_items", f"{len(items)} items exceed map.max_items ({p.max_items})"
        )
    run_child = ctx.run_child
    if run_child is None:
        raise EngineError("contract_violation", "child runs are not available")
    max_depth = ctx.workflow.spec.policy.max_depth
    if ctx.depth + 1 > max_depth:
        raise EngineError(
            "max_depth", f"nesting depth {ctx.depth + 1} exceeds policy.max_depth {max_depth}"
        )

    extra = render_params(p.with_, view)
    slots = [_Item() for _ in items]
    gate = asyncio.Semaphore(p.concurrency)
    stop = asyncio.Event()
    await ctx.emit(
        "map_started",
        payload={"workflow": p.workflow, "items": len(items), "concurrency": p.concurrency},
    )

    async def run_item(index: int, item: Any) -> None:
        slot = slots[index]
        async with gate:
            if stop.is_set():
                return
            slot.started = True
            try:
                child = await run_child(
                    ctx.run_id,
                    p.workflow,
                    {**extra, p.as_: item},
                    ctx.principal,
                    key=f"{agent.id}:{index}",
                )
            except ValueError as exc:  # the item does not fit the child's input
                slot.reason = str(exc)
            else:
                slot.run_id = str(child.id)
                slot.tokens = int(child.tokens_used or 0)
                slot.ok, slot.reason = _outcome(child)
                if slot.ok:
                    slot.body = (child.output or {}).get("body")
                elif child.status == "completed":
                    cause = await _cause(ctx, child)
                    if cause:
                        slot.reason = f"{slot.reason} ({cause})"
            if not slot.ok and p.on_error == "fail":
                stop.set()  # while still holding the slot, so the next item sees it
        await ctx.emit(
            "map_item",
            payload={"index": index, "run_id": slot.run_id, "ok": slot.ok, "reason": slot.reason},
        )

    await asyncio.gather(*(run_item(i, item) for i, item in enumerate(items)))

    tokens = sum(s.tokens for s in slots)
    failed = [i for i, s in enumerate(slots) if s.started and not s.ok]
    skipped = sum(1 for s in slots if not s.started)
    detail = {
        "items": len(items),
        "failed": failed,
        "skipped": skipped,
        "runs": [s.run_id for s in slots],
    }
    await ctx.emit(
        "map_finished",
        payload={"items": len(items), "failed": len(failed), "skipped": skipped},
    )
    if failed and p.on_error == "fail":
        first = failed[0]
        return AgentResult(
            "error",
            error_type="map_item_failed",
            message=f"item {first} failed: {slots[first].reason} "
            f"({len(failed)} failed, {skipped} not started of {len(items)})",
            tokens=tokens,
            detail=detail,
        )
    signal = "partial" if failed and "partial" in agent.routes else "default"
    key = next(iter(agent.outputs_for(signal)), None)
    outputs = {key: [s.body if s.ok else None for s in slots]} if key else {}
    return AgentResult(signal, outputs=outputs, tokens=tokens, detail=detail)


register_engine("map", map_engine)
