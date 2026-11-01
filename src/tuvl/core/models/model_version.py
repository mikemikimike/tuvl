"""ModelVersion — persistent tracking for multi-version model definitions.

Mirrors WorkflowVersion for ModelDefinition YAML documents.

Stores each ``(name, schema_version)`` pair so that:

- The ``enabled`` flag can be toggled via the admin API without a YAML edit;
  the toggle takes effect at the next boot (``apply_db_enabled_overrides()``,
  run inside ``init_db()``, lets the DB flag win over the YAML value).
- ``GET /admin/models`` can list all versions with their current status.

The table is created inside ``init_db()`` on the primary datasource.
``sync_model_versions()`` is called from the FastAPI lifespan after
``init_db()`` to upsert the in-memory ``MODEL_VERSION_REGISTRY`` into the
DB, preserving any ``enabled`` values that were previously toggled via the
admin API.
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
import structlog
from sqlmodel import Field, SQLModel

logger = structlog.get_logger("tuvl.models")


class ModelVersion(SQLModel, table=True):
    """Persistent record for one model definition document."""

    __tablename__ = "tuvl_system_model_versions"
    __table_args__ = (
        sa.UniqueConstraint("name", "schema_version", name="uq_model_name_version"),
        {"extend_existing": True},
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(sa_column=sa.Column(sa.String, nullable=False, index=True))
    schema_version: str = Field(
        sa_column=sa.Column(sa.String, nullable=False, index=True, server_default="v1"),
        default="v1",
    )
    enabled: bool = Field(
        sa_column=sa.Column(sa.Boolean, nullable=False, server_default="true"),
        default=True,
    )
    config_json: str = Field(sa_column=sa.Column(sa.Text, nullable=False))

    def get_config(self) -> dict[str, Any]:
        """Deserialise the stored JSON config."""
        config: dict[str, Any] = json.loads(self.config_json)
        return config


async def apply_db_enabled_overrides() -> None:
    """Apply admin-toggled ``enabled`` flags to the in-memory model registries.

    Called from ``init_db()`` after the engines connect and **before**
    ``create_all``, so a version activated via
    ``PATCH /admin/models/{name}/{version}/toggle`` is registered (and its
    table created) on the next boot without a YAML edit. The DB flag wins over
    the YAML ``enabled`` value; rows with no matching in-memory version are
    ignored, and the first boot (table not yet created) is a no-op.
    """
    from tuvl.core.datasources.postgres import _PRIMARY_DS, _engines_rw, _sessions_rw
    from tuvl.core.models import loader

    if not _engines_rw or _PRIMARY_DS not in _engines_rw:
        return

    from sqlalchemy import select

    try:
        async with _sessions_rw[_PRIMARY_DS]() as session:
            result = await session.execute(select(ModelVersion))
            rows = list(result.scalars().all())
    except Exception as exc:
        logger.info("model_versions.overrides.skipped", reason=str(exc.__class__.__name__))
        return

    for row in rows:
        cfg = loader.MODEL_VERSION_REGISTRY.get(row.name, {}).get(row.schema_version)
        if cfg is None:
            continue
        yaml_enabled = cfg.get("enabled", True) is not False
        if bool(row.enabled) == yaml_enabled:
            continue
        if row.enabled:
            loader._register_model_from_dict(
                {**cfg, "enabled": True},
                filename=f"<admin-toggle {row.name}@{row.schema_version}>",
            )
            logger.info(
                "model_versions.override.activated",
                model=row.name,
                schema_version=row.schema_version,
            )
        else:
            cls = loader.MODEL_REGISTRY.get(row.name)
            if cls is not None and getattr(cls, "__schema_version__", None) == row.schema_version:
                from tuvl.core.config_loader import _forget_model_tables

                _forget_model_tables([cls])
                loader.MODEL_REGISTRY.pop(row.name, None)
                loader.MODEL_DATASOURCE_MAP.pop(row.name, None)
                loader.SCHEMA_REGISTRY.pop(row.name, None)
                loader.MODEL_RELATIONS.pop(row.name, None)
                logger.info(
                    "model_versions.override.deactivated",
                    model=row.name,
                    schema_version=row.schema_version,
                )


async def sync_model_versions() -> None:
    """Upsert every ``MODEL_VERSION_REGISTRY`` entry into ``tuvl_system_model_versions``.

    Called once from the FastAPI lifespan after ``init_db()`` has created
    application tables.  Preserves the DB-controlled ``enabled`` flag when a
    row already exists so that admin toggles survive server restarts.

    Safe to call when no primary datasource is configured (no-op).
    """
    from tuvl.core.datasources.postgres import (
        _PRIMARY_DS,
        _engines_rw,
        _sessions_rw,
    )
    from tuvl.core.models.loader import MODEL_VERSION_REGISTRY

    if not _engines_rw or _PRIMARY_DS not in _engines_rw:
        logger.info("model_versions.sync.skipped", reason="no primary datasource")
        return

    from sqlalchemy import select

    async with _sessions_rw[_PRIMARY_DS]() as session:
        existing = {
            (r.name, r.schema_version): r
            for r in (await session.execute(select(ModelVersion))).scalars()
        }
        for name, versions in MODEL_VERSION_REGISTRY.items():
            for schema_version, config in versions.items():
                row = existing.get((name, schema_version))
                config_json = json.dumps(config)

                if row is None:
                    session.add(
                        ModelVersion(
                            name=name,
                            schema_version=schema_version,
                            enabled=bool(config.get("enabled", True)),
                            config_json=config_json,
                        )
                    )
                else:
                    row.config_json = config_json
                    session.add(row)

        await session.commit()

    total = sum(len(v) for v in MODEL_VERSION_REGISTRY.values())
    logger.info("model_versions.sync.complete", count=total)
