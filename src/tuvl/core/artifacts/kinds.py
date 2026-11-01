"""Canonical closed set of artifact types — the single source of truth.

Mirrors :mod:`tuvl.core.engine.step_kinds`: the validator, the loaders, and the
runtime all import these constants so the closed set lives in exactly one place.
"""

from __future__ import annotations

#: Every valid artifact ``type``.
ARTIFACT_TYPES: frozenset[str] = frozenset(
    {"prompt", "steering", "skill", "guardrail", "hook", "mcp", "judge", "rules"}
)

#: Markdown-with-front-matter artifacts under ``artifacts/``.
PROSE_TYPES: frozenset[str] = frozenset({"prompt", "steering", "skill"})

#: ``kind: Artifact`` YAML-envelope artifacts.
STRUCTURED_TYPES: frozenset[str] = frozenset({"guardrail", "hook", "mcp", "judge", "rules"})

#: Per-artifact content cap, enforced at load for every source — keeps
#: "fetch to memory" honest.
MAX_ARTIFACT_BYTES: int = 512 * 1024

#: Which artifact types each reference site accepts. Judge ``criteria`` takes
#: steering artifacts (the ``criteria`` type was folded into ``steering``).
REF_SITE_COMPAT: dict[str, frozenset[str]] = {
    "system": frozenset({"prompt"}),
    "prompt": frozenset({"prompt"}),
    "steering": frozenset({"steering", "prompt"}),
    "skills": frozenset({"skill"}),
    "criteria": frozenset({"steering"}),
    "guardrails": frozenset({"guardrail", "judge"}),
    "judge": frozenset({"judge"}),
    "decide.rules": frozenset({"rules"}),
    "hooks": frozenset({"hook"}),
    "mcp.server": frozenset({"mcp"}),
}
