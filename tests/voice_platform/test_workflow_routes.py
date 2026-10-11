"""Tests for workflow routes — /api/workflows."""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import Agent, User, Workflow
from voice_platform.telephony import inbound_handler

pytestmark = pytest.mark.asyncio


def _minimal_graph(label: str = "Done"):
    return {
        "nodes": [
            {"id": "trigger", "type": "trigger", "data": {"nodeType": "trigger"}},
            {"id": "end", "type": "end_call", "data": {"nodeType": "end_call", "label": label}},
        ],
        "edges": [{"id": "e-trigger-end", "source": "trigger", "target": "end"}],
    }


class TestListWorkflows:
    async def test_empty(self, client: AsyncClient):
        resp = await client.get("/api/workflows")
        assert resp.status_code == 200
        assert resp.json()["workflows"] == []

    async def test_with_workflow(self, client: AsyncClient, test_workflow):
        resp = await client.get("/api/workflows")
        assert resp.status_code == 200
        wfs = resp.json()["workflows"]
        assert len(wfs) >= 1
        assert wfs[0]["name"] == "Test Workflow"


class TestCreateWorkflow:
    async def test_create(self, client: AsyncClient, test_agent):
        payload = {
            "name": "My Workflow",
            "description": "Test",
            "trigger_phrases": ["hello", "hi"],
            "agent_id": test_agent.id,
            "action_type": "webhook",
            "action_url": "https://example.com/hook",
            "requires_approval": True,
        }
        resp = await client.post("/api/workflows", json=payload)
        assert resp.status_code == 201
        wf = resp.json()["workflow"]
        assert wf["name"] == "My Workflow"
        assert wf["requires_approval"] is True

    async def test_create_minimal(self, client: AsyncClient):
        payload = {
            "name": "Minimal WF",
            "trigger_phrases": ["test trigger"],
        }
        resp = await client.post("/api/workflows", json=payload)
        assert resp.status_code == 201

    async def test_missing_name(self, client: AsyncClient):
        payload = {"trigger_phrases": ["test"]}
        resp = await client.post("/api/workflows", json=payload)
        assert resp.status_code == 422  # Pydantic validation error

    async def test_empty_trigger_phrases(self, client: AsyncClient):
        payload = {"name": "WF", "trigger_phrases": []}
        resp = await client.post("/api/workflows", json=payload)
        assert resp.status_code == 422

    async def test_create_with_stringified_trigger_phrases(self, client: AsyncClient):
        payload = {
            "name": "String Trigger WF",
            "trigger_phrases": '["hello", "hello", "  hi  "]',
        }
        resp = await client.post("/api/workflows", json=payload)
        assert resp.status_code == 201
        assert resp.json()["workflow"]["trigger_phrases"] == ["hello", "hi"]

    async def test_create_with_transition_flexibility_strict(self, client: AsyncClient):
        payload = {
            "name": "Strict WF",
            "trigger_phrases": ["strict trigger"],
            "transition_flexibility": "strict",
        }
        resp = await client.post("/api/workflows", json=payload)
        assert resp.status_code == 201
        wf = resp.json()["workflow"]
        assert wf["transition_flexibility"] == "strict"

    async def test_create_with_transition_flexibility_flex(self, client: AsyncClient):
        payload = {
            "name": "Flex WF",
            "trigger_phrases": ["flex trigger"],
            "transition_flexibility": "flex",
        }
        resp = await client.post("/api/workflows", json=payload)
        assert resp.status_code == 201
        wf = resp.json()["workflow"]
        assert wf["transition_flexibility"] == "flex"

    async def test_rejects_second_active_graph_for_same_agent(self, client: AsyncClient, test_agent):
        first = await client.post("/api/workflows", json={
            "name": "Canonical Flow",
            "trigger_phrases": ["canonical"],
            "agent_id": test_agent.id,
            "graph": _minimal_graph("Canonical End"),
        })
        assert first.status_code == 201

        second = await client.post("/api/workflows", json={
            "name": "Conflicting Flow",
            "trigger_phrases": ["conflict"],
            "agent_id": test_agent.id,
            "graph": _minimal_graph("Conflicting End"),
        })

        assert second.status_code == 422
        assert "already linked" in second.json()["error"]["message"]

    async def test_rejects_unbounded_condition_cycle(self, client: AsyncClient):
        graph = {
            "nodes": [
                {"id": "trigger", "type": "trigger", "data": {"nodeType": "trigger"}},
                {
                    "id": "ask",
                    "type": "conversation",
                    "data": {"nodeType": "conversation", "config": {"variables_to_extract": ["retry"]}},
                },
                {
                    "id": "condition",
                    "type": "condition",
                    "data": {"nodeType": "condition", "config": {"expression": "retry == yes"}},
                },
                {"id": "end", "type": "end_call", "data": {"nodeType": "end_call"}},
            ],
            "edges": [
                {"id": "e1", "source": "trigger", "target": "ask"},
                {"id": "e2", "source": "ask", "target": "condition"},
                {"id": "e3", "source": "condition", "sourceHandle": "yes", "label": "Yes", "target": "ask"},
                {"id": "e4", "source": "condition", "sourceHandle": "no", "label": "No", "target": "end"},
            ],
        }

        response = await client.post("/api/workflows", json={
            "name": "Unbounded",
            "trigger_phrases": ["unbounded"],
            "graph": graph,
        })

        assert response.status_code == 422
        assert "unbounded cycle" in response.json()["error"]["message"].lower()


class TestGetWorkflow:
    async def test_get_existing(self, client: AsyncClient, test_workflow):
        resp = await client.get(f"/api/workflows/{test_workflow.id}")
        assert resp.status_code == 200
        assert resp.json()["workflow"]["name"] == "Test Workflow"

    async def test_not_found(self, client: AsyncClient):
        resp = await client.get("/api/workflows/99999")
        assert resp.status_code == 404


class TestUpdateWorkflow:
    async def test_update_name(self, client: AsyncClient, test_workflow):
        resp = await client.put(
            f"/api/workflows/{test_workflow.id}",
            json={"name": "Updated Workflow"},
        )
        assert resp.status_code == 200
        assert resp.json()["workflow"]["name"] == "Updated Workflow"

    async def test_update_trigger_phrases(self, client: AsyncClient, test_workflow):
        resp = await client.put(
            f"/api/workflows/{test_workflow.id}",
            json={"trigger_phrases": ["new trigger"]},
        )
        assert resp.status_code == 200

    async def test_update_trigger_phrases_comma_delimited_string(self, client: AsyncClient, test_workflow):
        resp = await client.put(
            f"/api/workflows/{test_workflow.id}",
            json={"trigger_phrases": "billing issue, schedule callback, billing issue"},
        )
        assert resp.status_code == 200
        assert resp.json()["workflow"]["trigger_phrases"] == [
            "billing issue",
            "schedule callback",
        ]

    async def test_partial_update(self, client: AsyncClient, test_workflow):
        resp = await client.put(
            f"/api/workflows/{test_workflow.id}",
            json={"description": "New description"},
        )
        assert resp.status_code == 200
        assert resp.json()["workflow"]["name"] == "Test Workflow"  # unchanged

    async def test_update_nonexistent(self, client: AsyncClient):
        resp = await client.put("/api/workflows/99999", json={"name": "X"})
        assert resp.status_code == 404

    async def test_update_agent_id_rejects_foreign_agent(self, client: AsyncClient, db_session, test_workflow):
        other_user = User(
            google_id="google-other-999",
            email="other@example.com",
            name="Other User",
            role="user",
        )
        db_session.add(other_user)
        await db_session.commit()
        await db_session.refresh(other_user)

        foreign_agent = Agent(
            user_id=other_user.id,
            name="Foreign Agent",
            prompt_preamble="Foreign",
            initial_message="Hi",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            stt_provider="deepgram",
            tts_provider="gtts",
        )
        db_session.add(foreign_agent)
        await db_session.commit()
        await db_session.refresh(foreign_agent)

        resp = await client.put(
            f"/api/workflows/{test_workflow.id}",
            json={"agent_id": foreign_agent.id},
        )
        assert resp.status_code == 404
        assert "Agent #2 was not found" in resp.json()["error"]["message"]

        verify = await db_session.execute(select(Workflow).where(Workflow.id == test_workflow.id))
        refreshed = verify.scalar_one()
        assert refreshed.agent_id == test_workflow.agent_id

    async def test_reassignment_moves_graph_and_clears_previous_agent(
        self,
        client: AsyncClient,
        db_session,
        test_user,
        test_agent,
    ):
        replacement = Agent(
            user_id=test_user.id,
            name="Replacement Agent",
            prompt_preamble="Replacement",
            initial_message="Hello",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            stt_provider="deepgram",
            tts_provider="gtts",
        )
        db_session.add(replacement)
        await db_session.commit()
        await db_session.refresh(replacement)

        graph = _minimal_graph("Moved End")
        created = await client.post("/api/workflows", json={
            "name": "Move Me",
            "trigger_phrases": ["move me"],
            "agent_id": test_agent.id,
            "graph": graph,
        })
        assert created.status_code == 201

        workflow_id = created.json()["workflow"]["id"]
        updated = await client.put(
            f"/api/workflows/{workflow_id}",
            json={"agent_id": replacement.id},
        )
        assert updated.status_code == 200

        await db_session.refresh(test_agent)
        await db_session.refresh(replacement)
        assert test_agent.graph_json is None
        assert test_agent.mode == "single_prompt"
        assert json.loads(replacement.graph_json) == graph
        assert replacement.mode == "conversational_flow"

    async def test_removing_graph_clears_linked_agent(
        self,
        client: AsyncClient,
        db_session,
        test_agent,
    ):
        created = await client.post("/api/workflows", json={
            "name": "Temporary Graph",
            "trigger_phrases": ["temporary"],
            "agent_id": test_agent.id,
            "graph": _minimal_graph(),
        })
        assert created.status_code == 201

        workflow_id = created.json()["workflow"]["id"]
        updated = await client.put(f"/api/workflows/{workflow_id}", json={"graph": None})
        assert updated.status_code == 200

        await db_session.refresh(test_agent)
        assert test_agent.graph_json is None
        assert test_agent.mode == "single_prompt"


class TestDeleteWorkflow:
    async def test_soft_delete(self, client: AsyncClient, test_workflow):
        resp = await client.delete(f"/api/workflows/{test_workflow.id}")
        assert resp.status_code == 200
        assert "message" in resp.json()

    async def test_delete_nonexistent(self, client: AsyncClient):
        resp = await client.delete("/api/workflows/99999")
        assert resp.status_code == 404

    async def test_deactivate_clears_agent_runtime_graph(self, client: AsyncClient, db_session, test_agent):
        created = await client.post("/api/workflows", json={
            "name": "Deactivate Graph",
            "trigger_phrases": ["deactivate"],
            "agent_id": test_agent.id,
            "graph": _minimal_graph(),
        })
        assert created.status_code == 201

        response = await client.delete(f"/api/workflows/{created.json()['workflow']['id']}")
        assert response.status_code == 200
        await db_session.refresh(test_agent)
        assert test_agent.graph_json is None
        assert test_agent.mode == "single_prompt"


class TestExecuteWorkflowValidation:
    async def test_rejects_nested_context(self, client: AsyncClient, test_workflow):
        resp = await client.post(
            f"/api/workflows/{test_workflow.id}/execute",
            json={
                "context": {
                    "caller_name": "Alice",
                    "details": {"nested": True},
                }
            },
        )

        assert resp.status_code == 422
        assert resp.json()["error"]["detail"]["field"] == "context"
        assert "primitive or shallow list" in resp.json()["error"]["message"].lower()

    async def test_rejects_oversized_context(self, client: AsyncClient, test_workflow):
        resp = await client.post(
            f"/api/workflows/{test_workflow.id}/execute",
            json={"context": {"blob": "x" * 100_001}},
        )

        assert resp.status_code == 422
        assert resp.json()["error"]["detail"]["field"] == "context"
        assert "too large" in resp.json()["error"]["message"].lower()


class TestUpdateWorkflow:
    async def test_update_transition_flexibility(self, client: AsyncClient, test_workflow):
        resp = await client.put(
            f"/api/workflows/{test_workflow.id}",
            json={"transition_flexibility": "strict"},
        )
        assert resp.status_code == 200
        wf = resp.json()["workflow"]
        assert wf["transition_flexibility"] == "strict"

    async def test_response_includes_updated_at(self, client: AsyncClient, test_workflow):
        resp = await client.get(f"/api/workflows/{test_workflow.id}")
        assert resp.status_code == 200
        wf = resp.json()["workflow"]
        assert "updated_at" in wf
        assert wf["updated_at"] is not None


class TestExecuteWorkflowApproval:
    async def test_manual_execute_requires_approval_creates_review(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
    ):
        from voice_platform.database import Workflow

        wf = Workflow(
            user_id=test_user.id,
            name="Approval WF",
            trigger_phrases=json.dumps(["approve me"]),
            steps_json=json.dumps([{"step_number": 1, "integration_id": 0, "action": "noop", "params": {}}]),
            requires_approval=True,
        )
        db_session.add(wf)
        await db_session.commit()
        await db_session.refresh(wf)

        resp = await client.post(
            f"/api/workflows/{wf.id}/execute",
            json={"context": {"caller_name": "Test"}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "pending_approval"
        assert data["steps_executed"] == 0
        assert "review_id" in data

    async def test_manual_execute_force_bypasses_approval(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        monkeypatch,
    ):
        from voice_platform.database import Workflow
        from voice_platform.integrations import executor

        async def _noop_execute(*args, **kwargs):
            return {"mode": "steps", "results": [{"step_number": 1, "status": "success"}]}

        monkeypatch.setattr(executor.WorkflowExecutor, "execute_workflow", _noop_execute)

        wf = Workflow(
            user_id=test_user.id,
            name="Force WF",
            trigger_phrases=json.dumps(["force me"]),
            steps_json=json.dumps([{"step_number": 1, "integration_id": 0, "action": "noop", "params": {}}]),
            requires_approval=True,
        )
        db_session.add(wf)
        await db_session.commit()
        await db_session.refresh(wf)

        resp = await client.post(
            f"/api/workflows/{wf.id}/execute",
            json={"context": {"caller_name": "Test"}, "force": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "steps"
        assert data["steps_executed"] == 1


class TestWorkflowContextInjection:
    async def test_includes_graph_summary(
        self,
        db_session,
        monkeypatch,
        test_workflow,
    ):
        test_workflow.graph_json = json.dumps(
            {
                "nodes": [
                    {
                        "id": "trigger",
                        "type": "workflowNode",
                        "data": {"nodeType": "trigger", "label": "Call Trigger"},
                    },
                    {
                        "id": "step-1",
                        "type": "workflowNode",
                        "data": {
                            "nodeType": "conversation",
                            "label": "Collect caller details",
                        },
                    },
                    {
                        "id": "end",
                        "type": "workflowNode",
                        "data": {"nodeType": "end", "label": "Workflow Complete"},
                    },
                ],
                "edges": [
                    {"id": "e-trigger-step-1", "source": "trigger", "target": "step-1"},
                    {"id": "e-step-1-end", "source": "step-1", "target": "end"},
                ],
            }
        )
        test_workflow.is_active = True
        db_session.add(test_workflow)
        await db_session.commit()
        await db_session.refresh(test_workflow)

        class _SessionShim:
            def __init__(self, session):
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr(inbound_handler, "async_session", lambda: _SessionShim(db_session))

        context = await inbound_handler._get_workflow_context(test_workflow.user_id, test_workflow.agent_id)

        assert "Workflow: Test Workflow" in context
        assert "Steps:" in context
        assert "CONVERSATION: Collect caller details" in context
