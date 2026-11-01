"""System Ledger & Pre-flight Bootstrapper.

Establishes the **immutable deployment mode** (``single_tenant`` /
``multi_tenant``) by locking it into the ``tuvl_system_registry`` Postgres table
on first (greenfield) boot, and then validating it on every subsequent
(brownfield) boot.

The ``LOCKED_DEPLOYMENT_MODE`` module-level constant is the single source of
truth for all runtime branching.  It is set exactly once — during the FastAPI
lifespan, before ``init_db()`` creates application tables — and is thereafter
read-only.

Boot sequence
-------------
1. ``app.py`` lifespan calls ``load_all_configs()`` → populates
   ``DATASOURCE_REGISTRY`` and ``PRIMARY_DS``.
2. Lifespan calls ``await run_pre_flight()`` → resolves and locks the mode.
3. Lifespan calls ``await init_db()`` → creates application tables.  Any
   system model that inherits from ``DynamicTenantModel`` and is lazily
   imported inside ``init_db()`` will automatically receive the ``tenant_id``
   column because ``LOCKED_DEPLOYMENT_MODE`` is already set.

Mode resolution order
---------------------
1. **Database lock (strongest)** — if ``tuvl_system_registry`` already exists,
   its ``deployment_mode`` row is the final truth.  A mismatch between the
   database value and ``.tuvl/system.yaml`` is logged as a warning; the
   database value always wins.
2. **``.tuvl/system.yaml``** — written by ``tuvl init [--multi-tenant]``.
   Read on greenfield (first-ever) boot to seed the database lock.
3. **Default (single_tenant)** — when no DB and no system.yaml exist (e.g.
   development without a DB configured), the engine boots silently as
   ``single_tenant`` with no DB lock.

The deprecated ``TUVL_MODE`` environment variable is no longer supported.
Use ``tuvl init --multi-tenant`` to configure multi-tenancy at project
creation time.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

import sqlalchemy as sa
import yaml
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Field, SQLModel, col

from tuvl.core.logger import logger
from tuvl.core.models.tables import table_of
from tuvl.core.system_config import SYSTEM_YAML_RELPATH

# ── Module-level deployment mode lock ────────────────────────────────────────
# Default is single_tenant.  Overwritten once by run_pre_flight().
# All other modules must import this module and read ``LOCKED_DEPLOYMENT_MODE``
# at call time (not at import time) to see the resolved value.
LOCKED_DEPLOYMENT_MODE: str = "single_tenant"

VALID_DEPLOYMENT_MODES: frozenset[str] = frozenset({"single_tenant", "multi_tenant"})
_REGISTRY_TABLE = "tuvl_system_registry"
_DEPLOYMENT_MODE_KEY = "deployment_mode"
_SYSTEM_YAML_RELPATH = SYSTEM_YAML_RELPATH


# ── System Registry SQLModel ──────────────────────────────────────────────────


class SystemRegistry(SQLModel, table=True):
    """Persistent key-value store for immutable system configuration.

    Created on first boot; validated on every subsequent boot.
    The ``deployment_mode`` row is written once and never mutated.
    """

    __tablename__ = _REGISTRY_TABLE
    __table_args__ = {"extend_existing": True}

    key: str = Field(
        sa_column=sa.Column(sa.String, primary_key=True, nullable=False),
    )
    value: str = Field(
        sa_column=sa.Column(sa.String, nullable=False),
    )


# ── system.yaml reader ────────────────────────────────────────────────────────


def _read_system_yaml_mode() -> str:
    """Read ``deployment_mode`` from ``.tuvl/system.yaml``.

    Returns ``"single_tenant"`` when the file is absent, unreadable, or does
    not contain a ``spec.deployment_mode`` key.  This keeps the engine
    boot-safe in environments where ``tuvl init`` was not run (e.g. CI).
    """
    project_dir = Path(os.environ.get("TUVL_PROJECT_DIR", ".")).resolve()
    system_yaml = project_dir / _SYSTEM_YAML_RELPATH

    if not system_yaml.exists():
        return "single_tenant"

    try:
        with system_yaml.open() as fh:
            data = yaml.safe_load(fh)
        mode = data.get("spec", {}).get("deployment_mode", "single_tenant")
        mode = str(mode).strip().lower()
        if mode not in VALID_DEPLOYMENT_MODES:
            logger.warning(
                "bootstrap: %s has invalid deployment_mode=%r — defaulting to single_tenant",
                _SYSTEM_YAML_RELPATH,
                mode,
            )
            return "single_tenant"
        return mode
    except Exception as exc:
        logger.warning(
            "bootstrap: could not read %s (%s) — defaulting to single_tenant",
            _SYSTEM_YAML_RELPATH,
            exc,
        )
        return "single_tenant"


# ── Pre-flight check ──────────────────────────────────────────────────────────


async def run_pre_flight() -> None:
    """Resolve and lock the deployment mode.

    Must be called inside the FastAPI lifespan, **after** ``load_all_configs()``
    has populated ``DATASOURCE_REGISTRY`` / ``PRIMARY_DS`` and **before**
    ``init_db()`` creates application tables.

    Raises
    ------
    RuntimeError
        When ``tuvl_system_registry`` exists but has no ``deployment_mode`` row.
    """
    global LOCKED_DEPLOYMENT_MODE

    # Lazy import avoids circular dependency at module level.
    from tuvl.core.datasources.loader import DATASOURCE_REGISTRY, PRIMARY_DS

    if not DATASOURCE_REGISTRY or not PRIMARY_DS:
        logger.info(
            "bootstrap: no primary datasource registered — booting as single_tenant (no DB lock)"
        )
        LOCKED_DEPLOYMENT_MODE = "single_tenant"
        return

    # ── Resolve the primary Postgres datasource ───────────────────────────
    # PRIMARY_DS was finalised by _finalize_primary_ds() during
    # load_all_configs(): explicit metadata.primary > first-postgres fallback.
    ds_config = DATASOURCE_REGISTRY.get(PRIMARY_DS)

    if ds_config is None:
        logger.info(
            "bootstrap: no postgres datasource found — booting as single_tenant (no DB lock)"
        )
        LOCKED_DEPLOYMENT_MODE = "single_tenant"
        return

    # ── Build a temporary async engine for the pre-flight check ──────────
    spec = ds_config.get("spec", {})
    conn_cfg = spec["connection"]
    driver = spec.get("driver", "asyncpg")
    password = quote_plus(str(conn_cfg["password"]))
    dsn = (
        f"postgresql+{driver}://{conn_cfg['username']}:{password}"
        f"@{conn_cfg['host']}:{conn_cfg['port']}/{conn_cfg['database']}"
    )

    pid = os.getpid()
    _temp_engine = create_async_engine(
        dsn, echo=False, pool_size=1, max_overflow=0, pool_recycle=1800, pool_timeout=30
    )

    try:
        async with _temp_engine.begin() as conn:
            # ── Does tuvl_system_registry already exist? ───────────────────────
            table_exists: bool = await conn.run_sync(
                lambda sync_conn: sa_inspect(sync_conn).has_table(_REGISTRY_TABLE)
            )

            if not table_exists:
                # ── Greenfield: first ever boot ───────────────────────────
                # Read the requested mode from .tuvl/system.yaml (written by
                # ``tuvl init [--multi-tenant]``).  Default to single_tenant
                # when the file is absent (plain dev / CI environment).
                requested_mode = _read_system_yaml_mode()

                logger.info(
                    "bootstrap.greenfield_boot",
                    pid=pid,
                    deployment_mode=requested_mode,
                    source=_SYSTEM_YAML_RELPATH,
                )

                await conn.run_sync(
                    lambda sync_conn: SQLModel.metadata.create_all(
                        sync_conn,
                        tables=[table_of(SystemRegistry)],
                        checkfirst=True,
                    )
                )

                # Write the deployment mode row. ON CONFLICT DO NOTHING makes
                # this safe under `--workers N`: if two workers both observe the
                # table as absent and race the seed INSERT, the loser is a no-op
                # instead of an IntegrityError that aborts startup.
                from sqlalchemy.dialects.postgresql import insert as _pg_insert

                await conn.execute(
                    _pg_insert(SystemRegistry)
                    .values(key=_DEPLOYMENT_MODE_KEY, value=requested_mode)
                    .on_conflict_do_nothing(index_elements=["key"])
                )

                LOCKED_DEPLOYMENT_MODE = requested_mode

            else:
                # ── Brownfield: existing deployment ───────────────────────
                # DB is the final source of truth.
                result = await conn.execute(
                    sa.select(SystemRegistry).where(col(SystemRegistry.key) == _DEPLOYMENT_MODE_KEY)
                )
                row = result.first()

                if row is None:
                    raise RuntimeError(
                        f"bootstrap: '{_REGISTRY_TABLE}' table exists but has no "
                        f"'{_DEPLOYMENT_MODE_KEY}' row — database is inconsistent. "
                        f"(pid={pid})"
                    )

                db_mode: str = row.value

                # Warn (do not crash) if system.yaml disagrees with the DB
                # lock — operator may have edited the file manually.
                yaml_mode = _read_system_yaml_mode()
                if yaml_mode != db_mode:
                    logger.warning(
                        "bootstrap.deployment_mode.mismatch",
                        pid=pid,
                        source=_SYSTEM_YAML_RELPATH,
                        yaml_mode=yaml_mode,
                        db_mode=db_mode,
                        resolution="database value takes precedence",
                    )

                logger.info(
                    "bootstrap.brownfield_boot",
                    pid=pid,
                    deployment_mode=db_mode,
                )
                LOCKED_DEPLOYMENT_MODE = db_mode

    finally:
        await _temp_engine.dispose()

    # ── Post-lock: inject tenant_id into already-built user model classes ─
    if LOCKED_DEPLOYMENT_MODE == "multi_tenant":
        _inject_tenant_columns_into_registry()
        _inject_tenant_columns_into_system_tables()
        _warn_if_tenant_safety_net_disabled()
        _hint_run_rls_check()


def _inject_tenant_columns_into_system_tables() -> None:
    """Give the system tables (runs, journal, checkpoints, approvals, artifacts, vector store)
    their ``tenant_id`` column.

    ``DynamicTenantModel.__init_subclass__`` runs before SQLModel has built the class's table, so
    its injection never fires; the system models are imported here, after the mode is locked, and
    their tables get the column before ``create_all`` emits the DDL.
    """
    import importlib

    from tuvl.core.models.base import inject_tenant_column, tenant_tables

    for module in ("tuvl.runtime.models", "tuvl.core.models.system", "tuvl.core.artifacts.models"):
        try:
            importlib.import_module(module)
        except ImportError:  # an optional dependency (pgvector) is absent
            continue
    added = [t.name for t in tenant_tables() if inject_tenant_column(t)]
    if added:
        logger.info("bootstrap.tenant_columns.system", pid=os.getpid(), tables=sorted(added))


def _hint_run_rls_check() -> None:
    """Print a one-time bootstrap hint reminding the operator to verify
    that the RLS policies are installed in the target database.

    Deliberately *not* a runtime query — the bootstrap path is
    performance-sensitive and policy verification is a deployment-time
    concern, not a per-process one.  Operators can run
    ``tuvl verify rls`` in CI or as a post-deploy gate.
    """
    logger.info(
        "bootstrap.rls.verify_hint",
        deployment_mode="multi_tenant",
        verify_cmd="tuvl verify rls",
        bootstrap_cmd="tuvl generate rls",
    )


def _warn_if_tenant_safety_net_disabled() -> None:
    """Emit a loud startup warning if multi-tenant mode is active but the
    ``TUVL_REQUIRE_TENANT_CONTEXT`` safety net is explicitly disabled.

    The safety net is what prevents a host application bug (forgetting to
    wire the tenant-extraction dependency on a new route) from silently
    bypassing tenant isolation.  Disabling it is a deliberate, advanced
    choice \u2014 we make it visible at boot so it is never forgotten.
    """
    from tuvl.core.config import settings

    if not settings.tuvl_require_tenant_context:
        logger.warning(
            "bootstrap.tenant_safety_net.disabled",
            deployment_mode="multi_tenant",
            env_var="TUVL_REQUIRE_TENANT_CONTEXT",
            value=False,
            consequence=(
                "engine will NOT raise when a request reaches the database without "
                "a tenant context; RLS policies that depend on "
                "current_setting('app.current_tenant_id') will see an empty value"
            ),
            recommendation="re-enable unless there is a documented opt-out reason",
        )


# ── Post-lock column injection ────────────────────────────────────────────────


def _inject_tenant_columns_into_registry() -> None:
    """Inject ``tenant_id`` into user-defined SQLModel classes in MODEL_REGISTRY.

    User models are constructed by ``create_sqlmodel_class()`` during
    ``load_all_configs()``, which runs *before* ``run_pre_flight()``.  At
    class-construction time ``LOCKED_DEPLOYMENT_MODE`` is still the default
    ``"single_tenant"``, so ``DynamicTenantModel.__init_subclass__`` cannot
    fire the injection for those classes.

    This function iterates over the already-constructed ``Table`` objects and
    appends a ``tenant_id`` column so that the subsequent ``create_all()``
    call in ``init_db()`` emits the correct DDL.

    The operation is idempotent: classes that already carry a ``tenant_id``
    column (e.g. classes that DO inherit from ``DynamicTenantModel`` and were
    processed correctly) are skipped.
    """
    try:
        from tuvl.core.models.loader import MODEL_REGISTRY
    except ImportError:
        return

    from tuvl.core.models.base import inject_tenant_column

    injected: list[str] = []

    for model_name, model_cls in MODEL_REGISTRY.items():
        table = table_of(model_cls)
        if inject_tenant_column(table):
            injected.append(model_name)

    pid = os.getpid()
    if injected:
        logger.info(
            "bootstrap.tenant_columns.injected",
            pid=pid,
            count=len(injected),
            models=injected,
        )
    else:
        logger.info(
            "bootstrap.tenant_columns.skipped",
            pid=pid,
            reason="no user models required tenant_id injection",
        )
