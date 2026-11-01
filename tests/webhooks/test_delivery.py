"""Webhooks end to end: journal event → outbox → signed minimal notification → retry or give up."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tuvl.api.runs import router
from tuvl.contract.schema import WorkflowDocument
from tuvl.core.auth.token import mint_token
from tuvl.core.config import settings
from tuvl.runtime.code import AGENT_REGISTRY
from tuvl.runtime.host import RuntimeHost, set_host
from tuvl.runtime.models import SystemWebhookDelivery
from tuvl.webhooks import dispatcher, signing

SECRET = "k" * 40


def bearer(user: str, scopes: list[str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(user, [], scopes, ttl_seconds=300)}"}


class Receiver:
    """A local HTTP server that answers from a script and records what it was sent."""

    def __init__(self) -> None:
        self.script: list[int] = [200]
        self.requests: list[dict[str, Any]] = []
        self.keep_alive = False
        self.connections = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        try:
            while True:
                head = (await reader.readuntil(b"\r\n\r\n")).decode()
                lines = head.split("\r\n")
                headers = {
                    k.lower(): v for k, _, v in (ln.partition(": ") for ln in lines[1:] if ln)
                }
                body = await reader.readexactly(int(headers.get("content-length", 0)))
                self.requests.append({"line": lines[0], "headers": headers, "body": body})
                status = self.script.pop(0) if len(self.script) > 1 else self.script[0]
                extra = (
                    "location: http://127.0.0.1:1/elsewhere\r\n"
                    if status in (301, 302, 307)
                    else ""
                )
                if self.keep_alive:
                    reply = 'content-length: 11\r\n\r\n{"ok":true}'
                else:
                    reply = "content-length: 0\r\nconnection: close\r\n\r\n"
                writer.write(f"HTTP/1.1 {status} X\r\n{extra}{reply}".encode())
                await writer.drain()
                if not self.keep_alive:
                    break
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        writer.close()


def _flow(url: str = "${WH_URL}", **hook: Any) -> WorkflowDocument:
    hooks = [
        {
            "name": "ops",
            "url": url,
            "secret": "${WH_SECRET}",
            "events": ["completed"],
            "stages": ["greet"],
            "allow_private": True,
            **hook,
        },
        {
            "name": "alerts",
            "url": url,
            "secret": "${WH_SECRET}",
            "events": ["failed"],
            "allow_private": True,
        },
    ]
    return WorkflowDocument.model_validate(
        {
            "kind": "Workflow",
            "version": "tuvl/v2",
            "metadata": {"name": "greet"},
            "spec": {
                "trigger": {"input": {"name": "str"}},
                "agents": [
                    {
                        "id": "greet",
                        "description": "greet",
                        "engine": "code",
                        "code": {"run": "greet"},
                        "inputs": {"name": "str"},
                        "outputs": {"text": "str"},
                        "routes": {"default": "END", "error": "END.failed"},
                    }
                ],
                "outputs": {"default": {"body": {"text": "{{ text }}"}}, "failed": {"status": 500}},
                "webhooks": hooks,
            },
        }
    )


async def _greet(inp: Any, ctx: Any) -> dict[str, Any]:
    return {"text": f"hello {inp.name} (a private detail)"}


@pytest.fixture
async def receiver() -> AsyncIterator[Receiver]:
    r = Receiver()
    await r.start()
    yield r
    await dispatcher.aclose()  # kept-alive connections would hold the server open
    await r.stop()


@pytest.fixture
def tokens() -> tuple[dict[str, str], dict[str, str]]:
    return bearer("root", ["iam:admin"]), bearer("r", ["runs:read"])


@pytest.fixture
async def host(
    pg_engine: AsyncEngine,
    receiver: Receiver,
    monkeypatch: pytest.MonkeyPatch,
    tokens: tuple[dict[str, str], dict[str, str]],
) -> AsyncIterator[RuntimeHost]:
    monkeypatch.setattr(settings, "tuvl_dev_mode", False)
    monkeypatch.setattr(settings, "tuvl_webhooks_enabled", True)
    monkeypatch.setenv("WH_URL", f"http://127.0.0.1:{receiver.port}/hook?k=v")
    monkeypatch.setenv("WH_SECRET", SECRET)
    monkeypatch.setitem(AGENT_REGISTRY, "greet", _greet)
    dispatcher._failures.clear()
    runtime = RuntimeHost(pg_engine, workflows={"greet": _flow()}, role="api")
    set_host(runtime)
    yield runtime
    await runtime.stop()
    set_host(None)


async def run_once(host: RuntimeHost, principal: str | None = None) -> uuid.UUID:
    doc = host.registry()["greet"]
    run_id = await host.enqueue(doc, {"name": "ada"}, principal=principal, trigger="api")
    while await host.worker.claim_some():
        await host.worker.drain()
    return run_id


async def rows(engine: AsyncEngine) -> list[Any]:
    async with AsyncSession(engine) as s:
        found = await s.execute(
            sa.select(SystemWebhookDelivery).order_by(SystemWebhookDelivery.created_at)  # type: ignore[arg-type]
        )
        return list(found.scalars().all())


async def make_due(engine: AsyncEngine) -> None:
    async with AsyncSession(engine) as s:
        await s.execute(
            sa.update(SystemWebhookDelivery.__table__).values(  # type: ignore[attr-defined]
                next_attempt_at=datetime(2000, 1, 1, tzinfo=UTC)
            )
        )
        await s.commit()


async def test_only_declared_events_are_queued(host: RuntimeHost) -> None:
    await run_once(host)
    queued = sorted((r.webhook, r.type, r.agent_id) for r in await rows(host.engine))
    assert queued == [("ops", "agent.completed", "greet"), ("ops", "run.completed", None)]


async def test_nothing_is_queued_while_webhooks_are_off(
    host: RuntimeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "tuvl_webhooks_enabled", False)
    await run_once(host)
    assert await rows(host.engine) == []


async def test_the_notification_is_minimal_signed_and_pinned(
    host: RuntimeHost, receiver: Receiver
) -> None:
    run_id = await run_once(host)
    assert await dispatcher.dispatch_once(host.engine) == 2
    assert len(receiver.requests) == 2
    for req in receiver.requests:
        assert req["line"] == "POST /hook?k=v HTTP/1.1"
        body = json.loads(req["body"])
        assert set(body) <= {"id", "type", "created_at", "workflow", "run_id", "seq", "agent"}
        assert body["run_id"] == str(run_id) and body["workflow"] == "greet"
        # the principal's name must not appear as a value; "ada" alone can occur inside a random hex id
        assert b"private detail" not in req["body"] and "ada" not in map(str, body.values())
        h = req["headers"]
        assert h["host"] == f"127.0.0.1:{receiver.port}"
        assert h["tuvl-delivery"] == body["id"] and h["tuvl-event"] == body["type"]
        assert signing.verify(h["tuvl-signature"], req["body"], [SECRET])
        assert not signing.verify(h["tuvl-signature"], req["body"], ["z" * 40])
    assert {r.status for r in await rows(host.engine)} == {"delivered"}


async def test_a_failing_receiver_is_retried_with_backoff_then_given_up_on(
    host: RuntimeHost, receiver: Receiver
) -> None:
    receiver.script = [500]
    await run_once(host)
    await dispatcher.dispatch_once(host.engine)
    first = await rows(host.engine)
    assert {r.status for r in first} == {"pending"}
    assert all(
        r.attempts == 1 and r.last_status == 500 and r.last_error == "http 500" for r in first
    )
    assert all(r.next_attempt_at > datetime.now(UTC) for r in first)
    assert await dispatcher.dispatch_once(host.engine) == 0  # not due yet

    async with AsyncSession(host.engine) as s:
        await s.execute(
            sa.update(SystemWebhookDelivery.__table__).values(  # type: ignore[attr-defined]
                attempts=dispatcher.MAX_ATTEMPTS - 1,
                next_attempt_at=datetime(2000, 1, 1, tzinfo=UTC),
            )
        )
        await s.commit()
    dispatcher._failures.clear()
    await dispatcher.dispatch_once(host.engine)
    assert {r.status for r in await rows(host.engine)} == {"dead"}


async def test_410_gone_stops_at_once_and_a_redirect_is_not_followed(
    host: RuntimeHost, receiver: Receiver
) -> None:
    receiver.script = [410]
    await run_once(host)
    await dispatcher.dispatch_once(host.engine)
    assert {r.status for r in await rows(host.engine)} == {"dead"}

    receiver.requests.clear()
    receiver.script = [302]
    await make_due(host.engine)
    async with AsyncSession(host.engine) as s:
        await s.execute(
            sa.update(SystemWebhookDelivery.__table__).values(status="pending", attempts=0)  # type: ignore[attr-defined]
        )
        await s.commit()
    await dispatcher.dispatch_once(host.engine)
    assert len(receiver.requests) == 2  # one per notification, none to the Location
    assert {r.last_status for r in await rows(host.engine)} == {302}


async def test_a_host_that_resolves_inside_is_never_called(
    host: RuntimeHost, receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    host.registry()["greet"].spec.webhooks[0].allow_private = False
    host.registry()["greet"].spec.webhooks[1].allow_private = False
    monkeypatch.setenv("WH_URL", "https://hooks.example.com/x")
    loop = asyncio.get_running_loop()
    real = loop.getaddrinfo

    async def inside(host_: str, port: int, **kw: Any) -> list[Any]:
        if host_ == "hooks.example.com":
            return [(2, 1, 6, "", ("10.0.0.7", port))]
        return await real(host_, port, **kw)

    monkeypatch.setattr(loop, "getaddrinfo", inside)
    await run_once(host)
    await dispatcher.dispatch_once(host.engine)
    assert receiver.requests == []
    done = await rows(host.engine)
    assert {r.status for r in done} == {"dead"}
    assert all("internal address" in (r.last_error or "") for r in done)


@pytest.mark.parametrize(
    ("url", "secret", "why"),
    [
        ("http://hooks.example.com/x", SECRET, "url refused"),
        ("https://127.0.0.1/x", SECRET, "url refused"),
        ("https://hooks.example.com/x", "short", "shorter than 32"),
    ],
)
async def test_a_bad_destination_or_secret_fails_closed(
    host: RuntimeHost,
    receiver: Receiver,
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    secret: str,
    why: str,
) -> None:
    for hook in host.registry()["greet"].spec.webhooks:
        hook.allow_private = False
    monkeypatch.setenv("WH_URL", url)
    monkeypatch.setenv("WH_SECRET", secret)
    await run_once(host)
    await dispatcher.dispatch_once(host.engine)
    assert receiver.requests == []
    done = await rows(host.engine)
    assert {r.status for r in done} == {"dead"} and all(why in (r.last_error or "") for r in done)


async def test_an_undeclared_webhook_is_dropped(host: RuntimeHost, receiver: Receiver) -> None:
    await run_once(host)
    host.registry()["greet"].spec.webhooks.clear()
    await dispatcher.dispatch_once(host.engine)
    assert receiver.requests == []
    assert {r.status for r in await rows(host.engine)} == {"dead"}


async def test_a_missing_environment_variable_retries_instead_of_giving_up(
    host: RuntimeHost, monkeypatch: pytest.MonkeyPatch
) -> None:
    await run_once(host)
    monkeypatch.delenv("WH_SECRET")
    await dispatcher.dispatch_once(host.engine)
    done = await rows(host.engine)
    assert {r.status for r in done} == {"pending"}
    assert all("undefined environment variable" in (r.last_error or "") for r in done)


async def test_a_receiver_that_keeps_failing_is_paused(
    host: RuntimeHost, receiver: Receiver
) -> None:
    receiver.script = [500]
    for _ in range(dispatcher.BREAKER_FAILURES):
        await run_once(host)
    await dispatcher.dispatch_once(host.engine)
    seen = len(receiver.requests)
    assert seen >= dispatcher.BREAKER_FAILURES
    await make_due(host.engine)
    await dispatcher.dispatch_once(host.engine)
    assert len(receiver.requests) == seen  # the open breaker deferred them all
    assert all(r.status == "pending" for r in await rows(host.engine))


async def test_the_run_api_lists_deliveries_and_redelivers_on_control(
    host: RuntimeHost, receiver: Receiver, tokens: tuple[dict[str, str], dict[str, str]]
) -> None:
    admin, reader = tokens
    app = FastAPI()
    app.include_router(router)
    run_id = await run_once(host, principal="r")
    await dispatcher.dispatch_once(host.engine)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        listing = await c.get(f"/api/runs/{run_id}/webhooks", headers=reader)
        assert listing.status_code == 200
        assert {d["status"] for d in listing.json()} == {"delivered"}
        assert (await c.get(f"/api/runs/{run_id}/webhooks")).status_code == 401
        one = listing.json()[0]["id"]
        url = f"/api/runs/{run_id}/webhooks/{one}/redeliver"
        assert (await c.post(url, headers=reader)).status_code == 403
        assert (await c.post(url, headers=admin)).status_code == 200
        wrong = f"/api/runs/{uuid.uuid4()}/webhooks/{one}/redeliver"
        assert (await c.post(wrong, headers=admin)).status_code in (404,)
    before = len(receiver.requests)
    await dispatcher.dispatch_once(host.engine)
    assert len(receiver.requests) == before + 1


# ── kept-alive connections never skip the destination checks ───────────────


def _resolving(monkeypatch: pytest.MonkeyPatch, answers: dict[str, list[Any]]) -> list[str]:
    """Each name resolves to the next of its answers (an address list or an exception)."""
    asked: list[str] = []

    async def fake(host_: str, port: int, *, allow_private: bool = False) -> list[str]:
        asked.append(host_)
        answer = answers[host_].pop(0) if len(answers[host_]) > 1 else answers[host_][0]
        if isinstance(answer, Exception):
            raise answer
        return list(answer)

    monkeypatch.setattr(dispatcher, "resolve", fake)
    return asked


async def test_deliveries_to_one_receiver_reuse_a_connection(
    host: RuntimeHost, receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    receiver.keep_alive = True
    monkeypatch.setenv("WH_URL", f"http://hooks-a.test:{receiver.port}/hook")
    _resolving(monkeypatch, {"hooks-a.test": [["127.0.0.1"]]})
    for _ in range(3):
        await run_once(host)
        await dispatcher.dispatch_once(host.engine)
    # each run sends two notifications at once: two connections, then only reuse
    assert len(receiver.requests) == 6 and receiver.connections == 2
    assert {r.status for r in await rows(host.engine)} == {"delivered"}


async def test_two_host_names_on_one_address_never_share_a_connection(
    host: RuntimeHost, receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    receiver.keep_alive = True
    _resolving(monkeypatch, {"hooks-a.test": [["127.0.0.1"]], "hooks-b.test": [["127.0.0.1"]]})
    for name in ("hooks-a.test", "hooks-b.test", "hooks-a.test"):
        monkeypatch.setenv("WH_URL", f"http://{name}:{receiver.port}/hook")
        await run_once(host)
        await dispatcher.dispatch_once(host.engine)
    hosts = [r["headers"]["host"].split(":")[0] for r in receiver.requests]
    assert hosts == ["hooks-a.test"] * 2 + ["hooks-b.test"] * 2 + ["hooks-a.test"] * 2
    assert receiver.connections == 4  # hooks-b opened its own; the last round reused hooks-a's


async def test_a_name_that_rebinds_inside_is_refused_despite_a_live_connection(
    host: RuntimeHost, receiver: Receiver, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tuvl.webhooks.guard import BlockedAddress

    receiver.keep_alive = True
    monkeypatch.setenv("WH_URL", f"http://hooks-a.test:{receiver.port}/hook")
    asked = _resolving(
        monkeypatch,
        {
            "hooks-a.test": [
                ["127.0.0.1"],
                ["127.0.0.1"],
                BlockedAddress("resolves to an internal address"),
            ]
        },
    )
    await run_once(host)
    await dispatcher.dispatch_once(host.engine)
    assert len(receiver.requests) == 2 and dispatcher._pool().clients  # connections are kept
    await run_once(host)
    await dispatcher.dispatch_once(host.engine)
    assert asked == ["hooks-a.test"] * 4  # checked again before every send
    assert len(receiver.requests) == 2
    statuses = sorted(r.status for r in await rows(host.engine))
    assert statuses == ["dead", "dead", "delivered", "delivered"]


async def test_a_new_address_or_host_gets_its_own_client_and_evicted_ones_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = dispatcher._Pool()
    async with pool.client(("https", "a.test", "203.0.113.1", 443)) as first:
        async with pool.client(("https", "a.test", "203.0.113.2", 443)) as moved:
            assert moved is not first
        async with pool.client(("https", "b.test", "203.0.113.1", 443)) as other:
            assert other is not first
    async with pool.client(("https", "a.test", "203.0.113.1", 443)) as again:
        assert again is first
        assert not again.follow_redirects and not again.trust_env

    monkeypatch.setattr(dispatcher, "POOLED_DESTINATIONS", 1)
    try:
        async with (
            pool.client(("https", "c.test", "203.0.113.3", 443)) as busy,
            pool.client(("https", "d.test", "203.0.113.4", 443)),
        ):
            assert not busy.is_closed  # evicted while in use: closed when the send ends
        assert busy.is_closed and first.is_closed
    finally:
        await pool.aclose()
