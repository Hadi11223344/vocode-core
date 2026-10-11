"""Tests for RetryPolicy Protocol and NoRetryPolicy default."""

import pytest

from voice_platform.runtime.tools.retry import NoRetryPolicy, RetryPolicy


class TestNoRetryPolicy:
    """NoRetryPolicy — default, no retries."""

    @pytest.mark.asyncio
    async def test_should_retry_returns_false(self):
        policy = NoRetryPolicy()
        result = await policy.should_retry(attempt=1, error="any error")
        assert result is False

    def test_delay_returns_zero(self):
        policy = NoRetryPolicy()
        assert policy.delay(attempt=1) == 0.0


class TestRetryPolicyProtocol:
    """RetryPolicy is a runtime_checkable Protocol."""

    def test_no_retry_policy_satisfies_protocol(self):
        assert isinstance(NoRetryPolicy(), RetryPolicy)

    def test_custom_policy_satisfies_protocol(self):
        class CustomRetry:
            async def should_retry(self, attempt: int, error: str) -> bool:
                return attempt < 3
            def delay(self, attempt: int) -> float:
                return 0.5 * attempt

        assert isinstance(CustomRetry(), RetryPolicy)
