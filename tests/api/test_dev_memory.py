"""Dev API: the memory browser's endpoints — list, read, forget one owner, forget one memory."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.runtime import test_builtins
from tests.runtime.test_memory_store import row
from tuvl.api.dev import router
from tuvl.runtime.host import RuntimeHost, set_host

vectors = test_builtins.vectors  # the pgvector fixture


@pytest.fixture
async def client(vectors: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    set_host(RuntimeHost(vectors, workflows={}, role="api"))
    async with AsyncSession(vectors) as s:
        s.add_all(
            [
                row("mem", "ada", "ada said email", 2),
                row("mem", "ada", "ada said no calls", 1),
                row("mem", "grace", "grace said hello", 0),
                row("kb", None, "a knowledge-base row", 0),
            ]
        )
        await s.commit()
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://dev"
    ) as c:
        yield c
    set_host(None)


async def test_collections_lists_only_memory_collections(client: httpx.AsyncClient) -> None:
    found = (await client.get("/dev/memory")).json()
    assert [(c["collection"], c["memories"], c["owners"]) for c in found] == [("mem", 3, 2)]


async def test_rows_are_newest_first_and_can_be_filtered_by_owner(
    client: httpx.AsyncClient,
) -> None:
    every = (await client.get("/dev/memory/mem")).json()
    assert [r["content"] for r in every] == [
        "grace said hello",
        "ada said no calls",
        "ada said email",
    ]
    ada = (await client.get("/dev/memory/mem", params={"key": "ada"})).json()
    assert {r["key"] for r in ada} == {"ada"} and len(ada) == 2
    assert (await client.get("/dev/memory/kb")).json() == []  # a knowledge base is not a memory


async def test_forget_one_owner_or_one_memory(client: httpx.AsyncClient) -> None:
    one = (await client.get("/dev/memory/mem", params={"key": "grace"})).json()[0]["id"]
    assert (await client.delete(f"/dev/memory/mem/{one}")).json()["removed"] == 1
    assert (await client.delete(f"/dev/memory/mem/{one}")).status_code == 404
    assert (await client.delete(f"/dev/memory/mem/{uuid.uuid4()}")).status_code == 404
    gone = (await client.delete("/dev/memory/mem", params={"key": "ada"})).json()
    assert gone["removed"] == 2
    assert (await client.get("/dev/memory/mem")).json() == []
    assert (await client.delete("/dev/memory/mem")).status_code == 422  # a key is required
    kb = (await client.get("/dev/memory/kb")).json()
    assert kb == []
