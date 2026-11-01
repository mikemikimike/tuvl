"""Hooks — artifact-backed, observe-only lifecycle events.

A ``type: hook`` artifact declares one lifecycle subscription::

    kind: Artifact
    metadata: { name: audit-tool-calls }
    spec:
      type: hook
      on: after_tool        # before_step | after_step | before_tool | after_tool | on_error
      action: log           # log | metric | notify
      target: alert_ops     # notify only — a declared APICall step in the workflow

Attached per step (``hooks: […]``) or workflow-wide (``spec.hooks:``). Hooks
never mutate context and never affect flow control — that's what guardrails
and the supervisor are for; a failing hook is logged and swallowed. ``notify``
fires a declared ``APICall`` component (author-declared, the same trust model
as agent tools) with the event payload merged into a private context copy.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from opentelemetry import metrics

from tuvl.core.artifacts.registry import ArtifactResolutionError, resolve_structured

logger = structlog.get_logger(__name__)

_meter = metrics.get_meter("tuvl.hooks")
HOOK_EVENTS_COUNTER = _meter.create_counter(
    "tuvl.hook.events", description="Workflow lifecycle hook firings"
)

#: Closed set of lifecycle events a hook may subscribe to.
HOOK_EVENTS: frozenset[str] = frozenset(
    {"before_step", "after_step", "before_tool", "after_tool", "on_error"}
)

#: Closed set of hook actions.
HOOK_ACTIONS: frozenset[str] = frozenset({"log", "metric", "notify"})

# Runs the declared notify target (an APICall component) with the event payload.
NotifyRunner = Callable[[dict[str, Any], dict[str, Any]], Awaitable[None]]


async def emit_hooks(
    refs: list[str],
    event: str,
    *,
    workflow: str,
    step_id: str,
    detail: dict[str, Any] | None = None,
    notify_runner: NotifyRunner | None = None,
) -> None:
    """Fire every referenced hook subscribed to *event*. Never raises."""
    for ref in refs:
        name = str(ref).removeprefix("artifact://").split("@")[0]
        try:
            spec = resolve_structured(
                ref, site="hooks", where=f"[{workflow}] step '{step_id}' hooks"
            )
        except ArtifactResolutionError as exc:
            logger.warning("hook.unresolved", hook=name, error=str(exc))
            continue
        if spec.get("on") != event:
            continue
        action = str(spec.get("action") or "log")
        payload = {
            "hook": name,
            "event": event,
            "workflow": workflow,
            "step_id": step_id,
            **(detail or {}),
        }
        try:
            if action == "metric":
                HOOK_EVENTS_COUNTER.add(
                    1,
                    {
                        "tuvl.hook.name": name,
                        "tuvl.hook.event": event,
                        "tuvl.workflow.name": workflow,
                    },
                )
            elif action == "notify":
                if notify_runner is None:
                    logger.warning("hook.notify_unavailable", hook=name, event=event)
                else:
                    await notify_runner(spec, payload)
            else:
                logger.info("workflow.hook", **payload)
        except Exception as exc:  # a hook must never affect the run
            logger.warning("hook.failed", hook=name, event=event, exc_type=type(exc).__name__)
