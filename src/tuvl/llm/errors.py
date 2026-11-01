"""Failures of a model call, by what a caller can do about them."""

from __future__ import annotations


class LLMError(Exception):
    """A model call failed. ``status_code`` is the provider's HTTP status when there was one."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BadRequestError(LLMError):
    """The provider rejected the request (HTTP 400/404/422)."""


class AuthenticationError(LLMError):
    """The key is missing, wrong or not allowed (HTTP 401/403)."""


class RateLimitError(LLMError):
    """HTTP 429."""


class Timeout(LLMError):  # noqa: N818
    """No answer within the call's timeout."""


class APIConnectionError(LLMError):
    """The provider could not be reached."""


class ServiceUnavailableError(LLMError):
    """HTTP 503/529 — overloaded or down."""


class InternalServerError(LLMError):
    """Any other HTTP 5xx."""


class ConfigurationError(LLMError):
    """The provider's endpoint cannot be built from the settings given."""


class UnsupportedProviderError(LLMError):
    """The model id names a provider tuvl has no adapter for."""


def from_status(status: int, message: str) -> LLMError:
    if status in (401, 403):
        return AuthenticationError(message, status_code=status)
    if status == 429:
        return RateLimitError(message, status_code=status)
    if status in (503, 529):
        return ServiceUnavailableError(message, status_code=status)
    if status >= 500:
        return InternalServerError(message, status_code=status)
    return BadRequestError(message, status_code=status)
