from functools import lru_cache

import redis

from app.core.config import settings


@lru_cache
def get_redis() -> redis.Redis:
    """General-purpose client (strings in, strings out)."""
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


@lru_cache
def get_rq_redis() -> redis.Redis:
    """Client for RQ. It must return bytes, so `decode_responses` stays off."""
    return redis.Redis.from_url(settings.redis_url)
