"""Tests for cross-version model collision enforcement (Phase 2.8)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
import sqlmodel

from tuvl.core.models import loader as model_loader
from tuvl.core.repositories.uow import WorkflowUoW


def _reset_registries(monkeypatch) -> None:
    monkeypatch.setattr(model_loader, "MODEL_REGISTRY", {})
    monkeypatch.setattr(model_loader, "MODEL_VERSION_REGISTRY", {})
    monkeypatch.setattr(model_loader, "MODEL_DATASOURCE_MAP", {})
    monkeypatch.setattr(model_loader, "MODEL_RELATIONS", {})
    monkeypatch.setattr(model_loader, "SECURE_FIELDS", set())
    # Use a fresh MetaData per test so SQLAlchemy doesn't reject re-registration
    # of tables created in previous tests.
    monkeypatch.setattr(sqlmodel.SQLModel, "metadata", sa.MetaData())


def _model_def(name: str, table: str, version: str, fields: list[dict]) -> dict:
    return {
        "kind": "ModelDefinition",
        "metadata": {"name": name, "schema_version": version},
        "spec": {
            "tablename": table,
            "datasource": "main_postgres",
            "fields": fields,
            "schema": False,  # skip pydantic schema generation in tests
        },
    }


# ── Loader-side cross-version collision detection ────────────────────────────


def test_loader_rejects_divergent_versions_on_shared_table(monkeypatch) -> None:
    _reset_registries(monkeypatch)
    v1 = _model_def(
        "CollideA",
        "collide_a",
        "v1",
        [
            {"name": "id", "type": "uuid", "primary_key": True},
            {"name": "name", "type": "string", "required": True},
        ],
    )
    v2 = _model_def(
        "CollideA",
        "collide_a",
        "v2",
        [
            {"name": "id", "type": "uuid", "primary_key": True},
            {"name": "name", "type": "string", "required": True},
            {"name": "score", "type": "integer", "required": True},
        ],
    )

    model_loader._register_model_from_dict(v1, "collide_v1.yaml")
    with pytest.raises(RuntimeError, match="Cross-version model collision"):
        model_loader._register_model_from_dict(v2, "collide_v2.yaml")


def test_loader_accepts_versions_on_distinct_tables(monkeypatch) -> None:
    _reset_registries(monkeypatch)
    v1 = _model_def(
        "DistinctTbl",
        "distinct_v1",
        "v1",
        [{"name": "id", "type": "uuid", "primary_key": True}],
    )
    v2 = _model_def(
        "DistinctTbl",
        "distinct_v2",
        "v2",
        [
            {"name": "id", "type": "uuid", "primary_key": True},
            {"name": "extra", "type": "string", "required": True},
        ],
    )

    model_loader._register_model_from_dict(v1, "v1.yaml")
    model_loader._register_model_from_dict(v2, "v2.yaml")


def test_loader_ignores_disabled_versions(monkeypatch) -> None:
    _reset_registries(monkeypatch)
    v1 = _model_def(
        "Disabled",
        "disabled_tbl",
        "v1",
        [{"name": "id", "type": "uuid", "primary_key": True}],
    )
    v1["enabled"] = False
    v2 = _model_def(
        "Disabled",
        "disabled_tbl",
        "v2",
        [
            {"name": "id", "type": "uuid", "primary_key": True},
            {"name": "score", "type": "integer", "required": True},
        ],
    )

    model_loader._register_model_from_dict(v1, "disabled_v1.yaml")
    # v1 is disabled \u2192 no enabled prior shape \u2192 v2 registers without raising.
    model_loader._register_model_from_dict(v2, "disabled_v2.yaml")


# ── WorkflowUoW-side version pin enforcement ─────────────────────────────────


def test_uow_rejects_version_pin_mismatch(monkeypatch) -> None:
    class _FakeCandidate:
        __schema_version__ = "v1"

        def __init__(self, **_kwargs):
            pass

    monkeypatch.setattr("tuvl.core.models.loader.MODEL_REGISTRY", {"Candidate": _FakeCandidate})

    uow = WorkflowUoW(
        primary_session=MagicMock(),
        allowed_models={"Candidate"},
        is_write=True,
        model_version_map={"Candidate": "v2"},
    )

    with pytest.raises(RuntimeError, match="version 'v2' but MODEL_REGISTRY holds"):
        _ = uow["Candidate"]


def test_uow_accepts_matching_version_pin(monkeypatch) -> None:
    class _FakeCandidate:
        __schema_version__ = "v2"

        def __init__(self, **_kwargs):
            pass

    monkeypatch.setattr("tuvl.core.models.loader.MODEL_REGISTRY", {"Candidate": _FakeCandidate})
    monkeypatch.setattr(
        "tuvl.core.repositories.base.MODEL_REGISTRY",
        {"Candidate": _FakeCandidate},
    )
    monkeypatch.setattr(
        "tuvl.core.repositories.uow._resolve_canonical",
        lambda name: "Candidate",
    )
    monkeypatch.setattr(
        "tuvl.core.models.loader.MODEL_DATASOURCE_MAP",
        {"Candidate": "main_postgres"},
    )

    uow = WorkflowUoW(
        primary_session=MagicMock(),
        allowed_models={"Candidate"},
        is_write=True,
        model_version_map={"Candidate": "v2"},
    )
    assert uow["Candidate"].model_class is _FakeCandidate


def test_uow_without_version_pin_skips_check(monkeypatch) -> None:
    class _Unstamped:
        # Deliberately no __schema_version__.
        def __init__(self, **_kwargs):
            pass

    monkeypatch.setattr("tuvl.core.repositories.base.MODEL_REGISTRY", {"Free": _Unstamped})
    monkeypatch.setattr("tuvl.core.models.loader.MODEL_REGISTRY", {"Free": _Unstamped})
    monkeypatch.setattr(
        "tuvl.core.repositories.uow._resolve_canonical",
        lambda name: "Free",
    )
    monkeypatch.setattr(
        "tuvl.core.models.loader.MODEL_DATASOURCE_MAP",
        {"Free": "main_postgres"},
    )

    uow = WorkflowUoW(
        primary_session=MagicMock(),
        allowed_models={"Free"},
        is_write=True,
        model_version_map={},  # no pin
    )
    assert uow["Free"].model_class is _Unstamped
