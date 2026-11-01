"""Connectivity check: list, then write, read back and delete a probe object."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from tuvl.storage.errors import StorageError
from tuvl.storage.store import Store

PAYLOAD = b"tuvl check storage"


async def check_store(store: Store) -> list[tuple[str, str | None]]:
    """Each step as ``(name, error or None)``; a read-only store is only listed."""
    key = f".tuvl-check/{uuid.uuid4().hex}"
    steps: list[tuple[str, str | None]] = []

    async def step(label: str, call: Callable[[], Awaitable[Any]]) -> bool:
        try:
            await call()
        except StorageError as exc:
            steps.append((label, f"{type(exc).__name__}: {exc}"))
            return False
        steps.append((label, None))
        return True

    async def read_back() -> None:
        data, _ = await store.get(key)
        if data != PAYLOAD:
            raise StorageError("the object read back differs from what was written")

    if not await step("list", lambda: store.list(limit=1)) or store.spec.readonly:
        return steps
    if await step("put", lambda: store.put(key, PAYLOAD, content_type="text/plain")):
        await step("head", lambda: store.head(key))
        await step("get", read_back)
        await step("delete", lambda: store.delete(key))
    return steps
