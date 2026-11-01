"""TD-56: a workflow that names a model that is not loaded is refused with the reason,
not started and failed at its first db call with a generic error."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from tuvl.api.runs import router as runs_router
from tuvl.contract.schema import WorkflowDocument
from tuvl.core.models import loader
from tuvl.runtime.host import RuntimeHost, WorkflowUnavailableError, set_host, unavailable_reasons


def doc(models: list[str]) -> WorkflowDocument:
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "uses_models"},
            "spec": {
                "models": models,
                "trigger": {
                    "input": {"x": "str"},
                    "http": {"path": "/api/uses-models", "public": True},
                },
                "agents": [
                    {
                        "id": "echo",
                        "description": "noop",
                        "engine": "code",
                        "code": {"run": "noop"},
                        "inputs": {"x": "str"},
                        "routes": {"default": "END", "error": "END"},
                    }
                ],
            },
        }
    )


@pytest.fixture(autouse=True)
def _registries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(loader.MODEL_REGISTRY, "Loaded", object)
    monkeypatch.setitem(loader.MODEL_VERSION_REGISTRY, "Disabled", {"v1": {"enabled": False}})
    monkeypatch.delitem(loader.MODEL_REGISTRY, "Disabled", raising=False)
    monkeypatch.delitem(loader.MODEL_REGISTRY, "Ghost", raising=False)
    monkeypatch.delitem(loader.MODEL_VERSION_REGISTRY, "Ghost", raising=False)


def test_reasons_tell_disabled_from_undefined() -> None:
    assert unavailable_reasons(doc(["Loaded", "Loaded@2"])) == []
    disabled, ghost = unavailable_reasons(doc(["Disabled@v1", "Ghost"]))
    assert "'Disabled' is disabled" in disabled and "re-enable" in disabled
    assert ghost == "model 'Ghost' is not defined in this project"


async def test_enqueue_refuses_and_names_the_model(pg_engine: AsyncEngine) -> None:
    host = RuntimeHost(pg_engine)
    with pytest.raises(WorkflowUnavailableError) as raised:
        await host.enqueue(doc(["Disabled"]), {"x": "1"}, principal=None, trigger="test")
    assert raised.value.workflow == "uses_models" and "disabled" in raised.value.reasons[0]
    run_id = await host.enqueue(doc(["Loaded"]), {"x": "1"}, principal=None, trigger="test")
    assert run_id


async def test_unavailable_lists_only_the_broken_workflows(pg_engine: AsyncEngine) -> None:
    ok, bad = doc(["Loaded"]), doc(["Disabled"])
    bad.metadata.name = "bad_one"
    host = RuntimeHost(pg_engine, workflows={"uses_models": ok, "bad_one": bad})
    assert list(host.unavailable()) == ["bad_one"]


async def test_rest_run_returns_409_with_reasons(pg_engine: AsyncEngine) -> None:
    broken = doc(["Disabled"])
    set_host(RuntimeHost(pg_engine, workflows={"uses_models": broken}))
    try:
        app = FastAPI()
        app.include_router(runs_router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            res = await client.post("/api/workflows/uses_models/runs", json={"input": {"x": "1"}})
    finally:
        set_host(None)
    assert res.status_code == 409, res.text
    detail: dict[str, Any] = res.json()["detail"]
    assert detail["error"] == "workflow_unavailable"
    assert "'Disabled' is disabled" in detail["reasons"][0]
