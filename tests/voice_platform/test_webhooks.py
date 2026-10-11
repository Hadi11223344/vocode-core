"""
GAP-03: Post-Call Webhook Tests
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_platform.events.webhook_dispatcher import WebhookDispatcher


class FakeCallLog:
    def __init__(self, id=1, agent_id=42, conversation_id="conv-abc123"):
        self.id = id
        self.agent_id = agent_id
        self.conversation_id = conversation_id
        self.direction = "inbound"
        self.from_phone = "+15551234567"
        self.to_phone = "+15559876543"
        self.status = "completed"
        self.started_at = None
        self.ended_at = None
        self.duration_secs = 300.5
        self.analysis_json = None


class FakeAgent:
    def __init__(self, webhook_url=None):
        self.webhook_url = webhook_url


@pytest.mark.asyncio
async def test_no_webhook_when_not_configured():
    """If agent has no webhook_url, nothing should be dispatched."""
    call_log = FakeCallLog(agent_id=42)
    agent = FakeAgent(webhook_url=None)

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=agent)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("voice_platform.events.webhook_dispatcher.async_session", return_value=mock_session):
        with patch.object(WebhookDispatcher, "_send_webhook") as mock_send:
            await WebhookDispatcher.dispatch_call_ended(call_log)
            mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_dispatched_when_configured():
    """If agent has webhook_url, _send_webhook should be created as a task."""
    call_log = FakeCallLog(agent_id=42)
    agent = FakeAgent(webhook_url="https://example.com/webhook")

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    )
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    # session.get is called twice: first for CallLog, then for Agent
    def mock_get(model, id):
        if model.__name__ == "CallLog":
            return call_log
        return agent

    mock_session.get = AsyncMock(side_effect=mock_get)

    with patch("voice_platform.events.webhook_dispatcher.async_session", return_value=mock_session):
        with patch("asyncio.create_task") as mock_create_task:
            await WebhookDispatcher.dispatch_call_ended(call_log)
            mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_build_payload_structure():
    """Verify payload contains all required fields."""
    call_log = FakeCallLog()
    call_log.analysis_json = json.dumps({"summary": "Test summary", "sentiment": "positive"})

    mock_transcript = MagicMock()
    mock_transcript.sender = "bot"
    mock_transcript.message = "Hello"
    mock_transcript.timestamp = 1700000000.0

    mock_action = MagicMock()
    mock_action.action_type = "transfer"
    mock_action.status = "success"
    mock_action.result_json = '{"destination": "+15559998888"}'
    mock_action.timestamp = 1700000100.0

    mock_session = AsyncMock()

    async def mock_execute(stmt):
        # First call = transcript query, second = action query
        if not hasattr(mock_execute, "call_count"):
            mock_execute.call_count = 0
        mock_execute.call_count += 1
        if mock_execute.call_count == 1:
            r = MagicMock()
            r.scalars.return_value.all.return_value = [mock_transcript]
            return r
        r = MagicMock()
        r.scalars.return_value.all.return_value = [mock_action]
        return r

    mock_session.execute = AsyncMock(side_effect=mock_execute)

    payload = await WebhookDispatcher._build_payload("call_ended", call_log, mock_session)

    assert payload["event"] == "call_ended"
    assert "timestamp" in payload
    assert payload["call"]["id"] == 1
    assert payload["call"]["conversation_id"] == "conv-abc123"
    assert len(payload["transcript"]) == 1
    assert payload["transcript"][0]["role"] == "agent"
    assert payload["transcript"][0]["message"] == "Hello"
    assert payload["analysis"]["summary"] == "Test summary"
    assert len(payload["actions"]) == 1
    assert payload["actions"][0]["tool"] == "transfer"


@pytest.mark.asyncio
async def test_sign_payload_deterministic():
    """Same payload should produce same signature."""
    from voice_platform.config import settings

    payload = {"event": "call_ended", "call": {"id": 1}}
    sig1 = WebhookDispatcher._sign_payload(payload)
    sig2 = WebhookDispatcher._sign_payload(payload)
    assert sig1 == sig2
    assert len(sig1) == 64  # SHA-256 hex


@pytest.mark.asyncio
async def test_send_webhook_success():
    """Successful webhook delivery should not retry."""
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        payload = {"event": "call_ended", "call": {"id": 1}}
        await WebhookDispatcher._send_webhook("https://example.com/hook", payload, "fake-sig")

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args.kwargs["headers"]["X-VOIA-Signature"] == "fake-sig"
        assert call_args.kwargs["headers"]["X-VOIA-Event"] == "call_ended"


@pytest.mark.asyncio
async def test_send_webhook_retry_on_500():
    """Failed webhooks should be retried up to 3 times."""
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            payload = {"event": "call_ended", "call": {"id": 1}}
            await WebhookDispatcher._send_webhook("https://example.com/hook", payload, "sig")

        assert mock_client.post.call_count == 3
