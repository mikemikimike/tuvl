"""Optional dependency groups of the ``tuvl`` distribution.

``pyproject.toml`` declares these as extras; this table is the runtime's view of
the same set. ``tuvl ship`` reads it to install only the extras a project uses,
and the modules that need one call :func:`require` so a missing package says
which extra to install.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass


class MissingExtraError(ImportError):
    """A feature was used whose optional dependency is not installed."""

    def __init__(self, extra: str, feature: str) -> None:
        self.extra = extra
        super().__init__(f"{feature} needs the {extra!r} extra: pip install 'tuvl[{extra}]'")


@dataclass(frozen=True)
class Extra:
    module: str  # the top-level import the extra provides
    package: str  # the distribution that provides it
    feature: str
    shipped: bool  # False: development tooling, never part of a production image


EXTRAS: dict[str, Extra] = {
    "mcp": Extra("mcp", "mcp", "MCP tools and MCP export", shipped=True),
    "redis": Extra("redis", "redis", "the Redis datasource", shipped=True),
    "vector": Extra("pgvector", "pgvector", "vector search", shipped=True),
    "otel-grpc": Extra(
        "grpc", "opentelemetry-exporter-otlp-proto-grpc", "OTLP export over gRPC", shipped=True
    ),
    "codegen": Extra("libcst", "libcst", "tuvl generate code", shipped=False),
    "test": Extra("aiosqlite", "aiosqlite", "tuvl run tests", shipped=False),
    "pdf": Extra("pypdf", "pypdf", "reading PDF ideas (tuvl import idea)", shipped=False),
    "review": Extra("ruff", "ruff", "linting Python in tuvl review code", shipped=False),
    "tui": Extra("textual", "textual", "the terminal UI of tuvl dev", shipped=False),
}


def available(extra: str) -> bool:
    try:
        return importlib.util.find_spec(EXTRAS[extra].module) is not None
    except (ImportError, ValueError):
        return False


def require(extra: str) -> None:
    if not available(extra):
        raise MissingExtraError(extra, EXTRAS[extra].feature)


TOOLCHAIN_EXTRAS = ("codegen", "test")


def toolchain_installed() -> bool:
    """Whether the developer toolchain (``tuvl[standard]``) is installed.

    ``TUVL_TOOLCHAIN=1`` / ``0`` forces the answer (tests, CI).
    """
    forced = os.environ.get("TUVL_TOOLCHAIN")
    if forced in {"0", "1"}:
        return forced == "1"
    return all(available(extra) for extra in TOOLCHAIN_EXTRAS)
