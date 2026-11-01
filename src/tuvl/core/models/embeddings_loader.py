"""Registry for embedding model configurations.

Reads ``EmbeddingRegistry`` YAML files from the models directory and
populates :data:`EMBEDDING_REGISTRY`.

**Multi-entry format** (``EmbeddingRegistry``) — list all embeddings in one file::

    kind: EmbeddingRegistry
    version: v1
    metadata:
      name: default
    spec:
      embeddings:
        - name: text-embedding-3-small
          provider: openai
          model: openai/text-embedding-3-small
          dimensions: 1536
        - name: gateway-embed          # api_base / api_key are optional
          model: openai/embed-alias
          api_base: ${LLM_GATEWAY_URL}
          api_key: ${LLM_GATEWAY_KEY}
          dimensions: 1024
        - name: nomic-embed
          provider: ollama
          model: ollama/nomic-embed-text
          dimensions: 768

**Single-entry format** (``EmbeddingConfig``) — one embedding per file::

    kind: EmbeddingConfig
    version: v1
    metadata:
      name: text-embedding-3-small
    spec:
      provider: openai
      model: openai/text-embedding-3-small
      dimensions: 1536
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# name → {name, provider, model, dimensions[, api_base, api_key]}
EMBEDDING_REGISTRY: dict[str, dict[str, Any]] = {}


def _endpoint(spec: dict[str, Any]) -> dict[str, Any]:
    """``api_base`` / ``api_key`` (an ``${ENV_VAR}`` reference) when the entry sets them."""
    return {k: spec[k] for k in ("api_base", "api_key") if spec.get(k)}


def _register_embedding_from_dict(data: dict[str, Any], filename: str = "<unknown>") -> None:
    """Register all entries from a parsed ``EmbeddingRegistry`` (or ``EmbeddingConfig``) dict."""
    kind = data.get("kind")
    if kind not in ("EmbeddingRegistry", "EmbeddingConfig"):
        return

    # EmbeddingConfig: single-entry format
    if kind == "EmbeddingConfig":
        name = data.get("metadata", {}).get("name") or data.get("name")
        spec = data.get("spec", data)
        if not name:
            logger.warning("embedding.config.missing_name", file=filename)
            return
        EMBEDDING_REGISTRY[name] = {
            "name": name,
            "provider": spec.get("provider", ""),
            "model": spec.get("model", ""),
            "dimensions": int(spec.get("dimensions", 1536)),
            **_endpoint(spec),
        }
        logger.info(
            "embedding.loaded",
            name=name,
            model=spec.get("model"),
            dimensions=spec.get("dimensions"),
        )
        return

    # EmbeddingRegistry: multi-entry format
    items = (data.get("spec") or {}).get("embeddings") or []
    for entry in items:
        name = entry.get("name")
        if not name:
            logger.warning("embedding.registry.entry_missing_name")
            continue
        EMBEDDING_REGISTRY[name] = {
            "name": name,
            "provider": entry.get("provider", ""),
            "model": entry.get("model", ""),
            "dimensions": int(entry.get("dimensions", 1536)),
            **_endpoint(entry),
        }
        logger.info(
            "embedding.loaded",
            name=name,
            model=entry.get("model"),
            dimensions=entry.get("dimensions"),
        )
