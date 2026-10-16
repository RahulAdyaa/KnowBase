"""Redis client singleton (lazy - safe to import without a server running)."""

from functools import lru_cache

from app.core.config import get_settings


@lru_cache
def get_redis():
    """Return a redis client, or None if redis is unavailable.

    Callers must handle None (rate limiting degrades to allow-all with a
    warning - acceptable for local dev, never for production).
    """
    try:
        import redis  # local import: keeps `import app...` working without redis installed
    except ImportError:
        return None

    client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=2)
    try:
        client.ping()
        return client
    except Exception:
        return None
