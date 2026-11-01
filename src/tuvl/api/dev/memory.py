"""Agent memory collections: browse and forget."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/memory", summary="Memory collections: how many memories, owners and when")
async def memory_collections() -> list[dict[str, Any]]:
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import AsyncSession

    from tuvl.runtime.host import get_host

    async with AsyncSession(get_host().engine) as session:
        rows = await session.execute(
            sa.text(
                "SELECT collection, count(*) AS memories, "
                "count(DISTINCT metadata->>'memory_key') AS owners, "
                "min(created_at) AS oldest, max(created_at) AS newest "
                "FROM tuvl_system_vector_store WHERE metadata ? 'memory_key' "
                "GROUP BY collection ORDER BY collection"
            )
        )
        return [
            {
                "collection": r.collection,
                "memories": r.memories,
                "owners": r.owners,
                "oldest": r.oldest.isoformat(),
                "newest": r.newest.isoformat(),
            }
            for r in rows
        ]


@router.get("/memory/{collection}", summary="The memories of a collection, newest first")
async def memory_rows(
    collection: str, key: str | None = None, limit: int = Query(default=50, ge=1, le=500)
) -> list[dict[str, Any]]:
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import AsyncSession

    from tuvl.runtime.host import get_host

    async with AsyncSession(get_host().engine) as session:
        rows = await session.execute(
            sa.text(
                "SELECT id, content, metadata, created_at FROM tuvl_system_vector_store "
                "WHERE collection = :c AND metadata ? 'memory_key' "
                "AND (CAST(:key AS text) IS NULL OR metadata->>'memory_key' = :key) "
                "ORDER BY created_at DESC LIMIT :n"
            ),
            {"c": collection, "key": key, "n": limit},
        )
        return [
            {
                "id": str(r.id),
                "key": r.metadata.get("memory_key"),
                "content": r.content,
                "at": r.created_at.isoformat(),
                "run_id": r.metadata.get("run_id"),
                "agent": r.metadata.get("agent"),
            }
            for r in rows
        ]


@router.delete("/memory/{collection}", summary="Forget everything one owner has in a collection")
async def memory_forget(collection: str, key: str = Query(min_length=1)) -> dict[str, Any]:
    from sqlalchemy.ext.asyncio import AsyncSession

    from tuvl.runtime import memory
    from tuvl.runtime.host import get_host

    async with AsyncSession(get_host().engine) as session:
        removed = await memory.forget(session, collection, key)
        await session.commit()
    return {"collection": collection, "key": key, "removed": removed}


@router.delete("/memory/{collection}/{row_id}", summary="Forget one memory")
async def memory_forget_one(collection: str, row_id: uuid.UUID) -> dict[str, Any]:
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import AsyncSession

    from tuvl.runtime.host import get_host

    async with AsyncSession(get_host().engine) as session:
        result: Any = await session.execute(
            sa.text(
                "DELETE FROM tuvl_system_vector_store "
                "WHERE id = :id AND collection = :c AND metadata ? 'memory_key'"
            ),
            {"id": row_id, "c": collection},
        )
        await session.commit()
    if not result.rowcount:
        raise HTTPException(404, "no such memory")
    return {"collection": collection, "id": str(row_id), "removed": 1}
