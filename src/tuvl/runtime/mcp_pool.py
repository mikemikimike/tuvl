"""Reused MCP sessions for ``tool`` agents (``use: mcp``).

One pool per worker process (per event loop), keyed by tenant, server ref and a hash of the
resolved server config, so a changed artifact, env var or credential opens a new session and
tenants never share one. A session closes after ``tuvl_mcp_idle_seconds`` without use.

Each session lives in its own owner task: the MCP transports hold anyio cancel scopes that
must be entered and exited in the same task, so callers only borrow the session and never
open or close it. A ``ClientSession`` multiplexes requests by id, so concurrent calls share
one session.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from tuvl.runtime.engines import EngineError

logger = structlog.get_logger(__name__)

Key = tuple[str, str, str]


@dataclass(eq=False)
class _Entry:
    key: Key
    ready: asyncio.Future[Any]
    last_used: float = field(default_factory=time.monotonic)
    in_use: int = 0
    retired: bool = False
    forced: bool = False
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None

    def retire(self, *, force: bool = False) -> None:
        self.retired = True
        self.forced = self.forced or force
        self.wake.set()


class McpPool:
    def __init__(self, idle_seconds: float) -> None:
        self.idle_seconds = idle_seconds
        self.loop = asyncio.get_running_loop()
        self._entries: dict[Key, _Entry] = {}
        self._all: set[_Entry] = set()

    def __len__(self) -> int:
        return len(self._entries)

    def _start(self, key: Key, server: dict[str, Any]) -> _Entry:
        entry = _Entry(key, self.loop.create_future())
        # Retrieve a start failure even when every waiter was cancelled, so asyncio does not warn.
        entry.ready.add_done_callback(lambda f: f.cancelled() or f.exception())
        self._entries[key] = entry
        self._all.add(entry)
        entry.task = self.loop.create_task(
            self._own(entry, server),
            name=f"mcp-session {key[1]}",
            context=contextvars.Context(),
        )
        return entry

    def _forget(self, entry: _Entry) -> None:
        if self._entries.get(entry.key) is entry:
            del self._entries[entry.key]

    def _closing(self, entry: _Entry) -> bool:
        if entry.forced:
            return True
        if entry.in_use:
            return False
        return entry.retired or time.monotonic() - entry.last_used >= self.idle_seconds

    async def _own(self, entry: _Entry, server: dict[str, Any]) -> None:
        from tuvl.runtime.tool import mcp_connect

        try:
            async with mcp_connect(entry.key[1], server) as session:
                entry.ready.set_result(session)
                while not self._closing(entry):
                    entry.wake.clear()
                    timeout = None
                    if not entry.retired and not entry.in_use:
                        timeout = max(0.05, entry.last_used + self.idle_seconds - time.monotonic())
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(entry.wake.wait(), timeout)
                self._forget(entry)
        except asyncio.CancelledError:
            if not entry.ready.done():
                entry.ready.cancel()
            raise
        except Exception as exc:
            if not entry.ready.done():
                entry.ready.set_exception(exc)
            else:
                logger.info("mcp session closed with an error", server=entry.key[1], error=str(exc))
        finally:
            entry.retired = True
            self._forget(entry)
            self._all.discard(entry)

    def _acquire(self, key: Key, server: dict[str, Any]) -> _Entry:
        entry = self._entries.get(key)
        if entry is None or entry.retired or (entry.task is not None and entry.task.done()):
            entry = self._start(key, server)
        entry.in_use += 1
        return entry

    def _release(self, entry: _Entry) -> None:
        entry.in_use -= 1
        entry.last_used = time.monotonic()
        entry.wake.set()

    async def call_tool(self, server_ref: str, where: str, name: str, args: Any) -> Any:
        from tuvl.runtime.tool import mcp_server_config

        server = mcp_server_config(server_ref, where)
        key = (_tenant(), server_ref, _digest(server))
        for attempt in (1, 2):
            entry = self._acquire(key, server)
            try:
                session = await asyncio.shield(entry.ready)
                try:
                    return await session.call_tool(name, arguments=args)
                except Exception as exc:
                    if _breaks_session(exc):
                        entry.retire()
                    # The request never left this process, so a fresh session can safely send it.
                    if attempt == 1 and _not_sent(exc):
                        continue
                    raise EngineError(
                        "mcp_error", f"{server_ref} {name}: {type(exc).__name__}: {exc}"
                    ) from exc
            finally:
                self._release(entry)
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        entries = list(self._all)
        for entry in entries:
            entry.retire(force=True)
        tasks = [e.task for e in entries if e.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._entries.clear()


def _tenant() -> str:
    from tuvl.core.context import current_tenant_id

    return current_tenant_id.get("")


def _digest(server: dict[str, Any]) -> str:
    raw = json.dumps(server, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _not_sent(exc: BaseException) -> bool:
    import anyio

    return isinstance(exc, anyio.ClosedResourceError | anyio.BrokenResourceError)


def _breaks_session(exc: BaseException) -> bool:
    from mcp.shared.exceptions import McpError
    from mcp.types import CONNECTION_CLOSED

    if isinstance(exc, McpError):
        # A timed-out request may mean a wedged server; a protocol error from a live one does not.
        return exc.error.code in (CONNECTION_CLOSED, 408)
    return True


_POOL: McpPool | None = None


def get_pool() -> McpPool:
    """This event loop's pool; a new loop (a CLI run, a test) gets a new one."""
    global _POOL
    from tuvl.core.config import settings

    loop = asyncio.get_running_loop()
    if _POOL is None or _POOL.loop is not loop or _POOL.loop.is_closed():
        _POOL = McpPool(settings.tuvl_mcp_idle_seconds)
    return _POOL


async def call_tool(server_ref: str, where: str, name: str, args: Any) -> Any:
    """Call one MCP tool on a pooled session; errors raise ``EngineError("mcp_error")``."""
    from tuvl.core.config import settings
    from tuvl.extras import require

    require("mcp")
    if settings.tuvl_mcp_idle_seconds <= 0:
        from tuvl.runtime.tool import mcp_session

        async with mcp_session(server_ref, where) as session:
            try:
                return await session.call_tool(name, arguments=args)
            except Exception as exc:
                raise EngineError(
                    "mcp_error", f"{server_ref} {name}: {type(exc).__name__}: {exc}"
                ) from exc
    return await get_pool().call_tool(server_ref, where, name, args)


async def aclose_all() -> None:
    """Close every pooled session of this event loop (app or worker shutdown)."""
    global _POOL
    pool = _POOL
    if pool is None:
        return
    with contextlib.suppress(RuntimeError):
        if pool.loop is not asyncio.get_running_loop():
            return
    _POOL = None
    await pool.aclose()
