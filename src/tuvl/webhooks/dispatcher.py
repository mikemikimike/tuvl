"""Deliver the outbox: claim due rows, send each notification once per attempt, schedule retries.

At-least-once: a receiver may see the same ``id`` twice (a crash after the call, before the row is
updated) and de-duplicates on it. A row is leased while in flight, so another worker skips it and a
crashed worker's row comes due again.

What goes over the wire is fixed: a JSON body, a signature, four headers. No redirect is followed,
the response body is discarded (a short one with a declared length is drained so the connection can
be reused), proxies from the environment are ignored (they would bypass the address check), and the
connection goes to the address that was checked, not to a second lookup.

Connections are kept alive per destination: one pooled client per (scheme, host name, checked
address, port). A connection is only reused for the host name whose certificate it verified and
the address that was checked on this attempt, so neither TLS verification nor the address check
can be skipped by sharing a connection between receivers.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
import weakref
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

import httpx
import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tuvl.core.engine.templating import expand_env
from tuvl.runtime.models import SystemWebhookDelivery
from tuvl.webhooks import notification, registry
from tuvl.webhooks.guard import BlockedAddress, resolve, url_problem
from tuvl.webhooks.signing import MIN_SECRET_BYTES, sign

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult

logger = structlog.get_logger(__name__)

_TABLE = SystemWebhookDelivery.__table__  # type: ignore[attr-defined]

MAX_ATTEMPTS = 8
#: Seconds to wait after attempt 1, 2, … (about eleven hours in all).
BACKOFF = (10, 30, 120, 600, 1800, 3600, 10_800, 21_600)
LEASE_SECONDS = 60
BATCH = 16
CONCURRENCY = 8
POLL_SECONDS = 1.0
BREAKER_FAILURES = 5
BREAKER_SECONDS = 300
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
#: Destinations with a kept-alive client, per event loop; the least recently used is closed.
POOLED_DESTINATIONS = 32
#: A response body up to this size is read and dropped, so its connection can carry the next one.
DRAIN_BYTES = 16 * 1024
DRAIN_SECONDS = 1.0


@dataclass
class Outcome:
    delivered: bool = False
    dead: bool = False
    status: int | None = None
    error: str | None = None


_failures: dict[tuple[str, str], tuple[int, float]] = {}


def _breaker_open(workflow: str, webhook: str) -> float:
    """Seconds until a tripped receiver is tried again (0 when it is not tripped)."""
    count, since = _failures.get((workflow, webhook), (0, 0.0))
    remaining = since + BREAKER_SECONDS - time.monotonic()
    return remaining if count >= BREAKER_FAILURES and remaining > 0 else 0.0


def _note(workflow: str, webhook: str, ok: bool) -> None:
    key = (workflow, webhook)
    if ok:
        _failures.pop(key, None)
        return
    count, _ = _failures.get(key, (0, 0.0))
    _failures[key] = (count + 1, time.monotonic())


_Destination = tuple[str, str, str, int]


class _Pool:
    """Clients keyed by destination. A client dropped from the pool is closed once no send is
    using it."""

    def __init__(self) -> None:
        self.clients: OrderedDict[_Destination, httpx.AsyncClient] = OrderedDict()
        self.busy: dict[httpx.AsyncClient, int] = {}

    @contextlib.asynccontextmanager
    async def client(self, key: _Destination) -> AsyncIterator[httpx.AsyncClient]:
        client = self.clients.pop(key, None)
        if client is None or client.is_closed:
            client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, trust_env=False)
        self.clients[key] = client
        self.busy[client] = self.busy.get(client, 0) + 1
        while len(self.clients) > POOLED_DESTINATIONS:
            _, old = self.clients.popitem(last=False)
            if not self.busy.get(old):
                await old.aclose()
        try:
            yield client
        finally:
            self.busy[client] -= 1
            if not self.busy[client]:
                del self.busy[client]
                if self.clients.get(key) is not client:
                    await client.aclose()

    async def aclose(self) -> None:
        clients, self.clients = list(self.clients.values()), OrderedDict()
        for client in clients:
            await client.aclose()


_pools: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _Pool] = weakref.WeakKeyDictionary()


def _pool() -> _Pool:
    loop = asyncio.get_running_loop()
    pool = _pools.get(loop)
    if pool is None:
        pool = _pools[loop] = _Pool()
    return pool


async def aclose() -> None:
    """Close the running event loop's kept-alive webhook connections (server shutdown)."""
    pool = _pools.pop(asyncio.get_running_loop(), None)
    if pool is not None:
        await pool.aclose()


def _now(session: AsyncSession) -> Any:
    return sa.func.now() if session.bind.dialect.name == "postgresql" else datetime.now(UTC)


def _later(session: AsyncSession, seconds: float) -> Any:
    if session.bind.dialect.name == "postgresql":
        return sa.func.now() + sa.func.make_interval(0, 0, 0, 0, 0, 0, seconds)
    return datetime.now(UTC) + timedelta(seconds=seconds)


async def claim(session: AsyncSession, limit: int = BATCH) -> list[Any]:
    """Lease up to *limit* due notifications. The caller commits."""
    pick = (
        sa.select(_TABLE.c.id)
        .where(_TABLE.c.status == "pending", _TABLE.c.next_attempt_at <= _now(session))
        .order_by(_TABLE.c.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(
        sa.update(_TABLE)
        .where(_TABLE.c.id.in_(pick))
        .values(next_attempt_at=_later(session, LEASE_SECONDS))
        .returning(*_TABLE.c)
    )
    return sorted(result.all(), key=lambda r: r.created_at)


async def _send(row: Any) -> Outcome:
    doc = registry().get(row.workflow)
    hook = next((h for h in doc.spec.webhooks if h.name == row.webhook), None) if doc else None
    if hook is None:
        return Outcome(dead=True, error="the webhook is no longer declared")
    try:
        url = expand_env(hook.url, source=f"webhook '{hook.name}' url") or ""
        secrets = [expand_env(hook.secret, source=f"webhook '{hook.name}' secret") or ""]
        if hook.previous_secret:
            secrets.append(
                expand_env(hook.previous_secret, source=f"webhook '{hook.name}' previous_secret")
                or ""
            )
    except OSError as exc:
        return Outcome(error=str(exc)[:200])
    secrets = [s for s in secrets if s]
    if not secrets or len(secrets[0].encode()) < MIN_SECRET_BYTES:
        return Outcome(dead=True, error=f"the secret is shorter than {MIN_SECRET_BYTES} bytes")
    problem = url_problem(url, allow_private=hook.allow_private)
    if problem:
        return Outcome(dead=True, error=f"url refused: {problem}")

    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        addresses = await resolve(host, port, allow_private=hook.allow_private)
    except BlockedAddress as exc:
        return Outcome(dead=True, error=str(exc))
    except OSError:
        return Outcome(error="the host name did not resolve")

    body = notification(row)
    target = addresses[0]
    netloc = f"[{target}]" if ":" in target else target
    path = parts.path or "/"
    pinned = f"{parts.scheme}://{netloc}:{port}{path}" + (f"?{parts.query}" if parts.query else "")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "tuvl-webhook/1",
        "Host": parts.netloc.rpartition("@")[2],
        "Tuvl-Event": row.type,
        "Tuvl-Delivery": str(row.id),
        "Tuvl-Signature": sign(body, secrets),
    }
    extensions = {"sni_hostname": host} if parts.scheme == "https" else {}
    try:
        async with (
            _pool().client((parts.scheme, host, target, port)) as client,
            client.stream(
                "POST", pinned, content=body, headers=headers, extensions=extensions
            ) as response,
        ):
            status = response.status_code
            await _drain(response)
    except httpx.TimeoutException:
        return Outcome(error="timeout")
    except httpx.HTTPError as exc:
        return Outcome(error=f"connection failed ({type(exc).__name__})")
    if 200 <= status < 300:
        return Outcome(delivered=True, status=status)
    if status == 410:
        return Outcome(dead=True, status=status, error="the receiver answered 410 Gone")
    return Outcome(status=status, error=f"http {status}")


async def _drain(response: httpx.Response) -> None:
    """Read and drop a short body; anything else is left unread and its connection closed."""
    try:
        declared = int(response.headers.get("content-length", ""))
    except ValueError:
        return
    if not 0 <= declared <= DRAIN_BYTES:
        return
    read = 0
    with contextlib.suppress(httpx.HTTPError, TimeoutError):
        async with asyncio.timeout(DRAIN_SECONDS):
            async for chunk in response.aiter_raw():
                read += len(chunk)
                if read > DRAIN_BYTES:
                    return


async def _finish(engine: AsyncEngine, row: Any, outcome: Outcome) -> None:
    attempts = row.attempts + 1
    async with AsyncSession(engine) as session:
        values: dict[str, Any] = {
            "attempts": attempts,
            "last_status": outcome.status,
            "last_error": outcome.error,
        }
        if outcome.delivered:
            values |= {"status": "delivered", "delivered_at": _now(session), "last_error": None}
        elif outcome.dead or attempts >= MAX_ATTEMPTS:
            values["status"] = "dead"
        else:
            values["next_attempt_at"] = _later(session, BACKOFF[min(attempts, len(BACKOFF)) - 1])
        await session.execute(sa.update(_TABLE).where(_TABLE.c.id == row.id).values(**values))
        await session.commit()


async def deliver_one(engine: AsyncEngine, row: Any) -> Outcome:
    wait = _breaker_open(row.workflow, row.webhook)
    if wait:
        async with AsyncSession(engine) as session:
            await session.execute(
                sa.update(_TABLE)
                .where(_TABLE.c.id == row.id)
                .values(next_attempt_at=_later(session, wait))
            )
            await session.commit()
        return Outcome(error="paused after repeated failures")
    try:
        outcome = await _send(row)
    except Exception as exc:  # never let one notification stop the loop
        logger.exception("webhook.send_crashed", webhook=row.webhook)
        outcome = Outcome(error=f"internal error ({type(exc).__name__})")
    _note(row.workflow, row.webhook, outcome.delivered)
    await _finish(engine, row, outcome)
    log = logger.info if outcome.delivered else logger.warning
    log(
        "webhook.delivered" if outcome.delivered else "webhook.failed",
        webhook=row.webhook,
        workflow=row.workflow,
        run_id=str(row.run_id),
        attempt=row.attempts + 1,
        status=outcome.status,
        error=outcome.error,
        dead=outcome.dead or row.attempts + 1 >= MAX_ATTEMPTS,
    )
    return outcome


async def dispatch_once(engine: AsyncEngine) -> int:
    """Claim and deliver one batch; the number of notifications attempted."""
    async with AsyncSession(engine) as session:
        rows = await claim(session)
        await session.commit()
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(row: Any) -> None:
        async with gate:
            await deliver_one(engine, row)

    await asyncio.gather(*(one(r) for r in rows))
    return len(rows)


async def redeliver(engine: AsyncEngine, delivery_id: uuid.UUID) -> bool:
    """Put a delivered or dead notification back in the queue."""
    async with AsyncSession(engine) as session:
        result = await session.execute(
            sa.update(_TABLE)
            .where(_TABLE.c.id == delivery_id)
            .values(status="pending", attempts=0, next_attempt_at=_now(session), last_error=None)
        )
        await session.commit()
        return bool(cast("CursorResult[Any]", result).rowcount)


async def dispatcher_loop(engine: AsyncEngine) -> None:
    """Lifespan background task: deliver until cancelled."""
    logger.info("webhooks.dispatcher_started")
    while True:
        try:
            busy = await dispatch_once(engine)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("webhooks.dispatch_failed")
            busy = 0
        if not busy:
            await asyncio.sleep(POLL_SECONDS)
