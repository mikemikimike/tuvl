import re
import uuid
from typing import Any, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl.core.auth.access import bind_principal_context, require_access
from tuvl.core.datasources.postgres import model_session
from tuvl.core.models.schemas import SCHEMA_REGISTRY
from tuvl.core.repositories.registry import get_repository
from tuvl.core.system_config import expose_model_crud

logger = structlog.get_logger(__name__)

# Sentinel returned by _parse_include when the query param is absent.
_NO_INCLUDE: frozenset[str] = frozenset()

# Matches filter[field_name] bracket-notation query params.
_FILTER_RE = re.compile(r"^filter\[([A-Za-z_][A-Za-z0-9_]*)\]$")


def _norm_groups(value: Any) -> list[str] | None:
    """Normalize a spec.access group entry — bare string becomes a one-element list."""
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    return [str(g) for g in value] or None


def _parse_filters(request: Request) -> dict[str, str] | None:
    """Extract ``filter[field]=value`` pairs from the query string.

    Example::

        ?filter[posting_id]=abc-123&filter[stage]=screening
        →  {"posting_id": "abc-123", "stage": "screening"}

    Returns ``None`` (not an empty dict) when no filter params are present so
    callers can distinguish "no filter" from "filter on zero columns".
    """
    result: dict[str, str] = {}
    for key, value in request.query_params.items():
        m = _FILTER_RE.match(key)
        if m:
            result[m.group(1)] = value
    return result or None


def _parse_include(include: str | None) -> frozenset[str]:
    """Convert a comma-separated ``?include=`` query string to a frozenset.

    Example:  "candidate,assessments"  →  frozenset({"candidate", "assessments"})
    """
    if not include:
        return _NO_INCLUDE
    return frozenset(s.strip() for s in include.split(",") if s.strip())


def _make_crud_router(model_name: str) -> APIRouter:
    schemas = SCHEMA_REGISTRY[model_name]
    CreateCls = schemas["create"]
    ReadCls = schemas["read"]
    UpdateCls = schemas["update"]
    ExpandedCls = schemas.get("expanded")  # None when no relations declared

    # ── Scope + group access control ──────────────────────────────────────
    # Scopes — convention: <modelnamelower>:read / :write / :delete,
    # overridable via spec.access.{read,write,delete}_scope in the model YAML.
    # Groups — spec.access.{read,write,delete}_groups pin the model to IAM
    # groups; scope AND group are both required, iam:admin bypasses. Absent
    # tiers cascade downward (write→read, delete→write) so declaring only
    # read_groups never leaves mutations open to a wider audience.
    access_cfg: dict = schemas.get("access") or {}
    _base = model_name.lower()
    _read_scope = str(access_cfg.get("read_scope") or f"{_base}:read")
    _write_scope = str(access_cfg.get("write_scope") or f"{_base}:write")
    _delete_scope = str(access_cfg.get("delete_scope") or f"{_base}:delete")
    _read_groups = _norm_groups(access_cfg.get("read_groups"))
    _write_groups = _norm_groups(access_cfg.get("write_groups")) or _read_groups
    _delete_groups = _norm_groups(access_cfg.get("delete_groups")) or _write_groups
    _auth_read = Depends(require_access(_read_scope, _read_groups))
    _auth_write = Depends(require_access(_write_scope, _write_groups))
    _auth_delete = Depends(require_access(_delete_scope, _delete_groups))

    enabled: frozenset[str] = schemas.get("crud") or frozenset()
    prefix = f"/models/{model_name.lower()}"
    # bind_principal_context authenticates every request and populates the
    # current_user_id / current_tenant_id ContextVars used by structlog,
    # OTel spans, and the multi-tenant DB session hook.
    router = APIRouter(
        prefix=prefix,
        tags=[model_name],
        dependencies=[Depends(bind_principal_context)],
    )

    # Single dependency instance shared by all routes for this model.
    # Automatically routes to the datasource declared in the model's YAML.
    _session = model_session(model_name)

    @router.post(
        "/",
        response_model=ReadCls,
        response_model_by_alias=True,
        status_code=201,
        summary=f"Create a new {model_name}",
        dependencies=[_auth_write],
    )
    async def create(body: CreateCls, session: AsyncSession = Depends(_session)) -> Any:  # type: ignore[valid-type]
        repo = get_repository(model_name, session)
        record = await repo.add(cast("Any", body).model_dump(exclude_none=False))
        await session.commit()
        await session.refresh(record)
        return record

    @router.get(
        "/",
        response_model=list[ReadCls],  # type: ignore[valid-type]
        response_model_by_alias=True,
        summary=f"List {model_name} records",
        dependencies=[_auth_read],
    )
    async def list_records(
        request: Request,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        include: str | None = Query(
            default=None,
            description=(
                "Comma-separated relation names to embed. "
                "Example: `?include=candidate,assessments`. "
                "Triggers a 1-query-per-relation IN-clause batch — never N+1."
            ),
        ),
        session: AsyncSession = Depends(_session),
    ) -> Any:
        repo = get_repository(model_name, session)
        incl = _parse_include(include)
        criteria = _parse_filters(request)
        refused = sorted(set(criteria or ()) - repo.filterable_columns())
        if refused:
            raise HTTPException(status_code=422, detail=f"Cannot filter on: {', '.join(refused)}.")

        if incl and ExpandedCls is not None:
            rows = await repo.list_expanded(
                include=incl, criteria=criteria, limit=limit, offset=offset
            )
            return [ExpandedCls.model_validate(r) for r in rows]

        return await repo.list(criteria=criteria, limit=limit, offset=offset)

    @router.get(
        "/{record_id}",
        response_model=ReadCls,
        response_model_by_alias=True,
        summary=f"Get a {model_name} by ID",
        dependencies=[_auth_read],
    )
    async def get_one(
        record_id: uuid.UUID,
        include: str | None = Query(
            default=None,
            description=(
                "Comma-separated relation names to embed. Example: `?include=candidate,posting`."
            ),
        ),
        session: AsyncSession = Depends(_session),
    ) -> Any:
        repo = get_repository(model_name, session)
        incl = _parse_include(include)

        if incl and ExpandedCls is not None:
            result = await repo.get_expanded(record_id, incl)
            if result is None:
                raise HTTPException(status_code=404, detail=f"{model_name} '{record_id}' not found")
            return ExpandedCls.model_validate(result)

        record = await repo.get(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"{model_name} '{record_id}' not found")
        return record

    @router.patch(
        "/{record_id}",
        response_model=ReadCls,
        response_model_by_alias=True,
        summary=f"Partially update a {model_name}",
        dependencies=[_auth_write],
    )
    async def update(
        record_id: uuid.UUID,
        body: UpdateCls,  # type: ignore[valid-type]
        session: AsyncSession = Depends(_session),
    ) -> Any:
        repo = get_repository(model_name, session)
        patch_data = cast("Any", body).model_dump(exclude_none=True)
        if not patch_data:
            raise HTTPException(status_code=422, detail="No fields provided to update")
        record = await repo.update(record_id, patch_data)
        if record is None:
            raise HTTPException(status_code=404, detail=f"{model_name} '{record_id}' not found")
        await session.commit()
        await session.refresh(record)
        return record

    @router.delete(
        "/{record_id}",
        status_code=204,
        summary=f"Delete a {model_name}",
        dependencies=[_auth_delete],
    )
    async def delete(record_id: uuid.UUID, session: AsyncSession = Depends(_session)) -> Response:
        repo = get_repository(model_name, session)
        deleted = await repo.remove(record_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"{model_name} '{record_id}' not found")
        await session.commit()
        return Response(status_code=204)

    endpoint_ops: dict[Any, str] = {
        create: "create",
        list_records: "list",
        get_one: "read",
        update: "update",
        delete: "delete",
    }
    router.routes = [
        r
        for r in router.routes
        if (op := endpoint_ops.get(getattr(r, "endpoint", None))) is not None and op in enabled
    ]
    return router


def build_crud_routers(app: Any) -> None:
    if not expose_model_crud():
        logger.info(
            "CRUD routers disabled (spec.api.expose_model_crud / TUVL_EXPOSE_MODEL_CRUD)",
            models=len(SCHEMA_REGISTRY),
        )
        return
    if not SCHEMA_REGISTRY:
        logger.info("No schemas registered, no CRUD routers mounted")
        return

    mounted = 0
    for model_name, schemas in SCHEMA_REGISTRY.items():
        ops = schemas.get("crud") or frozenset()
        if not ops:
            continue  # spec.api.crud is empty: the model exposes no routes
        app.include_router(_make_crud_router(model_name))
        mounted += 1
        logger.info("CRUD router mounted", model=model_name.lower(), operations=sorted(ops))

    logger.info("CRUD routers built", count=mounted, models=len(SCHEMA_REGISTRY))
