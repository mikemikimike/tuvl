"""Backward-compat shim — Redis manager has moved to tuvl.core.infra.redis."""

from tuvl.core.infra.redis import (  # noqa: F401
    close_redis,
    get_redis_client,
    init_redis,
    is_redis_available,
)
