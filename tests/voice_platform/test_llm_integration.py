"""Integration tests — verify full wiring path that unit tests may miss.

These tests mock the transport layer (httpx/SDK) but exercise the full
LLMClient → middleware → retry → timeout → adapter → translator stack.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_platform.runtime.llm.adapters import OllamaAdapter, OpenAIAdapter
from voice_platform.runtime.llm.client import LLMClient
from voice_platform.runtime.llm.factory import LLMFactory
from voice_platform.runtime.llm.middleware import MessagePipeline, MiddlewareContext, PIIRedactor
from voice_platform.runtime.llm.retry import RetryExecutor
from voice_platform.runtime.llm.session import ProviderSession
from voice_platform.runtime.llm.timeout import TimeoutExecutor
from voice_platform.runtime.llm.types import ProviderConfig, RetryPolicy, TimeoutPolicy


@pytest.mark.asyncio
async def test_integration_openai_adapter_complete():
    """OpenAIAdapter → mocked SDK → translator → CompletionResponse."""
    session = MagicMock(spec=ProviderSession)
    # Mock the SDK client's chat.completions.create
    mock_message = MagicMock()
    mock_message.content = "Hello from OpenAI"
    mock_message.tool_calls = None
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_choice.finish_reason = "stop"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = MagicMock(prompt_tokens=5, completion_tokens=5, total_tokens=10)

    session.sdk_client.chat.completions.create = AsyncMock(return_value=mock_response)

    adapter = OpenAIAdapter(session=session, model="gpt-4o")
    client = LLMClient(
        adapter=adapter,
        retry=RetryExecutor(RetryPolicy(max_retries=0)),
        timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
    )
    result = await client.complete([{"role": "user", "content": "Hi"}])
    assert result.content == "Hello from OpenAI"
    assert result.usage["total_tokens"] == 10


@pytest.mark.asyncio
async def test_integration_ollama_adapter_complete():
    """OllamaAdapter → mocked httpx → translator → CompletionResponse."""
    session = ProviderSession(
        api_key="ollama",
        base_url="http://localhost:11434/v1",
        timeout=60.0,
    )

    # Mock httpx response
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "message": {"content": "Hello from Ollama"},
        "done": True,
        "eval_count": 5,
        "prompt_eval_count": 3,
    }
    mock_http_client = MagicMock()
    mock_http_client.post = AsyncMock(return_value=mock_resp)
    mock_http_client.aclose = AsyncMock()
    session._http._client = mock_http_client

    adapter = OllamaAdapter(session=session, model="qwen3:8b")
    client = LLMClient(
        adapter=adapter,
        retry=RetryExecutor(RetryPolicy(max_retries=0)),
        timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
    )
    result = await client.complete([{"role": "user", "content": "Hi"}])
    assert result.content == "Hello from Ollama"
    assert result.usage["total_tokens"] == 8

    # Verify payload was built correctly
    call_args = mock_http_client.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["model"] == "qwen3:8b"
    assert payload["think"] is False
    assert payload["stream"] is False


@pytest.mark.asyncio
async def test_integration_llm_client_full_stack():
    """LLMClient → middleware (PII) → retry → timeout → adapter → translator."""
    session = ProviderSession(
        api_key="ollama",
        base_url="http://localhost:11434/v1",
        timeout=60.0,
    )

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "message": {"content": "Response"},
        "done": True,
        "eval_count": 1,
        "prompt_eval_count": 1,
    }
    mock_http_client = MagicMock()
    mock_http_client.post = AsyncMock(return_value=mock_resp)
    mock_http_client.aclose = AsyncMock()
    session._http._client = mock_http_client

    pipeline = MessagePipeline([PIIRedactor()])
    # Build client manually to use our mocked session
    adapter = OllamaAdapter(session=session, model="qwen3:8b")
    client = LLMClient(
        adapter=adapter,
        retry=RetryExecutor(RetryPolicy(max_retries=0)),
        timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
        middleware=pipeline,
    )
    ctx = MiddlewareContext(provider="ollama", model="qwen3:8b", conversation_id="test-123")
    result = await client.complete(
        [{"role": "user", "content": "My SSN is 123-45-6789"}],
        context=ctx,
    )
    assert result.content == "Response"

    # Verify PII was redacted before reaching the adapter
    call_args = mock_http_client.post.call_args
    payload = call_args.kwargs["json"]
    user_msg = payload["messages"][0]["content"]
    assert "123-45-6789" not in user_msg


@pytest.mark.asyncio
async def test_integration_ollama_streaming():
    """OllamaAdapter → mocked httpx stream → translator → StreamChunks."""
    session = ProviderSession(
        api_key="ollama",
        base_url="http://localhost:11434/v1",
        timeout=60.0,
    )

    # Mock streaming response
    class MockStreamContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aiter_lines(self):
            yield json.dumps({"message": {"content": "Hello"}, "done": False})
            yield json.dumps({"message": {"content": " world"}, "done": False})
            yield json.dumps({"message": {"content": ""}, "done": True})

    mock_resp = MockStreamContext()
    mock_resp.raise_for_status = MagicMock()
    mock_http_client = MagicMock()
    mock_http_client.stream = MagicMock(return_value=mock_resp)
    mock_http_client.aclose = AsyncMock()
    session._http._client = mock_http_client

    adapter = OllamaAdapter(session=session, model="qwen3:8b")
    client = LLMClient(
        adapter=adapter,
        retry=RetryExecutor(RetryPolicy(max_retries=0)),
        timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
    )
    chunks = []
    async for chunk in client.stream([{"role": "user", "content": "Hi"}]):
        chunks.append(chunk)
    assert len(chunks) == 3
    assert chunks[0].content == "Hello"
    assert chunks[1].content == " world"
    assert chunks[2].finish_reason == "stop"
