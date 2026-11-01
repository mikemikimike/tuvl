"""Local-disk backend: a directory on the engine host, confined to its root."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tuvl.storage.errors import Conflict, InvalidKey, NotFound, StorageError, TooLarge, Unsupported
from tuvl.storage.types import Method, RawInfo

_META_DIR = ".meta"
_CHUNK = 1 << 20


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class LocalBackend:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._real = os.path.realpath(self.root)

    def _path(self, key: str) -> Path:
        if key.split("/", 1)[0] == _META_DIR:
            raise InvalidKey(f"'{_META_DIR}' is reserved")
        target = os.path.realpath(self.root / key)
        if target != self._real and not target.startswith(self._real + os.sep):
            raise InvalidKey("key resolves outside the store root")
        return Path(target)

    def _meta_path(self, key: str) -> Path:
        return self.root / _META_DIR / f"{key}.json"

    def _info(self, key: str, path: Path) -> RawInfo:
        stat = path.stat()
        meta: dict[str, Any] = {}
        meta_file = self._meta_path(key)
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text())
            except (OSError, ValueError):
                meta = {}
        sha = meta.get("sha256", "")
        # A file written by an older version, or changed behind the store's back, is hashed again.
        if not sha or meta.get("size") != stat.st_size or meta.get("mtime_ns") != stat.st_mtime_ns:
            digest = hashlib.sha256()
            with path.open("rb") as fh:
                while chunk := fh.read(_CHUNK):
                    digest.update(chunk)
            sha = digest.hexdigest()
        return RawInfo(
            key=key,
            size=stat.st_size,
            content_type=meta.get("content_type", ""),
            etag=sha,
            sha256=sha,
            modified=_iso(stat.st_mtime),
        )

    def _put(
        self, key: str, data: bytes, content_type: str, metadata: dict[str, str], overwrite: bool
    ) -> RawInfo:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = dest.parent / f".{dest.name}.{secrets.token_hex(6)}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            if overwrite:
                os.replace(tmp, dest)
            else:
                try:
                    os.link(tmp, dest)
                except FileExistsError as exc:
                    raise Conflict(f"'{key}' already exists") from exc
        finally:
            tmp.unlink(missing_ok=True)
        stat = dest.stat()
        sha = metadata.get("sha256") or hashlib.sha256(data).hexdigest()
        meta = self._meta_path(key)
        meta.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        meta.write_text(
            json.dumps(
                {
                    "content_type": content_type,
                    "metadata": metadata,
                    "sha256": sha,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                }
            )
        )
        return RawInfo(
            key=key,
            size=stat.st_size,
            content_type=content_type,
            etag=sha,
            sha256=sha,
            modified=_iso(stat.st_mtime),
        )

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
        overwrite: bool,
    ) -> RawInfo:
        return await asyncio.to_thread(self._put, key, data, content_type, metadata, overwrite)

    def _get(self, key: str, max_bytes: int) -> tuple[bytes, RawInfo]:
        path = self._path(key)
        if not path.is_file():
            raise NotFound(f"'{key}' not found")
        if path.stat().st_size > max_bytes:
            raise TooLarge(f"'{key}' is larger than {max_bytes} bytes")
        return path.read_bytes(), self._info(key, path)

    async def get(self, key: str, max_bytes: int) -> tuple[bytes, RawInfo]:
        return await asyncio.to_thread(self._get, key, max_bytes)

    def _head(self, key: str) -> RawInfo:
        path = self._path(key)
        if not path.is_file():
            raise NotFound(f"'{key}' not found")
        return self._info(key, path)

    async def head(self, key: str) -> RawInfo:
        return await asyncio.to_thread(self._head, key)

    def _list(
        self, prefix: str, limit: int, cursor: str | None
    ) -> tuple[list[RawInfo], str | None]:
        keys: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            if Path(dirpath) == self.root:
                dirnames[:] = [d for d in dirnames if d != _META_DIR]
            for name in filenames:
                if name.startswith(".") and name.endswith(".tmp"):
                    continue
                rel = (Path(dirpath) / name).relative_to(self.root).as_posix()
                if rel.startswith(prefix) and (cursor is None or rel > cursor):
                    keys.append(rel)
        keys.sort()
        page = keys[:limit]
        more = len(keys) > limit
        items = [self._info(k, self.root / k) for k in page]
        return items, (page[-1] if more and page else None)

    async def list(
        self, prefix: str, limit: int, cursor: str | None
    ) -> tuple[list[RawInfo], str | None]:
        return await asyncio.to_thread(self._list, prefix, limit, cursor)

    def _delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        self._meta_path(key).unlink(missing_ok=True)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, key)

    def _copy(self, src: str, dst: str, overwrite: bool) -> RawInfo:
        data, info = self._get(src, 1 << 40)
        meta_file = self._meta_path(src)
        content_type, metadata = info.content_type, {}
        if meta_file.is_file():
            try:
                loaded = json.loads(meta_file.read_text())
                content_type, metadata = loaded.get("content_type", ""), loaded.get("metadata", {})
            except (OSError, ValueError) as exc:
                raise StorageError(f"unreadable metadata for '{src}'") from exc
        return self._put(dst, data, content_type, metadata, overwrite)

    async def copy(self, src: str, dst: str, *, overwrite: bool) -> RawInfo | None:
        return await asyncio.to_thread(self._copy, src, dst, overwrite)

    async def presign(self, key: str, method: Method, expires_in: int) -> str:
        raise Unsupported("presigned URLs are not available for local stores")

    async def aclose(self) -> None:
        return None
