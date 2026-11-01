"""Token revocation blacklist.

Stores hashes of revoked access tokens so they can be rejected even before
their embedded ``exp`` fact expires.  Uses Redis (SET with EXAT) when a
``type: redis`` datasource is configured, otherwise uses an in-process dict
with lazy expiry cleanup.

**Scaling requirement** — multi-worker / multi-process deployments MUST have
Redis configured.  Without it, a token revoked by one worker is still accepted
by all other workers.  Refer to documentation for Redis datasource setup.

Token values are never stored directly.  The SHA-256 hex digest of the raw
token string is used as the key, limiting the storage footprint and avoiding
sensitive data in Redis.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, ClassVar

_REDIS_KEY_PREFIX = "tuvl:blacklist:"
_SESSIONS_KEY_PREFIX = "tuvl:sessions-ended:"
# Fallback TTL when no expiry can be inferred from the token: 24 h
_FALLBACK_TTL = 86400


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class TokenBlacklist:
    """Async revocation store backed by Redis or in-process memory."""

    # In-process fallback: token_hash → expires_at (wall-clock seconds)
    _memory: ClassVar[dict[str, float]] = {}
    # In-process fallback: user_id → (sessions ended at, ms; entry expires_at, s or None)
    _sessions: ClassVar[dict[str, tuple[int, float | None]]] = {}

    @staticmethod
    def _use_redis() -> bool:
        from tuvl.core.infra.redis import is_redis_available

        return is_redis_available()

    @staticmethod
    def _redis() -> Any:
        from tuvl.core.infra.redis import get_redis_client

        return get_redis_client()

    def _gc_memory(self) -> None:
        """Remove expired entries from the in-process fallback dict."""
        now = time.time()
        expired = [k for k, exp in self._memory.items() if now > exp]
        for k in expired:
            del self._memory[k]

    async def revoke(self, token: str, ttl_seconds: int = _FALLBACK_TTL) -> None:
        """Mark *token* as revoked for up to *ttl_seconds* seconds.

        Parameters
        ----------
        token:
            Raw access token string.
        ttl_seconds:
            How long to keep the blacklist entry alive.  Should ideally match
            (or exceed) the remaining lifetime of the token so the entry is
            automatically purged once the token would have expired anyway.
        """
        h = _hash_token(token)
        if self._use_redis():
            await self._redis().set(f"{_REDIS_KEY_PREFIX}{h}", "1", ex=ttl_seconds)
        else:
            self._gc_memory()
            self._memory[h] = time.time() + ttl_seconds

    async def is_revoked(self, token: str) -> bool:
        """Return ``True`` if *token* is on the blacklist."""
        h = _hash_token(token)
        if self._use_redis():
            result = await self._redis().get(f"{_REDIS_KEY_PREFIX}{h}")
            return result is not None
        # In-memory fallback
        entry = self._memory.get(h)
        if entry is None:
            return False
        if time.time() > entry:
            del self._memory[h]
            return False
        return True

    async def end_sessions(self, user_id: str, ttl_seconds: int | None) -> None:
        """Refuse every token *user_id* was issued before now (deactivation, role
        changes, deletion). The mark lives as long as a token can (*ttl_seconds*;
        ``None``: tokens never expire, so neither does the mark)."""
        now_ms = int(time.time() * 1000)
        if self._use_redis():
            await self._redis().set(f"{_SESSIONS_KEY_PREFIX}{user_id}", str(now_ms), ex=ttl_seconds)
        else:
            self._sessions[user_id] = (now_ms, time.time() + ttl_seconds if ttl_seconds else None)

    async def sessions_ended_at(self, user_id: str) -> int | None:
        """When *user_id*'s sessions were last ended (epoch ms), or ``None``."""
        if self._use_redis():
            value = await self._redis().get(f"{_SESSIONS_KEY_PREFIX}{user_id}")
            return int(value) if value is not None else None
        entry = self._sessions.get(user_id)
        if entry is None:
            return None
        ended_at, expires_at = entry
        if expires_at is not None and time.time() > expires_at:
            del self._sessions[user_id]
            return None
        return ended_at


# Process-wide singleton used by verify_token and router endpoints.
token_blacklist = TokenBlacklist()
