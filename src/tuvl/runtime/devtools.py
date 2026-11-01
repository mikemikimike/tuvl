"""Developer controls (spec §19.4), active only in dev mode: breakpoints
before agents and step mode for whole runs.

A hit pauses the run through the normal pause path (status ``paused``, a
``paused`` journal event with the reason), so ``resume`` works unchanged.
Each position a run paused at is remembered, so resuming (or re-entering
the agent after a human decision) goes on instead of stopping there again. State is per process —
fine for ``tuvl dev``, which runs the API and the worker together.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

#: workflow → agent ids to pause before.
BREAKPOINTS: dict[str, set[str]] = {}
#: Runs that pause before every agent and approve every loop tool call.
STEP_RUNS: set[uuid.UUID] = set()
#: run → the (agent, step) positions it already paused at. A position pauses
#: once: resuming — or re-entering the same agent after a human decision — goes on.
_PAUSED_AT: dict[uuid.UUID, set[tuple[str, int]]] = {}


def enabled() -> bool:
    from tuvl.core.config import settings

    return bool(settings.tuvl_dev_mode)


def _file(project: Path) -> Path:
    return project / ".tuvl" / "breakpoints.json"


def load(project: Path) -> None:
    path = _file(project)
    BREAKPOINTS.clear()
    if path.is_file():
        for workflow, agents in json.loads(path.read_text()).items():
            BREAKPOINTS[workflow] = set(agents)


def set_breakpoints(project: Path, workflow: str, agents: list[str]) -> None:
    if agents:
        BREAKPOINTS[workflow] = set(agents)
    else:
        BREAKPOINTS.pop(workflow, None)
    path = _file(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({w: sorted(a) for w, a in sorted(BREAKPOINTS.items())}, indent=2) + "\n"
    )


def pause_reason(run_id: uuid.UUID, workflow: str, agent: str, step: int) -> str | None:
    """Why the run should pause before *agent*, or ``None``."""
    if not enabled():
        return None
    seen = _PAUSED_AT.setdefault(run_id, set())
    if (agent, step) in seen:
        return None
    if run_id in STEP_RUNS:
        reason = "step"
    elif agent in BREAKPOINTS.get(workflow, set()):
        reason = "breakpoint"
    else:
        return None
    seen.add((agent, step))
    return reason


def approve_tools(run_id: uuid.UUID) -> bool:
    """Step mode also stops before every loop tool call (approve / edit / reject)."""
    return enabled() and run_id in STEP_RUNS


def forget(run_id: uuid.UUID) -> None:
    STEP_RUNS.discard(run_id)
    _PAUSED_AT.pop(run_id, None)
