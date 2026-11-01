"""Implicit models bind to the primary datasource, not a hardcoded name (TD-35)."""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel

from tuvl.core.datasources import postgres
from tuvl.core.models import loader as model_loader


def _reset_registries(monkeypatch) -> None:
    monkeypatch.setattr(model_loader, "MODEL_REGISTRY", {})
    monkeypatch.setattr(model_loader, "MODEL_VERSION_REGISTRY", {})
    monkeypatch.setattr(model_loader, "MODEL_DATASOURCE_MAP", {})
    monkeypatch.setattr(model_loader, "MODEL_RELATIONS", {})
    monkeypatch.setattr(model_loader, "SECURE_FIELDS", set())
    monkeypatch.setattr(sqlmodel.SQLModel, "metadata", sa.MetaData())


def _model_def(name: str, table: str, *, datasource: str | None = None) -> dict:
    spec: dict = {
        "tablename": table,
        "fields": [{"name": "id", "type": "uuid", "primary_key": True}],
        "schema": False,
    }
    if datasource:
        spec["datasource"] = datasource
    return {
        "kind": "ModelDefinition",
        "metadata": {"name": name, "schema_version": "v1"},
        "spec": spec,
    }


def test_implicit_model_is_not_pinned_to_a_datasource_name(monkeypatch) -> None:
    """No spec.datasource → no map entry; consumers fall back to the primary."""
    _reset_registries(monkeypatch)
    model_loader._register_model_from_dict(_model_def("BindImplicit", "bind_implicit"), "x.yaml")
    assert "BindImplicit" in model_loader.MODEL_REGISTRY
    assert "BindImplicit" not in model_loader.MODEL_DATASOURCE_MAP


def test_explicit_model_keeps_its_datasource_binding(monkeypatch) -> None:
    _reset_registries(monkeypatch)
    model_loader._register_model_from_dict(
        _model_def("BindExplicit", "bind_explicit", datasource="analytics"), "x.yaml"
    )
    assert model_loader.MODEL_DATASOURCE_MAP["BindExplicit"] == "analytics"


def test_tables_for_datasource_assigns_implicit_models_to_primary(monkeypatch) -> None:
    """create_all must pick up implicit models on the primary datasource,
    whatever its metadata.name is — the scaffold names it 'default'."""
    _reset_registries(monkeypatch)
    model_loader._register_model_from_dict(_model_def("BindImplicit", "bind_implicit"), "x.yaml")
    model_loader._register_model_from_dict(
        _model_def("BindExplicit", "bind_explicit", datasource="analytics"), "y.yaml"
    )
    monkeypatch.setattr(postgres, "_PRIMARY_DS", "default")

    primary_tables = {t.name for t in postgres._tables_for_datasource("default")}
    analytics_tables = {t.name for t in postgres._tables_for_datasource("analytics")}
    assert primary_tables == {"bind_implicit"}
    assert analytics_tables == {"bind_explicit"}
    assert postgres._tables_for_datasource("main_postgres") == []
