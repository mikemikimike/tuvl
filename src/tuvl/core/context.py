"""Per-request async context variables.

This module is intentionally dependency-free so it can be imported by any
module in the call chain without risk of circular imports.
"""

from __future__ import annotations

from contextvars import ContextVar

# Multi-tenancy: identifies the active tenant for the current async task.
# Set by middleware or FastAPI dependencies in multi-tenant deployments.
# Consumed by the PostgreSQL checkout listener and the structlog processor.
current_tenant_id: ContextVar[str] = ContextVar("current_tenant_id", default="")

# Identity of the authenticated principal for the current async task.
# Set by ``tuvl.core.auth.access.get_current_user`` once an HTTP
# request has been authenticated, and consumed by:
#   * the structlog processor (adds ``user_id`` to every log line),
#   * the engine runner (adds ``tuvl.user.id`` to every OTel span),
#   * the workflow context builder (sets ``_user_id`` on the initial
#     context dict so node implementations and HITL records have access
#     to the caller identity).
# Empty string when the request is unauthenticated.
current_user_id: ContextVar[str] = ContextVar("current_user_id", default="")
