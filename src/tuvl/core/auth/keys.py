"""Key lifecycle for tuvl's access tokens (Ed25519-signed JWTs).

Production mode
---------------
Set ``TUVL_SIGNING_KEY`` to the hex-encoded Ed25519 private key (64 hex
characters / 32 bytes). The key is loaded once and reused for the lifetime of
the process, so tokens survive restarts.

Development mode
----------------
Without a key, a fresh one is generated in memory every time the process
starts. Tokens signed with an ephemeral key are **invalid after restart** — a
warning is emitted at startup to make this visible.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from tuvl.core.logger import logger

ENV_VAR = "TUVL_SIGNING_KEY"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate_private_key_hex() -> str:
    """A fresh 32-byte Ed25519 private key as 64 hex characters."""
    return (
        Ed25519PrivateKey.generate()
        .private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        .hex()
    )


class TuvlKeyManager:
    """The Ed25519 key pair that signs and verifies tuvl's access tokens.

    - ``public_key``  — verifies tokens (safe to share; see ``jwk``).
    - ``private_key`` — signs tokens (never exposed).
    - ``kid``         — key id, stamped in every token header.
    - ``is_ephemeral`` — ``True`` when the key was generated for this process.
    """

    def __init__(self) -> None:
        raw_hex = os.environ.get(ENV_VAR, "").strip()
        if raw_hex:
            try:
                self._private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw_hex))
            except (ValueError, TypeError) as exc:
                raise RuntimeError(
                    f"{ENV_VAR} is set but is not a 32-byte Ed25519 private key "
                    f"(expected 64 hex characters). Details: {exc}"
                ) from exc
            self.is_ephemeral = False
            logger.info("auth.key.loaded", env_var=ENV_VAR, mode="production", ephemeral=False)
        else:
            from tuvl.core.config import settings as _settings

            if not _settings.tuvl_dev_mode:
                raise RuntimeError(
                    f"{ENV_VAR} must be set when running in production mode. "
                    "Generate a persistent key with: tuvl generate key\n"
                    "Then add it to your .env:\n"
                    f"  {ENV_VAR}=<64-hex-char Ed25519 private key>"
                )
            self._private = Ed25519PrivateKey.generate()
            self.is_ephemeral = True
            logger.warning(
                "auth.key.ephemeral",
                env_var=ENV_VAR,
                reason="no signing key set; tokens will be invalid after process restart",
                hint=f"set {ENV_VAR} in your .env for persistent sessions",
            )
        raw_public = self.public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        self._x = _b64url(raw_public)
        self.kid = _b64url(hashlib.sha256(raw_public).digest()[:12])

    @property
    def public_key(self) -> Ed25519PublicKey:
        return self._private.public_key()

    @property
    def private_key(self) -> Ed25519PrivateKey:
        """Signs tokens. Never log it or send it anywhere."""
        return self._private

    @property
    def jwk(self) -> dict[str, str]:
        """The public key as a JWK (RFC 8037), for ``/auth/jwks.json``."""
        return {
            "kty": "OKP",
            "crv": "Ed25519",
            "x": self._x,
            "kid": self.kid,
            "alg": "EdDSA",
            "use": "sig",
        }


# ── Lazy singleton ────────────────────────────────────────────────────────────
# Constructed on first use rather than at import, so unrelated modules (the CLI,
# the validator) can be imported without a signing key in production mode.
_key_manager_singleton: TuvlKeyManager | None = None


def get_key_manager() -> TuvlKeyManager:
    """The process-wide ``TuvlKeyManager``, constructed on first call."""
    global _key_manager_singleton
    if _key_manager_singleton is None:
        _key_manager_singleton = TuvlKeyManager()
    return _key_manager_singleton


def __getattr__(name: str) -> TuvlKeyManager:
    if name == "key_manager":
        return get_key_manager()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
