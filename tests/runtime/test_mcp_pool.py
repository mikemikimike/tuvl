"""Pooled MCP sessions for ``tool`` agents, against a real stdio MCP server."""

from __future__ import annotations

import asyncio
import gc
import os
import signal
import sys
import textwrap
import warnings
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from tuvl.core.context import current_tenant_id
from tuvl.runtime import mcp_pool
from tuvl.runtime.engines import EngineError
from tuvl.runtime.tool import mcp_value

SERVER = textwrap.dedent("""
    import os, sys
    from mcp.server.fastmcp import FastMCP

    with open(sys.argv[1], "a") as f:
        f.write(f"{os.getpid()}\\n")

    mcp = FastMCP("t")

    @mcp.tool()
    def pid() -> dict:
        return {"pid": os.getpid(), "token": os.environ.get("TOKEN", "")}

    @mcp.tool()
    def die() -> str:
        os._exit(1)

    mcp.run()
""")


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    spawns = tmp_path / "spawns.txt"
    spawns.write_text("")
    configs = {
        "artifact://helpdesk@1": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [str(script), str(spawns)],
            "env": {"TOKEN": "${MCP_POOL_TOKEN}"},
        }
    }
    monkeypatch.setenv("MCP_POOL_TOKEN", "t1")
    monkeypatch.setattr(
        "tuvl.core.artifacts.registry.resolve_structured", lambda ref, **_: configs[ref]
    )
    return {"spawns": spawns, "configs": configs}


@pytest.fixture(autouse=True)
async def _close_pool() -> AsyncIterator[None]:
    yield
    await mcp_pool.aclose_all()


def spawned(server: dict[str, Any]) -> list[int]:
    return [int(x) for x in server["spawns"].read_text().split()]


async def pid(ref: str = "artifact://helpdesk@1") -> dict[str, Any]:
    result = await asyncio.wait_for(mcp_pool.call_tool(ref, "test", "pid", {}), 30)
    ok, value = mcp_value(result)
    assert ok
    return dict(value)


async def test_two_calls_share_one_process(server: dict[str, Any]) -> None:
    first, second = await pid(), await pid()
    assert first["pid"] == second["pid"]
    assert spawned(server) == [first["pid"]]


async def test_concurrent_first_calls_start_one_process(server: dict[str, Any]) -> None:
    results = await asyncio.gather(*(pid() for _ in range(5)))
    assert len({r["pid"] for r in results}) == 1
    assert len(spawned(server)) == 1


async def test_crash_mid_call_is_mcp_error_then_replaced(server: dict[str, Any]) -> None:
    before = await pid()
    with pytest.raises(EngineError) as exc:
        await asyncio.wait_for(mcp_pool.call_tool("artifact://helpdesk@1", "test", "die", {}), 30)
    assert exc.value.error_type == "mcp_error"
    after = await pid()
    assert after["pid"] != before["pid"]
    assert len(spawned(server)) == 2


async def test_server_killed_while_idle_is_replaced_transparently(
    server: dict[str, Any],
) -> None:
    before = await pid()
    os.kill(before["pid"], signal.SIGKILL)
    await asyncio.sleep(0.5)
    after = await pid()
    assert after["pid"] != before["pid"]


async def test_tenants_never_share_a_session(server: dict[str, Any]) -> None:
    token = current_tenant_id.set("acme")
    try:
        acme = await pid()
    finally:
        current_tenant_id.reset(token)
    token = current_tenant_id.set("globex")
    try:
        globex = await pid()
    finally:
        current_tenant_id.reset(token)
    token = current_tenant_id.set("acme")
    try:
        acme_again = await pid()
    finally:
        current_tenant_id.reset(token)
    assert acme["pid"] != globex["pid"]
    assert acme_again["pid"] == acme["pid"]


async def test_changed_config_or_env_opens_a_new_session(
    server: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await pid()
    monkeypatch.setenv("MCP_POOL_TOKEN", "t2")
    second = await pid()
    assert second["pid"] != first["pid"] and second["token"] == "t2"
    server["configs"]["artifact://helpdesk@1"]["args"].append("--changed")
    third = await pid()
    assert third["pid"] not in (first["pid"], second["pid"])


async def test_idle_session_is_closed(
    server: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tuvl.core.config.settings.tuvl_mcp_idle_seconds", 0.3)
    first = await pid()
    pool = mcp_pool.get_pool()
    assert len(pool) == 1
    for _ in range(50):
        await asyncio.sleep(0.1)
        if not len(pool):
            break
    assert len(pool) == 0
    assert (await pid())["pid"] != first["pid"]


async def test_zero_idle_opens_a_session_per_call(
    server: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tuvl.core.config.settings.tuvl_mcp_idle_seconds", 0)
    assert (await pid())["pid"] != (await pid())["pid"]


async def test_start_failure_is_mcp_error(server: dict[str, Any]) -> None:
    server["configs"]["artifact://helpdesk@1"]["command"] = "/nonexistent/mcp-server"
    with pytest.raises(EngineError) as exc:
        await pid()
    assert exc.value.error_type == "mcp_error"


async def test_shutdown_closes_every_session_cleanly(server: dict[str, Any]) -> None:
    token = current_tenant_id.set("acme")
    try:
        await pid()
    finally:
        current_tenant_id.reset(token)
    await pid()
    pool = mcp_pool.get_pool()
    tasks = [e.task for e in pool._all]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        await asyncio.wait_for(mcp_pool.aclose_all(), 30)
        gc.collect()
    assert all(t is not None and t.done() and not t.cancelled() for t in tasks)
    assert all(t is not None and t.exception() is None for t in tasks)
    assert not [w for w in caught if "cancel scope" in str(w.message).lower()]
    assert len(pool) == 0
