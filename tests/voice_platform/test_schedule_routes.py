"""Tests for scheduled call scheduler behavior."""

from datetime import datetime, timedelta, timezone

import pytest

from voice_platform.api import schedule_routes
from voice_platform.database import ScheduledCall

pytestmark = pytest.mark.asyncio


class TestScheduledCallRecovery:
    async def test_reaps_stale_executing_calls(self, db_session, monkeypatch, test_user, test_agent):
        stale_updated_at = datetime.now(timezone.utc) - timedelta(hours=3)
        scheduled_call = ScheduledCall(
            user_id=test_user.id,
            agent_id=test_agent.id,
            contact_name="Test Contact",
            phone_number="+15555550123",
            scheduled_at=stale_updated_at - timedelta(minutes=10),
            timezone="UTC",
            recurrence="none",
            status="executing",
            last_error=None,
            retry_count=0,
            updated_at=stale_updated_at,
        )
        db_session.add(scheduled_call)
        await db_session.commit()
        await db_session.refresh(scheduled_call)

        class _SessionShim:
            def __init__(self, session):
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr(schedule_routes, "async_session", lambda: _SessionShim(db_session))

        await schedule_routes.execute_pending_scheduled_calls()

        await db_session.refresh(scheduled_call)

        assert scheduled_call.status == "failed"
        assert scheduled_call.retry_count == 1
        assert "timed out waiting for the completion callback" in (scheduled_call.last_error or "")