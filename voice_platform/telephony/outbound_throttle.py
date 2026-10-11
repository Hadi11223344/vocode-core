"""
Voice Platform — Outbound Call CPS Rate Limiter
==================================================

Token-bucket-style rate limiter for outbound calls using Redis.
Ensures compliance with Twilio's default 1 CPS limit and prevents
carrier throttling / queue abuse.

Usage:
    from voice_platform.telephony.outbound_throttle import OutboundCallThrottler

    throttler = OutboundCallThrottler()
    ok = await throttler.acquire(user_id=1, max_cps=1)
    if not ok:
        raise HTTPException(429, "Rate limit exceeded — try again later")

    # Place the Twilio call...
"""

import asyncio
from typing import Optional

from loguru import logger

from voice_platform.config import settings

# ── Redis-backed Counter Limiter ───────────────────────────────────────

class OutboundCallThrottler:
    """
    CPS (Calls Per Second) rate limiter backed by Redis.

    Uses a per-second counter with TTL=1s for each user.
    This is a simple but effective approach for telephony CPS limits.

    If Redis is unavailable, falls back to an in-memory asyncio.Lock
    + dict for the current process (not distributed-safe, but prevents
    local bursts).
    """

    _instance: Optional["OutboundCallThrottler"] = None

    def __new__(cls) -> "OutboundCallThrottler":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._redis: Optional[object] = None
        self._fallback: dict[str, int] = {}  # user_id → count this second
        self._fallback_lock = asyncio.Lock()

    async def _get_redis(self):
        """Lazy-init Redis client."""
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            await self._redis.ping()
            logger.info("Outbound throttler connected to Redis")
        except Exception:
            logger.warning("Outbound throttler: Redis unavailable, using in-memory fallback")
            self._redis = None
        return self._redis

    async def acquire(
        self,
        user_id: int,
        max_cps: int = 1,
        wait: bool = False,
        max_wait_seconds: float = 5.0,
    ) -> bool:
        """
        Try to acquire a slot for an outbound call.

        Args:
            user_id: The calling user/account ID
            max_cps: Maximum calls per second allowed (default 1)
            wait: If True, block until a slot is available (up to max_wait_seconds)
            max_wait_seconds: How long to wait if wait=True

        Returns:
            True if slot acquired, False if rate limit exceeded
        """
        if max_cps <= 0:
            max_cps = 1

        deadline = asyncio.get_event_loop().time() + max_wait_seconds if wait else None

        while True:
            if await self._try_acquire(user_id, max_cps):
                return True
            if not wait or (deadline and asyncio.get_event_loop().time() >= deadline):
                return False
            await asyncio.sleep(0.2)  # Brief backoff before retry

    async def _try_acquire(self, user_id: int, max_cps: int) -> bool:
        redis = await self._get_redis()
        key = f"outbound_cps:{user_id}"

        if redis:
            try:
                # Use Lua for atomic check-and-increment
                lua = """
                local current = redis.call('GET', KEYS[1])
                if current and tonumber(current) >= tonumber(ARGV[1]) then
                    return 0
                end
                redis.call('INCR', KEYS[1])
                redis.call('EXPIRE', KEYS[1], ARGV[2])
                return 1
                """
                result = await redis.eval(lua, 1, key, str(max_cps), "1")
                return bool(int(result))
            except Exception as e:
                logger.warning(f"Redis CPS check failed: {e}, falling back to memory")
                self._redis = None

        # In-memory fallback (per-process only)
        async with self._fallback_lock:
            count = self._fallback.get(key, 0)
            if count >= max_cps:
                return False
            self._fallback[key] = count + 1
            # Schedule cleanup after ~1.1s
            asyncio.get_event_loop().call_later(1.1, self._cleanup_fallback, key)
            return True

    def _cleanup_fallback(self, key: str) -> None:
        """Remove expired in-memory counter entry."""
        self._fallback.pop(key, None)

    async def get_current_cps(self, user_id: int) -> int:
        """Return current calls-in-flight count for diagnostics."""
        redis = await self._get_redis()
        key = f"outbound_cps:{user_id}"
        if redis:
            try:
                val = await redis.get(key)
                return int(val or 0)
            except Exception:
                pass
        return self._fallback.get(key, 0)

    async def release(self, user_id: int) -> None:
        """Release a previously acquired throttle slot (e.g. on call creation failure).

        Decrements the per-second counter so the slot can be reused immediately.
        """
        redis = await self._get_redis()
        key = f"outbound_cps:{user_id}"
        if redis:
            try:
                await redis.decr(key)
                logger.debug(f"Released throttle slot for user {user_id}")
                return
            except Exception as e:
                logger.warning(f"Redis release failed: {e}")
                self._redis = None

        # In-memory fallback
        async with self._fallback_lock:
            count = self._fallback.get(key, 0)
            if count > 0:
                self._fallback[key] = count - 1
