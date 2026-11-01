"""apply_db_enabled_overrides — admin-toggled `enabled` flags win over YAML at boot.

Covers the init_db hook that reads ``tuvl_system_model_versions`` and
activates / deactivates model versions in the in-memory registries before
``create_all`` runs.
"""

from __future__ import annotations

from typing import Any

import pytest

from tuvl.core.models.loader import (
    MODEL_DATASOURCE_MAP,
    MODEL_REGISTRY,
    MODEL_VERSION_REGISTRY,
    SCHEMA_REGISTRY,
    _register_model_from_dict,
)
from tuvl.core.models.model_version import ModelVersion, apply_db_enabled_overrides


def _model_dict(
    name: str,
    tablename: str,
    schema_version: str = "v1",
    enabled: bool = True,
) -> dict[str, Any]:
    return {
        "kind": "ModelDefinition",
        "enabled": enabled,
        "metadata": {"name": name, "schema_version": schema_version},
        "spec": {
            "tablename": tablename,
            "fields": [
                {"name": "id", "type": "uuid", "primary_key": True},
                {"name": "label", "type": "string"},
            ],
        },
    }


class _FakeResult:
    def __init__(self, rows: list[ModelVersion]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[ModelVersion]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[ModelVersion]) -> None:
        self._rows = rows

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    async def execute(self, _query: Any) -> _FakeResult:
        return _FakeResult(self._rows)


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


def _patch_db(monkeypatch: pytest.MonkeyPatch, rows: list[ModelVersion]) -> None:
    from tuvl.core.datasources import postgres

    monkeypatch.setattr(postgres, "_PRIMARY_DS", "main_postgres")
    monkeypatch.setattr(postgres, "_engines_rw", {"main_postgres": object()})
    monkeypatch.setattr(postgres, "_sessions_rw", {"main_postgres": lambda: _FakeSession(rows)})


@pytest.mark.asyncio
async def test_db_toggle_activates_yaml_disabled_version(monkeypatch):
    _register_model_from_dict(_model_dict("OvrActA", "ovr_act_a_v1"))
    _register_model_from_dict(
        _model_dict("OvrActA", "ovr_act_a_v2", schema_version="v2", enabled=False)
    )
    assert MODEL_REGISTRY["OvrActA"].__schema_version__ == "v1"

    _patch_db(
        monkeypatch,
        [ModelVersion(name="OvrActA", schema_version="v2", enabled=True, config_json="{}")],
    )
    await apply_db_enabled_overrides()

    assert MODEL_REGISTRY["OvrActA"].__schema_version__ == "v2"


@pytest.mark.asyncio
async def test_db_toggle_deactivates_yaml_enabled_version(monkeypatch):
    _register_model_from_dict(_model_dict("OvrDeact", "ovr_deact_v1"))
    assert "OvrDeact" in MODEL_REGISTRY

    _patch_db(
        monkeypatch,
        [ModelVersion(name="OvrDeact", schema_version="v1", enabled=False, config_json="{}")],
    )
    await apply_db_enabled_overrides()

    assert "OvrDeact" not in MODEL_REGISTRY
    assert "OvrDeact" not in SCHEMA_REGISTRY
    assert "OvrDeact" not in MODEL_DATASOURCE_MAP


@pytest.mark.asyncio
async def test_matching_flags_are_a_noop(monkeypatch):
    _register_model_from_dict(_model_dict("OvrNoop", "ovr_noop_v1"))
    cls_before = MODEL_REGISTRY["OvrNoop"]

    _patch_db(
        monkeypatch,
        [ModelVersion(name="OvrNoop", schema_version="v1", enabled=True, config_json="{}")],
    )
    await apply_db_enabled_overrides()

    assert MODEL_REGISTRY["OvrNoop"] is cls_before


@pytest.mark.asyncio
async def test_row_without_matching_yaml_version_is_ignored(monkeypatch):
    _patch_db(
        monkeypatch,
        [ModelVersion(name="Ghost", schema_version="v9", enabled=False, config_json="{}")],
    )
    await apply_db_enabled_overrides()

    assert "Ghost" not in MODEL_REGISTRY


@pytest.mark.asyncio
async def test_noop_without_primary_datasource(monkeypatch):
    from tuvl.core.datasources import postgres

    monkeypatch.setattr(postgres, "_engines_rw", {})
    await apply_db_enabled_overrides()  # must not raise


@pytest.mark.asyncio
async def test_noop_when_table_missing(monkeypatch):
    class _Boom:
        async def __aenter__(self):
            raise RuntimeError("relation does not exist")

        async def __aexit__(self, *args):
            return False

    from tuvl.core.datasources import postgres

    monkeypatch.setattr(postgres, "_PRIMARY_DS", "main_postgres")
    monkeypatch.setattr(postgres, "_engines_rw", {"main_postgres": object()})
    monkeypatch.setattr(postgres, "_sessions_rw", {"main_postgres": lambda: _Boom()})

    await apply_db_enabled_overrides()  # first boot: must not raise
