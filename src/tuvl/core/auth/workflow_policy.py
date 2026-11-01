"""Workflow trigger auth policy — the single source of truth for who may call a trigger.

Shared by the REST mount (``manager._build_route_deps``), the versioned run
route, the system manifest, and the CLI validator, so the enforcement sites
can never drift. Deliberately free of FastAPI/key-manager
imports so the CLI can import it without the auth stack.

Production default: every trigger route requires a valid bearer token, even
when the workflow declares no ``required_scope``/``required_group``. Anonymous
access is an explicit opt-in via ``spec.trigger.public: true``. In dev mode
(``tuvl dev``), workflows without a scope/group requirement stay tokenless —
same trust envelope as the dev-key superuser shortcut, and boot-blocked in
production by the dev-mode sentinel.
"""

from __future__ import annotations

from dataclasses import dataclass

TRIGGER_PUBLIC_KEY = "public"


@dataclass(frozen=True)
class WorkflowAuthPolicy:
    public: bool
    required_scope: str | None
    required_group: str | None

    def anonymous_ok(self) -> bool:
        """True when the trigger may be served without a bearer token.

        A declared scope/group always wins — even against a (validator-rejected)
        ``public: true`` — so a contradictory config fails closed.
        """
        if self.required_scope or self.required_group:
            return False
        if self.public:
            return True
        from tuvl.core.config import settings

        return settings.tuvl_dev_mode
