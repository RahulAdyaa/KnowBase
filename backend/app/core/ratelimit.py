"""Sliding-window rate limiter backed by Redis.

Uses a simple fixed-window counter (INCR + EXPIRE). Good enough for API
abuse protection; swap for a token-bucket Lua script if you need burst control.
"""

import time

from app.core.logging import get_logger
from app.core.redis import get_redis

log = get_logger(__name__)


def check_rate_limit(key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds)."""
    client = get_redis()
    if client is None:
        log.warning("redis_unavailable_rate_limit_bypassed", extra={"key": key})
        return True, 0
    window = int(time.time() // window_seconds)
    redis_key = f"rl:{key}:{window}"
    try:
        count = client.incr(redis_key)
        if count == 1:
            client.expire(redis_key, window_seconds)
        if count > limit:
            ttl = client.ttl(redis_key)
            return False, max(ttl, 1)
        return True, 0
    except Exception as exc:  # fail open for availability
        log.warning("rate_limit_error_bypassed", extra={"err": str(exc)})
        return True, 0
