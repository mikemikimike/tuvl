"""A named store: the backend plus the rules every operation obeys (prefix, readonly, size, retries)."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from tuvl.storage.errors import (
    Conflict,
    Forbidden,
    InvalidKey,
    NotFound,
    TooLarge,
    Unavailable,
)
from tuvl.storage.keys import join_prefix, strip_prefix, validate_key, validate_prefix
from tuvl.storage.spec import StoreSpec
from tuvl.storage.types import Backend, Blob, Listing, Method, Presigned, RawInfo

T = TypeVar("T")
ATTEMPTS = 3
LIST_MAX = 1000


class Store:
    def __init__(self, name: str, spec: StoreSpec, backend: Backend) -> None:
        self.name = name
        self.spec = spec
        self.backend = backend

    def _full(self, key: str) -> str:
        return join_prefix(self.spec.prefix, validate_key(key))

    def _blob(self, info: RawInfo) -> Blob:
        return Blob(
            store=self.name,
            key=strip_prefix(self.spec.prefix, info.key),
            size=info.size,
            content_type=info.content_type,
            etag=info.etag,
            sha256=info.sha256,
            modified=info.modified,
        )

    def _writable(self, what: str) -> None:
        if self.spec.readonly:
            raise Forbidden(f"store '{self.name}' is read-only: {what} refused")

    async def _run(self, op: str, key: str, call: Callable[[], Awaitable[T]]) -> T:
        from opentelemetry import trace

        tracer = trace.get_tracer("tuvl.storage")
        with tracer.start_as_current_span(f"storage {op}") as span:
            span.set_attribute("storage.provider", self.spec.provider)
            span.set_attribute("storage.store", self.name)
            span.set_attribute("storage.op", op)
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    return await call()
                except Unavailable:
                    if attempt == ATTEMPTS:
                        raise
                    await asyncio.sleep(random.uniform(0.5, 1.0) * 0.2 * 2**attempt)
            raise AssertionError("unreachable")

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "",
        metadata: dict[str, str] | None = None,
        if_exists: str = "fail",
    ) -> Blob:
        self._writable("put")
        full = self._full(key)
        if len(data) > self.spec.max_object_bytes:
            raise TooLarge(
                f"{len(data)} bytes exceeds max_object_bytes ({self.spec.max_object_bytes})"
            )
        digest = hashlib.sha256(data).hexdigest()
        meta = {**(metadata or {}), "sha256": digest}
        overwrite = if_exists == "overwrite"

        async def call() -> RawInfo:
            return await self.backend.put(
                full,
                data,
                content_type=content_type or "application/octet-stream",
                metadata=meta,
                overwrite=overwrite,
            )

        try:
            info = await self._run("put", full, call)
        except Conflict:
            # A retried put whose first attempt landed finds its own object.
            existing = await self.backend.head(full)
            if existing.sha256 != digest:
                raise
            info = existing
        blob = self._blob(info)
        return blob if blob.sha256 else dataclasses.replace(blob, sha256=digest)

    async def get(self, key: str, max_bytes: int | None = None) -> tuple[bytes, Blob]:
        full = self._full(key)
        cap = min(max_bytes or self.spec.max_object_bytes, self.spec.max_object_bytes)

        async def call() -> tuple[bytes, RawInfo]:
            return await self.backend.get(full, cap)

        data, info = await self._run("get", full, call)
        return data, self._blob(info)

    async def head(self, key: str) -> Blob:
        full = self._full(key)
        return self._blob(await self._run("head", full, lambda: self.backend.head(full)))

    async def list(self, prefix: str = "", limit: int = 100, cursor: str | None = None) -> Listing:
        full = join_prefix(self.spec.prefix, validate_prefix(prefix))
        limit = max(1, min(limit, LIST_MAX))

        async def call() -> tuple[list[RawInfo], str | None]:
            return await self.backend.list(full, limit, cursor)

        infos, next_cursor = await self._run("list", full, call)
        return Listing([self._blob(i) for i in infos], next_cursor)

    async def delete(self, key: str) -> None:
        self._writable("delete")
        full = self._full(key)
        await self._run("delete", full, lambda: self.backend.delete(full))

    async def copy(
        self, key: str, to_key: str, *, to_store: Store | None = None, if_exists: str = "fail"
    ) -> Blob:
        target = to_store or self
        target._writable("copy")
        src, dst = self._full(key), target._full(to_key)
        overwrite = if_exists == "overwrite"
        if target is self:

            async def call() -> RawInfo | None:
                return await self.backend.copy(src, dst, overwrite=overwrite)

            info = await self._run("copy", src, call)
            if info is not None:
                return self._blob(info)
        data, source = await self.get(key)
        if not overwrite:
            try:
                await target.head(to_key)
            except NotFound:
                pass
            else:
                raise Conflict(f"'{to_key}' already exists")
        return await target.put(to_key, data, content_type=source.content_type, if_exists=if_exists)

    async def presign(self, key: str, method: Method = "GET", expires_in: int = 900) -> Presigned:
        if method == "PUT":
            self._writable("presign PUT")
        if not 1 <= expires_in <= self.spec.presign_max_seconds:
            raise InvalidKey(f"expires_in must be 1..{self.spec.presign_max_seconds} seconds")
        full = self._full(key)
        url = await self._run(
            "presign", full, lambda: self.backend.presign(full, method, expires_in)
        )
        expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        return Presigned(url, expires_at)

    async def aclose(self) -> None:
        await self.backend.aclose()
