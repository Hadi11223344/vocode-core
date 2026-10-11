"""Tests for call routes — /api/calls."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestListCalls:
    async def test_empty_list(self, client: AsyncClient):
        resp = await client.get("/api/calls")
        assert resp.status_code == 200
        data = resp.json()
        assert data["calls"] == []
        assert data["total"] == 0

    async def test_with_calls(self, client: AsyncClient, test_call):
        resp = await client.get("/api/calls")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    async def test_pagination(self, client: AsyncClient, test_call, completed_call):
        resp = await client.get("/api/calls?page=1&per_page=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["calls"]) == 1
        assert data["per_page"] == 1
        assert data["pages"] >= 2

    async def test_filter_by_status(self, client: AsyncClient, test_call, completed_call):
        resp = await client.get("/api/calls?status=active")
        assert resp.status_code == 200
        for call in resp.json()["calls"]:
            assert call["status"] == "active"


class TestGetActiveCalls:
    async def test_returns_active(self, client: AsyncClient, test_call):
        resp = await client.get("/api/calls/active")
        assert resp.status_code == 200
        calls = resp.json()["active_calls"]
        assert len(calls) >= 1
        assert all(c["status"] == "active" for c in calls)

    async def test_excludes_completed(self, client: AsyncClient, completed_call):
        resp = await client.get("/api/calls/active")
        assert resp.status_code == 200
        ids = [c["conversation_id"] for c in resp.json()["active_calls"]]
        assert completed_call.conversation_id not in ids


class TestGetCallDetail:
    async def test_get_existing(self, client: AsyncClient, test_call, test_transcript):
        resp = await client.get(f"/api/calls/{test_call.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["call"]["conversation_id"] == "conv-test-001"
        assert len(data["transcript"]) == 2

    async def test_not_found(self, client: AsyncClient):
        resp = await client.get("/api/calls/99999")
        assert resp.status_code == 404


class TestEndCall:
    async def test_end_active_call(self, client: AsyncClient, test_call):
        resp = await client.post(f"/api/calls/{test_call.id}/end")
        assert resp.status_code == 200
        assert resp.json()["call"]["status"] == "completed"
        assert resp.json()["call"]["ended_at"] is not None

    async def test_end_already_completed(self, client: AsyncClient, completed_call):
        resp = await client.post(f"/api/calls/{completed_call.id}/end")
        assert resp.status_code == 400

    async def test_end_nonexistent(self, client: AsyncClient):
        resp = await client.post("/api/calls/99999/end")
        assert resp.status_code == 404
