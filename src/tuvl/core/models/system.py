"""System-managed SQLModel tables for built-in tuvl RAG features.

These tables are ALWAYS created on the primary datasource — they are not
user-defined models and are never added to MODEL_REGISTRY or SCHEMA_REGISTRY.
They are created directly in ``init_db()`` via ``SQLModel.metadata.create_all``.

Requires the PostgreSQL ``pgvector`` extension (``CREATE EXTENSION vector``).
The extension is enabled automatically in ``init_db()`` before table creation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Computed, Index
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlmodel import Field

from tuvl.core.models.base import DynamicTenantModel

try:
    from pgvector.sqlalchemy import Vector as _Vector

    _PGVECTOR_AVAILABLE = True
except ImportError:  # pragma: no cover
    _Vector = None
    _PGVECTOR_AVAILABLE = False


def _default_dimensions() -> int:
    """Return the default embedding dimension from project settings."""
    try:
        from tuvl.core.config import settings

        return settings.tuvl_default_embedding_dimensions
    except Exception:
        return 1536


class SystemVectorStore(DynamicTenantModel, table=True):
    """Single physical table backing all logical vector collections.

    Each row belongs to exactly one *collection*.  The ``instance_id`` column
    enables **ephemeral scoping**: rows where ``instance_id IS NULL`` are
    *global* and visible across all workflow runs; rows with an instance_id
    are scoped to a single workflow execution.

    Full-hybrid retrieval uses **Reciprocal Rank Fusion (RRF)** at query time,
    fusing L2 vector distance on ``embedding`` and PostgreSQL full-text search
    on ``content_tsvector``.

    Indexes
    -------
    * GIN index on ``content_tsvector`` — fast lexical full-text search.
    * GIN index on ``metadata`` — fast JSONB containment queries (``@>``).
    * HNSW index on ``embedding`` — created post-table via raw SQL in
      ``init_db()`` because the dimension is a runtime value.
    """

    __tablename__ = "tuvl_system_vector_store"

    __table_args__ = (
        # GIN full-text index — enables fast @@ plainto_tsquery queries
        Index(
            "ix_svs_tsvector_gin",
            "content_tsvector",
            postgresql_using="gin",
        ),
        # GIN metadata index — enables fast @> JSONB containment queries
        Index(
            "ix_svs_metadata_gin",
            "metadata",
            postgresql_using="gin",
        ),
        # HNSW index for vector similarity is created via raw SQL in init_db()
        # after the table exists, because the dimension is a runtime setting.
        {"extend_existing": True},
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=sa.Column(
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
    )

    collection: str = Field(
        sa_column=sa.Column(sa.String, nullable=False, index=True),
    )

    instance_id: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.String, nullable=True, index=True),
    )

    content: str = Field(
        sa_column=sa.Column(sa.Text, nullable=False),
    )

    # When the row was written: orders a memory by time and drives retention.
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=sa.Column(
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            index=True,
        ),
    )

    # Computed, persisted tsvector for full-text search.
    # ``Computed`` with ``persisted=True`` maps to GENERATED ALWAYS AS … STORED.
    content_tsvector: Any | None = Field(
        default=None,
        sa_column=sa.Column(
            TSVECTOR,
            Computed("to_tsvector('english', content)", persisted=True),
            nullable=True,
        ),
    )

    # Vector embedding sized to settings.tuvl_default_embedding_dimensions — a
    # SINGLE global dimension shared by every collection (a mismatched embedding
    # model only fails at insert time). Falls back to Text when pgvector is not
    # installed so the table still creates; RAG nodes then error at call time.
    embedding: Any | None = Field(
        default=None,
        sa_column=sa.Column(
            _Vector(_default_dimensions())
            if _PGVECTOR_AVAILABLE and _Vector is not None
            else sa.Text,
            nullable=True,
        ),
    )

    # JSONB arbitrary metadata for caller-defined key/value pairs.
    # Attribute renamed to avoid SQLAlchemy's reserved "metadata" name.
    extra_metadata: dict | None = Field(
        default=None,
        sa_column=sa.Column("metadata", JSONB, nullable=True),
    )
