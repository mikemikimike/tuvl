"""Registry for vector collection configurations.

Reads ``CollectionRegistry`` YAML files from the models directory and
populates :data:`COLLECTION_REGISTRY`.

**Multi-entry format** (``CollectionRegistry``) — list all collections in one file::

    kind: CollectionRegistry
    version: v1
    metadata:
      name: default
    spec:
      collections:
        - name: knowledge-base
          description: General knowledge base
          embedding: text-embedding-3-small   # must match EMBEDDING_REGISTRY
        - name: internal-docs
          description: Internal documentation (uses global default embedding)

**Single-entry format** (``CollectionConfig``) — one collection per file::

    kind: CollectionConfig
    version: v1
    metadata:
      name: knowledge-base
    spec:
      description: General knowledge base
      embedding: text-embedding-3-small

Collections omitting ``embedding`` fall back to the global
``TUVL_DEFAULT_EMBEDDING`` / ``TUVL_DEFAULT_EMBEDDING_DIMENSIONS`` settings.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# name → {name, description, embedding}
COLLECTION_REGISTRY: dict[str, dict[str, Any]] = {}


def _register_collection_from_dict(data: dict[str, Any], filename: str = "<unknown>") -> None:
    """Register entries from a ``CollectionRegistry`` or ``CollectionConfig`` dict."""
    kind = data.get("kind")
    if kind not in ("CollectionRegistry", "CollectionConfig"):
        return

    if kind == "CollectionConfig":
        # Single-entry format (individual file)
        name = data.get("metadata", {}).get("name") or data.get("name")
        spec = data.get("spec", data)
        if not name:
            logger.warning("collection.config.missing_name", file=filename)
            return
        COLLECTION_REGISTRY[name] = {
            "name": name,
            "description": spec.get("description", ""),
            "embedding": spec.get("embedding"),
            "datasource": spec.get("datasource"),
        }
        logger.info(
            "collection.loaded",
            name=name,
            embedding=spec.get("embedding") or "global default",
        )
        return

    # CollectionRegistry: multi-entry format
    items = (data.get("spec") or {}).get("collections") or []
    for entry in items:
        name = entry.get("name")
        if not name:
            logger.warning("collection.registry.entry_missing_name")
            continue
        COLLECTION_REGISTRY[name] = {
            "name": name,
            "description": entry.get("description", ""),
            "embedding": entry.get("embedding"),
            "datasource": entry.get("datasource"),
        }
        logger.info(
            "collection.loaded",
            name=name,
            embedding=entry.get("embedding") or "global default",
        )


def _validate_collection_dimensions() -> None:
    """Warn when a collection's embedding dimension != the vector-store column.

    The shared ``tuvl_system_vector_store.embedding`` column is sized once to
    ``settings.tuvl_default_embedding_dimensions``. A collection bound to an
    embedding of a different dimension would otherwise only fail at insert time
    with an opaque pgvector mismatch — surface it at load instead.
    """
    from tuvl.core.config import settings
    from tuvl.core.models.embeddings_loader import EMBEDDING_REGISTRY

    store_dim = settings.tuvl_default_embedding_dimensions
    for name, coll in COLLECTION_REGISTRY.items():
        emb_name = coll.get("embedding")
        if not emb_name:
            continue  # falls back to the global default → matches by construction
        emb = EMBEDDING_REGISTRY.get(emb_name)
        if emb is None:
            continue  # an unknown embedding reference is reported elsewhere
        emb_dim = emb.get("dimensions")
        if emb_dim is not None and int(emb_dim) != int(store_dim):
            logger.warning(
                "collections.dimension_mismatch",
                collection=name,
                embedding=emb_name,
                embedding_dimensions=emb_dim,
                vector_store_dimensions=store_dim,
                consequence="inserts into this collection will fail with a pgvector "
                "dimension mismatch; align the dimensions or set "
                "tuvl_default_embedding_dimensions",
            )


def resolve_embedding_for_collection(collection_name: str) -> dict[str, Any]:
    """Return the resolved embedding config dict for *collection_name*.

    Resolution order:

    1. ``collection.embedding`` key → :data:`EMBEDDING_REGISTRY` lookup.
    2. Global default from ``settings.tuvl_default_embedding`` /
       ``settings.tuvl_default_embedding_dimensions``.

    Raises
    ------
    ValueError
        When *collection_name* is not in :data:`COLLECTION_REGISTRY`.
    ValueError
        When the collection references an embedding not in
        :data:`EMBEDDING_REGISTRY`.
    """
    if collection_name not in COLLECTION_REGISTRY:
        registered = list(COLLECTION_REGISTRY.keys()) or ["(none)"]
        raise ValueError(
            f"Collection '{collection_name}' is not registered. "
            f"Registered collections: {registered}. "
            "Define it in models/collections.yaml."
        )

    col = COLLECTION_REGISTRY[collection_name]
    embedding_name = col.get("embedding")

    if embedding_name:
        from tuvl.core.models.embeddings_loader import EMBEDDING_REGISTRY

        if embedding_name not in EMBEDDING_REGISTRY:
            raise ValueError(
                f"Collection '{collection_name}' references unknown embedding "
                f"'{embedding_name}'. Registered embeddings: "
                f"{list(EMBEDDING_REGISTRY.keys())}."
            )
        return EMBEDDING_REGISTRY[embedding_name]

    # Fall back to global defaults
    from tuvl.core.config import settings

    return {
        "name": "__default__",
        "model": settings.tuvl_default_embedding,
        "dimensions": settings.tuvl_default_embedding_dimensions,
    }
