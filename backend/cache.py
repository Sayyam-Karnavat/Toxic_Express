"""Redis client (shared with the arq job queue), JSON cache helpers and the rate limiter."""

import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis.exceptions import RedisError

from config import settings

logger = logging.getLogger(__name__)

_redis: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


async def init_redis() -> ArqRedis:
    global _redis
    if _redis is None:
        _redis = await create_pool(redis_settings(), retry=3)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def get_redis() -> ArqRedis:
    if _redis is None:
        raise RuntimeError("Redis is not initialised; call init_redis() first")
    return _redis


# --- JSON cache --------------------------------------------------------------------------------


async def cache_get_json(key: str) -> Any | None:
    try:
        raw = await get_redis().get(key)
    except RedisError:
        logger.warning("cache read failed for %s", key, exc_info=True)
        return None
    return json.loads(raw) if raw else None


async def cache_set_json(key: str, value: Any, ttl_seconds: int) -> None:
    try:
        await get_redis().set(key, json.dumps(value, default=str), ex=ttl_seconds)
    except RedisError:
        logger.warning("cache write failed for %s", key, exc_info=True)


async def cache_delete(*keys: str) -> None:
    if not keys:
        return
    try:
        await get_redis().delete(*keys)
    except RedisError:
        logger.warning("cache delete failed for %s", keys, exc_info=True)


# --- Rate limiting (sliding window counter) ----------------------------------------------------

# Weighted count = previous window * overlap + current window. Atomic in one round trip.
_SLIDING_WINDOW_LUA = """
local cur = tonumber(redis.call('GET', KEYS[1]) or '0')
local prev = tonumber(redis.call('GET', KEYS[2]) or '0')
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local elapsed = tonumber(ARGV[3])
local weighted = prev * ((window - elapsed) / window) + cur
if weighted + 1 > limit then
  return {0, math.floor(limit - weighted)}
end
redis.call('INCR', KEYS[1])
redis.call('PEXPIRE', KEYS[1], window * 2)
return {1, math.floor(limit - weighted - 1)}
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int


async def hit_rate_limit(key: str, limit: int, window_seconds: int) -> RateLimitResult:
    """Count one hit against `key`. Fails open (allows) if Redis is unavailable."""
    window_ms = window_seconds * 1000
    now_ms = int(time.time() * 1000)
    bucket = now_ms // window_ms
    elapsed = now_ms - bucket * window_ms
    keys = [f"rl:{key}:{bucket}", f"rl:{key}:{bucket - 1}"]
    try:
        redis: Any = get_redis()  # redis-py's eval() stubs only accept str args
        allowed, remaining = await redis.eval(
            _SLIDING_WINDOW_LUA, 2, *keys, limit, window_ms, elapsed
        )
    except RedisError:
        logger.error("rate limiter unavailable; allowing request for %s", key, exc_info=True)
        return RateLimitResult(True, limit, 0)
    retry_after = 0 if allowed else max(1, math.ceil((window_ms - elapsed) / 1000))
    return RateLimitResult(bool(allowed), max(0, int(remaining)), retry_after)
