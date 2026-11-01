"""DB-source artifact loading — merge ``tuvl_system_artifacts`` rows into the
in-memory registry at boot (after ``init_db``), below file-source precedence."""

from __future__ import annotations

import json
from typing import Any

import structlog

from tuvl.core.artifacts.kinds import PROSE_TYPES
from tuvl.core.artifacts.registry import register_artifact

logger = structlog.get_logger(__name__)


def _decode_content(type_: str, content: str) -> Any:
    if type_ in PROSE_TYPES:
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}


async def merge_db_artifacts() -> None:
    """Load enabled DB-source artifact rows into the registry.

    File-source names shadow DB rows (precedence file → db → external, warned
    by ``register_artifact``). Skipped silently on the first boot before the
    table exists, and entirely when no Postgres datasource is registered.
    """
    from tuvl.core.artifacts.models import SystemArtifact
    from tuvl.core.datasources.postgres import _PRIMARY_DS, _engines_rw, _sessions_rw

    if not _engines_rw or _PRIMARY_DS not in _engines_rw:
        return

    from sqlalchemy import select
    from sqlmodel import col

    try:
        async with _sessions_rw[_PRIMARY_DS]() as session:
            result = await session.execute(
                select(SystemArtifact).where(col(SystemArtifact.enabled).is_(True))
            )
            rows = list(result.scalars().all())
    except Exception as exc:
        logger.info("artifacts.db_merge.skipped", reason=type(exc).__name__)
        return

    for row in rows:
        register_artifact(
            name=row.name,
            type_=row.type,
            version=row.version,
            content=_decode_content(row.type, row.content),
            source="db",
            description=row.description or "",
            enabled=row.enabled,
        )
    if rows:
        logger.info("artifacts.db_merged", count=len(rows))
