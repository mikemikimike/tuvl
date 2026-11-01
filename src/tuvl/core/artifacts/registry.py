"""The in-memory artifact registry and ``artifact://`` reference resolution.

Artifacts are named, versioned, typed assets (prompts, steering, skills,
guardrails, hooks, MCP server configs) loaded at startup from three sources —
project files, DB uploads, and integrity-pinned external packs — into one
registry. Content lives in memory; runners never touch disk on the hot path
(file-source entries lazily re-read on mtime change so ``tuvl dev`` picks up
``.md`` edits without a restart).

Reference syntax: ``artifact://name[@version]`` in any string-typed field.
No version → latest enabled version. The ref declared in workflow YAML is the
grant — the same trust model as agent tools.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from tuvl.core.artifacts.kinds import PROSE_TYPES, REF_SITE_COMPAT

logger = structlog.get_logger(__name__)

ARTIFACT_REF_RE = re.compile(r"^artifact://([A-Za-z0-9][A-Za-z0-9_.-]*)(?:@(\d+))?$")

#: Lower rank wins a name collision (boot warns on shadowing).
SOURCE_PRECEDENCE: dict[str, int] = {"file": 0, "db": 1, "external": 2}


class ArtifactResolutionError(ValueError):
    """An ``artifact://`` reference that cannot be resolved (unknown name or
    version, disabled, or wrong type for the site)."""


@dataclass
class ArtifactVersion:
    content: Any  # str for prose types, dict for structured types
    content_hash: str
    source: str  # "file" | "db" | "external"
    enabled: bool = True
    path: Path | None = None  # file source only — for the mtime dev-refresh
    mtime: float | None = None


@dataclass
class ArtifactEntry:
    name: str
    type: str
    description: str = ""
    versions: dict[int, ArtifactVersion] = field(default_factory=dict)

    @property
    def source(self) -> str:
        return next(iter(self.versions.values())).source if self.versions else "file"

    @property
    def latest(self) -> int:
        enabled = [v for v, av in self.versions.items() if av.enabled]
        return max(enabled) if enabled else max(self.versions, default=0)


# name → entry (one source per name; collision precedence file → db → external)
ARTIFACT_REGISTRY: dict[str, ArtifactEntry] = {}


def content_hash(content: Any) -> str:
    raw = content if isinstance(content, str) else repr(sorted(str(content)))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def register_artifact(
    *,
    name: str,
    type_: str,
    version: int,
    content: Any,
    source: str,
    description: str = "",
    enabled: bool = True,
    path: Path | None = None,
    mtime: float | None = None,
) -> None:
    """Register one artifact version, enforcing name-collision precedence.

    A name owned by a higher-precedence source shadows later sources entirely
    (warned, never merged) — a checked-in file always beats a remote pack.
    """
    entry = ARTIFACT_REGISTRY.get(name)
    if entry is not None and entry.source != source:
        if SOURCE_PRECEDENCE[entry.source] <= SOURCE_PRECEDENCE[source]:
            logger.warning(
                "artifact.shadowed",
                name=name,
                kept_source=entry.source,
                shadowed_source=source,
            )
            return
        logger.warning(
            "artifact.shadowed",
            name=name,
            kept_source=source,
            shadowed_source=entry.source,
        )
        entry = None
    if entry is None:
        entry = ArtifactEntry(name=name, type=type_, description=description)
        ARTIFACT_REGISTRY[name] = entry
    if description and not entry.description:
        entry.description = description
    entry.versions[version] = ArtifactVersion(
        content=content,
        content_hash=content_hash(content),
        source=source,
        enabled=enabled,
        path=path,
        mtime=mtime,
    )


def is_artifact_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("artifact://")


def parse_ref(value: str) -> tuple[str, int | None]:
    """Return ``(name, pinned_version | None)``; raise on a malformed ref."""
    m = ARTIFACT_REF_RE.match(value.strip())
    if not m:
        raise ArtifactResolutionError(
            f"malformed artifact reference '{value}' — expected artifact://name[@version]"
        )
    name, ver = m.group(1), m.group(2)
    return name, int(ver) if ver else None


def _dev_refresh(av: ArtifactVersion) -> None:
    """File-source entries lazily re-read on mtime change so ``.md`` edits
    apply on the next run without a process restart (``tuvl dev`` only
    restarts on ``*.yaml``)."""
    if av.source != "file" or av.path is None:
        return
    try:
        mtime = av.path.stat().st_mtime
    except OSError:
        return
    if av.mtime is not None and mtime != av.mtime:
        from tuvl.core.artifacts.loader import read_prose_artifact

        try:
            _meta, body = read_prose_artifact(av.path)
        except ValueError as exc:
            logger.warning("artifact.refresh_failed", path=str(av.path), error=str(exc))
            return
        av.content = body
        av.content_hash = content_hash(body)
        av.mtime = mtime


def get_version(name: str, version: int | None, *, where: str) -> ArtifactVersion:
    """Resolve a name + optional pinned version to one enabled version."""
    entry = ARTIFACT_REGISTRY.get(name)
    if entry is None:
        raise ArtifactResolutionError(
            f"{where}: unknown artifact '{name}' — no artifact with this name is "
            f"registered (sources: artifacts/ files, uploads, artifact_sources)"
        )
    target = version if version is not None else entry.latest
    av = entry.versions.get(target)
    if av is None:
        raise ArtifactResolutionError(
            f"{where}: artifact '{name}' has no version {target} (known: {sorted(entry.versions)})"
        )
    if not av.enabled:
        raise ArtifactResolutionError(f"{where}: artifact '{name}@{target}' is disabled")
    _dev_refresh(av)
    return av


def resolve_prose(value: str, *, site: str, where: str) -> str:
    """Resolve a string field that may be inline prose or an artifact ref.

    Inline strings pass through untouched; ``artifact://`` refs resolve from
    the registry with site type-compatibility enforced.
    """
    if not is_artifact_ref(value):
        return value
    name, version = parse_ref(value)
    entry = ARTIFACT_REGISTRY.get(name)
    av = get_version(name, version, where=where)
    allowed = REF_SITE_COMPAT.get(site, PROSE_TYPES)
    if entry is not None and entry.type not in allowed:
        raise ArtifactResolutionError(
            f"{where}: artifact '{name}' has type '{entry.type}' — this field "
            f"accepts {sorted(allowed)}"
        )
    if not isinstance(av.content, str):
        raise ArtifactResolutionError(f"{where}: artifact '{name}' is not a prose artifact")
    return av.content


def resolve_structured(value: str, *, site: str, where: str) -> dict[str, Any]:
    """Resolve an ``artifact://`` ref to a structured artifact's spec dict."""
    name, version = parse_ref(value)
    entry = ARTIFACT_REGISTRY.get(name)
    av = get_version(name, version, where=where)
    allowed = REF_SITE_COMPAT.get(site, frozenset())
    if entry is not None and entry.type not in allowed:
        raise ArtifactResolutionError(
            f"{where}: artifact '{name}' has type '{entry.type}' — this field "
            f"accepts {sorted(allowed)}"
        )
    if not isinstance(av.content, dict):
        raise ArtifactResolutionError(f"{where}: artifact '{name}' is not a structured artifact")
    return av.content
