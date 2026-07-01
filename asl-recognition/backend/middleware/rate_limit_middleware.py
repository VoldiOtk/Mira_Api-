from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Dict, Optional

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# In-memory fallback store: { api_key_id: [(timestamp, ...), ...] }
_memory_windows: Dict[int, list] = defaultdict(list)
_memory_lock: asyncio.Lock = asyncio.Lock()


async def check_rate_limit(
    api_key_id: int,
    limit_per_minute: int,
    redis_client=None,
) -> None:
    """Sliding window rate limit (60-second window).

    Raises HTTP 429 if the caller exceeds ``limit_per_minute`` requests
    within the last 60 seconds.  Uses a Redis ZSET when available, otherwise
    falls back to a process-local in-memory store (not shared across workers).
    """
    now = time.time()
    window_start = now - 60.0

    if redis_client is not None:
        await _check_redis(api_key_id, limit_per_minute, now, window_start, redis_client)
    else:
        await _check_memory(api_key_id, limit_per_minute, now, window_start)


async def _check_redis(
    api_key_id: int,
    limit_per_minute: int,
    now: float,
    window_start: float,
    redis_client,
) -> None:
    key = f"rl:{api_key_id}"
    try:
        pipe = redis_client.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        pipe.zadd(key, {str(now): now})
        pipe.expire(key, 120)
        results = await pipe.execute()
        count_before_add = results[1]
        if count_before_add >= limit_per_minute:
            retry_after = int(60 - (now - window_start))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": f"Limite de {limit_per_minute} requêtes/minute dépassée.",
                    "limit": limit_per_minute,
                    "retry_after": max(retry_after, 1),
                },
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Redis unavailable — fail open (log and continue)
        logger.warning("Rate limit Redis error for key %s: %s", api_key_id, exc)


async def _check_memory(
    api_key_id: int,
    limit_per_minute: int,
    now: float,
    window_start: float,
) -> None:
    async with _memory_lock:
        timestamps = _memory_windows[api_key_id]
        # Evict old entries
        trimmed = [t for t in timestamps if t > window_start]
        if len(trimmed) >= limit_per_minute:
            _memory_windows[api_key_id] = trimmed
            oldest = trimmed[0] if trimmed else window_start
            retry_after = int(60 - (now - oldest))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": f"Limite de {limit_per_minute} requêtes/minute dépassée.",
                    "limit": limit_per_minute,
                    "retry_after": max(retry_after, 1),
                },
            )
        trimmed.append(now)
        _memory_windows[api_key_id] = trimmed


def get_redis_client():
    """Return an async Redis client if redis is configured, else None."""
    import os
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return None
    try:
        import redis.asyncio as aioredis  # type: ignore[import]
        return aioredis.from_url(redis_url, decode_responses=True)
    except Exception as exc:
        logger.warning("Could not connect to Redis: %s", exc)
        return None
