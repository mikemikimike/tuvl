"""tuvl.core — engine internals.

``tuvl.core.app`` is exposed lazily via PEP 562 ``__getattr__`` so that
``from tuvl.core.X import Y`` does not boot the FastAPI app stack or
instantiate the auth ``key_manager``.  Previously this module did
``from tuvl.core.app import app`` at import time, which ran the entire
startup chain (signing-key load, settings, datasources, etc.) just to
import a schema dataclass.

Access ``tuvl.core.app`` the same as before — the first attribute access
triggers the boot lazily; everything else is unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI as _FastAPI

    app: _FastAPI

__all__ = ["app"]


def __getattr__(name: str) -> Any:
    if name == "app":
        from tuvl.core.app import app as _app

        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
