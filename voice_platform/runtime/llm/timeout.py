"""TimeoutExecutor — reusable timeout wrapper. Not LLM-specific.

Uses TimeoutPolicy with phased timeouts (connection, first-byte, total).
Initially only total_timeout is enforced; phases are ready for future use.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from typing import Any, TypeVar

from voice_platform.runtime.llm.types import TimeoutPolicy

T = TypeVar("T")


class TimeoutExecutor:
    """Reusable timeout wrapper with configurable policy."""

    def __init__(self, policy: TimeoutPolicy):
        self._policy = policy

    @property
    def policy(self) -> TimeoutPolicy:
        return self._policy

    async def execute(
        self,
        func: Callable,
        *args: Any,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Call async func with timeout. Raises asyncio.TimeoutError on expiry.

        Uses the provided timeout or falls back to policy.total_timeout.
        """
        effective_timeout = timeout if timeout is not None else self._policy.total_timeout
        return await asyncio.wait_for(func(*args, **kwargs), timeout=effective_timeout)

    async def iterate(
        self,
        stream_factory: Callable[..., AsyncIterator[T]],
        *args: Any,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[T, None]:
        """Iterate an async stream under the configured total timeout."""
        effective_timeout = timeout if timeout is not None else self._policy.total_timeout
        async with asyncio.timeout(effective_timeout):
            async for item in stream_factory(*args, **kwargs):
                yield item
