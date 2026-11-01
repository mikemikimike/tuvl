"""Dynamic tenant-aware base model.

Provides :class:`DynamicTenantModel`, an abstract SQLModel base that injects a
``tenant_id`` column into every concrete subclass when running in
``multi_tenant`` mode (per the bootstrap pre-flight in
:mod:`tuvl.core.bootstrap`). It is a no-op in single-tenant deployments.

``__init_subclass__`` runs immediately after each subclass's SQLAlchemy
``Table`` is built. ``LOCKED_DEPLOYMENT_MODE`` is already set by then because
system models are lazily imported inside ``init_db()``, which runs *after*
``run_pre_flight()`` — so the hook can ``Table.append_column()`` before
``create_all()`` generates the DDL.

User-defined models (built by
:func:`tuvl.core.models.loader.create_sqlmodel_class`) inherit from ``SQLModel``
directly and are constructed *before* bootstrap; their ``tenant_id`` injection
is handled by :func:`tuvl.core.bootstrap._inject_tenant_columns_into_registry`.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

_TENANT_COL = "tenant_id"
DEFAULT_TENANT = "default_tenant"


def context_tenant() -> str:
    """Column default: the tenant bound for the running task, else ``default_tenant``."""
    from tuvl.core.context import current_tenant_id

    return current_tenant_id.get("") or DEFAULT_TENANT


def inject_tenant_column(table: sa.Table) -> bool:
    """Append ``tenant_id`` to *table* unless it has one. True when a column was added.

    The Python-side default makes every ORM insert carry the tenant bound by
    :func:`tuvl.tenancy.tenant_scope`, even though the mapper never saw the column;
    ``server_default`` covers rows that predate it.
    """
    if _TENANT_COL in table.c:
        return False
    table.append_column(
        sa.Column(
            _TENANT_COL,
            sa.String,
            nullable=False,
            index=True,
            server_default=DEFAULT_TENANT,
            default=context_tenant,
        )
    )
    return True


def tenant_tables() -> list[sa.Table]:
    """The table of every concrete :class:`DynamicTenantModel` subclass defined so far."""
    found: list[sa.Table] = []
    stack = list(DynamicTenantModel.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        table = getattr(cls, "__table__", None)
        if table is not None and table not in found:
            found.append(table)
    return found


class DynamicTenantModel(SQLModel):
    """Abstract base for tenant-aware persistent models.

    Subclasses that set ``table=True`` will automatically receive a
    ``tenant_id`` column if the system is locked in ``multi_tenant`` mode.
    In ``single_tenant`` mode this class is a transparent pass-through.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Only process table-bearing (non-abstract) subclasses.
        if not getattr(cls, "__tablename__", None):
            return

        # Lazy import avoids a circular dependency at module level:
        # bootstrap → logger → (nothing that imports base.py)
        try:
            import tuvl.core.bootstrap as _bootstrap
        except ImportError:
            return

        if _bootstrap.LOCKED_DEPLOYMENT_MODE != "multi_tenant":
            return

        table: sa.Table | None = getattr(cls, "__table__", None)
        if table is None:
            return

        # create_all() reads columns at DDL generation time, so appending to the
        # live Table is enough.
        if not inject_tenant_column(table):
            return

        # Mirror the annotation so introspection and Pydantic see the field.
        cls.__annotations__[_TENANT_COL] = str
        setattr(
            cls,
            _TENANT_COL,
            Field(
                default="default_tenant",
                sa_column_kwargs={"server_default": "default_tenant"},
            ),
        )
