"""Process-wide shared ``httpx.AsyncClient`` singletons.

Re-creating an ``AsyncClient`` for every outbound request defeats HTTP
connection pooling, forces a fresh TLS handshake each call, and adds
unnecessary GC pressure.  This module hands out long-lived clients keyed by
their effective timeout so that the engine's outbound API-call step and the
OAuth federation router share TCP+TLS state across requests.

Lifecycle
---------
Clients are created lazily on first use and closed by ``aclose_all()``,
which is invoked from the FastAPI lifespan shutdown handler in
``tuvl.core.app``.  Until shutdown, the same client instance is reused for
every caller with a matching timeout value.

Usage
-----
>>> from tuvl.core.infra.http_client import get_http_client
>>> client = get_http_client(timeout=15.0)
>>> resp = await client.get("https://example.com")
"""

from __future__ import annotations

import asyncio

import httpx

# Keyed by timeout (rounded to 1 decimal) \u2192 long-lived AsyncClient.
_clients: dict[float, httpx.AsyncClient] = {}
_lock = asyncio.Lock()


def get_http_client(timeout: float = 30.0) -> httpx.AsyncClient:
    """Return a process-wide ``httpx.AsyncClient`` for the given timeout.

    The returned client must **not** be closed by the caller \u2014 it is owned
    by this module and reused across requests.  Use it directly without an
    ``async with`` block::

        client = get_http_client(timeout=15.0)
        resp = await client.get(url)

    Parameters
    ----------
    timeout:
        Per-request timeout in seconds.  Clients with distinct timeout
        values are kept as separate pools (rounded to one decimal place).
    """
    key = round(float(timeout), 1)
    client = _clients.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=key)
        _clients[key] = client
    return client


async def aclose_all() -> None:
    """Close every cached client.  Intended for FastAPI lifespan shutdown."""
    import contextlib

    for client in list(_clients.values()):
        with contextlib.suppress(Exception):
            await client.aclose()
    _clients.clear()
