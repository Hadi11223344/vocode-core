"""
Regression tests for Google Drive 401 authentication fix.

Covers:
- OAuth manager sets Credentials.expiry so expired tokens are detected.
- OAuth manager refreshes expired tokens before returning them.
- GoogleDriveClient refreshes expired tokens before API requests.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
import pytest_asyncio
from google.oauth2.credentials import Credentials
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import GoogleOAuthToken, User
from voice_platform.encryption import decrypt, encrypt
from voice_platform.integrations.google_drive_client import GoogleDriveClient
from voice_platform.integrations.google_oauth import GoogleOAuthManager


@pytest.fixture
def patch_google_oauth_session(monkeypatch, db_session):
    """Patch database.async_session so GoogleOAuthManager uses the test db_session."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _session():
        yield db_session

    monkeypatch.setattr("voice_platform.database.async_session", _session)


@pytest_asyncio.fixture()
async def valid_google_oauth_token(
    db_session: AsyncSession, test_user: User
) -> GoogleOAuthToken:
    """Create a Google OAuth token row that is still valid."""
    token = GoogleOAuthToken(
        user_id=test_user.id,
        access_token=encrypt("valid-access-token"),
        refresh_token=encrypt("refresh-token"),
        token_type="Bearer",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scopes=json.dumps(
            [
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.readonly",
                "https://www.googleapis.com/auth/drive.file",
            ]
        ),
    )
    db_session.add(token)
    await db_session.commit()
    await db_session.refresh(token)
    return token


@pytest_asyncio.fixture()
async def expired_google_oauth_token(
    db_session: AsyncSession, test_user: User
) -> GoogleOAuthToken:
    """Create a Google OAuth token row with an expired access token."""
    token = GoogleOAuthToken(
        user_id=test_user.id,
        access_token=encrypt("old-access-token"),
        refresh_token=encrypt("refresh-token"),
        token_type="Bearer",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        scopes=json.dumps(
            [
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive.readonly",
                "https://www.googleapis.com/auth/drive.file",
            ]
        ),
    )
    db_session.add(token)
    await db_session.commit()
    await db_session.refresh(token)
    return token


@pytest.mark.asyncio
async def test_get_credentials_sets_expiry(
    db_session, test_user, valid_google_oauth_token, patch_google_oauth_session
):
    """Credentials.expiry must be set from the DB token so creads.expired is accurate."""
    creds = await GoogleOAuthManager.get_credentials(test_user.id)

    assert creds is not None
    assert creds.token == "valid-access-token"
    assert creds.expiry is not None
    assert creds.expiry.tzinfo is None
    assert creds.expired is False


@pytest.mark.asyncio
async def test_get_credentials_refreshes_expired_token(
    db_session,
    test_user,
    expired_google_oauth_token,
    monkeypatch,
    patch_google_oauth_session,
):
    """An expired token should be refreshed automatically and the DB updated."""

    def fake_refresh(self, request):
        self.token = "new-access-token"
        self.expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    creds = await GoogleOAuthManager.get_credentials(test_user.id)

    assert creds.token == "new-access-token"
    assert creds.expired is False

    await db_session.refresh(expired_google_oauth_token)
    assert decrypt(expired_google_oauth_token.access_token) == "new-access-token"


@pytest.mark.asyncio
async def test_drive_client_refreshes_expired_token(monkeypatch):
    """GoogleDriveClient refreshes an expired Credentials object before a request."""

    def fake_refresh(self, request):
        self.token = "refreshed-drive-token"
        self.expiry = datetime.now(timezone.utc) + timedelta(hours=1)

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    creds = Credentials(
        token="old-drive-token",
        refresh_token="refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client-id",
        client_secret="client-secret",
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
        expiry=(datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None),
    )

    client = GoogleDriveClient(access_token="old-drive-token", credentials=creds)
    await client._refresh_token()
    await client.aclose()

    assert client._token == "refreshed-drive-token"
    assert creds.token == "refreshed-drive-token"


@pytest.mark.asyncio
async def test_drive_client_skips_refresh_when_not_expired(monkeypatch):
    """GoogleDriveClient does not refresh a token that is still valid."""
    refresh_called = False

    def fake_refresh(self, request):
        nonlocal refresh_called
        refresh_called = True
        self.token = "should-not-change"

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    creds = Credentials(
        token="valid-drive-token",
        refresh_token="refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client-id",
        client_secret="client-secret",
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
        expiry=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None),
    )

    client = GoogleDriveClient(access_token="valid-drive-token", credentials=creds)
    await client._refresh_token()
    await client.aclose()

    assert refresh_called is False
    assert client._token == "valid-drive-token"
