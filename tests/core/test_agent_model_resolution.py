"""resolve_call_params — AgentModel name resolution + enabled enforcement (TD-7)
and per-call credential resolution (TD-10).

A disabled AgentModel must raise on the engine execution path, never silently
fall back to another provider; an unknown name falls back to llm_default_model.

TD-10: provider credentials must be returned as per-call ``extra`` kwargs
(passed straight through to ``tuvl.llm.acompletion``) rather than mutated into
``os.environ`` — a process-global first-write-wins side effect that would
otherwise let a stale/rotated key silently win over a per-model one.
"""

from __future__ import annotations

import os

import pytest

from tuvl.core.models import agent_models
from tuvl.core.models.agent_models import resolve_call_params


def _register(monkeypatch, registry: dict) -> None:
    monkeypatch.setattr(agent_models, "AGENT_MODEL_REGISTRY", registry)


def test_disabled_named_model_raises(monkeypatch):
    _register(monkeypatch, {"gpt4": {"model": "openai/gpt-4o", "enabled": False}})
    with pytest.raises(ValueError, match="disabled"):
        resolve_call_params({"model": "gpt4"}, "step1")


def test_enabled_named_model_resolves(monkeypatch):
    _register(monkeypatch, {"gpt4": {"model": "openai/gpt-4o", "enabled": True}})
    model, _timeout, _extra = resolve_call_params({"model": "gpt4"}, "step1")
    assert model == "openai/gpt-4o"


def test_unknown_name_is_used_as_model_string(monkeypatch):
    # A bare unregistered name (e.g. "gpt-4o") is passed through to the client
    # as-is — NOT swapped for llm_default_model (which the log used to claim).
    _register(monkeypatch, {})
    model, _timeout, _extra = resolve_call_params({"model": "gpt-4o"}, "step1")
    assert model == "gpt-4o"


def test_empty_model_falls_back_to_default(monkeypatch):
    from tuvl.core.config import settings

    _register(monkeypatch, {})
    model, _timeout, _extra = resolve_call_params({"model": ""}, "step1")
    assert model == settings.llm_default_model


def test_direct_model_string_passes_through(monkeypatch):
    _register(monkeypatch, {})
    model, _timeout, _extra = resolve_call_params({"model": "ollama/llama3"}, "step1")
    assert model == "ollama/llama3"


# ── TD-10: credentials via `extra` kwargs, not os.environ mutation ───────────


def test_openai_key_returned_in_extra_and_env_not_mutated(monkeypatch):
    from tuvl.core.config import settings

    _register(monkeypatch, {})
    monkeypatch.setattr(settings, "openai_api_key", "sk-configured-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    _model, _timeout, extra = resolve_call_params({"model": "gpt-4o"}, "step1")

    assert extra["api_key"] == "sk-configured-key"
    assert "OPENAI_API_KEY" not in os.environ


def test_anthropic_key_returned_in_extra_and_env_not_mutated(monkeypatch):
    from tuvl.core.config import settings

    _register(monkeypatch, {})
    monkeypatch.setattr(settings, "anthropic_api_key", "anthropic-configured-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    _model, _timeout, extra = resolve_call_params({"model": "anthropic/claude-3-opus"}, "step1")

    assert extra["api_key"] == "anthropic-configured-key"
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_ollama_base_returned_in_extra_and_env_not_mutated(monkeypatch):
    from tuvl.core.config import settings

    _register(monkeypatch, {})
    monkeypatch.setattr(settings, "ollama_base_url", "http://configured-ollama:11434")
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)

    _model, _timeout, extra = resolve_call_params({"model": "ollama/llama3"}, "step1")

    assert extra["api_base"] == "http://configured-ollama:11434"
    assert "OLLAMA_API_BASE" not in os.environ


def test_per_model_api_key_overrides_settings_default(monkeypatch):
    """A rotated/per-model key set on the AgentModel/step config must win over
    the process-wide settings default — the exact case the old
    os.environ.setdefault() approach got wrong (first write always won)."""
    from tuvl.core.config import settings

    _register(
        monkeypatch,
        {"gpt4": {"model": "openai/gpt-4o", "enabled": True, "api_key": "sk-per-model-key"}},
    )
    monkeypatch.setattr(settings, "openai_api_key", "sk-global-default-key")

    _model, _timeout, extra = resolve_call_params({"model": "gpt4"}, "step1")

    assert extra["api_key"] == "sk-per-model-key"


def test_unknown_provider_model_does_not_raise_and_omits_api_key(monkeypatch):
    from tuvl.core.config import settings

    _register(monkeypatch, {})
    monkeypatch.setattr(settings, "openai_api_key", "sk-should-not-be-used")

    _model, _timeout, extra = resolve_call_params({"model": "some/totally-unknown-model"}, "step1")

    assert "api_key" not in extra
