"""AgentModel (``kind: AgentModel``) registry and call-parameter resolution.

AgentModels are loaded by the central config loader at startup like every
other kind — the previous lazy per-call file cache in the agent runner is
gone. ``resolve_call_params`` is the single place an ``agent.model`` name (or
the supervisor's judge ``model``) becomes a ``provider/model`` string plus call
kwargs; it is shared by both agent execution modes and the supervisor judge.
"""

from __future__ import annotations

from typing import Any

import structlog

from tuvl.core.engine.templating import expand_env

logger = structlog.get_logger(__name__)

# name → flattened AgentModel config (spec promoted to root, `enabled` kept).
AGENT_MODEL_REGISTRY: dict[str, dict[str, Any]] = {}


def default_credentials(
    model: str, api_key: str | None, api_base: str | None
) -> tuple[str | None, str | None]:
    """Fill a missing key or base URL from settings for the provider *model* names.

    An explicit ``api_key``/``api_base`` on the AgentModel always wins; providers whose
    key lives in the environment (``GEMINI_API_KEY``, …) are read by the client itself.
    """
    from tuvl import llm
    from tuvl.core.config import settings

    provider = llm.provider_of(model) if (not api_key or not api_base) else None
    if not api_key:
        if provider == "openai" and settings.openai_api_key:
            api_key = settings.openai_api_key
        elif provider == "anthropic" and settings.anthropic_api_key:
            api_key = settings.anthropic_api_key
    if not api_base and provider in ("ollama", "ollama_chat"):
        api_base = settings.ollama_base_url
    return api_key, api_base


def _register_agent_model_from_dict(data: dict[str, Any], filename: str = "<unknown>") -> None:
    """Register a single ``AgentModel`` document into :data:`AGENT_MODEL_REGISTRY`.

    Only the spec-wrapped envelope is accepted; disabled models are registered
    (so resolution can fail loudly) but flagged.
    """
    if data.get("kind") != "AgentModel":
        return

    spec = data.get("spec")
    if not isinstance(spec, dict):
        raise ValueError(
            f"AgentModel in '{filename}' has no 'spec' block — the root-level "
            f"form is not accepted. Wrap model/temperature/… under 'spec:'."
        )

    name = (data.get("metadata") or {}).get("name")
    if not name:
        raise ValueError(f"AgentModel in '{filename}' is missing metadata.name")

    if spec.get("type") == "decision":
        from pydantic import ValidationError

        from tuvl.contract.schema import DecisionModelSpec

        try:
            DecisionModelSpec.model_validate(
                {
                    k: spec[k]
                    for k in ("type", "provider", "model", "api_base", "api_key")
                    if k in spec
                }
            )
        except ValidationError as exc:
            raise ValueError(f"AgentModel '{name}' in '{filename}': {exc}") from exc
    elif spec.get("type") not in (None, "llm"):
        raise ValueError(
            f"AgentModel '{name}' in '{filename}': spec.type must be 'llm' or 'decision'"
        )

    flattened = {**data, **spec}
    if flattened.get("provider") == "litellm":  # the 2.0 betas' name for provider "llm"
        flattened["provider"] = "llm"
    AGENT_MODEL_REGISTRY[name] = flattened
    logger.info(
        "AgentModel loaded",
        name=name,
        model=flattened.get("model"),
        enabled=flattened.get("enabled", True),
    )


def resolve_call_params(cfg: dict[str, Any], step_id: str) -> tuple[str, int, dict[str, Any]]:
    """Return ``(model, timeout_secs, extra_acompletion_kwargs)``.

    If ``cfg["model"]`` contains no ``/``, it is treated as the *name* of a
    registered ``AgentModel``. Otherwise it is used directly as a
    ``provider/model`` string (e.g. ``ollama/llama3``).

    A named model that is disabled (``enabled: false``) raises — a disabled
    model must never silently fall back to another provider.
    """
    from tuvl.core.config import settings

    model_ref: str = (cfg.get("model") or "").removesuffix(".yaml").removesuffix(".yml")
    file_cfg: dict[str, Any] = {}

    if model_ref and "/" not in model_ref:
        entry = AGENT_MODEL_REGISTRY.get(model_ref)
        if entry is None:
            # No registered AgentModel by this name — the value is used as-is as
            # a bare model id (e.g. "gpt-4o"). llm_default_model only
            # applies when the ref is empty.
            logger.warning(
                "agent.config.not_found",
                step_id=step_id,
                model_ref=model_ref,
                used_as="model_string",
            )
        elif entry.get("enabled", True) is False:
            raise ValueError(f"AgentModel '{model_ref}' is disabled (enabled: false).")
        else:
            file_cfg = entry

    model: str = file_cfg.get("model") or model_ref or settings.llm_default_model

    extra: dict[str, Any] = {}
    api_base = expand_env(
        file_cfg.get("api_base") or cfg.get("api_base"),
        source=f"AgentModel '{model_ref or step_id}' api_base",
    )
    api_key = expand_env(
        file_cfg.get("api_key") or cfg.get("api_key"),
        source=f"AgentModel '{model_ref or step_id}' api_key",
    )

    # Credentials are per-call kwargs, never mutated into os.environ, so rotated or
    # per-model keys take effect immediately.
    api_key, api_base = default_credentials(model, api_key, api_base)

    temperature = file_cfg.get("temperature")
    max_tokens = file_cfg.get("max_tokens")
    if api_base:
        extra["api_base"] = api_base
    if api_key:
        extra["api_key"] = api_key
    if temperature is not None:
        extra["temperature"] = float(temperature)
    if max_tokens is not None:
        extra["max_tokens"] = int(max_tokens)

    timeout = int(cfg.get("timeout") or file_cfg.get("timeout") or 60)
    return model, timeout, extra
