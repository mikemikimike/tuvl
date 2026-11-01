"""Internal system metadata endpoints (not user-facing CRUD)."""

from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from tuvl.core.auth.access import require_scope
from tuvl.core.models.loader import MODEL_REGISTRY, MODEL_RELATIONS

router = APIRouter(prefix="/api/_system", tags=["_system"])


def require_dev_mode() -> None:
    """404 outside dev mode.

    The schema/registry introspection endpoints below are consumed only by the
    dev-mode Insight UI. They expose model fields, datasource names, and the
    full registry contents, so in production they are pure reconnaissance
    surface — gate them off (404, so their existence isn't even disclosed).
    The SDK-facing /workflows manifest endpoints stay public.
    """
    from tuvl.core.config import settings

    if not settings.tuvl_dev_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get("/models", dependencies=[Depends(require_dev_mode)])
async def list_models() -> dict:
    """Return registered model names with their column fields and relation names.

    Response shape::

        {
          "Candidate": {
            "fields": ["id", "first_name", ...],
            "relations": ["education", "experience", ...]
          },
          ...
        }
    """
    return _build_system_models()


def _build_system_models() -> dict:
    """Sync helper — builds the system-models dict from the live registry."""
    result: dict = {}
    for name, cls in MODEL_REGISTRY.items():
        try:
            fields = [col.name for col in cast("Any", cls).__table__.columns]
        except AttributeError:
            fields = []
        relations = [r["name"] for r in MODEL_RELATIONS.get(name, [])]
        result[name] = {"fields": fields, "relations": relations}
    return result


def _manifest(name: str, doc: Any, *, agents: bool = False) -> dict[str, Any]:
    http = doc.spec.trigger.active_http
    entry: dict[str, Any] = {
        "name": name,
        "description": doc.metadata.description,
        "trigger_path": http.path if http else None,
        "trigger_method": http.method if http else None,
        # Declared trigger.public only — an anonymous caller learns it on the
        # first call anyway, and it lets the SDK skip token acquisition.
        "public": bool(http and http.public),
        "runs_url": f"/api/workflows/{name}/runs",
        "input": {
            k: str(v) if isinstance(v, str) else v.model_dump()
            for k, v in doc.spec.trigger.input.items()
        },
        "ends": sorted(doc.spec.outputs),
    }
    if agents:
        entry["agents"] = [{"id": a.id, "engine": a.engine} for a in doc.spec.agents]
    return entry


@router.get("/workflows")
async def list_workflows() -> dict[str, Any]:
    """Trigger routes and input contracts of every loaded workflow, for the
    ``@tuvl/client`` SDK.

    ``required_scope`` / ``required_group`` are intentionally NOT exposed —
    they would be anonymous reconnaissance of the auth model; callers learn
    their requirements from a 401/403.
    """
    from tuvl.contract.registry import WORKFLOWS

    return {name: _manifest(name, doc) for name, doc in sorted(WORKFLOWS.items()) if doc.enabled}


@router.get("/workflows/{name}")
async def get_workflow_manifest(name: str) -> dict[str, Any]:
    """The manifest of one workflow, with its agents (id and engine)."""
    from tuvl.contract.registry import WORKFLOWS

    doc = WORKFLOWS.get(name)
    if doc is None or not doc.enabled:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found.")
    return _manifest(name, doc, agents=True)


# ── Embedding & Collection registry endpoints ─────────────────────────────────
# Used by the developer portal to populate dropdowns and display registry state.


@router.get("/embeddings", dependencies=[Depends(require_dev_mode)])
async def list_embeddings() -> dict:
    """Return all registered embedding configurations.

    Response shape::

        {
          "text-embedding-3-small": {
            "name": "text-embedding-3-small",
            "provider": "openai",
            "model": "openai/text-embedding-3-small",
            "dimensions": 1536
          },
          ...
        }
    """
    from tuvl.core.models.embeddings_loader import EMBEDDING_REGISTRY

    return dict(EMBEDDING_REGISTRY)


@router.get("/collections", dependencies=[Depends(require_dev_mode)])
async def list_collections() -> dict:
    """Return all registered collection configurations.

    Response shape::

        {
          "knowledge-base": {
            "name": "knowledge-base",
            "description": "General knowledge base",
            "embedding": "text-embedding-3-small"
          },
          ...
        }
    """
    from tuvl.core.models.collections_loader import COLLECTION_REGISTRY

    return dict(COLLECTION_REGISTRY)


@router.get("/vector-status", dependencies=[Depends(require_dev_mode)])
async def vector_status() -> dict:
    """Return whether the pgvector extension is available and ready.

    Response shape::

        {
          "ready": true,
          "pgvector_package": true,
          "reason": null
        }

    ``ready`` is ``false`` when either the Python ``pgvector`` package is
    missing **or** the PostgreSQL server extension could not be enabled at
    startup.  The UI should hide / disable RAG-related controls when
    ``ready`` is ``false``.
    """
    from tuvl.core.datasources.postgres import _VECTOR_STORE_READY
    from tuvl.core.models.system import _PGVECTOR_AVAILABLE

    reason: str | None = None
    if not _PGVECTOR_AVAILABLE:
        reason = "pgvector Python package is not installed (pip install pgvector)"
    elif not _VECTOR_STORE_READY:
        reason = (
            "pgvector PostgreSQL extension is not available on the server. "
            "See https://github.com/pgvector/pgvector#installation"
        )

    from tuvl.core.datasources.postgres import _VECTOR_DS

    return {
        "ready": _VECTOR_STORE_READY,
        "pgvector_package": _PGVECTOR_AVAILABLE,
        "reason": reason,
        "datasource": _VECTOR_DS or None,
    }


@router.get("/pg-datasources", dependencies=[Depends(require_dev_mode)])
async def list_pg_datasources() -> dict:
    """Return all registered PostgreSQL datasource names.

    Response shape::

        {
          "datasources": ["main_postgres", "analytics_db"],
          "current_vector_datasource": "main_postgres"
        }
    """
    from tuvl.core.datasources.loader import DATASOURCE_REGISTRY
    from tuvl.core.datasources.postgres import _PRIMARY_DS, _VECTOR_DS

    pg_names = [
        name
        for name, cfg in DATASOURCE_REGISTRY.items()
        if cfg.get("spec", {}).get("type", "postgres") in ("postgres", "postgresql")
    ]
    return {
        "datasources": pg_names,
        "current_vector_datasource": _VECTOR_DS or _PRIMARY_DS,
    }


class VectorDatasourceUpdate(BaseModel):
    datasource: str


@router.put("/vector-datasource", dependencies=[Depends(require_scope("iam:admin"))])
async def set_vector_datasource(body: VectorDatasourceUpdate) -> dict:
    """Persist the chosen vector datasource to the project's config.yaml.

    The change takes effect after the next server restart — a
    ``restart_required`` flag is returned so the UI can notify the user.

    Response shape::

        { "ok": true, "datasource": "analytics_db", "restart_required": true }
    """
    from tuvl.core.config import settings
    from tuvl.core.datasources.loader import DATASOURCE_REGISTRY

    # Validate that the requested datasource actually exists.
    pg_names = [
        name
        for name, cfg in DATASOURCE_REGISTRY.items()
        if cfg.get("spec", {}).get("type", "postgres") in ("postgres", "postgresql")
    ]
    if body.datasource not in pg_names:
        raise HTTPException(
            status_code=422,
            detail=f"Datasource '{body.datasource}' not found. Available: {pg_names}",
        )

    import yaml
    from fastapi.concurrency import run_in_threadpool

    cfg_path = settings.project_dir / "config.yaml"

    def _read_modify_write() -> None:
        if cfg_path.exists():
            with cfg_path.open() as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {"kind": "ProjectConfig", "version": "v1"}
        data.setdefault("spec", {})["vector_datasource"] = body.datasource
        with cfg_path.open("w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    # Run the blocking file I/O off the event loop.
    await run_in_threadpool(_read_modify_write)

    return {"ok": True, "datasource": body.datasource, "restart_required": True}
