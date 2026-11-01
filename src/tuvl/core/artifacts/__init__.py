"""First-class artifact subsystem — named, versioned, browsable assets.

Prompts, steering, skills, guardrails, hooks, and MCP server configs are
authored as files (``artifacts/``), uploaded through Insight, or fetched from
integrity-pinned external sources, loaded at boot into one in-memory registry,
and consumed everywhere via ``artifact://name[@version]`` references.
"""

from tuvl.core.artifacts.kinds import (
    ARTIFACT_TYPES,
    MAX_ARTIFACT_BYTES,
    PROSE_TYPES,
    REF_SITE_COMPAT,
    STRUCTURED_TYPES,
)
from tuvl.core.artifacts.registry import (
    ARTIFACT_REGISTRY,
    ArtifactEntry,
    ArtifactResolutionError,
    ArtifactVersion,
    is_artifact_ref,
    parse_ref,
    register_artifact,
    resolve_prose,
    resolve_structured,
)

__all__ = [
    "ARTIFACT_REGISTRY",
    "ARTIFACT_TYPES",
    "MAX_ARTIFACT_BYTES",
    "PROSE_TYPES",
    "REF_SITE_COMPAT",
    "STRUCTURED_TYPES",
    "ArtifactEntry",
    "ArtifactResolutionError",
    "ArtifactVersion",
    "is_artifact_ref",
    "parse_ref",
    "register_artifact",
    "resolve_prose",
    "resolve_structured",
]
