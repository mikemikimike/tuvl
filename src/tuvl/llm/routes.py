"""Which endpoint and wire format a ``provider/model`` id uses."""

from __future__ import annotations

import os
from dataclasses import dataclass

from tuvl.llm.errors import ConfigurationError, UnsupportedProviderError


@dataclass(frozen=True)
class Provider:
    name: str
    wire: str  # "openai" | "anthropic"
    base_url: str
    key_env: str = ""
    #: ``max_completion_tokens`` instead of ``max_tokens`` (OpenAI's own API).
    completion_tokens_param: bool = False
    #: Gemini's OpenAI endpoint rejects ``additionalProperties`` in schemas.
    strict_schema: bool = True
    #: Local servers serve the OpenAI API under ``/v1`` of their root URL.
    v1_suffix: bool = False
    #: Cohere takes ``{"type": "json_object", "schema": …}`` for structured output.
    json_object_schema: bool = False
    #: The embeddings field for the output size; ``None`` when the API has none.
    dimensions_param: str | None = "dimensions"
    embeddings_only: bool = False
    #: An endpoint built from the environment when no ``api_base`` is given:
    #: ``{NAME}`` placeholders read the variables of ``base_env`` (``NAME=VAR1|VAR2``,
    #: ``NAME=VAR1|VAR2|default``) and ``base_url`` is the template.
    base_env: tuple[tuple[str, tuple[str, ...], str | None], ...] = ()
    #: No default endpoint: the AgentModel must set ``api_base`` (a gateway or proxy).
    base_required: bool = False


_PROVIDERS: tuple[Provider, ...] = (
    Provider("openai", "openai", "https://api.openai.com/v1", "OPENAI_API_KEY", True),
    Provider("anthropic", "anthropic", "https://api.anthropic.com", "ANTHROPIC_API_KEY"),
    Provider(
        "gemini",
        "openai",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        strict_schema=False,
    ),
    Provider("groq", "openai", "https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    Provider("mistral", "openai", "https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    Provider("deepseek", "openai", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    Provider("xai", "openai", "https://api.x.ai/v1", "XAI_API_KEY"),
    Provider("openrouter", "openai", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    Provider("together_ai", "openai", "https://api.together.xyz/v1", "TOGETHERAI_API_KEY"),
    Provider(
        "fireworks_ai", "openai", "https://api.fireworks.ai/inference/v1", "FIREWORKS_AI_API_KEY"
    ),
    Provider("perplexity", "openai", "https://api.perplexity.ai", "PERPLEXITYAI_API_KEY"),
    Provider(
        "cohere",
        "openai",
        "https://api.cohere.ai/compatibility/v1",
        "COHERE_API_KEY",
        json_object_schema=True,
        dimensions_param=None,
    ),
    Provider(
        "voyage",
        "openai",
        "https://api.voyageai.com/v1",
        "VOYAGE_API_KEY",
        dimensions_param="output_dimension",
        embeddings_only=True,
    ),
    Provider(
        "azure",
        "openai",
        "{endpoint}/openai/v1",
        "AZURE_OPENAI_API_KEY",
        True,
        base_env=(("endpoint", ("AZURE_OPENAI_ENDPOINT",), None),),
    ),
    Provider(
        "bedrock",
        "openai",
        "https://bedrock-runtime.{region}.amazonaws.com/openai/v1",
        "AWS_BEARER_TOKEN_BEDROCK",
        base_env=(("region", ("AWS_REGION", "AWS_DEFAULT_REGION"), None),),
    ),
    Provider(
        "vertex_ai",
        "openai",
        "https://{host}/v1beta1/projects/{project}/locations/{location}/endpoints/openapi",
        "VERTEX_ACCESS_TOKEN",
        base_env=(
            ("project", ("GOOGLE_CLOUD_PROJECT",), None),
            ("location", ("GOOGLE_CLOUD_LOCATION",), "us-central1"),
        ),
    ),
    Provider("litellm_proxy", "openai", "", "LITELLM_API_KEY", base_required=True),
    Provider("ollama", "openai", "http://localhost:11434", v1_suffix=True),
    Provider("ollama_chat", "openai", "http://localhost:11434", v1_suffix=True),
    Provider("lm_studio", "openai", "http://localhost:1234/v1"),
    Provider("vllm", "openai", "http://localhost:8000/v1"),
    Provider("hosted_vllm", "openai", "http://localhost:8000/v1"),
)
PROVIDERS: dict[str, Provider] = {p.name: p for p in _PROVIDERS}

#: Providers with their own wire format and no adapter here; reach them through a
#: gateway that speaks the OpenAI API (``openai/<model>`` plus ``api_base``).
_GATEWAY_ONLY = frozenset({"sagemaker", "watsonx", "huggingface", "replicate"})

#: Providers that need no key (local servers).
KEYLESS = frozenset({"ollama", "ollama_chat", "lm_studio", "vllm", "hosted_vllm"})


def split_model(model: str) -> tuple[str, str]:
    """``("openai", "gpt-4o")`` for ``"openai/gpt-4o"``; a bare id is an OpenAI model."""
    head, sep, rest = model.partition("/")
    if sep and head:
        return head, rest
    return "openai", model


def provider_of(model: str) -> str | None:
    """The provider id of *model*, ``None`` when no adapter knows it."""
    head, _ = split_model(model)
    return head if head in PROVIDERS else None


@dataclass(frozen=True)
class Route:
    provider: Provider
    model: str  # the id sent on the wire
    base_url: str
    api_key: str | None


def _first_env(names: tuple[str, ...]) -> str | None:
    return next((v for n in names if (v := os.environ.get(n))), None)


def base_env_vars(provider: Provider) -> list[str]:
    """The variables an endpoint built from the environment needs (without a default)."""
    return [names[0] for _, names, default in provider.base_env if default is None]


def _base_url(provider: Provider) -> str:
    if provider.base_required:
        raise ConfigurationError(f"{provider.name}: set api_base on the AgentModel")
    if not provider.base_env:
        return provider.base_url
    values: dict[str, str] = {}
    for key, names, default in provider.base_env:
        value = _first_env(names) or default
        if not value:
            raise ConfigurationError(
                f"{provider.name}: set {' or '.join(names)} (or api_base on the AgentModel)"
            )
        values[key] = value
    if provider.name == "vertex_ai":
        loc = values["location"]
        values["host"] = (
            "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
        )
    if provider.name == "azure":
        values["endpoint"] = (
            values["endpoint"].rstrip("/").removesuffix("/openai/v1").removesuffix("/openai")
        )
    return provider.base_url.format(**values)


def resolve(model: str, api_base: str | None, api_key: str | None) -> Route:
    head, rest = split_model(model)
    provider = PROVIDERS.get(head)
    if provider is None:
        if head in _GATEWAY_ONLY:
            raise UnsupportedProviderError(
                f"'{head}' has no built-in adapter — point an OpenAI-compatible gateway at it "
                f"and use 'openai/<model>' with api_base"
            )
        if not api_base:
            raise UnsupportedProviderError(
                f"unknown provider '{head}' (built in: {', '.join(sorted(PROVIDERS))}); "
                "for another OpenAI-compatible endpoint set api_base"
            )
        provider = Provider(head, "openai", api_base)
    base = (api_base or _base_url(provider)).rstrip("/")
    if provider.v1_suffix and not base.endswith("/v1"):
        base += "/v1"
    if provider.name == "azure" and "/openai" not in base:
        base += "/openai/v1"  # a bare resource URL, as the older docs showed
    key = api_key or (os.environ.get(provider.key_env) if provider.key_env else None)
    return Route(provider, rest, base, key)
