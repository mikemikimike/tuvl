from typing import Any

from tuvl.core.engine.templating import expand_env
from tuvl.core.logger import logger

DATASOURCE_REGISTRY: dict[str, dict[str, Any]] = {}

# The resolved primary Postgres datasource name.  Finalised by
# ``_finalize_primary_ds()`` after all DataSource YAMLs are loaded.
# Resolution order:
#   1. First datasource with ``metadata.primary: true`` (explicit).
#   2. First Postgres datasource in registry insertion order (auto-fallback).
PRIMARY_DS: str = ""

# Intermediate: name explicitly marked ``metadata.primary: true`` during
# registration.  Cleared by ``_reset_primary_state()``.
_EXPLICIT_PRIMARY_DS: str = ""


def _resolve_env(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(item) for item in value]
    if not isinstance(value, str):
        return value

    resolved_str = expand_env(value, source="DataSource config") or ""

    # Coerce plain integers (e.g. ports) but NEVER float-coerce and never strip a
    # leading zero — that would mangle numeric secrets ("0123" -> 123, "1e5" ->
    # 100000.0) and cause confusing auth failures.
    if resolved_str.isdigit() and (resolved_str == "0" or not resolved_str.startswith("0")):
        return int(resolved_str)
    return resolved_str


def _register_datasource_from_dict(data: dict[str, Any], filename: str = "<unknown>") -> None:
    """Register a single ``DataSource`` or ``RedisConfig`` dict into :data:`DATASOURCE_REGISTRY`."""
    global _EXPLICIT_PRIMARY_DS

    kind = data.get("kind")
    if kind not in ("DataSource", "RedisConfig"):
        return

    if data.get("enabled", True) is False:
        logger.info("Skipped datasource (enabled: false)", file=filename)
        return

    try:
        resolved = _resolve_env(data)
        name = resolved["metadata"]["name"]
        DATASOURCE_REGISTRY[name] = resolved

        if resolved["metadata"].get("primary", False):
            _EXPLICIT_PRIMARY_DS = name
            logger.info("Primary datasource explicitly marked", datasource=name)

        ds_type = resolved["spec"]["type"]
        conn = resolved["spec"]["connection"]
        host = conn["host"]
        port = conn["port"]
        db_or_name = conn.get("database") or conn.get("db", "")
        logger.info(
            "DataSource loaded", name=name, type=ds_type, host=host, port=port, db=db_or_name
        )
    except OSError as exc:
        logger.error("Datasource file OS error", file=filename, error=exc)
        raise
    except Exception as exc:
        logger.error("Error loading datasource", file=filename, error=exc)
        raise


def _finalize_primary_ds() -> None:
    """Resolve and publish ``PRIMARY_DS`` after all datasources are registered.

    Resolution order:

    1. ``metadata.primary: true`` — operator's explicit choice.
    2. First Postgres datasource in registry insertion order — deterministic
       auto-fallback when no datasource is explicitly marked primary.

    Call this once from ``load_all_datasources()`` (standalone path) and from
    ``load_all_configs()`` (central-loader path) after all DataSource entries
    have been registered.
    """
    global PRIMARY_DS

    if _EXPLICIT_PRIMARY_DS:
        PRIMARY_DS = _EXPLICIT_PRIMARY_DS
        return

    # Auto-fallback: first Postgres in load order.
    for name, cfg in DATASOURCE_REGISTRY.items():
        if cfg.get("spec", {}).get("type", "postgres") in ("postgres", "postgresql"):
            PRIMARY_DS = name
            logger.info("Primary datasource auto-selected (first postgres)", datasource=name)
            return

    PRIMARY_DS = ""


def _reset_primary_state() -> None:
    """Clear primary-datasource tracking state before a fresh config load."""
    global PRIMARY_DS, _EXPLICIT_PRIMARY_DS
    PRIMARY_DS = ""
    _EXPLICIT_PRIMARY_DS = ""
