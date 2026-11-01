"""Declared stores and the storage browser."""

from __future__ import annotations

import os
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException

from tuvl.core.config import settings

router = APIRouter()

# ── storage ──────────────────────────────────────────────────────────────────


def _stores_on_disk() -> dict[str, Any]:
    """The ``kind: Storage`` files as they are now: ``{name: {file, spec, error}}``."""

    from tuvl.storage import ConfigError, parse_store

    out: dict[str, Any] = {}
    directory = settings.dir_for("storage")
    for path in sorted(directory.glob("*.y*ml")) if directory.is_dir() else []:
        try:
            data = yaml.safe_load(path.read_text())
            name, spec = parse_store(data if isinstance(data, dict) else {})
        except (yaml.YAMLError, ConfigError) as exc:
            out[path.stem] = {"file": path.name, "spec": None, "error": str(exc)}
            continue
        out[name] = {"file": path.name, "spec": spec, "error": None}
    return out


def _open_store(name: str) -> Any:
    from tuvl.storage import ConfigError, Store, build_backend

    entry = _stores_on_disk().get(name)
    if entry is None or entry["spec"] is None:
        raise HTTPException(404, f"no valid Storage '{name}'")
    try:
        return Store(name, entry["spec"], build_backend(name, entry["spec"]))
    except ConfigError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/storage", summary="Declared stores, with the environment variables they still need")
async def list_stores() -> list[dict[str, Any]]:

    from tuvl.storage import required_env

    rows: list[dict[str, Any]] = []
    for name, entry in _stores_on_disk().items():
        spec = entry["spec"]
        rows.append(
            {
                "name": name,
                "file": entry["file"],
                "error": entry["error"],
                "provider": spec.provider if spec else None,
                "target": (spec.bucket or spec.container or spec.root) if spec else None,
                "prefix": spec.prefix if spec else None,
                "readonly": spec.readonly if spec else None,
                "missing": [v for v in required_env(spec) if v not in os.environ] if spec else [],
            }
        )
    return rows


@router.post("/storage/{name}/check", summary="Write, read and delete a probe object")
async def check_storage(name: str) -> dict[str, Any]:
    from tuvl.storage import ConfigError
    from tuvl.storage.check import check_store

    store = _open_store(name)
    try:
        steps = await check_store(store)
    except ConfigError as exc:
        steps = [("open", str(exc))]
    finally:
        await store.aclose()
    return {
        "ok": all(err is None for _, err in steps),
        "steps": [{"step": s, "error": e} for s, e in steps],
    }


@router.get("/storage/{name}/objects", summary="Objects under a prefix (read-only browser)")
async def storage_objects(
    name: str, prefix: str = "", cursor: str | None = None, limit: int = 100
) -> dict[str, Any]:
    from tuvl.storage import InvalidKey, StorageError

    store = _open_store(name)
    try:
        listing = await store.list(prefix, max(1, min(limit, 500)), cursor)
    except InvalidKey as exc:
        raise HTTPException(400, str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(502, f"{type(exc).__name__}: {exc}") from exc
    finally:
        await store.aclose()
    return {"items": [b.to_dict() for b in listing.items], "cursor": listing.cursor}
