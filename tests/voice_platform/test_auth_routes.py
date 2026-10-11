"""Tests for auth routes focused on dev-login hardening."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_dev_login_disabled_by_default(client: AsyncClient):
    response = await client.post(
        "/api/auth/dev-login",
        json={"email": "dev1@example.com", "name": "Dev One"},
    )

    assert response.status_code == 403
    assert "ALLOW_DEV_LOGIN" in response.json()["detail"]


async def test_dev_login_enabled_with_explicit_flag(client: AsyncClient, monkeypatch):
    from voice_platform.api import auth_routes

    monkeypatch.setattr(auth_routes.settings, "allow_dev_login", True)

    response = await client.post(
        "/api/auth/dev-login",
        json={"email": "dev2@example.com", "name": "Dev Two"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "dev2@example.com"
    assert isinstance(body["access_token"], str) and body["access_token"]


async def test_google_auth_rejects_unverified_email(client: AsyncClient, monkeypatch):
    from voice_platform.api import auth_routes

    def _fake_verify_google_token(_: str):
        return {
            "sub": "google-user-1",
            "email": "user@example.com",
            "email_verified": False,
            "name": "User",
        }

    monkeypatch.setattr(auth_routes, "verify_google_token", _fake_verify_google_token)

    response = await client.post(
        "/api/auth/google",
        json={"id_token": "fake-token"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Google account email must be verified"


async def test_google_auth_rejects_missing_email(client: AsyncClient, monkeypatch):
    from voice_platform.api import auth_routes

    def _fake_verify_google_token(_: str):
        return {
            "sub": "google-user-2",
            "email_verified": True,
            "name": "No Email User",
        }

    monkeypatch.setattr(auth_routes, "verify_google_token", _fake_verify_google_token)

    response = await client.post(
        "/api/auth/google",
        json={"id_token": "fake-token"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Google account email must be verified"
