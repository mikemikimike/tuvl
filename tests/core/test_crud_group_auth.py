"""CRUD scope+group access control — ``require_access`` semantics and the
read→write→delete group cascade in ``_make_crud_router``."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from tuvl.core.api.crud_router import _make_crud_router, _norm_groups
from tuvl.core.auth.access import Claims, decode_token, require_access
from tuvl.core.auth.token import mint_token
from tuvl.core.models.loader import (
    MODEL_DATASOURCE_MAP,
    MODEL_REGISTRY,
    MODEL_VERSION_REGISTRY,
    SCHEMA_REGISTRY,
    _register_model_from_dict,
)


def _claims(scopes: list[str], groups: list[str] | None = None) -> Claims:
    token = mint_token("user-1", groups or [], scopes, ttl_seconds=3600)
    return decode_token(token)


# ── require_access: scope AND group semantics ────────────────────────────────


def test_right_scope_and_group_passes():
    user = require_access("thing:read", ["eng"])(_claims(["thing:read"], ["eng"]))
    assert user.user_id == "user-1"


def test_right_scope_wrong_group_is_403():
    with pytest.raises(HTTPException) as exc:
        require_access("thing:read", ["eng"])(_claims(["thing:read"], ["ops"]))
    assert exc.value.status_code == 403


def test_right_group_missing_scope_is_403():
    with pytest.raises(HTTPException) as exc:
        require_access("thing:read", ["eng"])(_claims([], ["eng"]))
    assert exc.value.status_code == 403


def test_iam_admin_bypasses_scope_and_group():
    user = require_access("thing:read", ["eng"])(_claims(["iam:admin"], []))
    assert user.user_id == "user-1"


# ── _norm_groups ──────────────────────────────────────────────────────────────


def test_norm_groups_bare_string_becomes_list():
    assert _norm_groups("eng") == ["eng"]


def test_norm_groups_list_passthrough():
    assert _norm_groups(["eng", "ops"]) == ["eng", "ops"]


def test_norm_groups_none_stays_none():
    assert _norm_groups(None) is None


# ── cascade: read→write→delete groups in _make_crud_router ───────────────────


def _model_dict(name: str, tablename: str, access: dict | None = None) -> dict:
    spec: dict = {
        "tablename": tablename,
        "fields": [
            {"name": "id", "type": "uuid", "primary_key": True},
            {"name": "label", "type": "string"},
        ],
        "api": {"crud": ["list", "read", "create", "update", "delete"]},
    }
    if access:
        spec["access"] = access
    return {"kind": "ModelDefinition", "metadata": {"name": name}, "spec": spec}


def _route(router, method: str, has_id: bool):
    for r in router.routes:
        if method in r.methods and r.path.endswith("{record_id}") == has_id:
            return r
    raise AssertionError(f"no {method} route found (has_id={has_id})")


@pytest.fixture(autouse=True)
def _clean_registries():
    MODEL_REGISTRY.clear()
    MODEL_VERSION_REGISTRY.clear()
    SCHEMA_REGISTRY.clear()
    MODEL_DATASOURCE_MAP.clear()
    yield
    MODEL_REGISTRY.clear()
    MODEL_VERSION_REGISTRY.clear()
    SCHEMA_REGISTRY.clear()
    MODEL_DATASOURCE_MAP.clear()


def test_write_and_delete_cascade_from_read_groups():
    _register_model_from_dict(
        _model_dict("CascRead", "casc_read_v1", access={"read_groups": "eng"})
    )
    router = _make_crud_router("CascRead")

    write_dep = _route(router, "POST", False).dependencies[-1].dependency
    write_dep(_claims(["cascread:write"], ["eng"]))  # cascaded group accepted
    with pytest.raises(HTTPException):
        write_dep(_claims(["cascread:write"], ["ops"]))

    delete_dep = _route(router, "DELETE", True).dependencies[-1].dependency
    delete_dep(_claims(["cascread:delete"], ["eng"]))
    with pytest.raises(HTTPException):
        delete_dep(_claims(["cascread:delete"], ["ops"]))


def test_delete_cascades_from_write_groups_when_unset():
    _register_model_from_dict(
        _model_dict("CascWrite", "casc_write_v1", access={"write_groups": ["ops"]})
    )
    router = _make_crud_router("CascWrite")

    delete_dep = _route(router, "DELETE", True).dependencies[-1].dependency
    delete_dep(_claims(["cascwrite:delete"], ["ops"]))  # cascaded from write_groups
    with pytest.raises(HTTPException):
        delete_dep(_claims(["cascwrite:delete"], ["eng"]))

    # read has no group config at all — untouched by the write→delete cascade.
    read_dep = _route(router, "GET", False).dependencies[-1].dependency
    read_dep(_claims(["cascwrite:read"], []))


def test_no_groups_configured_is_scope_only_regression():
    _register_model_from_dict(_model_dict("NoGroups", "no_groups_v1"))
    router = _make_crud_router("NoGroups")

    read_dep = _route(router, "GET", False).dependencies[-1].dependency
    read_dep(_claims(["nogroups:read"], []))  # no group required at all


# ── list filters: only real, readable columns ────────────────────────────────


def test_filter_names_must_be_real_columns() -> None:
    from types import SimpleNamespace

    from sqlalchemy import Column, Integer, MetaData, String, Table

    from tuvl.core.repositories.base import BaseRepository

    table = Table("t", MetaData(), Column("id", Integer), Column("name", String))
    repo = BaseRepository.__new__(BaseRepository)
    repo.model_class = SimpleNamespace(__table__=table)  # type: ignore[assignment]
    assert repo.filterable_columns() == {"id", "name"}
    assert "metadata" not in repo.filterable_columns()
