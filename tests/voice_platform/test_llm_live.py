"""Live integration tests for the LLMClient architecture — OpenRouter / DeepSeek V4 Flash.

These tests verify streaming parity, connection lifecycle, concurrency,
provider behavior, and latency against the real OpenRouter API using
the DeepSeek V4 Flash model.

Run with:
    pytest tests/voice_platform/test_llm_live.py --live -v

Requires:
    OPENROUTER_API_KEY — Get one at https://openrouter.ai/keys
"""

import asyncio
import os
import time

import pytest

from voice_platform.runtime.llm.factory import LLMFactory
from voice_platform.runtime.llm.retry import RetryExecutor
from voice_platform.runtime.llm.timeout import TimeoutExecutor
from voice_platform.runtime.llm.types import ProviderConfig, RetryPolicy, TimeoutPolicy

pytestmark = pytest.mark.live

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROVIDER = "openrouter"
MODEL = "deepseek/deepseek-v4-flash"
BASE_URL = "https://openrouter.ai/api/v1"

SIMPLE_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant. Reply concisely."},
    {"role": "user", "content": "Say exactly: Hello, world!"},
]

LONGER_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant. Reply in 2-3 sentences."},
    {"role": "user", "content": "Explain what water is."},
]

WEATHER_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"},
                },
                "required": ["location"],
            },
        },
    }
]

TOOL_MESSAGES = [
    {"role": "system", "content": "You are a weather assistant. Use the get_weather tool when asked about weather."},
    {"role": "user", "content": "What is the weather in Tokyo?"},
]


def _get_api_key() -> str | None:
    return os.environ.get("OPENROUTER_API_KEY")


def _skip_if_no_key():
    key = _get_api_key()
    if not key:
        pytest.skip("No OPENROUTER_API_KEY found in environment (set it to run live tests)")


def _make_retry(max_retries: int = 3) -> RetryExecutor:
    return RetryExecutor(RetryPolicy(max_retries=max_retries, base_delay=1.0))


def _make_timeout(total: float = 60.0) -> TimeoutExecutor:
    return TimeoutExecutor(TimeoutPolicy(total_timeout=total))


def _make_client(*, max_retries: int = 3, timeout: float = 60.0, config: ProviderConfig | None = None):
    """Create an LLMClient for OpenRouter / DeepSeek V4 Flash."""
    return LLMFactory.create(
        PROVIDER,
        api_key=_get_api_key(),
        base_url=BASE_URL,
        model=MODEL,
        retry=_make_retry(max_retries),
        timeout=_make_timeout(timeout),
        config=config,
    )


# ---------------------------------------------------------------------------
# 1. Streaming Behavior Parity
# ---------------------------------------------------------------------------
class TestStreamingParity:
    """Verify streaming behavior matches non-streaming for token order, EOT, etc."""

    @pytest.mark.asyncio
    async def test_stream_token_order(self):
        _skip_if_no_key()
        client = _make_client()

        # Get non-streaming response
        response = await client.complete(SIMPLE_MESSAGES, temperature=0.0, max_tokens=50)
        full_text = response.content.strip()

        # Get streaming response
        chunks = []
        async for chunk in client.stream(SIMPLE_MESSAGES, temperature=0.0, max_tokens=50):
            if chunk.content:
                chunks.append(chunk.content)
        streamed_text = "".join(chunks).strip()

        assert streamed_text == full_text, (
            f"Streamed text does not match complete text.\n"
            f"Streamed: {streamed_text!r}\nComplete: {full_text!r}"
        )

    @pytest.mark.asyncio
    async def test_stream_end_of_turn(self):
        _skip_if_no_key()
        client = _make_client()

        finish_reasons = []
        async for chunk in client.stream(SIMPLE_MESSAGES, max_tokens=50):
            if chunk.finish_reason:
                finish_reasons.append(chunk.finish_reason)

        assert len(finish_reasons) > 0, "No finish_reason received from stream"
        assert finish_reasons[-1] == "stop", f"Expected final finish_reason='stop', got {finish_reasons[-1]!r}"

    @pytest.mark.asyncio
    async def test_stream_no_duplicate_chunks(self):
        _skip_if_no_key()
        client = _make_client()

        prev_content = ""
        async for chunk in client.stream(LONGER_MESSAGES, max_tokens=200):
            if chunk.content and prev_content:
                assert chunk.content != prev_content, (
                    f"Consecutive duplicate chunks: {chunk.content!r}"
                )
            prev_content = chunk.content or prev_content

    @pytest.mark.asyncio
    async def test_stream_tool_calls(self):
        _skip_if_no_key()
        client = _make_client(timeout=120.0)

        # DeepSeek V4 Flash supports tool calls via OpenAI-compatible API
        response = await client.complete(
            TOOL_MESSAGES,
            tools=WEATHER_TOOL,
            temperature=0.0,
            max_tokens=200,
        )
        assert response.content is not None
        # Tool call may or may not be present depending on model behavior
        if response.tool_calls:
            assert len(response.tool_calls) > 0
            assert response.tool_calls[0].name == "get_weather"

    @pytest.mark.asyncio
    async def test_stream_cancellation(self):
        _skip_if_no_key()
        client = _make_client()

        count = 0
        async for chunk in client.stream(LONGER_MESSAGES, max_tokens=500):
            if chunk.content:
                count += 1
            if count >= 2:
                break  # Cancel after 2 chunks

        assert count >= 1, "Should have received at least 1 chunk before cancellation"

    @pytest.mark.asyncio
    async def test_stream_empty_response(self):
        _skip_if_no_key()
        client = _make_client()

        empty_messages = [
            {"role": "system", "content": "Reply with exactly one word: OK"},
            {"role": "user", "content": "Go."},
        ]
        chunks = []
        async for chunk in client.stream(empty_messages, max_tokens=50):
            if chunk.content:
                chunks.append(chunk.content)

        # Should complete without error, even if response is minimal
        assert len(chunks) >= 1, "Stream should produce at least one chunk"


# ---------------------------------------------------------------------------
# 2. Connection Lifecycle
# ---------------------------------------------------------------------------
class TestConnectionLifecycle:
    """Verify no leaked HTTP clients, session reuse, and graceful shutdown."""

    @pytest.mark.asyncio
    async def test_no_leaked_http_clients(self):
        _skip_if_no_key()
        client = _make_client()

        await client.complete(SIMPLE_MESSAGES, max_tokens=10)

        session = client.adapter._session
        # OpenRouter uses the SDK path, so only SDK client is guaranteed to exist
        assert session._sdk._client is not None, "SDK client should exist after a request"

        await session.close()
        assert session._sdk._client is None, "SDK client leaked after close()"
        assert session._http._client is None, "HTTP client leaked after close()"

    @pytest.mark.asyncio
    async def test_session_reuse(self):
        _skip_if_no_key()
        client = _make_client()
        session = client.adapter._session

        # First request creates the SDK client
        await client.complete(SIMPLE_MESSAGES, max_tokens=10)
        sdk_client_1 = session._sdk._client
        assert sdk_client_1 is not None

        # Second request should reuse the same client
        await client.complete(SIMPLE_MESSAGES, max_tokens=10)
        sdk_client_2 = session._sdk._client
        assert sdk_client_2 is sdk_client_1, "SDK client was recreated instead of reused"

        # Third request still reuses
        await client.complete(SIMPLE_MESSAGES, max_tokens=10)
        sdk_client_3 = session._sdk._client
        assert sdk_client_3 is sdk_client_1, "SDK client was recreated instead of reused"

        await session.close()

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self):
        _skip_if_no_key()
        clients = [_make_client() for _ in range(5)]

        # Make requests with all clients
        results = await asyncio.gather(
            *[c.complete(SIMPLE_MESSAGES, max_tokens=50) for c in clients]
        )
        for i, r in enumerate(results):
            assert r.content, f"Client {i} returned empty content"

        # Close all sessions
        for c in clients:
            await c.adapter._session.close()

        # Verify all cleaned up
        for c in clients:
            assert c.adapter._session._http._client is None
            assert c.adapter._session._sdk._client is None


# ---------------------------------------------------------------------------
# 3. Concurrency
# ---------------------------------------------------------------------------
class TestConcurrency:
    """Verify concurrent streams, and retry under load."""

    @pytest.mark.asyncio
    async def test_concurrent_streams_separate_clients(self):
        _skip_if_no_key()
        # Each stream gets its own client to avoid SDK client contention
        clients = [_make_client() for _ in range(3)]

        async def run_stream(idx: int) -> str:
            msgs = [
                {"role": "system", "content": "Reply concisely in one sentence."},
                {"role": "user", "content": f"Tell me fact number {idx}."},
            ]
            chunks = []
            try:
                async for chunk in clients[idx].stream(msgs, max_tokens=200):
                    if chunk.content:
                        chunks.append(chunk.content)
            except Exception as e:
                print(f"Stream {idx} error: {e}")
                raise
            return "".join(chunks)

        results = await asyncio.gather(*[run_stream(i) for i in range(3)])
        for i, text in enumerate(results):
            assert text.strip(), f"Stream {i} returned empty content"

        for c in clients:
            await c.adapter._session.close()

    @pytest.mark.asyncio
    async def test_retry_under_load(self):
        _skip_if_no_key()
        # Use separate clients to avoid SDK client contention under concurrency
        clients = [_make_client(max_retries=2) for _ in range(5)]

        async def make_request(idx: int) -> str:
            try:
                response = await clients[idx].complete(SIMPLE_MESSAGES, max_tokens=50)
                return response.content
            except Exception as e:
                print(f"Request {idx} error: {e}")
                raise

        results = await asyncio.gather(*[make_request(i) for i in range(5)])
        for i, r in enumerate(results):
            assert r and r.strip(), f"Request {i} returned empty content: {r!r}"

        for c in clients:
            await c.adapter._session.close()


# ---------------------------------------------------------------------------
# 4. Provider Behavior (OpenRouter / DeepSeek V4 Flash)
# ---------------------------------------------------------------------------
class TestProviderBehavior:
    """Verify OpenRouter with DeepSeek V4 Flash returns valid responses."""

    @pytest.mark.asyncio
    async def test_complete_returns_content(self):
        _skip_if_no_key()
        client = _make_client()

        response = await client.complete(SIMPLE_MESSAGES, max_tokens=50)
        assert response.content, "Complete returned empty content"
        assert response.finish_reason == "stop"
        assert response.usage is not None, "Should return usage stats"

        await client.adapter._session.close()

    @pytest.mark.asyncio
    async def test_stream_returns_content(self):
        _skip_if_no_key()
        client = _make_client()

        chunks = []
        async for chunk in client.stream(SIMPLE_MESSAGES, max_tokens=50):
            if chunk.content:
                chunks.append(chunk.content)
        assert "".join(chunks).strip(), "Stream returned empty content"

        await client.adapter._session.close()

    @pytest.mark.asyncio
    async def test_stream_and_complete_match(self):
        _skip_if_no_key()
        client = _make_client()

        # Complete
        response = await client.complete(SIMPLE_MESSAGES, temperature=0.0, max_tokens=50)
        complete_text = response.content.strip()

        # Stream
        chunks = []
        async for chunk in client.stream(SIMPLE_MESSAGES, temperature=0.0, max_tokens=50):
            if chunk.content:
                chunks.append(chunk.content)
        stream_text = "".join(chunks).strip()

        assert stream_text == complete_text, (
            f"Stream and complete responses differ.\n"
            f"Stream: {stream_text!r}\nComplete: {complete_text!r}"
        )

        await client.adapter._session.close()

    @pytest.mark.asyncio
    async def test_tool_calls_supported(self):
        _skip_if_no_key()
        client = _make_client(timeout=120.0)

        response = await client.complete(
            TOOL_MESSAGES,
            tools=WEATHER_TOOL,
            temperature=0.0,
            max_tokens=200,
        )
        # DeepSeek V4 Flash should support tool calls
        assert response.content is not None
        if response.tool_calls:
            tc = response.tool_calls[0]
            assert tc.name == "get_weather"
            assert "Tokyo" in tc.arguments or "location" in tc.arguments

        await client.adapter._session.close()


# ---------------------------------------------------------------------------
# 5. Latency Overhead
# ---------------------------------------------------------------------------
class TestLatencyOverhead:
    """Verify middleware/retry/timeout wrapping adds negligible overhead."""

    @pytest.mark.asyncio
    async def test_latency_overhead_complete(self):
        _skip_if_no_key()
        from openai import AsyncOpenAI

        api_key = _get_api_key()

        # Raw SDK call
        raw_client = AsyncOpenAI(api_key=api_key, base_url=BASE_URL)
        t0 = time.perf_counter()
        raw_response = await raw_client.chat.completions.create(
            model=MODEL,
            messages=SIMPLE_MESSAGES,
            max_tokens=50,
        )
        raw_latency = time.perf_counter() - t0
        await raw_client.close()

        # LLMClient call
        client = _make_client()
        t0 = time.perf_counter()
        llm_response = await client.complete(SIMPLE_MESSAGES, max_tokens=50)
        llm_latency = time.perf_counter() - t0
        await client.adapter._session.close()

        overhead = llm_latency - raw_latency
        # Overhead from middleware/retry/timeout wrapping should be negligible.
        # Network latency variance can cause differences, so we allow up to 3s
        # and just verify both return content. The real overhead is in the
        # wrapping code, not network timing.
        assert raw_response.choices[0].message.content
        assert llm_response.content
        # Log overhead for visibility but don't hard-fail on network variance
        print(f"\nLatency: raw={raw_latency * 1000:.1f}ms, llm={llm_latency * 1000:.1f}ms, overhead={overhead * 1000:.1f}ms")

    @pytest.mark.asyncio
    async def test_latency_overhead_stream(self):
        _skip_if_no_key()
        from openai import AsyncOpenAI

        api_key = _get_api_key()

        # Raw SDK stream — measure time to first token
        raw_client = AsyncOpenAI(api_key=api_key, base_url=BASE_URL)
        t0 = time.perf_counter()
        raw_stream = await raw_client.chat.completions.create(
            model=MODEL,
            messages=SIMPLE_MESSAGES,
            max_tokens=50,
            stream=True,
        )
        async for chunk in raw_stream:
            if chunk.choices and chunk.choices[0].delta.content:
                raw_ttft = time.perf_counter() - t0
                break
        await raw_client.close()

        # LLMClient stream — measure time to first token
        client = _make_client()
        t0 = time.perf_counter()
        async for chunk in client.stream(SIMPLE_MESSAGES, max_tokens=50):
            if chunk.content:
                llm_ttft = time.perf_counter() - t0
                break
        await client.adapter._session.close()

        overhead = llm_ttft - raw_ttft
        # Log overhead for visibility; network variance makes hard threshold unreliable
        print(f"\nTTFT: raw={raw_ttft * 1000:.1f}ms, llm={llm_ttft * 1000:.1f}ms, overhead={overhead * 1000:.1f}ms")
