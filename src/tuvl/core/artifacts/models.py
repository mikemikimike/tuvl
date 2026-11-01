"""DB-source artifacts — the ``tuvl_system_artifacts`` table.

Production uploads land here (one row per version, never mutated in place —
hash-addressed history for free) and merge into the in-memory registry at
boot, below file-source artifacts in the name-collision precedence. Rows are
tenant-scoped in multi-tenant mode (``DynamicTenantModel``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from tuvl.core.models.base import DynamicTenantModel


class SystemArtifact(DynamicTenantModel, table=True):
    """One uploaded artifact version. Upload = new row; ``enabled`` is the only
    mutable column (disable = soft delete)."""

    __tablename__ = "tuvl_system_artifacts"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_tuvl_artifact_version"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(index=True)
    type: str
    version: int
    description: str = ""
    content: str  # prose text, or JSON-serialised spec for structured types
    content_hash: str
    enabled: bool = Field(default=True)
    created_by: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
