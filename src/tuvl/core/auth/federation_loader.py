"""Loader for federation provider YAML files.

Each YAML in the project's ``federation/`` directory must have:

    kind: FederationProvider
    version: v1
    metadata:
      name: google          # matches the URL param: /auth/oauth/google/...
      description: ...      # optional
    enabled: true           # default true; set false to disable without deleting
    spec:
      provider: google      # google | github | microsoft | custom
      client_id: ${GOOGLE_CLIENT_ID}
      client_secret: ${GOOGLE_CLIENT_SECRET}
      # Optional overrides (defaults are built-in for google/github/microsoft)
      auth_url: https://...
      token_url: https://...
      userinfo_url: https://...
      scope: "openid email profile"
      # Microsoft-only
      tenant_id: common
      # Restrict login to users whose email domain is in this list.
      # Omit to allow any email address from the provider.
      # allowed_domains:
      #   - example.com
      # Role to assign automatically when a new federated user logs in for the
      # first time.  The role must already exist in the IAM database.
      # Omit to leave new users unprivileged (an admin must assign roles manually).
      # default_role: member
"""

from __future__ import annotations

import os
import pathlib
import re
from typing import Any

import yaml

from tuvl.core.logger import logger

# Registry: name → resolved YAML dict
FEDERATION_REGISTRY: dict[str, dict[str, Any]] = {}

_ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")


def _resolve_env(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env(item) for item in value]
    if not isinstance(value, str):
        return value

    def _replace(match: re.Match) -> str:
        var_name: str = match.group(1)
        default: str | None = match.group(2)
        if default is not None:
            return os.environ.get(var_name, default)
        val = os.environ.get(var_name)
        if val is None:
            raise OSError(
                f"Federation config references undefined environment variable "
                f"'${{{var_name}}}'. Set it in your .env file or environment."
            )
        return val

    return _ENV_PATTERN.sub(_replace, value)


def _register_federation_from_dict(data: dict[str, Any], filename: str = "<unknown>") -> None:
    """Register a single ``FederationProvider`` dict into :data:`FEDERATION_REGISTRY`."""
    if not isinstance(data, dict) or data.get("kind") != "FederationProvider":
        return

    if data.get("enabled", True) is False:
        logger.info("Skipped federation provider (enabled: false)", file=filename)
        return

    try:
        resolved = _resolve_env(data)
    except OSError as exc:
        logger.warning(
            "Skipping federation provider, env resolution failed", file=filename, error=exc
        )
        return

    name: str = resolved["metadata"]["name"]
    FEDERATION_REGISTRY[name] = resolved
    provider_type = resolved.get("spec", {}).get("provider", name)
    logger.info("Federation provider loaded", name=name, type=provider_type)


def load_all_federation_providers(config_dir: pathlib.Path | str | None = None) -> None:
    """Walk *config_dir* (defaults to ``<project>/federation/``) and populate
    :data:`FEDERATION_REGISTRY` from every ``kind: FederationProvider`` YAML."""

    FEDERATION_REGISTRY.clear()

    if config_dir is None:
        from tuvl.core.config import settings

        config_dir = settings.dir_for("federation")

    base_path = pathlib.Path(config_dir)
    if not base_path.exists():
        logger.debug("No federation directory found, skipping", path=str(base_path))
        return

    yaml_files = list(base_path.glob("*.yaml"))
    if not yaml_files:
        logger.debug("No YAML files in federation directory, skipping", path=str(base_path))
        return

    for yaml_file in yaml_files:
        with open(yaml_file) as f:
            try:
                raw = yaml.safe_load(f)
            except yaml.YAMLError as exc:
                logger.warning(
                    "Skipping federation YAML, parse error", file=yaml_file.name, error=exc
                )
                continue

        _register_federation_from_dict(raw, yaml_file.name)

    if FEDERATION_REGISTRY:
        logger.info("Federation registry loaded", providers=list(FEDERATION_REGISTRY.keys()))
