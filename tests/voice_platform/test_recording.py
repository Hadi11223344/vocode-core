"""
GAP-09: Call Recording Playback Tests
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request


class FakeForm:
    def __init__(self, data: dict):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)


@pytest.mark.asyncio
async def test_recording_status_callback_updates_call_log():
    """Verify recording URL is stored when Twilio callback fires."""
    from voice_platform.api.twilio_routes import recording_status

    # Build a fake request with form data
    request = MagicMock(spec=Request)
    request.form = AsyncMock(return_value=FakeForm({
        "CallSid": "CA1234567890abcdef",
        "RecordingUrl": "https://api.twilio.com/2010-04-01/Accounts/ACxx/Recordings/RExx",
        "RecordingSid": "RE1234567890abcdef",
        "RecordingDuration": "120",
    }))

    # Mock DB session with a matching CallLog
    db = MagicMock()
    call_log = MagicMock()
    call_log.recording_url = None

    result_mock = MagicMock()
    result_mock.scalar_one_or_none = MagicMock(return_value=call_log)
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()

    response = await recording_status(request, db)

    # The .mp3 suffix should have been appended
    assert call_log.recording_url.endswith(".mp3")
    db.commit.assert_awaited_once()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_recording_status_callback_ignores_missing_sid():
    """Verify callback with no CallSid returns gracefully."""
    from voice_platform.api.twilio_routes import recording_status

    request = MagicMock(spec=Request)
    request.form = AsyncMock(return_value=FakeForm({}))

    db = MagicMock()
    db.execute = AsyncMock()

    response = await recording_status(request, db)

    # Should not have queried DB
    db.execute.assert_not_called()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_recording_status_callback_ignores_unknown_call():
    """Verify callback handles call not found gracefully."""
    from voice_platform.api.twilio_routes import recording_status

    request = MagicMock(spec=Request)
    request.form = AsyncMock(return_value=FakeForm({
        "CallSid": "CAunknown123",
        "RecordingUrl": "https://example.com/rec.mp3",
    }))

    db = MagicMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()

    response = await recording_status(request, db)

    db.commit.assert_not_called()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_recording_status_appends_mp3_if_missing():
    """Verify .mp3 extension is appended to bare Twilio URLs."""
    from voice_platform.api.twilio_routes import recording_status

    request = MagicMock(spec=Request)
    request.form = AsyncMock(return_value=FakeForm({
        "CallSid": "CAtest123",
        "RecordingUrl": "https://api.twilio.com/path/to/recording",
    }))

    db = MagicMock()
    call_log = MagicMock()
    call_log.recording_url = None

    result_mock = MagicMock()
    result_mock.scalar_one_or_none = MagicMock(return_value=call_log)
    db.execute = AsyncMock(return_value=result_mock)
    db.commit = AsyncMock()

    await recording_status(request, db)

    assert call_log.recording_url == "https://api.twilio.com/path/to/recording.mp3"
