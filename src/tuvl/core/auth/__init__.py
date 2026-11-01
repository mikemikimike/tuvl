"""tuvl.core.auth — Token-based (Ed25519 JWT) authentication and authorisation layer.

Re-exports are resolved lazily (PEP 562): importing this package — or any
light submodule such as ``schemas`` / ``workflow_policy`` (the CLI validator
does) — must never construct the key manager, which requires
``TUVL_SIGNING_KEY`` outside dev mode.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "key_manager": ("tuvl.core.auth.keys", "key_manager"),
    "verify_token": ("tuvl.core.auth.access", "verify_token"),
    "get_current_user": ("tuvl.core.auth.access", "get_current_user"),
    "require_groups": ("tuvl.core.auth.access", "require_groups"),
    "require_scope": ("tuvl.core.auth.access", "require_scope"),
    "TokenUser": ("tuvl.core.auth.schemas", "TokenUser"),
    "get_password_hash": ("tuvl.core.auth.crypto", "get_password_hash"),
    "verify_password": ("tuvl.core.auth.crypto", "verify_password"),
    "mint_token": ("tuvl.core.auth.token", "mint_token"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attr = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    return getattr(import_module(module_name), attr)
