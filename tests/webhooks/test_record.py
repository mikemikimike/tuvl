"""``webhooks.record`` looks the run up only when it has to."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

import tuvl.webhooks as webhooks
from tuvl.contract.schema import WorkflowDocument
from tuvl.core.config import settings

pytestmark = pytest.mark.asyncio


def _doc(name: str, hooks: list[dict[str, Any]]) -> WorkflowDocument:
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": name},
            "spec": {
                "agents": [
                    {
                        "id": "a",
                        "description": "a",
                        "engine": "code",
                        "code": {"run": "a"},
                        "routes": {"default": "END"},
                    }
                ],
                "webhooks": hooks,
            },
        }
    )


HOOK = {
    "name": "ops",
    "url": "https://hooks.example.com/x",
    "secret": "${WH_SECRET}",
    "events": ["completed"],
}


class _Session:
    def __init__(self, workflow: str) -> None:
        self.workflow, self.gets, self.added = workflow, 0, []

    async def get(self, _model: Any, _id: Any) -> Any:
        self.gets += 1
        return type("Run", (), {"workflow": self.workflow})()

    def add(self, row: Any) -> None:
        self.added.append(row)


@pytest.fixture
def loaded(monkeypatch: pytest.MonkeyPatch) -> dict[str, WorkflowDocument]:
    monkeypatch.setattr(settings, "tuvl_webhooks_enabled", True)
    workflows: dict[str, WorkflowDocument] = {"quiet": _doc("quiet", [])}
    monkeypatch.setattr(webhooks, "registry", lambda: workflows)
    return workflows


async def test_no_lookup_when_no_loaded_workflow_declares_webhooks(loaded: dict) -> None:
    s = _Session("quiet")
    assert await webhooks.record(s, uuid.uuid4(), "run_completed", 3, None) == 0  # type: ignore[arg-type]
    assert s.gets == 0


async def test_no_lookup_when_the_caller_names_the_workflow(loaded: dict) -> None:
    loaded["loud"] = _doc("loud", [HOOK])
    s = _Session("loud")
    assert await webhooks.record(s, uuid.uuid4(), "run_completed", 3, None, workflow="loud") == 1  # type: ignore[arg-type]
    assert s.gets == 0 and s.added[0].webhook == "ops"
    assert await webhooks.record(s, uuid.uuid4(), "run_completed", 4, None, workflow="quiet") == 0  # type: ignore[arg-type]


async def test_the_run_is_looked_up_when_the_workflow_is_unknown(loaded: dict) -> None:
    loaded["loud"] = _doc("loud", [HOOK])
    s = _Session("loud")
    assert await webhooks.record(s, uuid.uuid4(), "run_completed", 3, None) == 1  # type: ignore[arg-type]
    assert s.gets == 1
