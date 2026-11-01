"""Shared Pydantic schemas for the auth layer."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

# Allowlist for scope/group names carried in tokens. Lives here (not access)
# so the CLI validator can import it without touching the key manager.
SCOPE_NAME_RE = re.compile(r"^[\w:.\-/]+$")


class TokenUser(BaseModel):
    """Authenticated principal extracted from a verified access token.

    Attributes
    ----------
    user_id:
        The ``user("<id>")`` fact value from the token's authority block.
    groups:
        All ``group("<name>")`` fact values present in the token.
    scopes:
        All ``scope("<name>")`` fact values present in the token,
        e.g. ``["requisition:write", "candidate:read"]``.
    """

    user_id: str = Field(..., description="Identifier of the authenticated user.")
    groups: list[str] = Field(
        default_factory=list, description="Group memberships claimed by the token."
    )
    scopes: list[str] = Field(
        default_factory=list, description="Permission scopes claimed by the token."
    )
    tenant_id: str | None = Field(
        default=None,
        description=(
            'Tenant identifier extracted from the token\'s `tenant("<id>")` '
            "fact.  ``None`` when the token carries no tenant fact (single-tenant "
            "deployments, legacy tokens)."
        ),
    )
