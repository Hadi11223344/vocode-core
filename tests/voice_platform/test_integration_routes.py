"""
Tests for Integration Routes (/api/integrations).
"""

import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import Integration, User, UserApiKey

# ── Fixtures ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def gcal_api_key(db_session: AsyncSession, test_user: User) -> UserApiKey:
    key = UserApiKey(
        user_id=test_user.id,
        service="google_calendar",
        api_key='{"type": "service_account", "project_id": "test"}',
        label="Google Calendar Key",
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)
    return key


@pytest_asyncio.fixture()
async def gsheets_api_key(db_session: AsyncSession, test_user: User) -> UserApiKey:
    key = UserApiKey(
        user_id=test_user.id,
        service="google_sheets",
        api_key='{"type": "service_account", "project_id": "test"}',
        label="Google Sheets Key",
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)
    return key


@pytest_asyncio.fixture()
async def test_integration(
    db_session: AsyncSession, test_user: User, gcal_api_key: UserApiKey
) -> Integration:
    integ = Integration(
        user_id=test_user.id,
        service_type="google_calendar",
        name="Work Calendar",
        api_key_id=gcal_api_key.id,
        config_json=json.dumps({"calendar_id": "primary", "timezone": "America/New_York"}),
    )
    db_session.add(integ)
    await db_session.commit()
    await db_session.refresh(integ)
    return integ


# ── Integration Types ──────────────────────────────────────────────────

class TestIntegrationTypes:
    @pytest.mark.asyncio
    async def test_list_types(self, client):
        resp = await client.get("/api/integrations/types")
        assert resp.status_code == 200
        types = resp.json()["types"]
        type_ids = [t["id"] for t in types]
        assert "google_calendar" in type_ids
        assert "google_sheets" in type_ids

    @pytest.mark.asyncio
    async def test_types_have_capabilities(self, client):
        resp = await client.get("/api/integrations/types")
        for t in resp.json()["types"]:
            assert "capabilities" in t
            assert len(t["capabilities"]) > 0


# ── CRUD ───────────────────────────────────────────────────────────────

class TestCreateIntegration:
    @pytest.mark.asyncio
    async def test_create_gcal(self, client, gcal_api_key):
        resp = await client.post("/api/integrations", json={
            "service_type": "google_calendar",
            "name": "My Calendar",
            "api_key_id": gcal_api_key.id,
            "config": {"calendar_id": "primary"},
        })
        assert resp.status_code == 201
        data = resp.json()["integration"]
        assert data["service_type"] == "google_calendar"
        assert data["name"] == "My Calendar"
        assert data["config"]["calendar_id"] == "primary"

    @pytest.mark.asyncio
    async def test_create_invalid_type(self, client):
        resp = await client.post("/api/integrations", json={
            "service_type": "nonexistent_service",
            "name": "Bad Integration",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_gsheets_requires_spreadsheet_id(self, client, gsheets_api_key):
        resp = await client.post("/api/integrations", json={
            "service_type": "google_sheets",
            "name": "My Sheet",
            "api_key_id": gsheets_api_key.id,
        })
        assert resp.status_code == 400
        assert "spreadsheet_id" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_gsheets_with_config(self, client, gsheets_api_key):
        resp = await client.post("/api/integrations", json={
            "service_type": "google_sheets",
            "name": "Sales Sheet",
            "api_key_id": gsheets_api_key.id,
            "config": {"spreadsheet_id": "abc123", "sheet_name": "Leads"},
        })
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_create_mismatched_key(self, client, gcal_api_key):
        """api_key service must match integration service_type."""
        resp = await client.post("/api/integrations", json={
            "service_type": "google_sheets",
            "name": "Wrong Key Type",
            "api_key_id": gcal_api_key.id,
            "config": {"spreadsheet_id": "abc123"},
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_nonexistent_key(self, client):
        resp = await client.post("/api/integrations", json={
            "service_type": "google_calendar",
            "name": "No Key",
            "api_key_id": 9999,
        })
        assert resp.status_code == 404


class TestListIntegrations:
    @pytest.mark.asyncio
    async def test_list_empty(self, client):
        resp = await client.get("/api/integrations")
        assert resp.status_code == 200
        assert resp.json()["integrations"] == []

    @pytest.mark.asyncio
    async def test_list_with_data(self, client, test_integration):
        resp = await client.get("/api/integrations")
        assert resp.status_code == 200
        assert len(resp.json()["integrations"]) == 1


class TestGetIntegration:
    @pytest.mark.asyncio
    async def test_get_existing(self, client, test_integration):
        resp = await client.get(f"/api/integrations/{test_integration.id}")
        assert resp.status_code == 200
        assert resp.json()["integration"]["name"] == "Work Calendar"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, client):
        resp = await client.get("/api/integrations/9999")
        assert resp.status_code == 404


class TestUpdateIntegration:
    @pytest.mark.asyncio
    async def test_update_name(self, client, test_integration):
        resp = await client.put(f"/api/integrations/{test_integration.id}", json={
            "name": "Personal Calendar",
        })
        assert resp.status_code == 200
        assert resp.json()["integration"]["name"] == "Personal Calendar"

    @pytest.mark.asyncio
    async def test_update_config(self, client, test_integration):
        resp = await client.put(f"/api/integrations/{test_integration.id}", json={
            "config": {"calendar_id": "work@group.calendar.google.com"},
        })
        assert resp.status_code == 200
        assert resp.json()["integration"]["config"]["calendar_id"] == "work@group.calendar.google.com"

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, client):
        resp = await client.put("/api/integrations/9999", json={"name": "Nope"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_rejects_mismatched_key_service(self, client, test_integration, gsheets_api_key):
        resp = await client.put(
            f"/api/integrations/{test_integration.id}",
            json={"api_key_id": gsheets_api_key.id},
        )
        assert resp.status_code == 400
        assert "does not match" in resp.json()["detail"]


class TestDeleteIntegration:
    @pytest.mark.asyncio
    async def test_delete(self, client, test_integration):
        resp = await client.delete(f"/api/integrations/{test_integration.id}")
        assert resp.status_code == 200
        assert "deleted" in resp.json()["message"].lower() or "Work Calendar" in resp.json()["message"]

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, client):
        resp = await client.delete("/api/integrations/9999")
        assert resp.status_code == 404


# ── Google Drive File Browser ──────────────────────────────────────────

@pytest_asyncio.fixture()
async def drive_integration(db_session: AsyncSession, test_user: User) -> Integration:
    integ = Integration(
        user_id=test_user.id,
        service_type="google_drive_mcp",
        name="My Drive",
        config_json=json.dumps({"server_url": "https://drivemcp.googleapis.com/mcp/v1"}),
    )
    db_session.add(integ)
    await db_session.commit()
    await db_session.refresh(integ)
    return integ


class TestDriveFileBrowser:
    @pytest.mark.asyncio
    async def test_list_drive_files_unauthorized(self, client, drive_integration):
        """Should 401 when not authenticated."""
        resp = await client.get(f"/api/integrations/{drive_integration.id}/drive/files")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_drive_files_not_found(self, client):
        """Should 404 for non-existent integration."""
        resp = await client.get("/api/integrations/9999/drive/files")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_drive_files_no_oauth(self, client, drive_integration):
        """Should 401 when Google OAuth is not connected."""
        resp = await client.get(
            f"/api/integrations/{drive_integration.id}/drive/files",
        )
        assert resp.status_code == 401
        assert "not connected" in resp.json()["detail"].lower()


class TestDriveTestConnection:
    @pytest.mark.asyncio
    async def test_drive_test_connection_returns_401_reconnect_message(
        self, client, drive_integration, monkeypatch
    ):
        """Should return a clear reconnect message when the Drive API returns 401."""

        class FakeCredentials:
            token = "expired-token"
            refresh_token = "refresh-token"
            expired = False

        async def fake_get_credentials(user_id: int):
            return FakeCredentials()

        async def fake_test_connection(self):
            raise RuntimeError(
                'Drive API 401: { "error": { "code": 401, "message": "Request had invalid authentication credentials.'
            )

        monkeypatch.setattr(
            "voice_platform.integrations.google_oauth.GoogleOAuthManager.get_credentials",
            fake_get_credentials,
        )
        monkeypatch.setattr(
            "voice_platform.integrations.google_drive_client.GoogleDriveClient.test_connection",
            fake_test_connection,
        )

        resp = await client.post(f"/api/integrations/{drive_integration.id}/test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "reconnect" in data["message"].lower()
