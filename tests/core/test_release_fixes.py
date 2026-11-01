"""Regression tests for the release-readiness security/correctness fixes.

Each test pins a specific defect found in the deep pre-release review so it
cannot silently regress.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from tuvl.core.auth.access import Claims, decode_token, require_groups, require_scope
from tuvl.core.auth.token import mint_token


def _claims(scopes: list[str], groups: list[str] | None = None, ttl: int | None = 3600) -> Claims:
    token = mint_token("user-1", groups or [], scopes, ttl_seconds=ttl)
    return decode_token(token)


# ── Blocker: require_scope/require_groups omitted set_time(), rejecting every
#    TTL'd (i.e. every real production) token with a 403. ────────────────────


def test_require_scope_accepts_ttl_token():
    """A token carrying an embedded TTL check must authorize, not 403."""
    user = require_scope("docs:read")(_claims(["docs:read"], ttl=3600))
    assert user.user_id == "user-1"


def test_require_scope_rejects_missing_scope():
    with pytest.raises(HTTPException) as exc:
        require_scope("docs:write")(_claims(["docs:read"], ttl=3600))
    assert exc.value.status_code == 403


def test_require_scope_iam_admin_bypass_with_ttl():
    """iam:admin satisfies any scope, even on a TTL'd token."""
    user = require_scope("anything:at:all")(_claims(["iam:admin"], ttl=3600))
    assert user.user_id == "user-1"


def test_require_groups_accepts_ttl_token():
    user = require_groups(["admins"])(_claims([], groups=["admins"], ttl=3600))
    assert user.user_id == "user-1"


def test_require_groups_rejects_missing_group():
    with pytest.raises(HTTPException) as exc:
        require_groups(["admins"])(_claims([], groups=["users"], ttl=3600))
    assert exc.value.status_code == 403


# ── Blocker: BaseRepository read self.model_name without ever assigning it,
#    so ?include= relation expansion raised AttributeError (always 500). ─────


def test_base_repository_sets_model_name():
    from tuvl.core.models.loader import MODEL_REGISTRY
    from tuvl.core.repositories.base import BaseRepository

    class _Dummy:  # stand-in registered model
        pass

    MODEL_REGISTRY["_DummyRelModel"] = _Dummy
    try:
        repo = BaseRepository("_DummyRelModel", session=None)  # type: ignore[arg-type]
        # The attribute MUST exist (its absence is the relation-expansion crash).
        assert repo.model_name == "_DummyRelModel"
    finally:
        MODEL_REGISTRY.pop("_DummyRelModel", None)


# ── Medium: unauthenticated introspection. Dev-only endpoints are 404 in prod;
#    the public SDK workflow manifest no longer leaks required_scope/group. ───


def test_require_dev_mode_404_outside_dev(monkeypatch):
    from tuvl.core.api import system_router
    from tuvl.core.config import settings

    monkeypatch.setattr(settings, "tuvl_dev_mode", False)
    with pytest.raises(HTTPException) as exc:
        system_router.require_dev_mode()
    assert exc.value.status_code == 404  # not disclosed in production

    monkeypatch.setattr(settings, "tuvl_dev_mode", True)
    assert system_router.require_dev_mode() is None  # available in dev


@pytest.mark.asyncio
async def test_workflow_manifest_omits_scope_strings():
    from tuvl.contract.registry import WORKFLOWS
    from tuvl.contract.schema import WorkflowDocument
    from tuvl.core.api.system_router import get_workflow_manifest, list_workflows

    WORKFLOWS["t_manifest_wf"] = WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {
                "name": "t_manifest_wf",
                "required_scope": "secret:scope",
                "required_group": "secret-group",
            },
            "spec": {
                "trigger": {"http": {"path": "/x"}},
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
    try:
        listing = await list_workflows()
        assert "t_manifest_wf" in listing
        assert "secret" not in str(listing["t_manifest_wf"])
        # route-resolution fields the SDK actually needs stay present
        assert listing["t_manifest_wf"]["trigger_path"] == "/x"

        one = await get_workflow_manifest("t_manifest_wf")
        assert "secret" not in str(one)
        assert one["agents"] == [{"id": "a", "engine": "pending"}]
    finally:
        WORKFLOWS.pop("t_manifest_wf", None)
