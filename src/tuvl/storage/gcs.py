"""Google Cloud Storage over the JSON API (bearer tokens). HMAC keys use the S3 backend instead."""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from tuvl.storage.creds import CachedToken
from tuvl.storage.errors import Conflict, NotFound, StorageError, Unsupported, from_status
from tuvl.storage.http import Http, describe
from tuvl.storage.types import Method, RawInfo

DEFAULT_BASE = "https://storage.googleapis.com"


def _name(key: str) -> str:
    return quote(key, safe="")


def _resource_info(doc: dict[str, Any]) -> RawInfo:
    return RawInfo(
        key=str(doc.get("name", "")),
        size=int(doc.get("size", 0)),
        content_type=str(doc.get("contentType", "")),
        etag=str(doc.get("etag", "")),
        sha256=str((doc.get("metadata") or {}).get("sha256", "")),
        modified=str(doc.get("updated", ""))[:19] + "Z" if doc.get("updated") else "",
    )


class GcsBackend:
    def __init__(self, *, bucket: str, endpoint: str, token: CachedToken, http: Http) -> None:
        self.bucket = bucket
        self._base = (endpoint or DEFAULT_BASE).rstrip("/")
        self._token = token
        self._http = http

    def _api(self, suffix: str = "") -> str:
        return f"{self._base}/storage/v1/b/{self.bucket}/o{suffix}"

    async def _send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        ok: tuple[int, ...] = (200,),
        max_bytes: int | None = None,
    ) -> httpx.Response:
        out = dict(headers or {})
        out["authorization"] = f"Bearer {await self._token.get()}"
        response = await self._http.send(
            method, url, headers=out, content=body, max_bytes=max_bytes
        )
        if response.status_code in ok:
            return response
        raise _error(method, url, response)

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
        overwrite: bool,
    ) -> RawInfo:
        boundary = secrets.token_hex(16)
        head = json.dumps({"name": key, "contentType": content_type, "metadata": metadata})
        body = (
            (
                f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{head}\r\n"
                f"--{boundary}\r\nContent-Type: {content_type}\r\n\r\n"
            ).encode()
            + data
            + f"\r\n--{boundary}--".encode()
        )
        query = "uploadType=multipart" + ("" if overwrite else "&ifGenerationMatch=0")
        response = await self._send(
            "POST",
            f"{self._base}/upload/storage/v1/b/{self.bucket}/o?{query}",
            headers={"content-type": f"multipart/related; boundary={boundary}"},
            body=body,
        )
        return _resource_info(response.json())

    async def get(self, key: str, max_bytes: int) -> tuple[bytes, RawInfo]:
        response = await self._send(
            "GET", self._api(f"/{_name(key)}?alt=media"), max_bytes=max_bytes
        )
        h = response.headers
        modified = ""
        if h.get("last-modified"):
            modified = (
                parsedate_to_datetime(h["last-modified"])
                .astimezone(UTC)
                .strftime("%Y-%m-%dT%H:%M:%SZ")
            )
        return response.content, RawInfo(
            key=key,
            size=len(response.content),
            content_type=h.get("content-type", ""),
            etag=h.get("etag", "").strip('"'),
            sha256=h.get("x-goog-meta-sha256", ""),
            modified=modified,
        )

    async def head(self, key: str) -> RawInfo:
        response = await self._send("GET", self._api(f"/{_name(key)}"))
        return _resource_info(response.json())

    async def list(
        self, prefix: str, limit: int, cursor: str | None
    ) -> tuple[list[RawInfo], str | None]:
        params = [("maxResults", str(limit))]
        if prefix:
            params.append(("prefix", prefix))
        if cursor:
            params.append(("pageToken", cursor))
        query = "&".join(f"{k}={quote(v, safe='~')}" for k, v in params)
        doc = (await self._send("GET", self._api(f"?{query}"))).json()
        return [_resource_info(i) for i in doc.get("items", [])], doc.get("nextPageToken") or None

    async def delete(self, key: str) -> None:
        await self._send("DELETE", self._api(f"/{_name(key)}"), ok=(200, 204, 404))

    async def copy(self, src: str, dst: str, *, overwrite: bool) -> RawInfo | None:
        if not overwrite:
            try:
                await self.head(dst)
            except NotFound:
                pass
            else:
                raise Conflict(f"'{dst}' already exists")
        suffix = f"/{_name(src)}/copyTo/b/{self.bucket}/o/{_name(dst)}"
        if not overwrite:
            suffix += "?ifGenerationMatch=0"
        response = await self._send("POST", self._api(suffix))
        return _resource_info(response.json())

    async def presign(self, key: str, method: Method, expires_in: int) -> str:
        raise Unsupported("presigned URLs for GCS need HMAC keys (access_key and secret_key)")

    async def aclose(self) -> None:
        await self._http.aclose()


def _error(method: str, url: str, response: httpx.Response) -> StorageError:
    return from_status(response.status_code, describe(method, url, response))


__all__ = ["GcsBackend", "datetime"]
