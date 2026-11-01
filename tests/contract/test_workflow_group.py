"""metadata.group organises workflows in Insight's picker; it is optional and purely cosmetic."""

import pytest
from pydantic import ValidationError

from tuvl.contract.schema import WorkflowDocument


def _doc(metadata: dict) -> dict:
    return {
        "kind": "Workflow",
        "version": "tuvl/v2",
        "metadata": metadata,
        "spec": {
            "agents": [
                {
                    "id": "a",
                    "description": "step",
                    "engine": "pending",
                    "routes": {"default": "END"},
                }
            ]
        },
    }


def test_group_is_optional_and_parsed() -> None:
    assert WorkflowDocument.model_validate(_doc({"name": "demo"})).metadata.group is None
    assert (
        WorkflowDocument.model_validate(_doc({"name": "demo", "group": "payments"})).metadata.group
        == "payments"
    )


def test_unknown_metadata_keys_are_still_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowDocument.model_validate(_doc({"name": "demo", "grouping": "payments"}))
