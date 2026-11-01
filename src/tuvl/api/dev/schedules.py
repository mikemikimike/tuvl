"""Cron preview and the schedules the project declares."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from tuvl.core.config import settings

router = APIRouter()


@router.get("/schedule/preview", summary="Validate a cron expression and list its next fire times")
async def schedule_preview(cron: str, count: int = Query(default=5, ge=1, le=20)) -> dict[str, Any]:
    from cronsim import CronSimError

    from tuvl.core.engine.scheduler import upcoming

    if len(cron.split()) != 5:
        return {
            "ok": False,
            "error": "Cron needs 5 fields: minute hour day-of-month month day-of-week",
        }
    try:
        fires = upcoming(cron, count)
    except CronSimError as exc:
        return {"ok": False, "error": f"invalid cron expression: {exc}"}
    return {"ok": True, "next": [t.isoformat() for t in fires]}


@router.get(
    "/schedules", summary="Scheduled workflows: next fire, last run, and why one won't fire"
)
async def schedules() -> dict[str, Any]:
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import AsyncSession

    from tuvl.contract.registry import WORKFLOWS
    from tuvl.core.engine import scheduler
    from tuvl.runtime.host import get_host
    from tuvl.runtime.models import SystemRun

    multi_tenant = scheduler._multi_tenant()
    firing = scheduler.schedulable() if settings.tuvl_scheduler_enabled else {}
    host = get_host()
    out = []
    for name, doc in sorted(WORKFLOWS.items()):
        schedule = doc.spec.trigger.schedule
        if schedule is None:
            continue
        warnings = []
        if not doc.enabled:
            warnings.append("the workflow is disabled")
        if schedule.enabled and multi_tenant and not doc.spec.trigger.tenants:
            warnings.append("multi_tenant mode: list the tenants in trigger.tenants")
        last = None
        if not multi_tenant:
            async with AsyncSession(host.engine) as session:
                row = (
                    await session.execute(
                        sa.select(SystemRun)
                        .where(SystemRun.workflow == name, SystemRun.trigger.like("schedule:%"))  # type: ignore[attr-defined,arg-type]
                        .order_by(SystemRun.created_at.desc())  # type: ignore[attr-defined]
                        .limit(1)
                    )
                ).scalar_one_or_none()
            if row is not None:
                last = {
                    "run_id": str(row.id),
                    "status": row.status,
                    "at": row.created_at.isoformat(),
                }
        out.append(
            {
                "workflow": name,
                "cron": schedule.cron,
                "enabled": schedule.enabled,
                "firing": name in firing,
                "next": [t.isoformat() for t in scheduler.upcoming(schedule.cron, 3)]
                if name in firing
                else [],
                "tenants": list(doc.spec.trigger.tenants),
                "last_run": last,
                "warnings": warnings,
            }
        )
    return {
        "scheduler": {"enabled": settings.tuvl_scheduler_enabled, "multi_tenant": multi_tenant},
        "workflows": out,
    }
