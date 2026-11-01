"""Decision providers for ``decide.model`` (spec §10.3, §10.5).

A provider answers ``decide(request) → Decision``: one value from a closed
set of choices, with a confidence. It raises :class:`ProviderUnavailableError`
when it cannot answer (provider down, auth failure, missing local weights,
timeout, or an answer outside the choices) — the engine turns that into
``error / decision_model_unavailable`` and never falls back.

Built in: ``llm`` (enum-constrained structured output asking for the
decision and a confidence). A ``type: decision`` model's reported confidence
is trusted first, then token logprobs; an ``llm`` model's logprobs come first,
since self-reported LLM confidence is poorly calibrated. An answer with
neither is unavailable — never a silent 1.0.
``laya`` and ``jev`` speak the System One protocol (``POST /v1/systemone``) to
a server at the model's ``api_base`` — a laya-serve container or TypeSafe's
hosted Jev — and use the server's calibrated confidence. Other providers
register through the ``tuvl.decision_providers`` entry point group.

Every call updates a per-model status, which ``/health`` reports.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

ENTRY_POINT_GROUP = "tuvl.decision_providers"


@dataclass(frozen=True)
class DecisionRequest:
    model_ref: str
    #: The AgentModel entry (``provider``, ``model``, credentials …).
    config: Mapping[str, Any]
    inputs: Mapping[str, Any]
    choices: Sequence[str]
    description: str
    timeout: float | None = None


@dataclass(frozen=True)
class Decision:
    value: str
    confidence: float
    probabilities: dict[str, float] | None = None


class ProviderUnavailableError(Exception):
    """The decision model could not answer."""


Provider = Callable[[DecisionRequest], Awaitable[Decision]]
PROVIDERS: dict[str, Provider] = {}


@dataclass
class ModelStatus:
    provider: str
    model: str
    last_ok: str | None = None
    last_error: str | None = None
    error: str | None = None
    calls: int = 0


STATUS: dict[str, ModelStatus] = {}
#: Models whose provider rejected the ``logprobs`` parameter.
_NO_LOGPROBS: set[str] = set()


def register_provider(name: str, provider: Provider) -> None:
    PROVIDERS[name] = provider


def load_entry_point_providers() -> list[str]:
    """Register providers shipped by installed packages."""
    loaded: list[str] = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            register_provider(ep.name, ep.load())
            loaded.append(ep.name)
        except Exception as exc:  # a broken extra must not break boot
            logger.warning("decision.provider.load_failed", provider=ep.name, error=str(exc))
    return loaded


def resolve_model(ref: str) -> dict[str, Any]:
    """The AgentModel config for *ref*; an ``llm`` model decides through the built-in client."""
    from tuvl.core.models.agent_models import AGENT_MODEL_REGISTRY

    entry = AGENT_MODEL_REGISTRY.get(ref)
    if entry is None:
        raise ProviderUnavailableError(f"AgentModel '{ref}' is not defined")
    if entry.get("enabled", True) is False:
        raise ProviderUnavailableError(f"AgentModel '{ref}' is disabled")
    config = dict(entry)
    if config.get("type") != "decision":
        config["provider"] = "llm"
    return config


async def decide(request: DecisionRequest) -> Decision:
    provider_name = str(request.config.get("provider") or "llm")
    status = STATUS.setdefault(
        request.model_ref, ModelStatus(provider_name, str(request.config.get("model") or ""))
    )
    status.calls += 1
    now = _dt.datetime.now(_dt.UTC).isoformat()
    provider = PROVIDERS.get(provider_name)
    try:
        if provider is None:
            raise ProviderUnavailableError(
                f"decision provider '{provider_name}' is not installed (register it through "
                f"the {ENTRY_POINT_GROUP} entry point)"
            )
        decision = await provider(request)
        if decision.value not in request.choices:
            raise ProviderUnavailableError(
                f"answered {decision.value!r}, not one of {list(request.choices)}"
            )
    except ProviderUnavailableError as exc:
        status.last_error, status.error = now, str(exc)
        raise
    status.last_ok, status.error = now, None
    return decision


def health() -> dict[str, Any]:
    """Configured decision models and what their last call observed."""
    from tuvl.core.models.agent_models import AGENT_MODEL_REGISTRY

    out: dict[str, Any] = {}
    for name, entry in AGENT_MODEL_REGISTRY.items():
        if entry.get("type") != "decision":
            continue
        provider = str(entry.get("provider") or "")
        status = STATUS.get(name)
        out[name] = {
            "provider": provider,
            "model": entry.get("model"),
            "installed": provider in PROVIDERS,
            "last_ok": status.last_ok if status else None,
            "last_error": status.last_error if status else None,
            "error": status.error if status else None,
        }
    return out


# ── llm adapter ──────────────────────────────────────────────────────────


def _value_confidence(content: str, value: str, logprobs: Any) -> float | None:
    """exp(sum of the logprobs of the tokens that spell *value* in *content*)."""
    tokens = getattr(logprobs, "content", None) if logprobs is not None else None
    if not tokens:
        return None
    start = content.find(json.dumps(value)[1:-1])
    if start < 0:
        return None
    end = start + len(value)
    total, pos = 0.0, 0
    for tok in tokens:
        text = getattr(tok, "token", None) if not isinstance(tok, dict) else tok.get("token")
        lp = getattr(tok, "logprob", None) if not isinstance(tok, dict) else tok.get("logprob")
        if text is None or lp is None:
            return None
        if pos < end and pos + len(text) > start:
            total += float(lp)
        pos += len(text)
    return math.exp(total)


async def llm_provider(request: DecisionRequest) -> Decision:
    from tuvl import llm
    from tuvl.core.models.agent_models import resolve_call_params

    try:
        model, _timeout, extra = resolve_call_params(
            {"model": request.model_ref}, request.model_ref
        )
    except (ValueError, OSError) as exc:
        raise ProviderUnavailableError(str(exc)) from exc
    if request.config.get("type") == "decision" and request.config.get("model"):
        model = str(request.config["model"])
    schema = {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": list(request.choices)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["decision", "confidence"],
        "additionalProperties": False,
    }
    messages = [
        {
            "role": "system",
            "content": (
                f"{request.description}\nChoose exactly one of: {', '.join(request.choices)}. "
                'Answer with a JSON object {"decision": "<choice>", "confidence": <0..1>} '
                "and nothing else."
            ),
        },
        {
            "role": "user",
            "content": "## Input\n" + json.dumps(dict(request.inputs), default=str, indent=2),
        },
    ]
    response_format = {"type": "json_schema", "json_schema": {"name": "decision", "schema": schema}}

    async def call(logprobs: bool) -> Any:
        kwargs: dict[str, Any] = {"logprobs": True} if logprobs else {}
        return await llm.acompletion(
            model=model,
            messages=messages,
            response_format=response_format,
            timeout=request.timeout,
            **kwargs,
            **extra,
        )

    try:
        try:
            response = await call(model not in _NO_LOGPROBS)
        except llm.BadRequestError as exc:
            if "logprob" not in str(exc).lower() or model in _NO_LOGPROBS:
                raise
            _NO_LOGPROBS.add(model)  # some models reject the parameter outright
            response = await call(False)
        content = response.choices[0].message.content or ""
        answer = json.loads(content.strip().strip("`").removeprefix("json"))
        if not isinstance(answer, dict):
            raise ValueError(f"expected a JSON object, got {type(answer).__name__}")
        value = str(answer["decision"])
    except Exception as exc:
        raise ProviderUnavailableError(
            f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}"
        ) from exc
    reported = _reported_confidence(answer.get("confidence"))
    from_logprobs = _value_confidence(
        content, value, getattr(response.choices[0], "logprobs", None)
    )
    if request.config.get("type") == "decision":
        confidence = reported if reported is not None else from_logprobs
    else:
        confidence = from_logprobs if from_logprobs is not None else reported
    if confidence is None:
        raise ProviderUnavailableError(
            f"{model} answered {value!r} with no confidence (no logprobs, no confidence field)"
        )
    return Decision(value=value, confidence=confidence)


def _reported_confidence(raw: Any) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    value = float(raw)
    return value if math.isfinite(value) and 0.0 <= value <= 1.0 else None


register_provider("llm", llm_provider)


# ── System One adapter (laya-serve, Jev) ─────────────────────────────────────


async def systemone_provider(request: DecisionRequest) -> Decision:
    import httpx

    from tuvl.core.engine.templating import expand_env

    config = request.config
    source = f"AgentModel '{request.model_ref}'"
    try:
        base = expand_env(config.get("api_base"), source=f"{source} api_base")
        key = expand_env(config.get("api_key"), source=f"{source} api_key")
    except OSError as exc:
        raise ProviderUnavailableError(str(exc)) from exc
    if not base:
        raise ProviderUnavailableError(f"{source} has no api_base")
    body: dict[str, Any] = {
        "state": dict(request.inputs),
        "questions": {
            "decision": {
                "type": "choice",
                "instructions": request.description,
                "criteria": {choice: choice for choice in request.choices},
            }
        },
    }
    model = str(config.get("model") or "")
    if model and model != "auto":
        body["model"] = model
    headers = {"authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=request.timeout) as client:
            response = await client.post(
                base.rstrip("/") + "/v1/systemone", json=body, headers=headers
            )
        response.raise_for_status()
        answer = response.json()["answers"]["decision"]
        value = str(answer["choice"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        detail = exc.response.text[:300] if isinstance(exc, httpx.HTTPStatusError) else str(exc)
        raise ProviderUnavailableError(f"{type(exc).__name__}: {' '.join(detail.split())}") from exc
    # laya-serve's answer_confidence is the calibrated probability of the choice; the strict
    # Jev contract carries only `confidence`.
    confidence = _reported_confidence(answer.get("answer_confidence"))
    if confidence is None:
        confidence = _reported_confidence(answer.get("confidence"))
    if confidence is None:
        raise ProviderUnavailableError(f"{request.model_ref} answered {value!r} with no confidence")
    probabilities = answer.get("probabilities")
    return Decision(
        value=value,
        confidence=confidence,
        probabilities=(
            {str(k): float(v) for k, v in probabilities.items()}
            if isinstance(probabilities, dict)
            else None
        ),
    )


register_provider("laya", systemone_provider)
register_provider("jev", systemone_provider)
