"""Shared model-client scripting helpers.

One canonical copy of the acompletion stub used across the agent/supervisor
suites (each previously carried its own subtly-divergent copy). ``script()``
installs a deterministic turn sequence; the returned list captures every call's
kwargs for assertions on the prompt that was actually sent.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from tuvl import llm as llm_client


def tool_call(call_id: str, name: str, arguments: dict[str, Any]) -> SimpleNamespace:
    """One entry of an assistant turn's ``tool_calls`` list."""
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def turn(
    content: str = "", tool_calls: list | None = None, total_tokens: int = 10
) -> SimpleNamespace:
    """One scripted LLM response in the client's response shape."""
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(total_tokens=total_tokens),
    )


def outcome_turn(outcome: str, result: Any = "ok", total_tokens: int = 10) -> SimpleNamespace:
    """A final no-tool turn emitting an AutonomousAgent outcome."""
    return turn(
        content=json.dumps({"outcome": outcome, "result": result}), total_tokens=total_tokens
    )


def script(turns: list, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Monkeypatch ``tuvl.llm.acompletion`` to replay *turns* in order.

    Returns the list that accumulates each call's kwargs. Each fake call yields
    to the event loop like a real network call would, so concurrent watcher
    tasks (e.g. the Supervisor) get scheduled between turns.
    """
    calls: list[dict] = []
    seq = iter(turns)

    async def _fake(**kwargs):
        calls.append(kwargs)
        await asyncio.sleep(0)
        return next(seq)

    monkeypatch.setattr(llm_client, "acompletion", _fake)
    return calls
