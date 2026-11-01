"""TD-40: in multi-tenant mode runs carry their tenant, workers execute them under it, and a
schedule fans out one run per listed tenant.

The mode decides the system tables' columns when their models are imported, so the scenario runs
in a fresh interpreter against a throwaway database and reports what it saw as JSON.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import uuid

import pytest
from sqlalchemy.engine import make_url

SCENARIO = textwrap.dedent(
    """
    import asyncio, json, sys
    from datetime import UTC, datetime

    import tuvl.core.bootstrap as bootstrap
    bootstrap.LOCKED_DEPLOYMENT_MODE = "multi_tenant"

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlmodel import SQLModel

    from tuvl.contract import registry
    from tuvl.contract.schema import WorkflowDocument
    from tuvl.core.context import current_tenant_id
    from tuvl.core.datasources import postgres
    from tuvl.core.engine import scheduler
    from tuvl.runtime import models, queue
    from tuvl.runtime.host import RuntimeHost, set_host
    from tuvl.tenancy import tenant_scope

    out = {}

    def wf(name, trigger):
        return WorkflowDocument.model_validate({
            "kind": "Workflow", "version": "tuvl/v2", "metadata": {"name": name},
            "spec": {"trigger": trigger, "agents": [{
                "id": "a", "description": "d", "engine": "pending", "routes": {"default": "END"}}]},
        })

    async def main():
        engine = create_async_engine(sys.argv[1])
        tables = [m.__table__ for m in models.RUNTIME_TABLES]

        # a database first booted in multi-tenant mode by an earlier build: no tenant_id column
        async with engine.begin() as c:
            await c.run_sync(lambda sc: SQLModel.metadata.create_all(sc, tables=tables))
        async with engine.begin() as c:
            for t in tables:
                await c.execute(text(f'ALTER TABLE "{t.name}" DROP COLUMN IF EXISTS tenant_id'))
        out["columns_before"] = await columns(engine)

        bootstrap._inject_tenant_columns_into_system_tables()
        postgres._PRIMARY_DS = "default"
        postgres._engines_rw["default"] = engine
        await postgres.ensure_tenant_columns()
        out["columns_after"] = await columns(engine)

        # the engine hook puts the bound tenant into the transaction's RLS variable
        queue.bind_engine_tenant(engine)
        async def guc():
            async with AsyncSession(engine) as s:
                return (await s.execute(text("select current_setting('app.current_tenant_id', true)"))).scalar()
        with tenant_scope("acme"):
            out["guc_in_scope"] = await guc()
        out["guc_outside"] = await guc()

        # a run needs a tenant
        try:
            async with AsyncSession(engine) as s:
                await queue.enqueue(s, workflow="w", workflow_hash="h", trigger="t", input={})
            out["no_tenant"] = "accepted"
        except postgres.MissingTenantContextError:
            out["no_tenant"] = "refused"

        # a worker executes each run under its own tenant
        seen = {}
        async def executor(run_id, lease):
            async with AsyncSession(engine) as s:
                seen[str(run_id)] = [current_tenant_id.get(""), (await s.execute(text(
                    "select current_setting('app.current_tenant_id', true)"))).scalar()]
                await queue.release(s, run_id, lease.owner, "completed")
                await s.commit()
        ids = {}
        for tenant in ("acme", "globex"):
            with tenant_scope(tenant):
                async with AsyncSession(engine) as s:
                    ids[tenant] = str(await queue.enqueue(
                        s, workflow="w", workflow_hash="h", trigger="t", input={}))
                    await s.commit()
        worker = queue.Worker(engine, executor, owner="w1")
        await worker.claim_some()
        await worker.drain()
        out["executed_as"] = {t: seen[i] for t, i in ids.items()}

        # a schedule fans out one run per tenant, once per fire
        nightly = wf("nightly", {"schedule": "0 6 * * *", "tenants": ["acme", "globex"]})
        orphan = wf("orphan", {"schedule": "0 7 * * *"})
        registry.WORKFLOWS.update({"nightly": nightly, "orphan": orphan})
        set_host(RuntimeHost(engine, workflows={"nightly": nightly, "orphan": orphan}))
        out["schedulable"] = sorted(scheduler.schedulable())
        fire = datetime(2026, 10, 18, 6, 0, tzinfo=UTC)
        await scheduler._fire("nightly", fire)
        await scheduler._fire("nightly", fire)  # a second process: no duplicates
        async with engine.connect() as c:
            rows = (await c.execute(text(
                "select tenant_id, trigger from tuvl_system_runs where workflow = 'nightly' order by tenant_id"))).all()
            ev = (await c.execute(text(
                "select distinct e.tenant_id from tuvl_system_run_events e join tuvl_system_runs r on r.id = e.run_id "
                "where r.workflow = 'nightly'"))).all()
        out["scheduled"] = [[t, trig] for t, trig in rows]
        out["scheduled_event_tenants"] = sorted(r[0] for r in ev)
        out["run_tenants"] = {t: (await tenant_of(engine, i)) for t, i in ids.items()}

        # one tenant never reaches another's runs, whatever its scopes
        import httpx
        from fastapi import FastAPI
        from tuvl.api import runs as runs_api
        from tuvl.core.auth.schemas import TokenUser

        scopes = ["iam:admin", "runs:read", "runs:control"]
        users = {
            "acme": TokenUser(user_id="a1", scopes=scopes, tenant_id="acme"),
            "globex": TokenUser(user_id="g1", scopes=scopes, tenant_id="globex"),
        }

        async def fake_user(request):
            return users.get(request.headers.get("x-user"))

        runs_api.current_user = fake_user
        app = FastAPI()
        app.include_router(runs_api.router)
        api = {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            acme_run, globex_run = ids["acme"], ids["globex"]
            for who, run, label in (("globex", acme_run, "globex_reads_acme"), ("acme", acme_run, "acme_reads_acme")):
                api[label] = (await client.get(f"/api/runs/{run}", headers={"x-user": who})).status_code
            api["globex_aborts_acme"] = (
                await client.post(f"/api/runs/{acme_run}/abort", headers={"x-user": "globex"})
            ).status_code
            api["acme_aborts_own"] = (
                await client.post(f"/api/runs/{acme_run}/abort", headers={"x-user": "acme"})
            ).status_code
            listed = (await client.get("/api/runs", headers={"x-user": "globex"})).json()
            api["globex_list"] = sorted({r["run_id"] for r in listed})
        out["api"] = api
        out["globex_run_id"] = ids["globex"]
        out["run_tenants_ids"] = ids

    async def columns(engine):
        async with engine.connect() as c:
            rows = (await c.execute(text(
                "select table_name from information_schema.columns where column_name = 'tenant_id' "
                "and table_name like 'tuvl_system_run%' or (column_name='tenant_id' and table_name='tuvl_system_approvals')"))).all()
        return sorted(r[0] for r in rows)

    async def tenant_of(engine, run_id):
        async with engine.connect() as c:
            return (await c.execute(text("select tenant_id from tuvl_system_runs where id = :i"), {"i": run_id})).scalar()

    asyncio.run(main())
    print("RESULT " + json.dumps(out))
    """
)


def _urls() -> tuple[str, str, str]:
    base = os.environ.get("TUVL_TEST_PG_URL")
    if not base:
        pytest.skip("TUVL_TEST_PG_URL is not set")
    url = make_url(base)
    scratch = f"tuvl_mt_{uuid.uuid4().hex[:10]}"
    admin = url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )
    return admin, scratch, url.set(database=scratch).render_as_string(hide_password=False)


async def test_runs_carry_their_tenant_and_schedules_fan_out() -> None:
    asyncpg = pytest.importorskip("asyncpg")
    admin, scratch, url = _urls()
    try:
        conn = await asyncpg.connect(admin.replace("postgresql://", "postgresql://", 1))
    except Exception as exc:  # unreachable Postgres, like the pg_engine fixture
        pytest.skip(f"Postgres not available ({type(exc).__name__})")
    await conn.execute(f'CREATE DATABASE "{scratch}"')
    try:
        proc = subprocess.run(
            [sys.executable, "-c", SCENARIO, url],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        await conn.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
        await conn.close()
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-3000:]
    line = next(x for x in proc.stdout.splitlines() if x.startswith("RESULT "))
    got = json.loads(line.removeprefix("RESULT "))

    tables = [
        "tuvl_system_approvals",
        "tuvl_system_run_checkpoints",
        "tuvl_system_run_deltas",
        "tuvl_system_run_events",
        "tuvl_system_runs",
    ]
    assert got["columns_before"] == []  # the premise: an earlier build left no column
    assert got["columns_after"] == tables  # ensure_tenant_columns added it everywhere
    assert got["guc_in_scope"] == "acme" and got["guc_outside"] in (None, "")
    assert got["no_tenant"] == "refused"
    assert got["executed_as"] == {"acme": ["acme", "acme"], "globex": ["globex", "globex"]}
    assert got["run_tenants"] == {"acme": "acme", "globex": "globex"}
    assert got["schedulable"] == ["nightly"]  # the workflow with no tenants is not scheduled
    assert [t for t, _ in got["scheduled"]] == ["acme", "globex"]  # once each, never twice
    assert all(trigger.startswith("schedule:") for _, trigger in got["scheduled"])
    assert got["scheduled"][0][1].endswith(":acme") and got["scheduled"][1][1].endswith(":globex")
    assert got["scheduled_event_tenants"] == ["acme", "globex"]

    api = got["api"]
    assert api["globex_reads_acme"] == 404  # admin scope does not cross tenants
    assert api["acme_reads_acme"] == 200
    assert api["globex_aborts_acme"] == 404  # nor does runs:control
    assert api["acme_aborts_own"] == 409  # reachable, but already completed
    assert got["globex_run_id"] in api["globex_list"]
    assert not set(api["globex_list"]) & {got["run_tenants_ids"]["acme"]}
