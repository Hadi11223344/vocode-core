"""Tests for campaign route helpers."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.api.campaign_routes import (
    _build_twilio_webhook_urls,
    _get_user_twilio_credentials,
)
from voice_platform.database import User, UserApiKey
from voice_platform.encryption import encrypt


def test_build_twilio_webhook_urls_normalizes_http_trailing_slash():
    voice_url, status_url = _build_twilio_webhook_urls("http://localhost:3000/")

    assert voice_url == "https://localhost:3000/inbound_call"
    assert status_url == "https://localhost:3000/call_status"


def test_build_twilio_webhook_urls_normalizes_https_domain():
    voice_url, status_url = _build_twilio_webhook_urls("https://example.ngrok-free.app")

    assert voice_url == "https://example.ngrok-free.app/inbound_call"
    assert status_url == "https://example.ngrok-free.app/call_status"


@pytest.mark.asyncio
async def test_get_user_twilio_credentials_returns_none_without_key(
    db_session: AsyncSession,
    test_user: User,
):
    creds = await _get_user_twilio_credentials(db_session, int(test_user.id))
    assert creds is None


@pytest.mark.asyncio
async def test_get_user_twilio_credentials_returns_decrypted_values(
    db_session: AsyncSession,
    test_user: User,
):
    record = UserApiKey(
        user_id=test_user.id,
        service="twilio",
        api_key=encrypt("AC1234567890"),
        api_secret=encrypt("auth-token-123"),
        is_active=True,
    )
    db_session.add(record)
    await db_session.commit()

    creds = await _get_user_twilio_credentials(db_session, int(test_user.id))
    assert creds == ("AC1234567890", "auth-token-123")
