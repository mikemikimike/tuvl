"""Standalone helpers shared by the checks and by the runtime."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from tuvl.contract.schema import (
    DecideAgent,
    HumanAgent,
    LlmAgent,
    LoopAgent,
    McpToolRef,
    ParallelAgent,
    PendingAgent,
    ToolAgent,
    WorkflowDocument,
)
from tuvl.contract.tel import TELError

_TRIGGER = "$trigger"


# ── helpers ──────────────────────────────────────────────────────────────────


def _merge(a: dict[str, frozenset[str]], b: dict[str, frozenset[str]]) -> dict[str, frozenset[str]]:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, frozenset()) | v
    return out


def artifact_refs(agent: Any) -> Iterator[tuple[tuple[str | int, ...], str, str]]:
    """Every ``artifact://`` reference an agent declares: ``(loc, site, ref)``."""
    for k, ref in enumerate(agent.hooks):
        yield ("hooks", k), "hooks", ref
    guardrails = getattr(agent, "guardrails", None)
    if guardrails is not None:
        for gate in ("input", "output", "tools"):
            for k, ref in enumerate(getattr(guardrails, gate)):
                yield ("guardrails", gate, k), "guardrails", ref
    if isinstance(agent, LlmAgent):
        for key in ("system", "prompt"):
            text = getattr(agent.llm, key)
            if text and text.startswith("artifact://"):
                yield ("llm", key), key, text
        for k, ref in enumerate(agent.llm.skills):
            yield ("llm", "skills", k), "skills", ref
    elif isinstance(agent, LoopAgent):
        if agent.loop.steering.startswith("artifact://"):
            yield ("loop", "steering"), "steering", agent.loop.steering
        for k, ref in enumerate(agent.loop.skills):
            yield ("loop", "skills", k), "skills", ref
        for j, tool in enumerate(agent.loop.tools):
            if isinstance(tool, McpToolRef):
                yield ("loop", "tools", j, "mcp"), "mcp.server", tool.mcp
        if agent.loop.supervisor and agent.loop.supervisor.judge:
            yield ("loop", "supervisor", "judge"), "judge", agent.loop.supervisor.judge
    elif isinstance(agent, DecideAgent) and isinstance(agent.decide.rules, str):
        yield ("decide", "rules"), "decide.rules", agent.decide.rules
    elif isinstance(agent, ToolAgent) and agent.tool.use == "mcp":
        yield ("tool", "server"), "mcp.server", agent.tool.server


def document_artifact_refs(doc: WorkflowDocument) -> Iterator[tuple[str, str, str]]:
    """Every artifact reference in a workflow: ``(where, site, ref)``."""
    name = doc.metadata.name
    for agent in doc.spec.agents:
        for loc, site, ref in artifact_refs(agent):
            yield f"[{name}] agent '{agent.id}' {'.'.join(map(str, loc))}", site, ref
    for k, ref in enumerate(doc.spec.hooks):
        yield f"[{name}] spec.hooks[{k}]", "hooks", ref
    if doc.spec.supervisor and doc.spec.supervisor.judge:
        yield f"[{name}] spec.supervisor.judge", "judge", doc.spec.supervisor.judge


def determinism_of(agent: Any) -> str:
    """``deterministic`` | ``bounded`` (a model decides) | ``external`` (a
    human) | ``pending`` — the agent's determinism class (spec §19)."""
    if isinstance(agent, PendingAgent):
        return "pending"
    if isinstance(agent, HumanAgent):
        return "external"
    if isinstance(agent, ParallelAgent):
        order = ("deterministic", "bounded", "external", "pending")
        return max((determinism_of(b) for b in agent.parallel.branches), key=order.index)
    if isinstance(agent, (LlmAgent, LoopAgent)) or (
        isinstance(agent, DecideAgent)
        and agent.decide.model is not None
        and not agent.decide.shadow
    ):
        return "bounded"
    return "deterministic"


_EFFECT_RANK = {"read": 0, "write": 1, "destructive": 2}


def _waits_for_a_person(agent: Any) -> str | None:
    """Why *agent* would leave its run waiting (so a mapped workflow cannot contain it)."""
    if isinstance(agent, HumanAgent):
        return "waits for a person (human)"
    if isinstance(agent, PendingAgent):
        return "is pending (contract only)"
    if isinstance(agent, LoopAgent) and any(
        getattr(tool, "approval", None) is not None for tool in agent.loop.tools
    ):
        return "has a loop tool that needs approval"
    return None


def derived_effect(agent: Any) -> str | None:
    """The effect a ``tool`` agent has by construction (spec §9.3). ``code``
    agents are not checked — their writes commit inside their own step's
    transaction; other engines have no side effects of their own."""
    if not isinstance(agent, ToolAgent):
        return None
    tool = agent.tool
    if tool.use == "db":
        return {"read": "read", "list": "read", "delete": "destructive"}.get(tool.op, "write")
    if tool.use == "http":
        return "read" if tool.method in ("GET", "HEAD") else "write"
    if tool.use == "storage":
        if tool.op == "delete":
            return "destructive"
        if tool.op in ("put", "copy") or (tool.op == "presign" and tool.method == "PUT"):
            return "write"
        return "read"
    return "write"


def _strings(value: Any, loc: tuple[str | int, ...]) -> Iterator[tuple[tuple[str | int, ...], str]]:
    if isinstance(value, str):
        yield loc, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, (*loc, str(k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _strings(v, (*loc, i))


def _tel_message(exc: Exception) -> str:
    if isinstance(exc, TELError):
        if exc.text and exc.pos is not None:
            return f"{exc.message} (column {exc.pos + 1} of {exc.text!r})"
        return exc.message
    return str(exc)


def _sccs(edges: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's strongly connected components (iterative)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = 0
    for root in edges:
        if root in index:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, i = work.pop()
            if i == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            succ = edges.get(node, [])
            if i < len(succ):
                work.append((node, i + 1))
                nxt = succ[i]
                if nxt not in edges:
                    continue
                if nxt not in index:
                    work.append((nxt, 0))
                elif nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
                continue
            if low[node] == index[node]:
                comp: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                out.append(comp)
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return out
