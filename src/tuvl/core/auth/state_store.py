"""OAuth 2.0 CSRF state token store.

Provides an abstraction that uses Redis (when a ``type: redis`` datasource is
configured and reachable) or an in-process dict fallback.

**Scaling requirement** — in multi-worker / multi-process deployments you
*must* configure a Redis datasource so that OAuth state tokens minted by one
worker are visible to the worker that handles the callback.  Without Redis,
each worker maintains its own isolated state dict; callbacks routed to a
different worker will always fail the CSRF check.

Usage::

    store = OAuthStateStore()

    # In /auth/oauth/{provider}/start
    state_token = await store.new_state("github")

    # In /auth/oauth/{provider}/callback
    if not await store.consume_state(state_token, "github"):
        raise HTTPException(400, "Invalid or expired OAuth state.")
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any, ClassVar

_STATE_TTL: int = 600  # seconds (10 min)
_REDIS_KEY_PREFIX = "tuvl:oauth_state:"
_DEVICE_PREFIX = "tuvl:oauth_device:"


class OAuthStateStore:
    """Thread-safe (async) OAuth state store backed by Redis or in-process memory."""

    # In-process fallback: state → (provider, expires_at_monotonic)
    _memory: ClassVar[dict[str, tuple[str, float]]] = {}
    # Device-flow sessions: handle → (provider, payload, expires_at_monotonic)
    _devices: ClassVar[dict[str, tuple[str, dict[str, Any], float]]] = {}

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _use_redis() -> bool:
        from tuvl.core.infra.redis import is_redis_available

        return is_redis_available()

    @staticmethod
    def _redis() -> Any:
        from tuvl.core.infra.redis import get_redis_client

        return get_redis_client()

    # ── Public API ────────────────────────────────────────────────────────────

    async def new_state(self, provider: str) -> str:
        """Generate and store a new CSRF state token for *provider*.

        Returns the opaque state string that should be embedded in the
        authorization redirect URL and later verified in the callback.
        """
        state = secrets.token_urlsafe(32)

        if self._use_redis():
            await self._redis().set(
                f"{_REDIS_KEY_PREFIX}{state}",
                provider,
                ex=_STATE_TTL,
            )
        else:
            self._memory[state] = (provider, time.monotonic() + _STATE_TTL)

        return state

    async def new_device(self, provider: str, payload: dict[str, Any], *, ttl: int) -> str:
        """Store a device-flow session and return its opaque handle."""
        handle = secrets.token_urlsafe(32)
        if self._use_redis():
            blob = json.dumps({"provider": provider, "payload": payload})
            await self._redis().set(f"{_DEVICE_PREFIX}{handle}", blob, ex=ttl)
        else:
            self._devices[handle] = (provider, payload, time.monotonic() + ttl)
        return handle

    async def get_device(self, handle: str, provider: str) -> dict[str, Any] | None:
        """The stored payload for *handle*, or ``None`` if unknown, expired or another provider's."""
        if self._use_redis():
            raw = await self._redis().get(f"{_DEVICE_PREFIX}{handle}")
            if raw is None:
                return None
            entry = json.loads(raw)
            return entry["payload"] if entry.get("provider") == provider else None
        found = self._devices.get(handle)
        if found is None:
            return None
        stored_provider, payload, expires_at = found
        if time.monotonic() >= expires_at:
            self._devices.pop(handle, None)
            return None
        return payload if stored_provider == provider else None

    async def drop_device(self, handle: str) -> None:
        if self._use_redis():
            await self._redis().delete(f"{_DEVICE_PREFIX}{handle}")
        else:
            self._devices.pop(handle, None)

    async def consume_state(self, state: str, provider: str) -> bool:
        """Pop *state* and return ``True`` iff it exists, matches *provider*, and hasn't expired.

        The state is deleted atomically (single GET+DEL pipeline on Redis) so
        it can only be consumed once.
        """
        if self._use_redis():
            redis = self._redis()
            # Atomic GET-and-DELETE using a pipeline
            async with redis.pipeline(transaction=True) as pipe:
                pipe.get(f"{_REDIS_KEY_PREFIX}{state}")
                pipe.delete(f"{_REDIS_KEY_PREFIX}{state}")
                stored_provider, _ = await pipe.execute()

            if stored_provider is None:
                return False
            return bool(stored_provider == provider)

        # In-memory fallback
        entry = self._memory.pop(state, None)
        if entry is None:
            return False
        stored_provider, expires_at = entry
        return stored_provider == provider and time.monotonic() < expires_at


# Single process-wide instance used by the auth router.
oauth_state_store = OAuthStateStore()
