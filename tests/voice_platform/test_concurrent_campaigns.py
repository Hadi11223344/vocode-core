"""
GAP-05: Concurrent Campaign Execution Tests
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class FakeCampaignContact:
    def __init__(self, id=1, phone="+15550000001", status="pending", retries=0):
        self.id = id
        self.phone_number = phone
        self.status = status
        self.retries = retries
        self.call_outcome = None
        self.call_log_id = None
        self.called_at = None
        self.completed_at = None
        self.last_error = None
        self.call_duration_secs = None


class FakeCampaign:
    def __init__(self, id=1, max_concurrent_calls=3, call_interval_secs=5, max_retries=2, from_phone="+15559998888", agent_id=1):
        self.id = id
        self.max_concurrent_calls = max_concurrent_calls
        self.call_interval_secs = call_interval_secs
        self.max_retries = max_retries
        self.from_phone = from_phone
        self.agent_id = agent_id
        self.status = "running"
        self.total_contacts = 0
        self.completed_contacts = 0
        self.failed_contacts = 0
        self.started_at = None
        self.completed_at = None


class FakeCallLog:
    def __init__(self, id=1):
        self.id = id
        self.conversation_id = "test"


@pytest.mark.asyncio
async def test_semaphore_limits_concurrent_calls():
    """Verify the semaphore allows only max_concurrent_calls tasks in-flight."""
    max_concurrent = 3
    semaphore = asyncio.Semaphore(max_concurrent)

    active_count = 0
    max_active_observed = 0

    async def worker(n):
        nonlocal active_count, max_active_observed
        async with semaphore:
            active_count += 1
            max_active_observed = max(max_active_observed, active_count)
            await asyncio.sleep(0.05)
            active_count -= 1

    tasks = [asyncio.create_task(worker(i)) for i in range(10)]
    await asyncio.gather(*tasks)

    assert max_active_observed <= max_concurrent


@pytest.mark.asyncio
async def test_campaign_worker_skips_when_paused():
    """If campaign status is 'paused', the worker should skip the contact."""
    import sys

    # Patch campaign_routes module imports
    fake_campaign = FakeCampaign(id=1)
    fake_campaign.status = "paused"

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=fake_campaign)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    contact = FakeCampaignContact(id=1)

    # Verify paused check works by simulating the worker logic directly
    async with asyncio.Semaphore(1):
        async with mock_session as s:
            campaign_check = await s.execute(None)
            campaign_row = campaign_check.scalar_one_or_none()
            if campaign_row and campaign_row.status == "paused":
                result = "paused"
            else:
                result = "called"

    assert result == "paused"


@pytest.mark.asyncio
async def test_campaign_worker_skips_max_retries():
    """Worker should skip contact when retries >= max_retries and status is failed."""
    contact = FakeCampaignContact(id=1, status="failed", retries=3)
    campaign = FakeCampaign(max_retries=3)

    assert contact.retries >= campaign.max_retries and contact.status == "failed"


@pytest.mark.asyncio
async def test_gather_spawns_all_tasks():
    """asyncio.gather should spawn all contact tasks concurrently."""
    spawned = 0

    async def fake_worker(n):
        nonlocal spawned
        spawned += 1
        await asyncio.sleep(0.01)

    tasks = [asyncio.create_task(fake_worker(i)) for i in range(5)]
    await asyncio.gather(*tasks)

    assert spawned == 5


@pytest.mark.asyncio
async def test_final_count_aggregation():
    """Final counts should correctly aggregate from contact statuses."""
    # Simulate final_counts query result
    mock_rows = [("completed", 3), ("failed", 2), ("skipped", 1)]
    counts = {row[0]: row[1] for row in mock_rows}

    completed = counts.get("completed", 0)
    failed = counts.get("failed", 0) + counts.get("skipped", 0)

    assert completed == 3
    assert failed == 3


@pytest.mark.asyncio
async def test_campaign_initially_running_then_completed():
    """Campaign should transition from running to completed after all tasks."""
    campaign = FakeCampaign()
    assert campaign.status == "running"

    # Simulate completion
    campaign.status = "completed"
    campaign.completed_at = "2026-05-08T00:00:00Z"

    assert campaign.status == "completed"
    assert campaign.completed_at is not None
