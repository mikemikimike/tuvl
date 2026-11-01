"""MCP export (P5.1, spec §15.3): workflows as tools on /mcp, with REST auth."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.api.test_runs_api import WORKFLOWS, _doc, _echo, _greet, token
from tuvl.api.mcp_export import mount_mcp
from tuvl.core.config import settings
from tuvl.runtime.code import AGENT_REGISTRY
from tuvl.runtime.host import RuntimeHost, set_host


def _exported(name: str) -> Any:
    data = WORKFLOWS[name].model_dump(mode="json", exclude_unset=True, by_alias=True)
    data["spec"]["trigger"]["mcp"] = {"enabled": True}
    meta = {k: v for k, v in data["metadata"].items() if k != "name"}
    return _doc(name, data["spec"], **meta)


EXPORTED = {name: _exported(name) for name in ("greet", "echo", "refund")}
SECRET = _exported("greet").model_copy(deep=True)
SECRET.metadata.name = "secret"
SECRET.metadata.required_scope = "secret:run"
EXPORTED["secret"] = SECRET
EXPORTED["hidden"] = WORKFLOWS["slow"]  # not exported

ALICE = token("alice", ["greet:run", "mcp:connect"])


@pytest.fixture
async def host(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[RuntimeHost]:
    monkeypatch.setattr(settings, "tuvl_dev_mode", False)
    for name, fn in {"greet": _greet, "echo": _echo}.items():
        monkeypatch.setitem(AGENT_REGISTRY, name, fn)
    runtime = RuntimeHost(pg_engine, workflows=EXPORTED, role="api")
    set_host(runtime)
    yield runtime
    await runtime.stop()
    set_host(None)


@asynccontextmanager
async def mounted(host: RuntimeHost) -> AsyncIterator[FastAPI]:
    """The session manager's task group must open and close in one task."""
    application = FastAPI()
    async with AsyncExitStack() as stack:
        assert await mount_mcp(application, host, stack) == 4
        yield application


def _http(app: FastAPI, headers: dict[str, str]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers
    )


async def test_mcp_requires_a_token_with_mcp_connect(host: RuntimeHost) -> None:
    init = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    async with mounted(host) as app, _http(app, {}) as c:
        assert (await c.post("/mcp", json=init)).status_code == 401
    async with mounted(host) as app, _http(app, token("bob", ["greet:run"])) as c:
        assert (await c.post("/mcp", json=init)).status_code == 403


async def test_tools_calls_progress_and_pending(host: RuntimeHost) -> None:
    progress: list[str | None] = []

    async def on_progress(value: float, total: float | None, message: str | None) -> None:
        progress.append(message)

    async with (
        mounted(host) as app,
        _http(app, ALICE) as http,
        streamable_http_client("http://test/mcp", http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = {t.name: t for t in (await session.list_tools()).tools}
        assert set(tools) == {"greet", "echo", "refund"}  # 'secret' needs secret:run
        greet = tools["greet"]
        assert greet.description == "Greet someone"
        assert greet.inputSchema["required"] == ["name"]
        assert greet.outputSchema is not None
        assert "text" in greet.outputSchema["properties"]["body"]["properties"]
        assert greet.annotations is not None and greet.annotations.readOnlyHint is False

        ok = await session.call_tool("greet", {"name": "ada"}, progress_callback=on_progress)
        assert not ok.isError and ok.structuredContent is not None
        assert ok.structuredContent["body"] == {"text": "hello ada"}
        assert ok.structuredContent["outcome"] == "completed"
        assert ok.structuredContent["status"] == 201 and ok.structuredContent["end"] == "default"
        assert progress == ["greet started"]

        bad = await session.call_tool("greet", {"name": 7})
        assert bad.isError and "input schema" in bad.content[0].text  # type: ignore[union-attr]

        pending = await session.call_tool("refund", {"amount": 30})
        assert not pending.isError and pending.structuredContent is not None
        descriptor = pending.structuredContent  # validated by the client against outputSchema
        assert descriptor["outcome"] == "pending" and descriptor["state"] == "waiting_human"
        assert descriptor["approval"]["kind"] == "human" and descriptor["run_id"]

        hidden = await session.call_tool("secret", {"name": "x"})
        assert hidden.isError and "unknown tool" in hidden.content[0].text  # type: ignore[union-attr]


async def test_nothing_exported_mounts_nothing(pg_engine: AsyncEngine) -> None:
    host = RuntimeHost(pg_engine, workflows={"slow": WORKFLOWS["slow"]}, role="api")
    application = FastAPI()
    async with AsyncExitStack() as stack:
        assert await mount_mcp(application, host, stack) == 0
    assert not any(getattr(r, "path", "") == "/mcp" for r in application.routes)
