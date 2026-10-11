"""RetryPolicy Protocol and NoRetryPolicy default.

Protocol-based so future implementations (ExponentialRetry, ProviderRetry,
IdempotentRetry, CircuitBreakerRetry) can be added without touching ToolRuntime.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RetryPolicy(Protocol):
    """Protocol for retry strategies.

    Retry wraps ONLY plugin execution — not the full ToolRuntime lifecycle.
    ToolRuntime calls should_retry() after a failed adapter.execute(); if True,
    it sleeps for delay() seconds and retries.
    """

    async def should_retry(self, attempt: int, error: str) -> bool:
        """Return True if the execution should be retried."""
        ...

    def delay(self, attempt: int) -> float:
        """Return the delay in seconds before the next attempt."""
        ...


class NoRetryPolicy:
    """Default — no retries."""

    async def should_retry(self, attempt: int, error: str) -> bool:
        return False

    def delay(self, attempt: int) -> float:
        return 0.0
