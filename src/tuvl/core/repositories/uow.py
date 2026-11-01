"""Unit of Work scoped to a single workflow execution.

Restricts repository access to models declared in the workflow's ``context:`` field,
and routes each model to the correct datasource session.
"""

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from tuvl.core.repositories.base import BaseRepository


class WorkflowUoW:
    """Unit of Work that gates repository access to the models declared in the workflow's context."""

    def __init__(
        self,
        primary_session: AsyncSession,
        allowed_models: set[str],
        is_write: bool = True,
        model_version_map: dict[str, str] | None = None,
    ) -> None:
        self._primary = primary_session
        self._allowed: frozenset[str] = frozenset(m.lower() for m in allowed_models)
        self._is_write = is_write
        # Maps model name → target schema version (e.g. {"Candidate": "v2"}).
        # Populated from context.models[].version in the workflow YAML.
        # Available to functional nodes via context["_context_model_versions"].
        self._model_version_map: dict[str, str] = model_version_map or {}
        self._secondary_sessions: dict[str, AsyncSession] = {}
        self._repos: dict[str, BaseRepository[Any]] = {}

    def __getitem__(self, model_name: str) -> BaseRepository[Any]:
        """
        Return the repository for *model_name*, routing to the correct
        datasource session.

        Raises
        ------
        PermissionError
            When *model_name* is not in this workflow's ``context:`` list.
        RuntimeError
            When the workflow pinned a specific ``version`` for this model
            (via ``context.models[].version``) but the version registered in
            ``MODEL_REGISTRY`` does not match the pin.  This prevents silent
            cross-version data corruption when multiple ModelDefinition
            files declare different shapes of the same name.
        """
        key = model_name.lower()
        if key not in self._allowed:
            allowed_display = sorted(self._allowed) if self._allowed else ["(none declared)"]
            raise PermissionError(
                f"Model '{model_name}' is not declared in this workflow's context. "
                f"Allowed models: {allowed_display}. "
                f"Add it to the 'context:' field in the workflow YAML."
            )
        if key not in self._repos:
            canonical = _resolve_canonical(key)
            # Cross-version pin enforcement.  ``_model_version_map`` is keyed
            # by the original (case-preserving) model name, so look up both
            # the canonical form and the supplied form.
            pinned = self._model_version_map.get(canonical) or self._model_version_map.get(
                model_name
            )
            if pinned:
                from tuvl.core.models.loader import MODEL_REGISTRY

                loaded_cls = MODEL_REGISTRY.get(canonical)
                loaded_version = (
                    getattr(loaded_cls, "__schema_version__", None) if loaded_cls else None
                )
                if loaded_version != pinned:
                    raise RuntimeError(
                        f"Workflow pinned model '{canonical}' to version "
                        f"{pinned!r} but MODEL_REGISTRY holds version "
                        f"{loaded_version!r}. Refusing to execute against a "
                        f"mismatched schema. Enable the requested version's "
                        f"ModelDefinition file or update the workflow's "
                        f"``context.models[].version`` pin."
                    )
            session = self._session_for(canonical)
            self._repos[key] = BaseRepository(canonical, session)
        return self._repos[key]

    async def commit_secondary(self) -> None:
        """Commit and close all non-primary datasource sessions.

        Every secondary session is closed even if an earlier one's commit
        raises — otherwise the remaining sessions are neither committed,
        rolled back, nor closed, leaking pooled connections. The first
        exception encountered is re-raised once every session is closed.
        """
        first_exc: Exception | None = None
        for _ds_name, session in list(self._secondary_sessions.items()):
            try:
                await session.commit()
            except Exception as exc:
                if first_exc is None:
                    first_exc = exc
            finally:
                await session.close()
        self._secondary_sessions.clear()
        if first_exc is not None:
            raise first_exc

    async def rollback_secondary(self) -> None:
        """Roll back and close all non-primary datasource sessions."""
        for _ds_name, session in list(self._secondary_sessions.items()):
            try:
                await session.rollback()
            finally:
                await session.close()
        self._secondary_sessions.clear()

    @property
    def allowed_models(self) -> frozenset[str]:
        """Lowercase names of models this workflow may access."""
        return self._allowed

    @property
    def model_version_map(self) -> dict[str, str]:
        """Maps model name → target schema version from ``context.models``."""
        return self._model_version_map

    def __repr__(self) -> str:  # pragma: no cover
        return f"WorkflowUoW(allowed={sorted(self._allowed)}, is_write={self._is_write})"

    def _session_for(self, canonical_name: str) -> AsyncSession:
        """
        Return (or lazily open) the session that owns *canonical_name*.

        Models belonging to the primary datasource reuse the FastAPI-injected
        session.  Models on other datasources get their own session opened
        from the matching engine pool.
        """
        from tuvl.core.datasources.postgres import primary_ds_name
        from tuvl.core.models.loader import MODEL_DATASOURCE_MAP

        primary = primary_ds_name()
        ds_name = MODEL_DATASOURCE_MAP.get(canonical_name, primary)

        if ds_name == primary:
            return self._primary

        if ds_name not in self._secondary_sessions:
            from tuvl.core.datasources.postgres import (
                _bind_tenant_isolation,
                get_session_factory,
            )

            factory = get_session_factory(ds_name, self._is_write)
            # Open the session without a context manager so we control
            # its lifetime explicitly via commit_secondary / rollback_secondary.
            session = factory()
            # Secondary sessions must enforce the same tenant isolation as the
            # primary. Without this, a model routed to a non-primary datasource
            # runs with no tenant GUC — fail-closed (no rows) where RLS exists,
            # or a cross-tenant leak where it was never applied. No-op in
            # single-tenant mode.
            _bind_tenant_isolation(session)
            self._secondary_sessions[ds_name] = session

        return self._secondary_sessions[ds_name]


def _resolve_canonical(lowercase_name: str) -> str:
    """
    Return the correctly-cased name as registered in ``MODEL_REGISTRY``.
    Falls through with the original value so ``BaseRepository`` can surface
    a clear "not found" error.
    """
    from tuvl.core.models.loader import MODEL_REGISTRY

    for registered in MODEL_REGISTRY:
        if registered.lower() == lowercase_name:
            return registered
    return lowercase_name
