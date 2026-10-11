"""
GAP-02: Warm Transfer with Context Whisper Tests
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from starlette.datastructures import QueryParams


class FakeForm:
    def __init__(self, data: dict):
        self._data = data

    async def multi_items(self):
        return list(self._data.items())

    def get(self, key, default=""):
        return self._data.get(key, default)


def _make_request(query: dict = None, form: dict = None):
    req = MagicMock(spec=Request)
    req.query_params = QueryParams(query or {})
    req.form = AsyncMock(return_value=FakeForm(form or {}))
    req.app.state.base_url = "https://demo.voia.io"
    return req


@pytest.mark.asyncio
async def test_transfer_dial_includes_whisper_url():
    """Verify transfer TwiML includes whisper URL on Number element and hold music."""
    from voice_platform.api.twilio_routes import transfer_dial_twiML

    req = _make_request(
        query={"To": "+15551234567", "conversation_id": "conv-abc123"},
        form={"From": "+15559876543"},
    )

    response = await transfer_dial_twiML(req)
    twiml = response.body.decode()

    assert "<Dial" in twiml
    assert "<Number" in twiml
    assert "whisper?conversation_id=conv-abc123" in twiml
    assert "+15551234567" in twiml
    assert "<Say" in twiml  # hold message


@pytest.mark.asyncio
async def test_transfer_dial_without_destination_returns_error():
    """Verify missing destination returns error TwiML."""
    from voice_platform.api.twilio_routes import transfer_dial_twiML

    req = _make_request(query={})
    response = await transfer_dial_twiML(req)
    twiml = response.body.decode()

    assert "Unable to complete transfer" in twiml
    assert "<Dial" not in twiml


@pytest.mark.asyncio
async def test_transfer_call_passes_destination_to_dial_endpoint():
    """The REST redirect must preserve the requested transfer destination."""
    from voice_platform.api.twilio_routes import TransferCallRequest, transfer_call

    twilio_client = MagicMock()
    req = _make_request()
    transfer_request = TransferCallRequest(
        call_sid="CA1234567890",
        destination="+15551234567",
    )

    with patch(
        "voice_platform.api.twilio_routes._get_twilio_client",
        new_callable=AsyncMock,
        return_value=(twilio_client, "sid", "token", None),
    ):
        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            result = await transfer_call(
                transfer_request,
                req,
                user=MagicMock(),
                db=AsyncMock(),
            )

    update_kwargs = mock_to_thread.await_args.kwargs
    assert "To=%2B15551234567" in update_kwargs["url"]
    assert "conversation_id=CA1234567890" in update_kwargs["url"]
    assert update_kwargs["fallback_url"] == update_kwargs["url"]
    assert result["success"] is True


@pytest.mark.asyncio
async def test_transfer_status_on_success_returns_empty():
    """Successful transfer status should return empty response."""
    from voice_platform.api.twilio_routes import transfer_status

    req = _make_request(
        query={"conversation_id": "conv-abc123"},
        form={"DialCallStatus": "completed"},
    )

    response = await transfer_status(req)
    assert response.body == b""


@pytest.mark.asyncio
async def test_transfer_status_on_failure_reconnects_ai():
    """Failed transfer should return TwiML reconnecting caller to AI stream."""
    from voice_platform.api.twilio_routes import transfer_status

    req = _make_request(
        query={"conversation_id": "conv-abc123"},
        form={"DialCallStatus": "busy"},
    )

    response = await transfer_status(req)
    twiml = response.body.decode()

    assert "I'm sorry, I wasn't able to connect you" in twiml
    assert "<Connect>" in twiml or "<Connect" in twiml
    assert "connect_call/conv-abc123" in twiml


@pytest.mark.asyncio
async def test_transfer_whisper_handles_missing_conv_id():
    """Whisper without conversation_id should return fallback message."""
    from voice_platform.api.twilio_routes import transfer_whisper

    req = _make_request(query={})
    response = await transfer_whisper(req)
    twiml = response.body.decode()

    assert "No context available" in twiml


@pytest.mark.asyncio
async def test_transfer_whisper_handles_missing_call_log():
    """Whisper with unknown conversation_id should return fallback message."""
    from voice_platform.api.twilio_routes import transfer_whisper

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("voice_platform.database.async_session", return_value=mock_session):
        req = _make_request(query={"conversation_id": "conv-unknown"})
        response = await transfer_whisper(req)
        twiml = response.body.decode()

    assert "Context not found" in twiml


@pytest.mark.asyncio
async def test_transfer_whisper_generates_summary():
    """Whisper with existing call log and transcripts should include summary."""
    from voice_platform.api.twilio_routes import transfer_whisper

    call_log = MagicMock()
    call_log.id = 1

    t1 = MagicMock()
    t1.sender = "human"
    t1.message = "I want to upgrade my plan."
    t1.timestamp = 1.0

    t2 = MagicMock()
    t2.sender = "bot"
    t2.message = "I can help with that."
    t2.timestamp = 2.0

    transcripts = [t1, t2]

    # First execute -> CallLog, second -> Transcript query
    exec_results = []

    def make_scalar_result(obj):
        r = MagicMock()
        r.scalar_one_or_none = MagicMock(return_value=obj)
        return r

    def make_scalars_result(items):
        r = MagicMock()
        r.scalars.return_value.all = MagicMock(return_value=items)
        return r

    async def fake_execute(stmt):
        # First call: select(CallLog)
        if len(exec_results) == 0:
            exec_results.append("call_log")
            return make_scalar_result(call_log)
        # Second call: select(Transcript)
        exec_results.append("transcript")
        return make_scalars_result(transcripts)

    mock_session = AsyncMock()
    mock_session.execute = fake_execute
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("voice_platform.database.async_session", return_value=mock_session):
        with patch("voice_platform.api.twilio_routes._generate_transfer_summary", new_callable=AsyncMock) as mock_summary:
            mock_summary.return_value = "Customer wants to upgrade. Already discussed pricing."
            req = _make_request(query={"conversation_id": "conv-123"})
            response = await transfer_whisper(req)
            twiml = response.body.decode()

    assert "Incoming transferred call" in twiml
    assert "Customer wants to upgrade" in twiml
    mock_summary.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_transfer_summary_falls_back_on_httpx_failure():
    """If LLM API call fails, fallback to transcript excerpt."""
    from voice_platform.api.twilio_routes import _generate_transfer_summary

    text = "Customer: I need help\nAgent: I can help you\nCustomer: Great thanks"

    with patch.dict("os.environ", {"GROQ_API_KEY": "fake-key"}):
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(side_effect=Exception("API down"))
            result = await _generate_transfer_summary(text)

    assert "Customer: I need help" in result


@pytest.mark.asyncio
async def test_generate_transfer_summary_empty_input():
    """Empty transcript should return 'No transcript available.'"""
    from voice_platform.api.twilio_routes import _generate_transfer_summary

    result = await _generate_transfer_summary("")
    assert result == "No transcript available."

    result = await _generate_transfer_summary("   ")
    assert result == "No transcript available."
