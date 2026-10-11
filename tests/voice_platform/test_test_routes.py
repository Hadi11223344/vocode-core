"""Tests for test case CRUD and simulation endpoints."""

from typing import Any, cast

import pytest
from httpx import AsyncClient

from voice_platform.database import TestCase, TestRun

pytestmark = pytest.mark.asyncio


async def test_create_test_case(client: AsyncClient, test_agent):
    """Creating a test case should return 200 with the test case data."""
    response = await client.post(
        f"/api/agents/{test_agent.id}/test_cases",
        json={
            "label": "Greeting Test",
            "user_prompt": "Hello, can you help me?",
            "success_criteria": "hello, welcome, help",
            "criteria_type": "keyword",
        },
    )
    assert response.status_code == 200
    tc = response.json()["test_case"]
    assert tc["label"] == "Greeting Test"
    assert tc["user_prompt"] == "Hello, can you help me?"
    assert tc["criteria_type"] == "keyword"
    assert tc["agent_id"] == test_agent.id


async def test_list_test_cases(client: AsyncClient, test_agent):
    """Listing test cases should return all cases for the agent."""
    await client.post(
        f"/api/agents/{test_agent.id}/test_cases",
        json={
            "label": "Test 1",
            "user_prompt": "Hi",
            "success_criteria": "hello",
            "criteria_type": "keyword",
        },
    )
    await client.post(
        f"/api/agents/{test_agent.id}/test_cases",
        json={
            "label": "Test 2",
            "user_prompt": "Bye",
            "success_criteria": "goodbye",
            "criteria_type": "keyword",
        },
    )
    response = await client.get(f"/api/agents/{test_agent.id}/test_cases")
    assert response.status_code == 200
    cases = response.json()["test_cases"]
    assert len(cases) == 2


async def test_update_test_case(client: AsyncClient, test_agent):
    """Updating a test case should modify the correct fields."""
    create_resp = await client.post(
        f"/api/agents/{test_agent.id}/test_cases",
        json={
            "label": "Original",
            "user_prompt": "Hello",
            "success_criteria": "hi",
            "criteria_type": "keyword",
        },
    )
    tc_id = create_resp.json()["test_case"]["id"]

    response = await client.put(
        f"/api/agents/{test_agent.id}/test_cases/{tc_id}",
        json={"label": "Updated Label", "criteria_type": "contains"},
    )
    assert response.status_code == 200
    tc = response.json()["test_case"]
    assert tc["label"] == "Updated Label"
    assert tc["criteria_type"] == "contains"
    assert tc["user_prompt"] == "Hello"  # unchanged


async def test_delete_test_case(client: AsyncClient, test_agent):
    """Deleting a test case should remove it."""
    create_resp = await client.post(
        f"/api/agents/{test_agent.id}/test_cases",
        json={
            "label": "To Delete",
            "user_prompt": "test",
            "success_criteria": "test",
            "criteria_type": "keyword",
        },
    )
    tc_id = create_resp.json()["test_case"]["id"]

    response = await client.delete(f"/api/agents/{test_agent.id}/test_cases/{tc_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True

    list_resp = await client.get(f"/api/agents/{test_agent.id}/test_cases")
    cases = list_resp.json()["test_cases"]
    assert len(cases) == 0


async def test_create_test_case_invalid_criteria_type(client: AsyncClient, test_agent):
    """Invalid criteria_type should return 422."""
    response = await client.post(
        f"/api/agents/{test_agent.id}/test_cases",
        json={
            "label": "Bad",
            "user_prompt": "test",
            "success_criteria": "test",
            "criteria_type": "invalid_type",
        },
    )
    assert response.status_code == 422


async def test_test_case_not_found(client: AsyncClient, test_agent):
    """Updating a non-existent test case should return 404."""
    response = await client.put(
        f"/api/agents/{test_agent.id}/test_cases/99999",
        json={"label": "Nope"},
    )
    assert response.status_code == 404


async def test_simulate_with_mock(client: AsyncClient, test_agent, monkeypatch):
    """Simulate endpoint should return pass/fail based on response evaluation."""
    from voice_platform.api import test_routes

    async def _fake_run_simulation(agent, user_id, user_prompt, success_criteria, criteria_type, tc_id, db):
        return {
            "id": 1,
            "test_case_id": tc_id,
            "user_prompt": user_prompt,
            "agent_response": "Hello! Welcome, how can I help?",
            "passed": True,
            "criteria_type": criteria_type,
            "success_criteria": success_criteria,
            "latency_ms": 150,
            "tokens": 42,
        }

    monkeypatch.setattr(test_routes, "_run_simulation", _fake_run_simulation)

    response = await client.post(
        f"/api/agents/{test_agent.id}/simulate",
        json={
            "user_prompt": "Hi there",
            "success_criteria": "hello, welcome",
            "criteria_type": "keyword",
        },
    )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["passed"] is True
    assert result["agent_response"] == "Hello! Welcome, how can I help?"


async def test_batch_test_with_mock(client: AsyncClient, test_agent, monkeypatch):
    """Batch test should return summary with pass/fail counts."""
    from voice_platform.api import test_routes

    # Create two test cases
    await client.post(
        f"/api/agents/{test_agent.id}/test_cases",
        json={"label": "Test 1", "user_prompt": "Hi", "success_criteria": "hello", "criteria_type": "keyword"},
    )
    await client.post(
        f"/api/agents/{test_agent.id}/test_cases",
        json={"label": "Test 2", "user_prompt": "Bye", "success_criteria": "goodbye", "criteria_type": "keyword"},
    )

    call_count = 0

    async def _fake_run_simulation(agent, user_id, user_prompt, success_criteria, criteria_type, tc_id, db):
        nonlocal call_count
        call_count += 1
        return {
            "id": call_count,
            "test_case_id": tc_id,
            "user_prompt": user_prompt,
            "agent_response": "Hello!" if call_count == 1 else "Goodbye!",
            "passed": call_count == 1,
            "criteria_type": criteria_type,
            "success_criteria": success_criteria,
            "latency_ms": 100,
            "tokens": 10,
        }

    monkeypatch.setattr(test_routes, "_run_simulation", _fake_run_simulation)

    response = await client.post(f"/api/agents/{test_agent.id}/batch_test")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["passed"] == 1
    assert data["failed"] == 1
    assert len(data["results"]) == 2


async def test_batch_test_empty(client: AsyncClient, test_agent):
    """Batch test with no test cases should return empty summary."""
    response = await client.post(f"/api/agents/{test_agent.id}/batch_test")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["passed"] == 0


async def test_test_history(client: AsyncClient, test_agent, db_session):
    """Test history should return recent test runs."""
    from datetime import datetime, timezone

    run = TestRun(
        agent_id=test_agent.id,
        user_id=cast(Any, test_agent.user_id),
        test_case_id=None,
        user_prompt="test prompt",
        agent_response="test response",
        passed=True,
        criteria_type="keyword",
        success_criteria="test",
        latency_ms=100,
        tokens_used=10,
    )
    db_session.add(run)
    await db_session.commit()

    response = await client.get(f"/api/agents/{test_agent.id}/test_history")
    assert response.status_code == 200
    runs = response.json()["test_runs"]
    assert len(runs) >= 1
    assert runs[0]["user_prompt"] == "test prompt"
    assert runs[0]["passed"] is True


async def test_evaluate_response_keyword():
    """Keyword evaluation should match any comma-separated keyword."""
    from voice_platform.api.test_routes import _evaluate_response

    assert _evaluate_response("Hello, welcome!", "keyword", "hello, goodbye") is True
    assert _evaluate_response("Goodbye!", "keyword", "hello, welcome") is False


async def test_evaluate_response_contains():
    """Contains evaluation should check exact substring."""
    from voice_platform.api.test_routes import _evaluate_response

    assert _evaluate_response("I can help you", "contains", "help you") is True
    assert _evaluate_response("I can assist", "contains", "help you") is False


async def test_evaluate_response_not_contains():
    """Not_contains evaluation should pass when substring is absent."""
    from voice_platform.api.test_routes import _evaluate_response

    assert _evaluate_response("Hello there", "not_contains", "goodbye") is True
    assert _evaluate_response("Hello and goodbye", "not_contains", "goodbye") is False


async def test_simulate_nonexistent_agent(client: AsyncClient):
    """Simulating on a non-existent agent should return 404."""
    response = await client.post(
        "/api/agents/99999/simulate",
        json={
            "user_prompt": "Hi",
            "success_criteria": "hello",
            "criteria_type": "keyword",
        },
    )
    assert response.status_code == 404


async def test_create_test_case_nonexistent_agent(client: AsyncClient):
    """Creating a test case for a non-existent agent should return 404."""
    response = await client.post(
        "/api/agents/99999/test_cases",
        json={
            "label": "Test",
            "user_prompt": "Hi",
            "success_criteria": "hello",
            "criteria_type": "keyword",
        },
    )
    assert response.status_code == 404


async def test_delete_nonexistent_test_case(client: AsyncClient, test_agent):
    """Deleting a non-existent test case should return 404."""
    response = await client.delete(f"/api/agents/{test_agent.id}/test_cases/99999")
    assert response.status_code == 404


async def test_simulate_empty_prompt(client: AsyncClient, test_agent):
    """Simulate with empty user_prompt should return 422."""
    response = await client.post(
        f"/api/agents/{test_agent.id}/simulate",
        json={
            "user_prompt": "",
            "success_criteria": "hello",
            "criteria_type": "keyword",
        },
    )
    assert response.status_code == 422
