"""Webhooks: a minimal, signed notification when a run reaches a declared stage.

A workflow declares its receivers in ``spec.webhooks`` (see :class:`tuvl.contract.schema.Webhook`).
When the journal records a matching event, a row is written to the outbox in the same transaction;
the dispatcher (:mod:`tuvl.webhooks.dispatcher`) sends it later. The notification names the run and
what happened and nothing else, so the receiver pulls the run with its own token.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from tuvl.contract.schema import WorkflowDocument
from tuvl.runtime.models import SystemRun, SystemWebhookDelivery

#: journal event → notification type
SOURCES: dict[str, str] = {
    "run_completed": "run.completed",
    "run_failed": "run.failed",
    "run_aborted": "run.aborted",
    "approval_requested": "run.waiting",
    "agent_completed": "agent.completed",
}
_ON = {
    "run.completed": "completed",
    "run.failed": "failed",
    "run.aborted": "aborted",
    "run.waiting": "waiting",
}


def enabled() -> bool:
    from tuvl.core.config import settings

    return bool(settings.tuvl_webhooks_enabled)


def registry() -> Mapping[str, WorkflowDocument]:
    from tuvl.contract.registry import WORKFLOWS

    try:
        from tuvl.runtime.host import get_host

        return get_host().registry()
    except Exception:  # no host (offline tooling): the loaded registry
        return WORKFLOWS


async def record(
    session: AsyncSession,
    run_id: uuid.UUID,
    event_type: str,
    seq: int,
    agent_id: str | None,
    *,
    workflow: str | None = None,
) -> int:
    """Queue a notification for every declared webhook that wants this event. The caller commits.
    *workflow* is the run's workflow when the caller knows it; otherwise the run is looked up."""
    kind = SOURCES.get(event_type)
    if kind is None or not enabled():
        return 0
    workflows = registry()
    if workflow is None:
        if not any(d.spec.webhooks for d in workflows.values()):
            return 0
        run = await session.get(SystemRun, run_id)
        workflow = run.workflow if run is not None else None
    doc = workflows.get(workflow) if workflow is not None else None
    if doc is None or not doc.spec.webhooks:
        return 0
    queued = 0
    for hook in doc.spec.webhooks:
        wanted = agent_id in hook.stages if kind == "agent.completed" else _ON[kind] in hook.events
        if not wanted:
            continue
        session.add(
            SystemWebhookDelivery(
                run_id=run_id,
                workflow=doc.metadata.name,
                webhook=hook.name,
                type=kind,
                seq=seq,
                agent_id=agent_id if kind in ("agent.completed", "run.waiting") else None,
            )
        )
        queued += 1
    return queued


def notification(row: Any) -> bytes:
    """The request body. Stable across retries, so a receiver can de-duplicate on ``id``."""
    body: dict[str, Any] = {
        "id": str(row.id),
        "type": row.type,
        "created_at": row.created_at.isoformat(),
        "workflow": row.workflow,
        "run_id": str(row.run_id),
        "seq": row.seq,
    }
    if row.agent_id:
        body["agent"] = row.agent_id
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
