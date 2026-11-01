"""``loop.memory``: a loop agent opens with what its owner said before, and stores its result."""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.runtime import test_builtins, test_loop_engine
from tests.runtime.test_loop_engine import call, events, finish, start, workflows
from tuvl.contract.schema import MemoryParams

vectors = test_builtins.vectors  # the pgvector fixture
agents = pytest.fixture(autouse=True)(test_loop_engine.agents.__wrapped__)  # type: ignore[attr-defined]
model = test_loop_engine.model


def remembering(**memory: Any) -> dict[str, Any]:
    wfs = workflows(tools=[{"agent": "lookup_order"}])
    wfs["wf"].spec.agents[0].loop.memory = MemoryParams(  # type: ignore[union-attr]
        collection="kb", write=["ticket", "resolution"], **memory
    )
    return wfs


async def test_a_later_run_opens_with_the_earlier_one(vectors: AsyncEngine, model: Any) -> None:  # noqa: F811
    script = model(finish(), finish())
    first = await start(vectors, remembering())
    assert first.status == "completed", first.error
    opening = script.seen[0][1]["content"]
    assert "Earlier context" not in opening  # nothing to recall yet
    assert [e["fields"] for e in await events(vectors, first.id, "memory_written")] == [
        ["ticket", "resolution"]
    ]

    second = await start(vectors, remembering())
    prompt = script.seen[1][1]["content"]
    assert '<data name="memory">' in prompt and "ticket: refund order o-2 please" in prompt
    assert "resolution: done" in prompt
    recalled = (await events(vectors, second.id, "memory_recalled"))[0]
    assert recalled["used"] == 1


async def test_a_loop_that_does_not_finish_remembers_nothing(
    vectors: AsyncEngine, model: Any
) -> None:  # noqa: F811
    model([call("lookup_order", order_id="o-1")], "just text", "still text")
    run = await start(vectors, remembering())
    assert run.end_name == "failed"  # the model never called finish
    async with AsyncSession(vectors) as s:
        stored = (
            await s.execute(sa.text("select count(*) from tuvl_system_vector_store"))
        ).scalar_one()
    assert stored == 0
