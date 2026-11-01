"""External artifact sources — integrity-pinned fetch at startup.

``config.yaml`` declares the sources::

    spec:
      artifact_sources:
        - name: org-prompt-pack
          url: https://artifacts.example.com/packs/support-v3.tar.gz
          sha256: "9f2c…"     # REQUIRED — unpinned sources are refused

Each source is a ``.tar.gz`` of prose ``.md`` (front-matter) and structured
``kind: Artifact`` YAML files. Downloads are verified against the pinned
``sha256`` before anything enters the registry, then unpacked into the
hash-keyed disk cache ``.tuvl/artifacts/cache/<sha256>/`` — a warm cache means
offline restarts, and a tampered re-fetch can never shadow a pinned artifact.
External artifacts sit LAST in the name-collision precedence: a checked-in
file always beats a remote pack.
"""

from __future__ import annotations

import hashlib
import io
import pathlib
import tarfile
from typing import Any

import structlog
import yaml

from tuvl.core.artifacts.loader import (
    _register_artifact_from_dict,
    read_prose_artifact,
)
from tuvl.core.artifacts.registry import register_artifact

logger = structlog.get_logger(__name__)


def _cache_root() -> pathlib.Path:
    from tuvl.core.config import settings

    return settings.project_dir / ".tuvl" / "artifacts" / "cache"


def _register_cached_dir(cache_dir: pathlib.Path, source_name: str) -> int:
    """Register every artifact file under one unpacked cache dir as
    ``source="external"``."""
    count = 0
    for path in sorted(cache_dir.rglob("*.md")):
        try:
            meta, body = read_prose_artifact(path)
        except ValueError as exc:
            logger.error(
                "artifact.external.load_failed",
                source=source_name,
                file=path.name,
                error=str(exc),
            )
            continue
        register_artifact(
            name=str(meta["name"]),
            type_=str(meta["type"]),
            version=int(meta.get("version", 1)),
            content=body,
            source="external",
            description=str(meta.get("description") or ""),
            enabled=meta.get("enabled", True) is not False,
        )
        count += 1
    for path in sorted(cache_dir.rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:
            logger.error(
                "artifact.external.load_failed",
                source=source_name,
                file=path.name,
                error=str(exc),
            )
            continue
        if not isinstance(data, dict) or data.get("kind") != "Artifact":
            continue
        try:
            _register_artifact_from_dict(data, f"{source_name}/{path.name}", source="external")
        except ValueError as exc:
            logger.error(
                "artifact.external.load_failed",
                source=source_name,
                file=path.name,
                error=str(exc),
            )
            continue
        count += 1
    return count


async def _fetch(url: str) -> bytes:
    from tuvl.core.infra.http_client import get_http_client

    client = get_http_client(timeout=60)
    response = await client.get(url)
    response.raise_for_status()
    return response.content


def _unpack(archive: bytes, dest: pathlib.Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        # filter="data" refuses absolute paths, traversal, links — a hostile
        # archive cannot write outside the cache dir.
        tar.extractall(dest, filter="data")


async def load_external_artifacts() -> None:
    """Fetch, verify, cache, and register every declared external source.

    A source without ``sha256`` is refused. A warm cache dir is used without
    any network I/O; a fetch whose digest mismatches the pin is discarded.
    Failures never abort boot by themselves — the ref-resolution pass decides
    whether a missing artifact is fatal.
    """
    from tuvl.core.config import settings

    sources: list[dict[str, Any]] = (
        settings._project_config.get("spec", {}).get("artifact_sources") or []
    )
    for source in sources:
        name = str(source.get("name") or source.get("url") or "<unnamed>")
        url = source.get("url")
        sha256 = str(source.get("sha256") or "").strip().lower()
        if not url:
            logger.error("artifact.source.invalid", source=name, reason="missing url")
            continue
        if not sha256:
            logger.error(
                "artifact.source.refused",
                source=name,
                reason="missing sha256 — unpinned sources are refused",
            )
            continue

        cache_dir = _cache_root() / sha256
        if not cache_dir.is_dir():
            try:
                payload = await _fetch(str(url))
            except Exception as exc:
                logger.error(
                    "artifact.source.fetch_failed",
                    source=name,
                    url=url,
                    error=str(exc),
                )
                continue
            digest = hashlib.sha256(payload).hexdigest()
            if digest != sha256:
                logger.error(
                    "artifact.source.integrity_mismatch",
                    source=name,
                    expected=sha256,
                    got=digest,
                )
                continue
            try:
                _unpack(payload, cache_dir)
            except Exception as exc:
                logger.error("artifact.source.unpack_failed", source=name, error=str(exc))
                continue

        count = _register_cached_dir(cache_dir, name)
        logger.info("artifact.source.loaded", source=name, artifacts=count)
