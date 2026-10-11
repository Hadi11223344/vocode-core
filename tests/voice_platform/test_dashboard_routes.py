"""Tests for dashboard routes — /api/dashboard."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


class TestDashboardStats:
    async def test_empty_stats(self, client: AsyncClient):
        resp = await client.get("/api/dashboard/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] == 0
        assert data["active_calls"] == 0
        assert data["agents_count"] == 0

    async def test_with_data(self, client: AsyncClient, test_call, test_agent):
        resp = await client.get("/api/dashboard/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_calls"] >= 1
        assert data["active_calls"] >= 1
        assert data["agents_count"] >= 1

    async def test_stats_keys(self, client: AsyncClient):
        resp = await client.get("/api/dashboard/stats")
        data = resp.json()
        expected_keys = {
            "total_calls",
            "total_duration_mins",
            "avg_duration_secs",
            "active_calls",
            "calls_today",
            "calls_this_week",
            "agents_count",
        }
        assert expected_keys.issubset(set(data.keys()))


class TestDashboardRecent:
    async def test_empty(self, client: AsyncClient):
        resp = await client.get("/api/dashboard/recent")
        assert resp.status_code == 200
        assert resp.json()["recent_calls"] == []

    async def test_with_calls(self, client: AsyncClient, test_call, completed_call):
        resp = await client.get("/api/dashboard/recent")
        assert resp.status_code == 200
        recent = resp.json()["recent_calls"]
        assert len(recent) == 2
