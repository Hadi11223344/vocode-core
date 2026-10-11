"""Unit tests for LLMGenerationService."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from voice_platform.runtime.services.llm import LLMGenerationService
from voice_platform.runtime.llm.types import CompletionResponse


@pytest.mark.asyncio
async def test_generate_returns_content_on_success():
    """generate() returns stripped content from LLM client."""
    mock_runtime = MagicMock()
    mock_runtime.client = MagicMock()
    mock_runtime.client.complete = AsyncMock(
        return_value=CompletionResponse(content="  hello world  ")
    )
    mock_runtime.model_ref = MagicMock()
    mock_runtime.model_ref.provider = "openrouter"
    mock_runtime.model_ref.model = "test-model"

    factory = MagicMock()
    factory.create_from_agent = AsyncMock(return_value=mock_runtime)

    svc = LLMGenerationService(factory)
    result = await svc.generate(
        agent_id=1, user_id=1,
        system_prompt="system", user_prompt="user",
    )
    assert result == "hello world"
    factory.create_from_agent.assert_called_once_with(1, 1)


@pytest.mark.asyncio
async def test_generate_returns_none_when_factory_returns_none():
    """generate() returns None when factory can't build a runtime (no API key)."""
    factory = MagicMock()
    factory.create_from_agent = AsyncMock(return_value=None)

    svc = LLMGenerationService(factory)
    result = await svc.generate(
        agent_id=1, user_id=1,
        system_prompt="system", user_prompt="user",
    )
    assert result is None


@pytest.mark.asyncio
async def test_generate_returns_none_on_exception():
    """generate() returns None on LLM client exception."""
    mock_runtime = MagicMock()
    mock_runtime.client = MagicMock()
    mock_runtime.client.complete = AsyncMock(side_effect=Exception("API down"))
    mock_runtime.model_ref = MagicMock()
    mock_runtime.model_ref.provider = "openrouter"
    mock_runtime.model_ref.model = "test-model"

    factory = MagicMock()
    factory.create_from_agent = AsyncMock(return_value=mock_runtime)

    svc = LLMGenerationService(factory)
    result = await svc.generate(
        agent_id=1, user_id=1,
        system_prompt="system", user_prompt="user",
    )
    assert result is None


@pytest.mark.asyncio
async def test_generate_returns_none_for_empty_content():
    """generate() returns None for empty content."""
    mock_runtime = MagicMock()
    mock_runtime.client = MagicMock()
    mock_runtime.client.complete = AsyncMock(
        return_value=CompletionResponse(content="")
    )
    mock_runtime.model_ref = MagicMock()
    mock_runtime.model_ref.provider = "openrouter"
    mock_runtime.model_ref.model = "test-model"

    factory = MagicMock()
    factory.create_from_agent = AsyncMock(return_value=mock_runtime)

    svc = LLMGenerationService(factory)
    result = await svc.generate(
        agent_id=1, user_id=1,
        system_prompt="system", user_prompt="user",
    )
    assert result is None


@pytest.mark.asyncio
async def test_generate_passes_max_tokens_and_temperature():
    """generate() passes max_tokens and temperature to client.complete()."""
    mock_runtime = MagicMock()
    mock_runtime.client = MagicMock()
    mock_runtime.client.complete = AsyncMock(
        return_value=CompletionResponse(content="result")
    )
    mock_runtime.model_ref = MagicMock()
    mock_runtime.model_ref.provider = "openrouter"
    mock_runtime.model_ref.model = "test-model"

    factory = MagicMock()
    factory.create_from_agent = AsyncMock(return_value=mock_runtime)

    svc = LLMGenerationService(factory)
    await svc.generate(
        agent_id=1, user_id=1,
        system_prompt="system", user_prompt="user",
        max_tokens=100, temperature=0.5,
    )
    call_kwargs = mock_runtime.client.complete.call_args
    assert call_kwargs.kwargs["max_tokens"] == 100
    assert call_kwargs.kwargs["temperature"] == 0.5
