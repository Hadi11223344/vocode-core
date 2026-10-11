"""Tests for agent CRUD routes — /api/agents."""

import json

import pytest
from httpx import AsyncClient

from voice_platform.database import Integration

pytestmark = pytest.mark.asyncio


class TestListAgents:
    async def test_returns_empty_list(self, client: AsyncClient):
        resp = await client.get("/api/agents")
        assert resp.status_code == 200
        assert resp.json()["agents"] == []

    async def test_returns_agents_for_user(self, client: AsyncClient, test_agent):
        resp = await client.get("/api/agents")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        assert len(agents) == 1
        assert agents[0]["name"] == "Test Agent"


class TestCreateAgent:
    async def test_creates_agent(self, client: AsyncClient):
        payload = {
            "name": "New Agent",
            "prompt_preamble": "You are helpful.",
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "stt_provider": "deepgram",
            "tts_provider": "gtts",
        }
        resp = await client.post("/api/agents", json=payload)
        assert resp.status_code == 201
        agent = resp.json()["agent"]
        assert agent["name"] == "New Agent"
        assert agent["llm_provider"] == "openai"

    async def test_creates_agent_with_google_drive_integration(self, client: AsyncClient, db_session, test_user):
        integration = Integration(
            user_id=test_user.id,
            service_type="google_drive_mcp",
            name="Team Drive",
            config_json=json.dumps({"server_url": "https://drivemcp.googleapis.com/mcp/v1"}),
        )
        db_session.add(integration)
        await db_session.commit()
        await db_session.refresh(integration)

        payload = {
            "name": "Drive Agent",
            "prompt_preamble": "You are helpful.",
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "stt_provider": "deepgram",
            "tts_provider": "gtts",
            "google_drive_integration_id": integration.id,
        }
        resp = await client.post("/api/agents", json=payload)
        assert resp.status_code == 201
        agent = resp.json()["agent"]
        assert agent["google_drive_integration_id"] == integration.id

    async def test_rejects_non_drive_integration_for_drive_slot(self, client: AsyncClient, db_session, test_user):
        integration = Integration(
            user_id=test_user.id,
            service_type="google_calendar",
            name="Work Calendar",
            config_json=json.dumps({"calendar_id": "primary"}),
        )
        db_session.add(integration)
        await db_session.commit()
        await db_session.refresh(integration)

        payload = {
            "name": "Bad Drive Agent",
            "prompt_preamble": "You are helpful.",
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "stt_provider": "deepgram",
            "tts_provider": "gtts",
            "google_drive_integration_id": integration.id,
        }
        resp = await client.post("/api/agents", json=payload)
        assert resp.status_code == 422
        assert resp.json()["error"]["detail"]["field"] == "google_drive_integration_id"

    async def test_invalid_llm_provider(self, client: AsyncClient):
        payload = {
            "name": "Bad Agent",
            "prompt_preamble": "test",
            "llm_provider": "invalid",
            "stt_provider": "deepgram",
            "tts_provider": "gtts",
        }
        resp = await client.post("/api/agents", json=payload)
        assert resp.status_code == 422
        assert "Invalid LLM provider" in resp.json()["error"]["message"]

    async def test_invalid_stt_provider(self, client: AsyncClient):
        payload = {
            "name": "Bad Agent",
            "prompt_preamble": "test",
            "llm_provider": "openai",
            "stt_provider": "invalid_stt",
            "tts_provider": "gtts",
        }
        resp = await client.post("/api/agents", json=payload)
        assert resp.status_code == 422
        assert "Invalid STT provider" in resp.json()["error"]["message"]

    async def test_invalid_tts_provider(self, client: AsyncClient):
        payload = {
            "name": "Bad Agent",
            "prompt_preamble": "test",
            "llm_provider": "openai",
            "stt_provider": "deepgram",
            "tts_provider": "invalid_tts",
        }
        resp = await client.post("/api/agents", json=payload)
        assert resp.status_code == 422
        assert "Invalid TTS provider" in resp.json()["error"]["message"]

    async def test_all_valid_providers(self, client: AsyncClient):
        """Verifies that every valid provider combination is accepted."""
        for llm in ["openai", "anthropic", "groq", "gemini", "commandcode"]:
            payload = {
                "name": f"Agent-{llm}",
                "prompt_preamble": "test",
                "llm_provider": llm,
                "stt_provider": "deepgram",
                "tts_provider": "elevenlabs",
            }
            resp = await client.post("/api/agents", json=payload)
            assert resp.status_code == 201, f"Failed for llm_provider={llm}"

    async def test_invalid_llm_model_for_provider(self, client: AsyncClient):
        payload = {
            "name": "Bad Model Agent",
            "prompt_preamble": "test",
            "llm_provider": "groq",
            "llm_model": "gpt-4o-mini",
            "stt_provider": "deepgram",
            "tts_provider": "gtts",
        }
        resp = await client.post("/api/agents", json=payload)
        assert resp.status_code == 422
        assert resp.json()["error"]["detail"]["field"] == "llm_model"

    async def test_invalid_team_id_rejected(self, client: AsyncClient):
        payload = {
            "name": "Team Agent",
            "prompt_preamble": "test",
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "stt_provider": "deepgram",
            "tts_provider": "gtts",
            "team_id": 99999,
        }
        resp = await client.post("/api/agents", json=payload)
        assert resp.status_code == 422
        assert resp.json()["error"]["detail"]["field"] == "team_id"

    async def test_single_prompt_ignores_bad_transition_flexibility(self, client: AsyncClient):
        payload = {
            "name": "Single Prompt Agent",
            "prompt_preamble": "test",
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "stt_provider": "deepgram",
            "tts_provider": "gtts",
            "mode": "single_prompt",
            "transition_flexibility": "invalid",
        }
        resp = await client.post("/api/agents", json=payload)
        assert resp.status_code == 201
        assert resp.json()["agent"]["transition_flexibility"] == "invalid"

    async def test_creates_initial_prompt_version(self, client: AsyncClient, db_session):
        from voice_platform.database import PromptVersion

        payload = {
            "name": "Versioned Agent",
            "prompt_preamble": "You are versioned.",
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
            "stt_provider": "deepgram",
            "tts_provider": "gtts",
        }
        resp = await client.post("/api/agents", json=payload)
        assert resp.status_code == 201
        agent_id = resp.json()["agent"]["id"]

        result = await db_session.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(PromptVersion).where(PromptVersion.agent_id == agent_id)
        )
        versions = result.scalars().all()
        assert len(versions) == 1
        assert versions[0].version == 1
        assert versions[0].is_active is True


class TestUpdateAgent:
    async def test_update_invalid_llm_model(self, client: AsyncClient, test_agent):
        resp = await client.put(
            f"/api/agents/{test_agent.id}",
            json={"llm_model": "gpt-4o-mini"},
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["detail"]["field"] == "llm_model"

    async def test_update_unknown_fields_ignored(self, client: AsyncClient, test_agent):
        resp = await client.put(
            f"/api/agents/{test_agent.id}",
            json={"nonexistent_field": "ignored", "name": "Updated Name"},
        )
        assert resp.status_code == 200
        assert resp.json()["agent"]["name"] == "Updated Name"


class TestKnowledgeBaseLinking:
    async def test_create_agent_syncs_knowledge_base_link(self, client: AsyncClient):
        kb_resp = await client.post("/api/knowledge-bases", json={"name": "Support KB"})
        assert kb_resp.status_code == 201
        kb_id = kb_resp.json()["knowledge_base"]["id"]

        create_resp = await client.post(
            "/api/agents",
            json={
                "name": "KB Agent",
                "prompt_preamble": "You are helpful.",
                "llm_provider": "openai",
                "llm_model": "gpt-4o-mini",
                "stt_provider": "deepgram",
                "tts_provider": "gtts",
                "knowledge_base_id": kb_id,
            },
        )
        assert create_resp.status_code == 201
        agent_id = create_resp.json()["agent"]["id"]

        kb_detail = await client.get(f"/api/knowledge-bases/{kb_id}")
        assert kb_detail.status_code == 200
        assert kb_detail.json()["knowledge_base"]["agent_ids"] == [agent_id]

    async def test_update_agent_moves_knowledge_base_link(self, client: AsyncClient):
        kb1_resp = await client.post("/api/knowledge-bases", json={"name": "KB One"})
        kb2_resp = await client.post("/api/knowledge-bases", json={"name": "KB Two"})
        assert kb1_resp.status_code == 201
        assert kb2_resp.status_code == 201
        kb1_id = kb1_resp.json()["knowledge_base"]["id"]
        kb2_id = kb2_resp.json()["knowledge_base"]["id"]

        create_resp = await client.post(
            "/api/agents",
            json={
                "name": "Mover Agent",
                "prompt_preamble": "You are helpful.",
                "llm_provider": "openai",
                "llm_model": "gpt-4o-mini",
                "stt_provider": "deepgram",
                "tts_provider": "gtts",
                "knowledge_base_id": kb1_id,
            },
        )
        assert create_resp.status_code == 201
        agent_id = create_resp.json()["agent"]["id"]

        update_resp = await client.put(
            f"/api/agents/{agent_id}",
            json={"knowledge_base_id": kb2_id},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["agent"]["knowledge_base_id"] == kb2_id

        kb1_detail = await client.get(f"/api/knowledge-bases/{kb1_id}")
        kb2_detail = await client.get(f"/api/knowledge-bases/{kb2_id}")
        assert kb1_detail.json()["knowledge_base"]["agent_ids"] == []
        assert kb2_detail.json()["knowledge_base"]["agent_ids"] == [agent_id]

    async def test_delete_agent_clears_knowledge_base_link(self, client: AsyncClient):
        kb_resp = await client.post("/api/knowledge-bases", json={"name": "Cleanup KB"})
        assert kb_resp.status_code == 201
        kb_id = kb_resp.json()["knowledge_base"]["id"]

        create_resp = await client.post(
            "/api/agents",
            json={
                "name": "Delete Me",
                "prompt_preamble": "You are helpful.",
                "llm_provider": "openai",
                "llm_model": "gpt-4o-mini",
                "stt_provider": "deepgram",
                "tts_provider": "gtts",
                "knowledge_base_id": kb_id,
            },
        )
        assert create_resp.status_code == 201
        agent_id = create_resp.json()["agent"]["id"]

        delete_resp = await client.delete(f"/api/agents/{agent_id}")
        assert delete_resp.status_code == 200

        kb_detail = await client.get(f"/api/knowledge-bases/{kb_id}")
        assert kb_detail.status_code == 200
        assert kb_detail.json()["knowledge_base"]["agent_ids"] == []

    async def test_create_agent_from_template_links_knowledge_base(self, client: AsyncClient):
        kb_resp = await client.post("/api/knowledge-bases", json={"name": "Template KB"})
        assert kb_resp.status_code == 201
        kb_id = kb_resp.json()["knowledge_base"]["id"]

        create_resp = await client.post(
            "/api/agents/from-template",
            json={
                "template_id": "support",
                "name": "Template Agent",
                "knowledge_base_id": kb_id,
            },
        )
        assert create_resp.status_code == 201
        agent = create_resp.json()["agent"]
        assert agent["knowledge_base_id"] == kb_id

        kb_detail = await client.get(f"/api/knowledge-bases/{kb_id}")
        assert kb_detail.status_code == 200
        assert agent["id"] in kb_detail.json()["knowledge_base"]["agent_ids"]

    async def test_create_agent_from_template_links_google_drive(self, client: AsyncClient, db_session, test_user):
        from voice_platform.database import Integration
        integration = Integration(
            user_id=test_user.id,
            service_type="google_drive_mcp",
            name="Docs Drive",
            config_json=json.dumps({"server_url": "https://drivemcp.googleapis.com/mcp/v1"}),
        )
        db_session.add(integration)
        await db_session.commit()
        await db_session.refresh(integration)

        create_resp = await client.post(
            "/api/agents/from-template",
            json={
                "template_id": "support",
                "name": "Template Drive Agent",
                "google_drive_integration_id": integration.id,
            },
        )
        assert create_resp.status_code == 201
        agent = create_resp.json()["agent"]
        assert agent["google_drive_integration_id"] == integration.id


class TestGetAgent:
    async def test_get_existing(self, client: AsyncClient, test_agent):
        resp = await client.get(f"/api/agents/{test_agent.id}")
        assert resp.status_code == 200
        assert resp.json()["agent"]["name"] == "Test Agent"

    async def test_not_found(self, client: AsyncClient):
        resp = await client.get("/api/agents/99999")
        assert resp.status_code == 404


class TestUpdateAgent:
    async def test_update_name(self, client: AsyncClient, test_agent):
        resp = await client.put(
            f"/api/agents/{test_agent.id}",
            json={"name": "Updated Name"},
        )
        assert resp.status_code == 200
        assert resp.json()["agent"]["name"] == "Updated Name"

    async def test_partial_update(self, client: AsyncClient, test_agent):
        resp = await client.put(
            f"/api/agents/{test_agent.id}",
            json={"temperature": 1.5},
        )
        assert resp.status_code == 200
        agent = resp.json()["agent"]
        assert agent["temperature"] == 1.5
        assert agent["name"] == "Test Agent"  # unchanged

    async def test_update_links_google_drive_integration(self, client: AsyncClient, db_session, test_user, test_agent):
        integration = Integration(
            user_id=test_user.id,
            service_type="google_drive_mcp",
            name="Docs Drive",
            config_json=json.dumps({"server_url": "https://drivemcp.googleapis.com/mcp/v1"}),
        )
        db_session.add(integration)
        await db_session.commit()
        await db_session.refresh(integration)

        resp = await client.put(
            f"/api/agents/{test_agent.id}",
            json={"google_drive_integration_id": integration.id},
        )
        assert resp.status_code == 200
        assert resp.json()["agent"]["google_drive_integration_id"] == integration.id

    async def test_update_invalid_provider(self, client: AsyncClient, test_agent):
        resp = await client.put(
            f"/api/agents/{test_agent.id}",
            json={"llm_provider": "bad"},
        )
        assert resp.status_code == 400

    async def test_update_nonexistent(self, client: AsyncClient):
        resp = await client.put("/api/agents/99999", json={"name": "X"})
        assert resp.status_code == 404

    async def test_masked_api_keys_are_not_overwritten(
        self, client: AsyncClient, db_session, test_agent
    ):
        test_agent.llm_api_key = "real-llm-key"
        test_agent.stt_api_key = "real-stt-key"
        test_agent.tts_api_key = "real-tts-key"
        await db_session.commit()

        resp = await client.put(
            f"/api/agents/{test_agent.id}",
            json={
                "name": "Updated without replacing keys",
                "llm_api_key": "***",
                "stt_api_key": "***",
                "tts_api_key": "***",
            },
        )

        assert resp.status_code == 200
        await db_session.refresh(test_agent)
        assert test_agent.llm_api_key == "real-llm-key"
        assert test_agent.stt_api_key == "real-stt-key"
        assert test_agent.tts_api_key == "real-tts-key"


class TestDeleteAgent:
    async def test_soft_delete(self, client: AsyncClient, test_agent):
        resp = await client.delete(f"/api/agents/{test_agent.id}")
        assert resp.status_code == 200
        assert "deactivated" in resp.json()["message"]

    async def test_delete_nonexistent(self, client: AsyncClient):
        resp = await client.delete("/api/agents/99999")
        assert resp.status_code == 404


class TestGetProviders:
    async def test_returns_providers(self, client: AsyncClient):
        resp = await client.get("/api/agents/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "llm_providers" in data
        assert "stt_providers" in data
        assert "tts_providers" in data
        # Check at least one provider in each category
        llm_ids = [p["id"] for p in data["llm_providers"]]
        assert "openai" in llm_ids
        assert "anthropic" in llm_ids
        assert "commandcode" in llm_ids

    async def test_openrouter_in_providers(self, client: AsyncClient):
        """OpenRouter must be listed in providers so the frontend can show it."""
        resp = await client.get("/api/agents/providers")
        llm_ids = [p["id"] for p in resp.json()["llm_providers"]]
        assert "openrouter" in llm_ids


class TestWorkflowIntegration:
    """Tests for workflow_id linkage during agent creation and mode switching."""

    async def test_create_agent_with_workflow_id(self, client: AsyncClient):
        """Agent can be created with a linked workflow_id instead of graph_json."""
        # First create a workflow with a valid graph
        wf_resp = await client.post(
            "/api/workflows",
            json={
                "name": "Test Flow",
                "trigger_phrases": "[\"hello\", \"help\"]",
                "graph": {
                    "nodes": [
                        {"id": "n1", "type": "trigger", "position": {"x": 0, "y": 0},
                         "data": {"label": "Start", "nodeType": "trigger"}},
                        {"id": "n2", "type": "conversation", "position": {"x": 0, "y": 100},
                         "data": {"label": "Greet", "nodeType": "conversation"}},
                        {"id": "n3", "type": "end_call", "position": {"x": 0, "y": 200},
                         "data": {"label": "End", "nodeType": "end_call"}},
                    ],
                    "edges": [
                        {"id": "e1", "source": "n1", "target": "n2"},
                        {"id": "e2", "source": "n2", "target": "n3"},
                    ],
                },
            },
        )
        assert wf_resp.status_code == 201
        wf_id = wf_resp.json()["workflow"]["id"]

        # Create agent with workflow_id in conversational_flow mode
        agent_resp = await client.post(
            "/api/agents",
            json={
                "name": "Flow Agent",
                "prompt_preamble": "You are helpful.",
                "llm_provider": "openai",
                "llm_model": "gpt-4o-mini",
                "stt_provider": "deepgram",
                "tts_provider": "gtts",
                "mode": "conversational_flow",
                "workflow_id": wf_id,
            },
        )
        assert agent_resp.status_code == 201
        agent = agent_resp.json()["agent"]
        assert agent["mode"] == "conversational_flow"
        assert agent["workflow_id"] == wf_id

    async def test_conversational_flow_without_graph_or_workflow_rejected(self, client: AsyncClient):
        """Conversational flow mode without graph_json or workflow_id should fail."""
        resp = await client.post(
            "/api/agents",
            json={
                "name": "Bad Flow Agent",
                "prompt_preamble": "test",
                "llm_provider": "openai",
                "llm_model": "gpt-4o-mini",
                "stt_provider": "deepgram",
                "tts_provider": "gtts",
                "mode": "conversational_flow",
            },
        )
        assert resp.status_code == 422
        assert "graph_json" in resp.json()["error"]["detail"]["field"]

    async def test_create_agent_with_graph_json_still_works(self, client: AsyncClient):
        """Direct graph_json should still work for backward compat."""
        resp = await client.post(
            "/api/agents",
            json={
                "name": "Graph Agent",
                "prompt_preamble": "test",
                "llm_provider": "openai",
                "llm_model": "gpt-4o-mini",
                "stt_provider": "deepgram",
                "tts_provider": "gtts",
                "mode": "conversational_flow",
                "graph_json": {
                    "nodes": [
                        {"id": "n1", "type": "trigger", "position": {"x": 0, "y": 0},
                         "data": {"label": "Start", "nodeType": "trigger"}},
                    ],
                    "edges": [],
                },
            },
        )
        assert resp.status_code == 201
        agent = resp.json()["agent"]
        assert agent["mode"] == "conversational_flow"
        assert agent["graph_json"] is not None

    async def test_workflow_id_not_found_rejected(self, client: AsyncClient):
        """Non-existent workflow_id should be rejected."""
        resp = await client.post(
            "/api/agents",
            json={
                "name": "Bad WF Agent",
                "prompt_preamble": "test",
                "llm_provider": "openai",
                "llm_model": "gpt-4o-mini",
                "stt_provider": "deepgram",
                "tts_provider": "gtts",
                "mode": "conversational_flow",
                "workflow_id": 99999,
            },
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["detail"]["field"] == "workflow_id"

    async def test_agent_to_dict_includes_workflow_id(self, client: AsyncClient):
        """Agent.to_dict() should include workflow_id field."""
        resp = await client.post(
            "/api/agents",
            json={
                "name": "Dict Check Agent",
                "prompt_preamble": "test",
                "llm_provider": "openai",
                "llm_model": "gpt-4o-mini",
                "stt_provider": "deepgram",
                "tts_provider": "gtts",
            },
        )
        assert resp.status_code == 201
        agent = resp.json()["agent"]
        assert "workflow_id" in agent
