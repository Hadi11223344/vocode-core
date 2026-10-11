"""RetryExecutor — reusable retry wrapper. Not LLM-specific.

Supports both status-code-based and predicate-based retry decisions.
Async and sync variants for reuse across LLM, ToolRuntime, Webhook, MCP, etc.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from typing import Any, TypeVar

from loguru import logger

from voice_platform.runtime.llm.exceptions import ProviderUnavailableError, RateLimitError
from voice_platform.runtime.llm.types import RetryPolicy

T = TypeVar("T")


class RetryExecutor:
    """Reusable retry wrapper with configurable policy."""

    def __init__(self, policy: RetryPolicy):
        self._policy = policy

    @property
    def policy(self) -> RetryPolicy:
        return self._policy

    async def execute_async(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Call async func with retries per policy. Raises after exhausting retries."""
        last_exc: Exception | None = None
        for attempt in range(self._policy.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exc = e
                if not self._should_retry(e, attempt):
                    raise
                wait = self._compute_delay(e, attempt)
                logger.warning(
                    f"Retry {attempt + 1}/{self._policy.max_retries} "
                    f"after {wait:.1f}s: {e}"
                )
                await asyncio.sleep(wait)
        raise last_exc  # type: ignore[misc]

    async def execute_stream(
        self,
        stream_factory: Callable[..., AsyncIterator[T]],
        *args: Any,
        **kwargs: Any,
    ) -> AsyncGenerator[T, None]:
        """Iterate a stream with retries before its first emitted item.

        Retrying after yielding would duplicate or corrupt partial LLM output,
        so failures after the first item are surfaced to the caller.
        """
        for attempt in range(self._policy.max_retries + 1):
            emitted = False
            try:
                async for item in stream_factory(*args, **kwargs):
                    emitted = True
                    yield item
                return
            except Exception as exc:
                if emitted or not self._should_retry(exc, attempt):
                    raise
                wait = self._compute_delay(exc, attempt)
                logger.warning(
                    f"Retry {attempt + 1}/{self._policy.max_retries} "
                    f"after {wait:.1f}s: {exc}"
                )
                await asyncio.sleep(wait)

    def execute_sync(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Call sync func with retries per policy. Raises after exhausting retries."""
        import time
        last_exc: Exception | None = None
        for attempt in range(self._policy.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exc = e
                if not self._should_retry(e, attempt):
                    raise
                wait = self._compute_delay(e, attempt)
                logger.warning(
                    f"Retry {attempt + 1}/{self._policy.max_retries} "
                    f"after {wait:.1f}s: {e}"
                )
                time.sleep(wait)
        raise last_exc  # type: ignore[misc]

    def _should_retry(self, exc: Exception, attempt: int) -> bool:
        """Determine if we should retry based on policy."""
        if attempt >= self._policy.max_retries:
            return False
        # Check predicate first
        if self._policy.retry_if is not None:
            try:
                if self._policy.retry_if(exc):
                    return True
            except Exception:
                pass
        # Check status codes
        status = getattr(exc, "status_code", None)
        if status is not None and status in self._policy.retry_on_status:
            return True
        # Check known retryable runtime exceptions
        if isinstance(exc, (RateLimitError, ProviderUnavailableError)):
            return True
        # Check for common transient HTTP status attributes
        if hasattr(exc, "response"):
            resp = exc.response
            if hasattr(resp, "status_code") and resp.status_code in self._policy.retry_on_status:
                return True
        return False

    def _compute_delay(self, exc: Exception, attempt: int) -> float:
        """Compute delay for this retry attempt."""
        delay = (2 ** attempt) * self._policy.base_delay
        # Respect Retry-After header for rate limit errors
        if self._policy.respect_retry_after:
            retry_after = None
            if isinstance(exc, RateLimitError) and exc.retry_after is not None:
                retry_after = exc.retry_after
            elif hasattr(exc, "response"):
                resp = exc.response
                if hasattr(resp, "headers"):
                    ra_header = resp.headers.get("Retry-After")
                    if ra_header:
                        try:
                            retry_after = float(ra_header)
                        except (ValueError, TypeError):
                            pass
            if retry_after is not None:
                delay = min(retry_after, self._policy.retry_after_cap)
        return delay
