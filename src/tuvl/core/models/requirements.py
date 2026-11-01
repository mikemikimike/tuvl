"""What the project's models need to run: which AgentModels the workflows use and which
environment variables those models read (validate V028/V029, boot check, ``/health``,
``tuvl ship``, ``tuvl check system``).

Everything here is static — no model is called.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from tuvl import llm
from tuvl.llm.routes import base_env_vars

#: The variable the model client reads for a provider when the AgentModel has no ``api_key``.
PROVIDER_KEY_ENV: dict[str, str] = {
    name: p.key_env for name, p in llm.PROVIDERS.items() if p.key_env
}
#: Providers that need no key (local servers).
KEYLESS_PROVIDERS = llm.KEYLESS

_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:[^}]*)?\}")


@dataclass
class ModelNeed:
    """One model the project uses, and what it needs from the environment."""

    name: str
    kind: str  # "llm" | "decision"
    model: str
    provider: str
    env: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    used_by: list[str] = field(default_factory=list)

    def missing(self, environ: Mapping[str, str] | None = None) -> list[str]:
        environ = os.environ if environ is None else environ
        return [v for v in self.env if not environ.get(v)]

    def to_json(self, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
        missing = self.missing(environ)
        return {
            "kind": self.kind,
            "model": self.model,
            "provider": self.provider,
            "env": self.env,
            "missing": missing,
            "configured": not missing and not self.problems,
            "problems": self.problems,
            "used_by": self.used_by,
        }


def _required_vars(value: Any) -> list[str]:
    """``${VAR}`` references without a default in *value*."""
    if not isinstance(value, str):
        return []
    return [m.group(1) for m in _REF.finditer(value) if m.group(2) is None]


def need_for(name: str, spec: Mapping[str, Any]) -> ModelNeed:
    """What the AgentModel *name* (its flattened ``spec``) needs to run."""
    kind = "decision" if spec.get("type") == "decision" else "llm"
    model = str(spec.get("model") or "")
    api_key, api_base = spec.get("api_key"), spec.get("api_base")
    if kind == "decision":
        provider = str(spec.get("provider") or "llm")
        if provider != "llm":
            need = ModelNeed(name, kind, model, provider)
            need.env = _required_vars(api_base) + _required_vars(api_key)
            return need
    provider = model.split("/", 1)[0] if "/" in model else "openai"
    need = ModelNeed(name, kind, model, provider)
    need.env += _required_vars(api_base)
    if api_key:
        if not _REF.search(str(api_key)):
            need.problems.append("api_key is a literal value — use an ${ENV_VAR} reference")
        need.env += _required_vars(api_key)
    elif provider in PROVIDER_KEY_ENV:
        need.env.append(PROVIDER_KEY_ENV[provider])
        if provider in llm.PROVIDERS and not api_base:
            need.env += base_env_vars(llm.PROVIDERS[provider])
            if llm.PROVIDERS[provider].base_required:
                need.problems.append(f"provider '{provider}' needs api_base")
    elif provider not in KEYLESS_PROVIDERS and not api_base:
        need.problems.append(
            f"no credentials: provider '{provider}' has no known key variable — "
            "set api_key: ${ENV_VAR} (and api_base if needed)"
        )
    need.env = list(dict.fromkeys(need.env))
    return need


def workflow_model_refs(workflows: Iterable[Any]) -> dict[str, list[str]]:
    """Model reference → ``workflow.agent`` users, over 2.0 workflow documents."""
    refs: dict[str, list[str]] = {}
    for doc in workflows:
        for agent in doc.spec.agents:
            ref = None
            if agent.engine == "llm":
                ref = agent.llm.model
            elif agent.engine == "loop":
                ref = agent.loop.model
            elif agent.engine == "decide" and agent.decide.model is not None:
                ref = agent.decide.model.ref
            if ref:
                refs.setdefault(str(ref), []).append(f"{doc.metadata.name}.{agent.id}")
    return refs


def project_needs(
    workflows: Iterable[Any], agent_models: Mapping[str, Mapping[str, Any]]
) -> tuple[list[ModelNeed], list[tuple[str, list[str]]]]:
    """(needs of every model the workflows use, unknown references with their users).

    A reference containing ``/`` is a direct ``provider/model`` id; a bare name must be an AgentModel.
    """
    needs: list[ModelNeed] = []
    unknown: list[tuple[str, list[str]]] = []
    for ref, users in sorted(workflow_model_refs(workflows).items()):
        if ref in agent_models:
            need = need_for(ref, agent_models[ref])
        elif "/" in ref:
            need = need_for(ref, {"model": ref})
        else:
            unknown.append((ref, users))
            continue
        need.used_by = users
        needs.append(need)
    return needs, unknown


class ModelConfigError(RuntimeError):
    """A production server refuses to start without its models' configuration."""


#: Boot-time view of every model the loaded workflows use (``/health``, Insight).
MODEL_STATUS: dict[str, dict[str, Any]] = {}


def check_at_boot(*, production: bool) -> None:
    """Check the loaded workflows' models against the environment (no model is called).

    Production refuses to start on an unknown model or a missing variable; development
    starts and records the gaps in :data:`MODEL_STATUS`.
    """
    from tuvl.contract.registry import WORKFLOWS
    from tuvl.core.logger import logger
    from tuvl.core.models.agent_models import AGENT_MODEL_REGISTRY

    needs, unknown = project_needs(WORKFLOWS.values(), AGENT_MODEL_REGISTRY)
    MODEL_STATUS.clear()
    problems: list[str] = []
    for ref, users in unknown:
        MODEL_STATUS[ref] = {
            "configured": False,
            "problems": ["unknown AgentModel"],
            "used_by": users,
        }
        problems.append(f"unknown AgentModel '{ref}' (used by {', '.join(users)})")
    for need in needs:
        MODEL_STATUS[need.name] = need.to_json()
        missing = need.missing()
        if missing:
            problems.append(
                f"model '{need.name}' needs {', '.join(missing)} (used by {', '.join(need.used_by)})"
            )
        problems += [f"model '{need.name}': {p}" for p in need.problems]
    if not problems:
        return
    if production:
        raise ModelConfigError("refusing to start — " + "; ".join(problems))
    for problem in problems:
        logger.warning("models.not_configured", detail=problem)
