"""Tests for review routes — /api/reviews."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from voice_platform.database import ReviewQueue

pytestmark = pytest.mark.asyncio

# The execute_action is imported inside the approve endpoint function body from
# voice_platform.actions.action_executor, so we patch at that module path.
EXEC_ACTION_PATH = "voice_platform.actions.action_executor.execute_action"


class TestListReviews:
    async def test_empty(self, client: AsyncClient):
        resp = await client.get("/api/reviews")
        assert resp.status_code == 200
        assert resp.json()["reviews"] == []
        assert resp.json()["total"] == 0

    async def test_with_review(self, client: AsyncClient, test_review):
        resp = await client.get("/api/reviews")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    async def test_filter_by_status(self, client: AsyncClient, test_review):
        resp = await client.get("/api/reviews?status=pending")
        assert resp.status_code == 200
        for r in resp.json()["reviews"]:
            assert r["status"] == "pending"

    async def test_pagination(self, client: AsyncClient, test_review):
        resp = await client.get("/api/reviews?page=1&per_page=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["per_page"] == 1


class TestGetReview:
    async def test_get_existing(self, client: AsyncClient, test_review):
        resp = await client.get(f"/api/reviews/{test_review.id}")
        assert resp.status_code == 200
        assert resp.json()["review"]["status"] == "pending"

    async def test_not_found(self, client: AsyncClient):
        resp = await client.get("/api/reviews/99999")
        assert resp.status_code == 404


class TestApproveReview:
    @patch(EXEC_ACTION_PATH, new_callable=AsyncMock, return_value={"success": True})
    async def test_approve(self, mock_exec, client: AsyncClient, test_review):
        resp = await client.post(
            f"/api/reviews/{test_review.id}/approve",
            json={"notes": "Looks good"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["review"]["status"] == "approved"
        assert "approved" in data["message"].lower()

    async def test_approve_nonexistent(self, client: AsyncClient):
        resp = await client.post("/api/reviews/99999/approve", json={})
        assert resp.status_code == 404

    @patch(EXEC_ACTION_PATH, new_callable=AsyncMock, return_value={"success": True})
    async def test_approve_already_approved(self, mock_exec, client: AsyncClient, test_review):
        # First approve
        await client.post(f"/api/reviews/{test_review.id}/approve", json={})
        # Attempt to approve again
        resp = await client.post(f"/api/reviews/{test_review.id}/approve", json={})
        assert resp.status_code == 422
        assert "already" in resp.json()["error"]["message"].lower()

    @patch(EXEC_ACTION_PATH, new_callable=AsyncMock, return_value={"success": False, "error": "downstream failed"})
    async def test_approve_failed_execution_keeps_review_pending(self, mock_exec, client: AsyncClient, db_session, test_review):
        resp = await client.post(f"/api/reviews/{test_review.id}/approve", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["review"]["status"] == "pending"
        assert data["execution"]["success"] is False
        assert "remains pending" in data["message"].lower()

        result = await db_session.execute(select(ReviewQueue).where(ReviewQueue.id == test_review.id))
        refreshed = result.scalar_one()
        assert refreshed.status == "pending"

    @patch("voice_platform.integrations.executor.WorkflowExecutor.execute_workflow", new_callable=AsyncMock)
    async def test_approve_workflow_execution_runs_steps(self, mock_execute_workflow, client: AsyncClient, db_session, test_user, test_call):
        mock_execute_workflow.return_value = {
            "mode": "graph",
            "results": [{"status": "success", "result": {"ok": True}}],
        }
        review = ReviewQueue(
            call_log_id=test_call.id,
            user_id=test_user.id,
            workflow_id=123,
            action_type="workflow_execution",
            action_url=None,
            action_params=json.dumps({
                "workflow_id": 123,
                "steps": [
                    {
                        "step_number": 1,
                        "integration_id": 0,
                        "action": "notification",
                        "params": {"message": "hello"},
                    }
                ],
                "context": {"caller_phone": "+15551234567"},
            }),
            trigger_context="test",
            status="pending",
        )
        db_session.add(review)
        await db_session.commit()
        await db_session.refresh(review)

        resp = await client.post(f"/api/reviews/{review.id}/approve", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["review"]["status"] == "approved"
        assert data["execution"]["success"] is True
        assert data["execution"]["mode"] == "graph"
        assert data["execution"]["steps_executed"] == 1
        assert mock_execute_workflow.await_count == 1

        # ensure persisted as approved
        result = await db_session.execute(select(ReviewQueue).where(ReviewQueue.id == review.id))
        updated = result.scalar_one()
        assert updated.status == "approved"


class TestRejectReview:
    async def test_reject(self, client: AsyncClient, test_review):
        resp = await client.post(
            f"/api/reviews/{test_review.id}/reject",
            json={"notes": "Not appropriate"},
        )
        assert resp.status_code == 200
        assert resp.json()["review"]["status"] == "rejected"

    async def test_reject_nonexistent(self, client: AsyncClient):
        resp = await client.post("/api/reviews/99999/reject", json={})
        assert resp.status_code == 404

    @patch(EXEC_ACTION_PATH, new_callable=AsyncMock, return_value={"success": True})
    async def test_reject_already_approved(self, mock_exec, client: AsyncClient, test_review):
        await client.post(f"/api/reviews/{test_review.id}/approve", json={})
        resp = await client.post(f"/api/reviews/{test_review.id}/reject", json={})
        assert resp.status_code == 422
        assert "already" in resp.json()["error"]["message"].lower()
