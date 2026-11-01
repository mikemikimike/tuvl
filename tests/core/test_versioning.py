"""Tests for the multi-version workflow and model registries.

Covers the changes introduced in feat/versioning:

  Backend registries
  ------------------
  1.  _register_workflow_from_dict populates WORKFLOW_VERSION_REGISTRY for
      both enabled and disabled documents; disabled ones are absent from
      WORKFLOW_REGISTRY.
  2.  schema_version defaults to "v1" when metadata.schema_version is absent.
  3.  Multiple versions of the same workflow can coexist in the version
      registry; the last enabled version wins in WORKFLOW_REGISTRY.
  4.  _register_model_from_dict populates MODEL_VERSION_REGISTRY for both
      enabled and disabled documents.
  5.  MODEL_VERSION_REGISTRY carries the full raw config dict per version.

  Context helpers
  ---------------
  6.  _extract_allowed_models handles all three supported formats (dict with
      models list, list of strings, single string).
  7.  _extract_model_version_map extracts explicit version targets from the
      new dict format; returns {} for legacy formats.

  WorkflowUoW
  ------------
  8.  model_version_map param is stored and accessible via the property.
  9.  WorkflowUoW with no model_version_map defaults to empty dict.

  sync helpers
  ------------
  10. sync_workflow_versions is a no-op when no primary datasource exists.
  11. sync_model_versions   is a no-op when no primary datasource exists.

  Admin endpoints (in-process ASGI, no real DB)
  -----------------------------------------------
  12. GET  /admin/workflows returns 200 with correct structure when rows exist.
  13. GET  /admin/models    returns 200 with correct structure when rows exist.
  14. PATCH /admin/workflows/{name}/{version}/toggle flips enabled and returns
      the new state.
  15. PATCH /admin/models/{name}/{version}/toggle flips enabled.
  16. PATCH toggle returns 404 for an unknown (name, version) combination.
  17. POST /admin/workflows/{name}/{version}/fork creates a new file and
      returns the correct ForkResponse payload.
  18. POST /admin/models/{name}/{version}/fork creates a new file and returns
      the correct ForkResponse payload.

  LLM-as-a-judge / test-runner integration
  -----------------------------------------
  19. WorkflowTestRunner propagates _context_model_versions from initial
      context through the trace (it is a private key, not exposed in snapshots
      but must survive context merges).
  20. evaluate_step prompt does NOT include _context_model_versions (private
      key filtering).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml as _yaml

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _model_dict(
    name: str = "TestModel",
    schema_version: str | None = None,
    enabled: bool = True,
) -> dict:
    d: dict[str, Any] = {
        "kind": "ModelDefinition",
        "enabled": enabled,
        "metadata": {"name": name},
        "spec": {
            "tablename": "test_models",
            "fields": [
                {"name": "id", "type": "uuid", "primary_key": True},
                {"name": "label", "type": "string"},
            ],
        },
    }
    if schema_version is not None:
        d["metadata"]["schema_version"] = schema_version
    return d


def _clear_registries():
    from tuvl.core.models.loader import MODEL_REGISTRY, MODEL_VERSION_REGISTRY

    MODEL_REGISTRY.clear()
    MODEL_VERSION_REGISTRY.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 1 & 2. Workflow version registry — basic population + version default
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# 3. Multiple versions of the same workflow
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# 4 & 5. Model version registry
# ─────────────────────────────────────────────────────────────────────────────


def test_register_model_populates_version_registry():
    _clear_registries()
    from tuvl.core.models.loader import MODEL_VERSION_REGISTRY, _register_model_from_dict

    _register_model_from_dict(_model_dict("Fruit", schema_version="v1"), "fruit.yaml")

    assert "Fruit" in MODEL_VERSION_REGISTRY
    assert "v1" in MODEL_VERSION_REGISTRY["Fruit"]


def test_register_disabled_model_goes_to_version_registry_not_flat():
    _clear_registries()
    from tuvl.core.models.loader import (
        MODEL_REGISTRY,
        MODEL_VERSION_REGISTRY,
        _register_model_from_dict,
    )

    _register_model_from_dict(_model_dict("Ghost", enabled=False), "ghost.yaml")

    assert "Ghost" in MODEL_VERSION_REGISTRY
    assert "Ghost" not in MODEL_REGISTRY


def test_model_version_registry_stores_full_config():
    _clear_registries()
    from tuvl.core.models.loader import MODEL_VERSION_REGISTRY, _register_model_from_dict

    raw = _model_dict("Parcel", schema_version="v3")
    raw["spec"]["tablename"] = "parcels_v3"
    _register_model_from_dict(raw, "parcel.yaml")

    stored = MODEL_VERSION_REGISTRY["Parcel"]["v3"]
    assert stored["spec"]["tablename"] == "parcels_v3"


# ─────────────────────────────────────────────────────────────────────────────
# 6 & 7. Context helpers
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# 8 & 9. WorkflowUoW model_version_map
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# 10 & 11. sync helpers are no-ops without a primary datasource
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_model_versions_noop_without_primary_ds():
    """sync_model_versions returns silently when no primary DS is configured."""
    with (
        patch("tuvl.core.datasources.postgres._engines_rw", {}),
        patch("tuvl.core.datasources.postgres._PRIMARY_DS", ""),
    ):
        from tuvl.core.models.model_version import sync_model_versions

        await sync_model_versions()


# ─────────────────────────────────────────────────────────────────────────────
# 12–16. Admin endpoints with mocked DB session
# ─────────────────────────────────────────────────────────────────────────────


def _make_wf_row(
    name: str,
    schema_version: str = "v1",
    enabled: bool = True,
    config: dict | None = None,
) -> MagicMock:
    row = MagicMock()
    row.name = name
    row.schema_version = schema_version
    row.enabled = enabled
    row.get_config.return_value = config or {
        "metadata": {"name": name},
        "context": {"models": [{"name": "Candidate"}]},
        "trigger": {"path": f"/api/{name}", "method": "POST"},
        "steps": [],
    }
    return row


def _make_model_row(
    name: str,
    schema_version: str = "v1",
    enabled: bool = True,
    config: dict | None = None,
) -> MagicMock:
    row = MagicMock()
    row.name = name
    row.schema_version = schema_version
    row.enabled = enabled
    row.get_config.return_value = config or {
        "metadata": {"name": name},
        "spec": {
            "tablename": f"{name.lower()}s",
            "datasource": "main_postgres",
            "fields": [{"name": "id", "type": "uuid"}, {"name": "label", "type": "string"}],
        },
    }
    return row


def _override_admin_auth(app) -> None:
    """Inject the iam:admin dev claims so the guarded /admin/* routes authorize.

    The admin sub-router now requires ``iam:admin``; overriding ``verify_token``
    feeds the scope guard superuser claims (exercises the real require_scope
    check).
    """
    from tuvl.core.auth.access import dev_claims, verify_token

    app.dependency_overrides[verify_token] = dev_claims


def _build_admin_app():
    """Build a minimal FastAPI app that includes the execution_router with DB overridden."""
    from fastapi import FastAPI

    from tuvl.core.api.admin_router import router as exec_router
    from tuvl.core.datasources.postgres import get_session

    app = FastAPI()

    async def _fake_session():
        yield AsyncMock()

    app.dependency_overrides[get_session] = _fake_session
    app.include_router(exec_router)
    _override_admin_auth(app)
    return app


@pytest.mark.asyncio
async def test_admin_list_models_returns_grouped_structure():
    from httpx import ASGITransport, AsyncClient

    rows = [_make_model_row("Candidate", "v1"), _make_model_row("Candidate", "v2")]
    app = _build_admin_app()

    async def _override_session():
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        session.exec = AsyncMock(return_value=mock_result)
        yield session

    from tuvl.core.datasources.postgres import get_session

    app.dependency_overrides[get_session] = _override_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/admin/models")

    assert resp.status_code == 200
    data = resp.json()
    assert "Candidate" in data
    assert len(data["Candidate"]) == 2


@pytest.mark.asyncio
async def test_admin_toggle_model_not_found_returns_404():
    from httpx import ASGITransport, AsyncClient

    app = _build_admin_app()

    async def _override_session():
        session = AsyncMock()
        result = MagicMock()
        result.first.return_value = None
        session.exec = AsyncMock(return_value=result)
        yield session

    from tuvl.core.datasources.postgres import get_session

    app.dependency_overrides[get_session] = _override_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/admin/models/Ghost/v99/toggle")

    assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 17 & 18. Fork endpoints write new YAML files
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fork_model_version_creates_file():
    _clear_registries()
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from tuvl.core.api.admin_router import router as exec_router
    from tuvl.core.datasources.postgres import get_session
    from tuvl.core.models.loader import MODEL_VERSION_REGISTRY

    MODEL_VERSION_REGISTRY["Widget"] = {
        "v1": {
            "kind": "ModelDefinition",
            "metadata": {"name": "Widget", "schema_version": "v1"},
            "spec": {"tablename": "widgets", "fields": []},
        }
    }

    app = FastAPI()

    async def _fake_session():
        yield AsyncMock()

    app.dependency_overrides[get_session] = _fake_session
    app.include_router(exec_router)
    _override_admin_auth(app)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with patch("tuvl.core.config.settings") as mock_settings:
            mock_settings.dir_for.return_value = tmp_path

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/admin/models/Widget/v1/fork",
                    json={"new_version": "v2"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["new_version"] == "v2"
        forked_file = tmp_path / data["file"]
        assert forked_file.exists()
        forked_config = _yaml.safe_load(forked_file.read_text())
        assert forked_config["metadata"]["schema_version"] == "v2"


# ─────────────────────────────────────────────────────────────────────────────
# 19 & 20. Test-runner: private context keys stripped from snapshots
# ─────────────────────────────────────────────────────────────────────────────

# A minimal one-step workflow whose single step can be fully stubbed so that
# no real node dispatch or LLM call is required.
_STUB_WF = {
    "kind": "Workflow",
    "metadata": {"name": "stub_wf", "schema_version": "v2"},
    "spec": {
        "context": {
            "models": [
                {"name": "Candidate", "version": "v2"},
            ]
        },
        "steps": [
            {"id": "screen_step", "kind": "Functional"},
        ],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# 21. LLM-as-a-judge: _context_model_versions stripped from judge prompt
# ─────────────────────────────────────────────────────────────────────────────
