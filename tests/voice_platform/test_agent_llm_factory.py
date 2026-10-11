"""Unit tests for AgentLLMFactory."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from voice_platform.runtime.llm.factory import AgentLLMFactory
from voice_platform.runtime.llm.types import LLMRuntime


@pytest.mark.asyncio
async def test_create_from_agent_no_agent_id_uses_platform_defaults():
    """create_from_agent with no agent_id uses platform defaults."""
    session = MagicMock()
    factory = AgentLLMFactory(session)

    with patch.object(AgentLLMFactory, "_resolve_platform_api_key", return_value="test-key"):
        with patch.object(AgentLLMFactory, "_build_runtime") as mock_build:
            mock_build.return_value = MagicMock(spec=LLMRuntime)
            result = await factory.create_from_agent(None, user_id=1)
            assert result is not None
            mock_build.assert_called_once()


@pytest.mark.asyncio
async def test_create_from_agent_returns_none_when_no_api_key():
    """create_from_agent returns None when no API key is available."""
    session = MagicMock()
    factory = AgentLLMFactory(session)

    with patch.object(AgentLLMFactory, "_resolve_platform_api_key", return_value=None):
        result = await factory.create_from_agent(None, user_id=1)
        assert result is None


@pytest.mark.asyncio
async def test_create_from_agent_with_agent_id_queries_db():
    """create_from_agent with agent_id queries the DB for agent config."""
    mock_agent = MagicMock()
    mock_agent.llm_provider = "openai"
    mock_agent.llm_model = "gpt-4"
    mock_agent.llm_api_key = "agent-key"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_agent)

    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    factory = AgentLLMFactory(session)

    with patch.object(AgentLLMFactory, "_build_runtime") as mock_build:
        mock_build.return_value = MagicMock(spec=LLMRuntime)
        result = await factory.create_from_agent(agent_id=42, user_id=1)
        assert result is not None
        call_kwargs = mock_build.call_args.kwargs
        assert call_kwargs["provider"] == "openai"
        assert call_kwargs["model"] == "gpt-4"
        assert call_kwargs["api_key"] == "agent-key"


@pytest.mark.asyncio
async def test_create_from_agent_agent_not_found_falls_back():
    """create_from_agent falls back to platform defaults when agent not found."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)

    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    factory = AgentLLMFactory(session)

    with patch.object(AgentLLMFactory, "_resolve_platform_api_key", return_value="platform-key"):
        with patch.object(AgentLLMFactory, "_build_runtime") as mock_build:
            mock_build.return_value = MagicMock(spec=LLMRuntime)
            result = await factory.create_from_agent(agent_id=999, user_id=1)
            assert result is not None
            call_kwargs = mock_build.call_args.kwargs
            assert call_kwargs["api_key"] == "platform-key"


def test_resolve_platform_api_key_openrouter():
    with patch("voice_platform.runtime.llm.factory.settings") as mock_settings:
        mock_settings.openrouter_api_key = "or-key"
        assert AgentLLMFactory._resolve_platform_api_key("openrouter") == "or-key"


def test_resolve_platform_api_key_openai():
    with patch("voice_platform.runtime.llm.factory.settings") as mock_settings:
        mock_settings.openai_api_key = "oai-key"
        assert AgentLLMFactory._resolve_platform_api_key("openai") == "oai-key"


def test_resolve_platform_api_key_unknown_provider():
    with patch("voice_platform.runtime.llm.factory.settings") as mock_settings:
        assert AgentLLMFactory._resolve_platform_api_key("unknown") is None


def test_resolve_base_url_known_providers():
    assert AgentLLMFactory._resolve_base_url("openrouter") == "https://openrouter.ai/api/v1"
    assert AgentLLMFactory._resolve_base_url("gemini") == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert AgentLLMFactory._resolve_base_url("groq") == "https://api.groq.com/openai/v1"


def test_resolve_base_url_unknown_provider():
    assert AgentLLMFactory._resolve_base_url("unknown") is None


def test_build_runtime_returns_llm_runtime():
    """_build_runtime returns an LLMRuntime with client, context, and model_ref."""
    with patch("voice_platform.runtime.llm.factory.LLMFactory.create") as mock_create:
        mock_client = MagicMock()
        mock_create.return_value = mock_client

        runtime = AgentLLMFactory._build_runtime(
            provider="openrouter",
            model="test-model",
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
        )
        assert isinstance(runtime, LLMRuntime)
        assert runtime.client is mock_client
        assert runtime.model_ref.provider == "openrouter"
        assert runtime.model_ref.model == "test-model"
        assert runtime.middleware_context.provider == "openrouter"
        assert runtime.middleware_context.model == "test-model"
