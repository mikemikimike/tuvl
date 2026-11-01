"""What backends and the store exchange."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

Method = Literal["GET", "PUT"]


@dataclass(frozen=True)
class RawInfo:
    """An object as a backend sees it: the full key, prefix included."""

    key: str
    size: int
    content_type: str = ""
    etag: str = ""
    sha256: str = ""
    modified: str = ""


@dataclass(frozen=True)
class Blob:
    """An object as a workflow sees it: the key is relative to the store's prefix."""

    store: str
    key: str
    size: int
    content_type: str = ""
    etag: str = ""
    sha256: str = ""
    modified: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Listing:
    items: list[Blob]
    cursor: str | None = None


@dataclass(frozen=True)
class Presigned:
    url: str
    expires_at: str


class Backend(Protocol):
    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
        overwrite: bool,
    ) -> RawInfo: ...

    async def get(self, key: str, max_bytes: int) -> tuple[bytes, RawInfo]: ...

    async def head(self, key: str) -> RawInfo: ...

    async def list(
        self, prefix: str, limit: int, cursor: str | None
    ) -> tuple[list[RawInfo], str | None]: ...

    async def delete(self, key: str) -> None: ...

    async def copy(self, src: str, dst: str, *, overwrite: bool) -> RawInfo | None:
        """Server-side copy, or ``None`` when the backend has none (the store then reads and writes)."""
        ...

    async def presign(self, key: str, method: Method, expires_in: int) -> str: ...

    async def aclose(self) -> None: ...
