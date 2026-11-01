"""Storage errors. ``code`` is the stable name the tool engine maps to a signal or error type."""

from __future__ import annotations


class StorageError(Exception):
    code = "storage_error"


class NotFound(StorageError):  # noqa: N818
    code = "not_found"


class Conflict(StorageError):  # noqa: N818
    code = "conflict"


class TooLarge(StorageError):  # noqa: N818
    code = "too_large"


class InvalidKey(StorageError):  # noqa: N818
    code = "invalid_key"


class Forbidden(StorageError):  # noqa: N818
    code = "forbidden"


class AuthError(StorageError):
    code = "auth"


class Unsupported(StorageError):  # noqa: N818
    code = "unsupported"


class ConfigError(StorageError):
    code = "config"


class Unavailable(StorageError):  # noqa: N818
    """A failure worth retrying: connection error, 5xx."""

    code = "transient"


class RateLimited(Unavailable):
    code = "rate_limit"


class Timeout(Unavailable):
    code = "timeout"


def from_status(status: int, message: str) -> StorageError:
    if status == 404:
        return NotFound(message)
    if status in (409, 412):
        return Conflict(message)
    if status == 401:
        return AuthError(message)
    if status == 403:
        return Forbidden(message)
    if status in (413, 507):
        return TooLarge(message)
    if status == 429:
        return RateLimited(message)
    if status >= 500:
        return Unavailable(message)
    return StorageError(message)
