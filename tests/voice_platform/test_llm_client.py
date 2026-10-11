"""Unit tests for Phase 3: LLMClient, RetryExecutor, TimeoutExecutor, MessagePipeline, LLMFactory."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_platform.runtime.llm.adapters import OllamaAdapter, OpenAIAdapter
from voice_platform.runtime.llm.adapters.base import ProviderAdapter
from voice_platform.runtime.llm.client import LLMClient
from voice_platform.runtime.llm.exceptions import (
    AuthenticationError,
    ProviderUnavailableError,
    RateLimitError,
    UnsupportedCapability,
)
from voice_platform.runtime.llm.factory import LLMFactory
from voice_platform.runtime.llm.middleware import MessagePipeline, MiddlewareContext, PIIRedactor
from voice_platform.runtime.llm.retry import RetryExecutor
from voice_platform.runtime.llm.session import ProviderSession
from voice_platform.runtime.llm.timeout import TimeoutExecutor
from voice_platform.runtime.llm.types import (
    CompletionResponse,
    ProviderCapability,
    ProviderConfig,
    RetryPolicy,
    StreamChunk,
    TimeoutPolicy,
)

# ─── RetryExecutor ─────────────────────────────────────────────────────

class TestRetryExecutor:
    @pytest.mark.asyncio
    async def test_no_retry_on_success(self):
        executor = RetryExecutor(RetryPolicy(max_retries=3))
        func = AsyncMock(return_value="ok")
        result = await executor.execute_async(func)
        assert result == "ok"
        assert func.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_429(self):
        executor = RetryExecutor(RetryPolicy(max_retries=3, base_delay=0.01))
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                exc = RateLimitError("rate limited", retry_after=0.01)
                raise exc
            return "ok"

        result = await executor.execute_async(flaky)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_401(self):
        executor = RetryExecutor(RetryPolicy(max_retries=3, base_delay=0.01))
        func = AsyncMock(side_effect=AuthenticationError("bad key"))
        with pytest.raises(AuthenticationError):
            await executor.execute_async(func)
        assert func.call_count == 1

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        executor = RetryExecutor(RetryPolicy(max_retries=2, base_delay=0.01))
        func = AsyncMock(side_effect=ProviderUnavailableError("down"))
        with pytest.raises(ProviderUnavailableError):
            await executor.execute_async(func)
        assert func.call_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_predicate_based_retry(self):
        called = [0]

        class TransientError(Exception):
            pass

        def is_transient(e):
            return isinstance(e, TransientError)

        executor = RetryExecutor(RetryPolicy(max_retries=2, base_delay=0.01, retry_if=is_transient))

        async def flaky():
            called[0] += 1
            if called[0] < 2:
                raise TransientError("transient")
            return "ok"

        result = await executor.execute_async(flaky)
        assert result == "ok"
        assert called[0] == 2

    def test_sync_retry(self):
        executor = RetryExecutor(RetryPolicy(max_retries=2, base_delay=0.01))
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ProviderUnavailableError("down")
            return "ok"

        result = executor.execute_sync(flaky)
        assert result == "ok"
        assert call_count == 2


# ─── TimeoutExecutor ───────────────────────────────────────────────────

class TestTimeoutExecutor:
    @pytest.mark.asyncio
    async def test_success_within_timeout(self):
        executor = TimeoutExecutor(TimeoutPolicy(total_timeout=5.0))

        async def quick():
            return "ok"

        result = await executor.execute(quick)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        executor = TimeoutExecutor(TimeoutPolicy(total_timeout=0.05))

        async def slow():
            await asyncio.sleep(1.0)
            return "ok"

        with pytest.raises(asyncio.TimeoutError):
            await executor.execute(slow)

    @pytest.mark.asyncio
    async def test_custom_timeout_override(self):
        executor = TimeoutExecutor(TimeoutPolicy(total_timeout=0.01))

        async def quick():
            return "ok"

        result = await executor.execute(quick, timeout=5.0)
        assert result == "ok"


# ─── MessagePipeline ───────────────────────────────────────────────────

class TestMessagePipeline:
    @pytest.mark.asyncio
    async def test_empty_pipeline_passthrough(self):
        pipeline = MessagePipeline()
        ctx = MiddlewareContext(provider="openai", model="gpt-4o")
        messages = [{"role": "user", "content": "Hello"}]
        result = await pipeline.process(messages, ctx)
        assert result == messages

    @pytest.mark.asyncio
    async def test_pii_redactor_applied(self):
        pipeline = MessagePipeline([PIIRedactor()])
        ctx = MiddlewareContext(provider="openai", model="gpt-4o")
        messages = [{"role": "user", "content": "My SSN is 123-45-6789"}]
        result = await pipeline.process(messages, ctx)
        assert "123-45-6789" not in result[0]["content"]

    @pytest.mark.asyncio
    async def test_middleware_order_preserved(self):
        order = []

        class FirstMiddleware:
            async def process(self, messages, context):
                order.append("first")
                return messages

        class SecondMiddleware:
            async def process(self, messages, context):
                order.append("second")
                return messages

        pipeline = MessagePipeline([FirstMiddleware(), SecondMiddleware()])
        ctx = MiddlewareContext(provider="openai", model="gpt-4o")
        await pipeline.process([], ctx)
        assert order == ["first", "second"]

    def test_pipeline_is_immutable(self):
        pipeline = MessagePipeline([PIIRedactor()])
        assert isinstance(pipeline.middlewares, tuple)
        assert len(pipeline.middlewares) == 1


# ─── LLMClient ─────────────────────────────────────────────────────────

class TestLLMClient:
    def _make_mock_adapter(self, **cap_overrides):
        adapter = MagicMock(spec=ProviderAdapter)
        default_cap = ProviderCapability(
            supports_tools=True, supports_streaming=True, supports_system_messages=True,
        )
        adapter.capabilities = default_cap
        adapter.translate_messages = MagicMock(side_effect=lambda msgs: msgs)
        adapter.complete = AsyncMock(return_value=CompletionResponse(content="Hello"))
        adapter.session = MagicMock()
        adapter.session.close = AsyncMock()
        # adapter.stream is an async generator function — calling it returns
        # an async generator, not a coroutine. Use MagicMock, not AsyncMock.
        adapter.stream = MagicMock(side_effect=lambda *a, **kw: self._mock_stream())
        return adapter

    async def _mock_stream(self):
        yield StreamChunk(content="Hi")
        yield StreamChunk(finish_reason="stop")

    @pytest.mark.asyncio
    async def test_complete_calls_adapter(self):
        adapter = self._make_mock_adapter()
        client = LLMClient(
            adapter=adapter,
            retry=RetryExecutor(RetryPolicy(max_retries=0)),
            timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
        )
        result = await client.complete([{"role": "user", "content": "Hi"}])
        assert result.content == "Hello"
        adapter.complete.assert_called_once()
        adapter.session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self):
        adapter = self._make_mock_adapter()
        client = LLMClient(
            adapter=adapter,
            retry=RetryExecutor(RetryPolicy(max_retries=0)),
            timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
        )
        chunks = []
        async for chunk in client.stream([{"role": "user", "content": "Hi"}]):
            chunks.append(chunk)
        assert len(chunks) == 2
        assert chunks[0].content == "Hi"
        assert chunks[1].finish_reason == "stop"
        adapter.session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stream_retries_failure_during_initial_iteration(self):
        adapter = self._make_mock_adapter()
        attempts = 0

        async def flaky_stream(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ProviderUnavailableError("connection reset")
            yield StreamChunk(content="recovered")

        adapter.stream = MagicMock(side_effect=flaky_stream)
        client = LLMClient(
            adapter=adapter,
            retry=RetryExecutor(RetryPolicy(max_retries=1, base_delay=0)),
            timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=1.0)),
        )

        chunks = [chunk async for chunk in client.stream([{"role": "user", "content": "Hi"}])]

        assert [chunk.content for chunk in chunks] == ["recovered"]
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_stream_timeout_covers_iteration(self):
        adapter = self._make_mock_adapter()

        async def slow_stream(*args, **kwargs):
            await asyncio.sleep(1)
            yield StreamChunk(content="too late")

        adapter.stream = MagicMock(side_effect=slow_stream)
        client = LLMClient(
            adapter=adapter,
            retry=RetryExecutor(RetryPolicy(max_retries=0)),
            timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=0.01)),
        )

        with pytest.raises(asyncio.TimeoutError):
            async for _ in client.stream([{"role": "user", "content": "Hi"}]):
                pass

    @pytest.mark.asyncio
    async def test_capability_validation_tools_unsupported(self):
        adapter = self._make_mock_adapter()
        adapter.capabilities = ProviderCapability(supports_tools=False, supports_streaming=True)
        client = LLMClient(
            adapter=adapter,
            retry=RetryExecutor(RetryPolicy(max_retries=0)),
            timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
        )
        with pytest.raises(UnsupportedCapability):
            await client.complete([{"role": "user", "content": "Hi"}], tools=[{"type": "function"}])

    @pytest.mark.asyncio
    async def test_capability_validation_streaming_unsupported(self):
        adapter = self._make_mock_adapter()
        adapter.capabilities = ProviderCapability(supports_tools=True, supports_streaming=False)
        client = LLMClient(
            adapter=adapter,
            retry=RetryExecutor(RetryPolicy(max_retries=0)),
            timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
        )
        with pytest.raises(UnsupportedCapability):
            async for _ in client.stream([{"role": "user", "content": "Hi"}]):
                pass

    @pytest.mark.asyncio
    async def test_middleware_applied(self):
        adapter = self._make_mock_adapter()
        pipeline = MessagePipeline([PIIRedactor()])
        client = LLMClient(
            adapter=adapter,
            retry=RetryExecutor(RetryPolicy(max_retries=0)),
            timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
            middleware=pipeline,
        )
        ctx = MiddlewareContext(provider="openai", model="gpt-4o")
        await client.complete(
            [{"role": "user", "content": "My SSN is 123-45-6789"}],
            context=ctx,
        )
        # Verify PII was redacted before adapter call
        called_messages = adapter.translate_messages.call_args[0][0]
        assert "123-45-6789" not in called_messages[0]["content"]

    def test_capabilities_proxied_from_adapter(self):
        adapter = self._make_mock_adapter()
        client = LLMClient(
            adapter=adapter,
            retry=RetryExecutor(RetryPolicy()),
            timeout=TimeoutExecutor(TimeoutPolicy()),
        )
        assert client.capabilities is adapter.capabilities


# ─── LLMFactory ────────────────────────────────────────────────────────

class TestLLMFactory:
    def test_supported_providers(self):
        providers = LLMFactory.supported_providers()
        assert "openai" in providers
        assert "ollama" in providers
        assert "gemini" in providers
        assert "groq" in providers
        assert len(providers) == 7

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            LLMFactory.create(
                "unknown",
                api_key="sk-test",
                model="test",
                retry=RetryExecutor(RetryPolicy()),
                timeout=TimeoutExecutor(TimeoutPolicy()),
            )

    def test_creates_openai_client(self):
        client = LLMFactory.create(
            "openai",
            api_key="sk-test",
            model="gpt-4o",
            retry=RetryExecutor(RetryPolicy()),
            timeout=TimeoutExecutor(TimeoutPolicy()),
        )
        assert isinstance(client, LLMClient)
        assert client.capabilities.supports_tools is True
        assert isinstance(client.adapter, OpenAIAdapter)

    def test_creates_ollama_client(self):
        client = LLMFactory.create(
            "ollama",
            api_key="ollama",
            base_url="http://localhost:11434/v1",
            model="qwen3:8b",
            retry=RetryExecutor(RetryPolicy()),
            timeout=TimeoutExecutor(TimeoutPolicy()),
            config=ProviderConfig(options={"num_ctx": 65536}),
        )
        assert isinstance(client.adapter, OllamaAdapter)
        assert client.capabilities.requires_non_streaming_for_tools is True

    def test_injected_executors_used(self):
        retry = RetryExecutor(RetryPolicy(max_retries=5))
        timeout = TimeoutExecutor(TimeoutPolicy(total_timeout=30.0))
        client = LLMFactory.create(
            "openai",
            api_key="sk-test",
            model="gpt-4o",
            retry=retry,
            timeout=timeout,
        )
        assert client._retry is retry
        assert client._timeout is timeout
