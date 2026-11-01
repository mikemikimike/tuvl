"""tuvl — Intelligent Workflows. Deterministic Execution.

Public surface
--------------

* ``tuvl.__version__`` — installed package version (via ``importlib.metadata``).
* ``tuvl.tenancy`` — tenant-context API for multi-tenant deployments.
  See ``tuvl.tenancy.tenant_scope`` and ``MissingTenantContextError``.
* ``tuvl.core.app`` — FastAPI application instance, exposed lazily so that
  importing ``tuvl`` for version metadata never triggers a full engine boot.
* ``tuvl.agent`` / ``tuvl.Ctx`` — the 2.0 ``code`` agent decorator and its
  context object (``from tuvl import agent, Ctx``), imported lazily.

For workflow / model authoring, consult ``docs/tuvl-agentic-manual.md`` —
the engine reads YAML; you almost never need to import from
``tuvl.core.*`` directly.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("tuvl")
except PackageNotFoundError:  # pragma: no cover — uninstalled checkout
    __version__ = "0.0.0+local"

__all__ = ["Ctx", "__version__", "agent"]


def __getattr__(name: str) -> object:
    if name in ("agent", "Ctx"):
        from tuvl.runtime import code

        return getattr(code, name)
    raise AttributeError(f"module 'tuvl' has no attribute {name!r}")
