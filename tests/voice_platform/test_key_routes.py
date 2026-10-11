"""
Tests for API Key Management Routes (/api/keys).
"""

import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import VALID_KEY_SERVICES, User, UserApiKey

# ── Fixtures ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def test_api_key(db_session: AsyncSession, test_user: User) -> UserApiKey:
    key = UserApiKey(
        user_id=test_user.id,
        service="openai",
        api_key="sk-test1234567890abcdefghijklmnop",
        label="My OpenAI Key",
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)
    return key


@pytest_asyncio.fixture()
async def test_twilio_key(db_session: AsyncSession, test_user: User) -> UserApiKey:
    key = UserApiKey(
        user_id=test_user.id,
        service="twilio",
        api_key="ACtest123456789",
        api_secret="auth_token_test_secret",
        metadata_json=json.dumps({"phone_number": "+15551234567", "account_sid": "ACtest123456789"}),
        label="My Twilio",
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)
    return key


# ── Services Endpoint ──────────────────────────────────────────────────

class TestListServices:
    @pytest.mark.asyncio
    async def test_list_services(self, client):
        resp = await client.get("/api/keys/services")
        assert resp.status_code == 200
        data = resp.json()
        services = data["services"]
        assert len(services) >= 7
        service_ids = [s["id"] for s in services]
        assert "openai" in service_ids
        assert "gemini" in service_ids
        assert "deepgram" in service_ids
        assert "twilio" in service_ids
        assert "google_calendar" in service_ids
        assert "google_sheets" in service_ids

    @pytest.mark.asyncio
    async def test_services_have_required_fields(self, client):
        resp = await client.get("/api/keys/services")
        for s in resp.json()["services"]:
            assert "id" in s
            assert "name" in s
            assert "category" in s
            assert "description" in s


# ── CRUD Operations ───────────────────────────────────────────────────

class TestCreateKey:
    @pytest.mark.asyncio
    async def test_create_key(self, client):
        resp = await client.post("/api/keys", json={
            "service": "openai",
            "api_key": "sk-newkey1234567890abcdefghijk",
            "label": "Test Key",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["key"]["service"] == "openai"
        assert "sk-n" in data["key"]["masked_key"]  # Masked
        assert "hijk" in data["key"]["masked_key"]   # Last 4 chars visible
        assert data["key"]["label"] == "Test Key"

    @pytest.mark.asyncio
    async def test_create_gemini_key(self, client):
        resp = await client.post("/api/keys", json={
            "service": "gemini",
            "api_key": "AIzaSyTestGeminiKey123456789",
        })
        assert resp.status_code == 201
        assert resp.json()["key"]["service"] == "gemini"

    @pytest.mark.asyncio
    async def test_create_invalid_service(self, client):
        resp = await client.post("/api/keys", json={
            "service": "invalid_service",
            "api_key": "test-key",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_twilio_requires_secret(self, client):
        resp = await client.post("/api/keys", json={
            "service": "twilio",
            "api_key": "ACtest123",
        })
        assert resp.status_code == 400
        assert "api_secret" in resp.json()["detail"].lower() or "Auth Token" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_twilio_with_secret(self, client):
        resp = await client.post("/api/keys", json={
            "service": "twilio",
            "api_key": "ACtest123456789test",
            "api_secret": "auth_token_secret_value",
            "metadata_json": json.dumps({"phone_number": "+15551234567"}),
        })
        assert resp.status_code == 201
        assert resp.json()["key"]["has_secret"] is True

    @pytest.mark.asyncio
    async def test_create_replaces_existing(self, client, test_api_key):
        """Creating a key for an existing service updates it instead."""
        resp = await client.post("/api/keys", json={
            "service": "openai",
            "api_key": "sk-brandnew1234567890abcdefgh",
        })
        assert resp.status_code == 201
        assert "Updated" in resp.json()["message"]

    @pytest.mark.asyncio
    async def test_invalid_metadata_json(self, client):
        resp = await client.post("/api/keys", json={
            "service": "deepgram",
            "api_key": "dg-test-key-12345678901234567",
            "metadata_json": "not valid json {{{",
        })
        assert resp.status_code == 400


class TestListKeys:
    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        resp = await client.get("/api/keys")
        assert resp.status_code == 200
        assert resp.json()["keys"] == []

    @pytest.mark.asyncio
    async def test_list_with_keys(self, client, test_api_key, test_twilio_key):
        resp = await client.get("/api/keys")
        assert resp.status_code == 200
        keys = resp.json()["keys"]
        assert len(keys) == 2

    @pytest.mark.asyncio
    async def test_keys_are_masked(self, client, test_api_key):
        resp = await client.get("/api/keys")
        key = resp.json()["keys"][0]
        # Full key should NOT be visible
        assert key["masked_key"] != "sk-test1234567890abcdefghijklmnop"
        # But masked version should have first 4 and last 4
        assert "..." in key["masked_key"]


class TestGetKeyByService:
    @pytest.mark.asyncio
    async def test_get_existing(self, client, test_api_key):
        resp = await client.get("/api/keys/openai")
        assert resp.status_code == 200
        assert resp.json()["key"]["service"] == "openai"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, client):
        resp = await client.get("/api/keys/gemini")
        assert resp.status_code == 404


class TestUpdateKey:
    @pytest.mark.asyncio
    async def test_update_label(self, client, test_api_key):
        resp = await client.put(f"/api/keys/{test_api_key.id}", json={
            "label": "Updated Label",
        })
        assert resp.status_code == 200
        assert resp.json()["key"]["label"] == "Updated Label"

    @pytest.mark.asyncio
    async def test_update_deactivate(self, client, test_api_key):
        resp = await client.put(f"/api/keys/{test_api_key.id}", json={
            "is_active": False,
        })
        assert resp.status_code == 200
        assert resp.json()["key"]["is_active"] is False

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, client):
        resp = await client.put("/api/keys/9999", json={"label": "Nope"})
        assert resp.status_code == 404


class TestDeleteKey:
    @pytest.mark.asyncio
    async def test_delete(self, client, test_api_key):
        resp = await client.delete(f"/api/keys/{test_api_key.id}")
        assert resp.status_code == 200
        assert "openai" in resp.json()["message"].lower()

        # Verify it's gone
        resp2 = await client.get("/api/keys")
        assert len(resp2.json()["keys"]) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, client):
        resp = await client.delete("/api/keys/9999")
        assert resp.status_code == 404


class TestValidateKey:
    @pytest.mark.asyncio
    async def test_validate_existing(self, client, test_api_key):
        resp = await client.get("/api/keys/validate/openai")
        assert resp.status_code == 200
        assert resp.json()["has_key"] is True
        assert resp.json()["is_active"] is True

    @pytest.mark.asyncio
    async def test_validate_missing(self, client):
        resp = await client.get("/api/keys/validate/gemini")
        assert resp.status_code == 200
        assert resp.json()["has_key"] is False
