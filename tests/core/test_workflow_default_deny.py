"""Production default-deny for workflow triggers: a bearer token is required
unless the trigger opts into ``trigger.http.public: true`` or dev mode exempts
it, and a declared scope/group always wins — even against ``public``."""

from __future__ import annotations

from typing import Any

import pytest

from tuvl.api.auth import workflow_policy
from tuvl.contract.schema import WorkflowDocument
from tuvl.core.config import settings


def _doc(public: bool = False, **meta: Any) -> WorkflowDocument:
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "wf", **meta},
            "spec": {
                "trigger": {"http": {"path": "/wf", "public": public}},
                "agents": [
                    {
                        "id": "a",
                        "description": "d",
                        "engine": "pending",
                        "routes": {"default": "END"},
                    }
                ],
            },
        }
    )


@pytest.fixture(autouse=True)
def _production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tuvl_dev_mode", False)


def test_unscoped_trigger_needs_a_token() -> None:
    assert workflow_policy(_doc()).anonymous_ok() is False


def test_public_trigger_is_anonymous_ok() -> None:
    assert workflow_policy(_doc(public=True)).anonymous_ok() is True


@pytest.mark.parametrize("meta", [{"required_scope": "x:y"}, {"required_group": "g"}])
def test_scope_or_group_wins_over_public(meta: dict[str, str]) -> None:
    assert workflow_policy(_doc(public=True, **meta)).anonymous_ok() is False


def test_dev_mode_exempts_unscoped_triggers_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tuvl_dev_mode", True)
    assert workflow_policy(_doc()).anonymous_ok() is True
    assert workflow_policy(_doc(required_scope="x:y")).anonymous_ok() is False
