"""
GAP-01: Live Knowledge Base Retrieval Tests
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vocode.streaming.agent.chat_gpt_agent import ChatGPTAgent
from vocode.streaming.models.agent import ChatGPTAgentConfig


class MockTranscript:
    def __init__(self, last_msg=None):
        self._last = last_msg

    def get_last_user_message(self):
        return self._last


@pytest.fixture
def agent_with_kb():
    config = ChatGPTAgentConfig(
        openai_api_key="test-key",
        prompt_preamble="You are a helpful assistant.",
        model_name="gpt-4o-mini",
        knowledge_base_id=42,
    )
    agent = ChatGPTAgent(agent_config=config)
    agent.transcript = MockTranscript(("human", "What is enterprise pricing?"))
    return agent


@pytest.fixture
def agent_without_kb():
    config = ChatGPTAgentConfig(
        openai_api_key="test-key",
        prompt_preamble="You are a helpful assistant.",
        model_name="gpt-4o-mini",
    )
    agent = ChatGPTAgent(agent_config=config)
    agent.transcript = MockTranscript(("human", "Hello"))
    return agent


@pytest.mark.asyncio
async def test_kb_retrieval_skipped_when_no_kb_configured(agent_without_kb):
    """Agents without knowledge_base_id should skip retrieval immediately."""
    result = await agent_without_kb._retrieve_live_kb_context()
    assert result is None


@pytest.mark.asyncio
async def test_kb_retrieval_skipped_when_no_transcript(agent_with_kb):
    """If transcript is None, retrieval should return None."""
    agent_with_kb.transcript = None
    result = await agent_with_kb._retrieve_live_kb_context()
    assert result is None


@pytest.mark.asyncio
async def test_kb_retrieval_skipped_when_no_user_message(agent_with_kb):
    """If there's no user message in transcript, return None."""
    agent_with_kb.transcript = MockTranscript(None)
    result = await agent_with_kb._retrieve_live_kb_context()
    assert result is None


@pytest.mark.asyncio
async def test_kb_retrieval_returns_context_on_match(agent_with_kb):
    """When KB has matching chunks, formatted context should be returned."""
    mock_kb = MagicMock()
    mock_kb.is_active = True
    mock_kb.name = "Product Docs"
    mock_kb.chunks_json = json.dumps([
        "Our enterprise pricing is $99 per month with unlimited calls.",
        "The basic plan starts at $19 per month.",
        "Enterprise includes priority support and custom integrations.",
    ])
    mock_kb.content = None
    mock_kb.chunk_size = 500
    mock_kb.max_chunks_per_query = 3

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_kb)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("voice_platform.database.async_session", return_value=mock_session):
        with patch("redis.asyncio.from_url") as mock_redis_factory:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)  # cache miss
            mock_redis.aclose = AsyncMock()
            mock_redis_factory.return_value = mock_redis
            result = await agent_with_kb._retrieve_live_kb_context()

    assert result is not None
    assert "Product Docs" in result
    assert "enterprise" in result.lower()


@pytest.mark.asyncio
async def test_kb_retrieval_returns_none_when_kb_inactive(agent_with_kb):
    """Inactive KB should result in no context injection."""
    mock_kb = MagicMock()
    mock_kb.is_active = False

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_kb)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("voice_platform.database.async_session", return_value=mock_session):
        result = await agent_with_kb._retrieve_live_kb_context()

    assert result is None


@pytest.mark.asyncio
async def test_kb_retrieval_returns_none_when_no_chunks(agent_with_kb):
    """KB with no chunks and no content should return None."""
    mock_kb = MagicMock()
    mock_kb.is_active = True
    mock_kb.chunks_json = None
    mock_kb.content = None

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_kb)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("voice_platform.database.async_session", return_value=mock_session):
        result = await agent_with_kb._retrieve_live_kb_context()

    assert result is None


@pytest.mark.asyncio
async def test_kb_retrieval_falls_back_to_content_chunking(agent_with_kb):
    """If chunks_json is empty but content exists, chunk on the fly."""
    mock_kb = MagicMock()
    mock_kb.is_active = True
    mock_kb.name = "Pricing FAQ"
    mock_kb.chunks_json = None
    mock_kb.content = "Enterprise pricing is $99/mo. Basic is $19/mo. Pro is $49/mo."
    mock_kb.chunk_size = 100
    mock_kb.max_chunks_per_query = 2

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_kb)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("voice_platform.database.async_session", return_value=mock_session):
        with patch("redis.asyncio.from_url") as mock_redis_factory:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)  # cache miss
            mock_redis.aclose = AsyncMock()
            mock_redis_factory.return_value = mock_redis
            with patch("voice_platform.integrations.knowledge_base.KnowledgeBaseClient.retrieve") as retrieve_patch:
                retrieve_patch.return_value = [{"chunk": "Enterprise pricing is $99/mo.", "score": 0.5, "index": 0}]
                with patch("voice_platform.integrations.knowledge_base.KnowledgeBaseClient.format_context") as format_patch:
                    format_patch.return_value = "Pricing FAQ context"
                    result = await agent_with_kb._retrieve_live_kb_context()

    assert result is not None
    assert "Pricing FAQ context" == result


@pytest.mark.asyncio
async def test_kb_retrieval_graceful_on_db_error(agent_with_kb):
    """Database errors should be caught and return None (don't break the call)."""
    with patch("voice_platform.database.async_session", side_effect=Exception("DB down")):
        result = await agent_with_kb._retrieve_live_kb_context()
    assert result is None


@pytest.mark.asyncio
async def test_kb_retrieval_uses_last_human_message_as_query(agent_with_kb):
    """The query passed to retrieve() should be the last human message text."""
    mock_kb = MagicMock()
    mock_kb.is_active = True
    mock_kb.name = "Test KB"
    mock_kb.chunks_json = json.dumps(["Chunk one", "Chunk two"])
    mock_kb.content = None
    mock_kb.chunk_size = 500
    mock_kb.max_chunks_per_query = 2

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_kb)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("voice_platform.database.async_session", return_value=mock_session) as session_patch:
        with patch("voice_platform.integrations.knowledge_base.KnowledgeBaseClient.retrieve") as retrieve_patch:
            retrieve_patch.return_value = [{"chunk": "test", "score": 0.5, "index": 0}]
            with patch("voice_platform.integrations.knowledge_base.KnowledgeBaseClient.format_context") as format_patch:
                format_patch.return_value = "formatted context"
                result = await agent_with_kb._retrieve_live_kb_context()

    # Verify retrieve was called with the correct query
    retrieve_patch.assert_called_once()
    call_args = retrieve_patch.call_args
    assert call_args.kwargs["query"] == "What is enterprise pricing?"
