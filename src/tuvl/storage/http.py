"""One pooled httpx client per event loop, with transport failures mapped to storage errors."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from typing import Any

import httpx

from tuvl.storage.errors import StorageError, TooLarge, Unavailable, from_status
from tuvl.storage.errors import Timeout as StorageTimeout

_SECRET_QUERY = re.compile(
    r"([?&](?:sig|X-Amz-Signature|X-Amz-Credential|X-Amz-Security-Token|X-Goog-Signature|token|access_token)=)[^&\s\"']+",
    re.IGNORECASE,
)


class _RedactSecrets(logging.Filter):
    """httpx logs full URLs; a SAS token or signature in the query must not reach the logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SECRET_QUERY.sub(r"\1[redacted]", record.getMessage())
        record.args = None
        return True


def _redact_httpx_logs() -> None:
    log = logging.getLogger("httpx")
    if not any(isinstance(f, _RedactSecrets) for f in log.filters):
        log.addFilter(_RedactSecrets())


class Http:
    def __init__(
        self, timeout: float = 30.0, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        _redact_httpx_logs()
        self._timeout = httpx.Timeout(timeout, connect=min(5.0, timeout))
        self._transport = transport
        self._clients: dict[int, httpx.AsyncClient] = {}

    def client(self) -> httpx.AsyncClient:
        loop_id = id(asyncio.get_running_loop())
        client = self._clients.get(loop_id)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=self._timeout, transport=self._transport)
            self._clients[loop_id] = client
        return client

    async def send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
        data: Mapping[str, str] | None = None,
        max_bytes: int | None = None,
    ) -> httpx.Response:
        """The response with its body read (at most *max_bytes*); a non-2xx status is returned, not raised."""
        request = self.client().build_request(
            method, url, headers=dict(headers or {}), content=content, data=data
        )
        try:
            response = await self.client().send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise StorageTimeout(f"{method} {url}: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise Unavailable(f"{method} {url}: {type(exc).__name__}: {exc}") from exc
        try:
            declared = response.headers.get("content-length")
            if (
                max_bytes is not None
                and declared
                and int(declared) > max_bytes
                and method != "HEAD"
            ):
                raise TooLarge(f"object is larger than {max_bytes} bytes")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if max_bytes is not None and len(body) > max_bytes:
                    raise TooLarge(f"object is larger than {max_bytes} bytes")
        except httpx.TimeoutException as exc:
            raise StorageTimeout(f"{method} {url}: {type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise Unavailable(f"{method} {url}: {type(exc).__name__}: {exc}") from exc
        finally:
            await response.aclose()
        response._content = bytes(body)
        return response

    async def expect(
        self, method: str, url: str, ok: tuple[int, ...] = (200,), **kwargs: Any
    ) -> httpx.Response:
        response = await self.send(method, url, **kwargs)
        if response.status_code not in ok:
            raise from_status(response.status_code, describe(method, url, response))
        return response

    async def aclose(self) -> None:
        clients, self._clients = list(self._clients.values()), {}
        for client in clients:
            if not client.is_closed:
                try:
                    await client.aclose()
                except (RuntimeError, StorageError):
                    continue


def describe(method: str, url: str, response: httpx.Response) -> str:
    """A one-line failure message that never includes the query string (it may carry a signature)."""
    path = url.split("?", 1)[0]
    detail = response.text.strip().replace("\n", " ")[:200]
    return f"{method} {path} returned {response.status_code}" + (f": {detail}" if detail else "")
