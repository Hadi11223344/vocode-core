"""Unit tests for EmbeddingClient."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from voice_platform.runtime.embeddings.client import EmbeddingClient
from voice_platform.runtime.llm.session import ProviderSession
from voice_platform.runtime.llm.retry import RetryExecutor
from voice_platform.runtime.llm.timeout import TimeoutExecutor
from voice_platform.runtime.llm.types import RetryPolicy, TimeoutPolicy


@pytest.mark.asyncio
async def test_embedding_client_embed():
    """EmbeddingClient.embed() calls SDK and returns vectors."""
    session = ProviderSession(api_key="sk-test", timeout=30.0)

    # Mock the SDK client
    mock_data_item = MagicMock()
    mock_data_item.embedding = [0.1, 0.2, 0.3]
    mock_response = MagicMock()
    mock_response.data = [mock_data_item]
    session._sdk._client = MagicMock()
    session._sdk._client.embeddings.create = AsyncMock(return_value=mock_response)

    client = EmbeddingClient(
        session=session,
        retry=RetryExecutor(RetryPolicy(max_retries=0)),
        timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=30.0)),
    )
    result = await client.embed(["hello world"], model="text-embedding-3-small")
    assert result is not None
    assert len(result) == 1
    assert result[0] == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_embedding_client_empty_texts():
    """EmbeddingClient.embed() returns [] for empty input."""
    session = ProviderSession(api_key="sk-test", timeout=30.0)
    client = EmbeddingClient(
        session=session,
        retry=RetryExecutor(RetryPolicy()),
        timeout=TimeoutExecutor(TimeoutPolicy()),
    )
    result = await client.embed([])
    assert result == []


@pytest.mark.asyncio
async def test_embedding_client_failure_returns_none():
    """EmbeddingClient.embed() returns None on API failure."""
    session = ProviderSession(api_key="sk-test", timeout=30.0)
    session._sdk._client = MagicMock()
    session._sdk._client.embeddings.create = AsyncMock(side_effect=Exception("API down"))

    client = EmbeddingClient(
        session=session,
        retry=RetryExecutor(RetryPolicy(max_retries=0)),
        timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=30.0)),
    )
    result = await client.embed(["hello"], model="text-embedding-3-small")
    assert result is None
