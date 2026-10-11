"""
Voice Platform — Redis Cache Helpers
======================================

Lightweight caching utilities for expensive-to-build objects.

- Agent config caching: avoids rebuilding vocode AgentConfig from DB on every call
- KB chunk caching: caches parsed knowledge base chunks

All caches use Redis with TTL. If Redis is unavailable, the cache gracefully
falls back to direct computation (no cache).
"""

import json
from typing import Any, Optional

from loguru import logger

from voice_platform.config import settings


class RedisCache:
    """Simple Redis-based cache with JSON serialization."""

    _client = None

    @classmethod
    def _get_client(cls):
        if cls._client is not None:
            return cls._client
        try:
            import redis.asyncio as aioredis
            cls._client = aioredis.from_url(settings.redis_url, decode_responses=True)
            return cls._client
        except Exception:
            logger.debug("Redis unavailable — cache disabled")
            return None

    @classmethod
    async def get(cls, key: str) -> Optional[Any]:
        """Fetch a cached value by key."""
        client = cls._get_client()
        if client is None:
            return None
        try:
            raw = await client.get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        return None

    @classmethod
    async def set(cls, key: str, value: Any, ttl_seconds: int = 300) -> bool:
        """Store a value in cache with TTL."""
        client = cls._get_client()
        if client is None:
            return False
        try:
            await client.set(key, json.dumps(value), ex=ttl_seconds)
            return True
        except Exception:
            return False

    @classmethod
    async def set_nx(cls, key: str, value: Any, ttl_seconds: int = 300) -> bool:
        """Atomically set a key only if it does not exist (distributed lock)."""
        client = cls._get_client()
        if client is None:
            return False
        try:
            return await client.set(key, json.dumps(value), nx=True, ex=ttl_seconds) is True
        except Exception:
            return False

    @classmethod
    async def delete(cls, key: str) -> bool:
        """Remove a key from cache."""
        client = cls._get_client()
        if client is None:
            return False
        try:
            await client.delete(key)
            return True
        except Exception:
            return False

    @classmethod
    async def delete_pattern(cls, pattern: str) -> int:
        """Remove all keys matching a pattern."""
        client = cls._get_client()
        if client is None:
            return 0
        try:
            keys = await client.keys(pattern)
            if keys:
                return await client.delete(*keys)
        except Exception:
            pass
        return 0
