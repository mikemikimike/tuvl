"""Production artifact API — DB-source uploads behind token scopes.

``artifacts:read`` lists/reads; ``artifacts:write`` uploads (``iam:admin``
bypasses). An upload is prompt-level trust — a prompt artifact carries
instruction-level authority once a workflow references it — so
``artifacts:write`` belongs to the same principals who may edit workflows.

Uploads create a NEW version row (never in-place mutation) and register into
this worker's in-memory registry immediately; other workers pick the row up at
their next boot, the same restart semantics as the admin model toggle.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl.core.artifacts.kinds import ARTIFACT_TYPES, MAX_ARTIFACT_BYTES, PROSE_TYPES
from tuvl.core.artifacts.registry import (
    ARTIFACT_REGISTRY,
    content_hash,
    register_artifact,
)
from tuvl.core.auth.access import bind_principal_context, require_scope
from tuvl.core.auth.schemas import TokenUser
from tuvl.core.context import current_user_id
from tuvl.core.datasources.postgres import get_session

router = APIRouter(
    prefix="/api/artifacts",
    tags=["artifacts"],
    dependencies=[Depends(bind_principal_context)],
)

_READ = Depends(require_scope("artifacts:read"))
_WRITE = Depends(require_scope("artifacts:write"))


class ArtifactUpload(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    type: str
    content: str  # prose text, or a JSON string for structured types
    description: str = ""
    version: int | None = None  # default: next version for the name


@router.get("")
async def list_artifacts(_: TokenUser = _READ) -> dict[str, Any]:
    """List every registered artifact (all sources) with version metadata."""
    return {
        "artifacts": sorted(
            (
                {
                    "name": e.name,
                    "type": e.type,
                    "description": e.description,
                    "source": e.source,
                    "versions": sorted(e.versions),
                    "latest": e.latest,
                }
                for e in ARTIFACT_REGISTRY.values()
            ),
            key=lambda a: a["name"],
        )
    }


@router.get("/{name}")
async def get_artifact(
    name: str, version: int | None = None, _: TokenUser = _READ
) -> dict[str, Any]:
    from tuvl.core.artifacts.registry import ArtifactResolutionError, get_version

    entry = ARTIFACT_REGISTRY.get(name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    try:
        av = get_version(name, version, where="api.artifacts")
    except ArtifactResolutionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "name": entry.name,
        "type": entry.type,
        "description": entry.description,
        "source": av.source,
        "version": version if version is not None else entry.latest,
        "content": av.content,
        "content_hash": av.content_hash,
    }


@router.post("", status_code=201)
async def upload_artifact(
    body: ArtifactUpload,
    session: AsyncSession = Depends(get_session),
    _: TokenUser = _WRITE,
) -> dict[str, Any]:
    """Persist a new artifact version row and register it on this worker."""
    from tuvl.core.artifacts.models import SystemArtifact

    if body.type not in ARTIFACT_TYPES:
        raise HTTPException(
            status_code=422, detail=f"type must be one of {sorted(ARTIFACT_TYPES)}."
        )
    if len(body.content.encode()) > MAX_ARTIFACT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"content exceeds the {MAX_ARTIFACT_BYTES // 1024} KB cap.",
        )
    if body.type in PROSE_TYPES:
        content_obj: object = body.content
    else:
        try:
            content_obj = json.loads(body.content)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"structured artifact content must be a JSON object: {exc}",
            ) from exc
        if not isinstance(content_obj, dict):
            raise HTTPException(
                status_code=422, detail="structured artifact content must be a JSON object."
            )

    entry = ARTIFACT_REGISTRY.get(body.name)
    if entry is not None and entry.type != body.type:
        raise HTTPException(
            status_code=409,
            detail=f"artifact '{body.name}' already exists with type '{entry.type}'.",
        )
    version = body.version or ((max(entry.versions) + 1) if entry else 1)
    if entry is not None and version in entry.versions:
        raise HTTPException(
            status_code=409,
            detail=f"artifact '{body.name}' version {version} already exists — "
            f"uploads create new versions, never overwrite.",
        )

    row = SystemArtifact(
        name=body.name,
        type=body.type,
        version=version,
        description=body.description,
        content=body.content,
        content_hash=content_hash(content_obj),
        created_by=current_user_id.get("") or None,
    )
    session.add(row)
    await session.commit()

    register_artifact(
        name=body.name,
        type_=body.type,
        version=version,
        content=content_obj,
        source="db",
        description=body.description,
    )
    return {"name": body.name, "version": version, "content_hash": row.content_hash}
