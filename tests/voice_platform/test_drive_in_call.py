import json
from types import SimpleNamespace

import pytest
import pytest_asyncio

from vocode.streaming.models.actions import ActionInput
from voice_platform.actions import platform_tools
from voice_platform.actions.platform_tools import (
    PlatformToolAction,
    PlatformToolActionConfig,
    PlatformToolParameters,
    build_mcp_tool_actions_for_server,
    clear_document_cache,
    get_cached_documents,
)
from voice_platform.agents.agent_factory import build_agent_config
from voice_platform.database import Integration


@pytest.fixture(autouse=True)
def reset_drive_state():
    platform_tools._DOCUMENT_CACHE.clear()
    platform_tools._MCP_TOOL_CACHE.clear()
    platform_tools._call_tool_counts.clear()
    yield
    platform_tools._DOCUMENT_CACHE.clear()
    platform_tools._MCP_TOOL_CACHE.clear()
    platform_tools._call_tool_counts.clear()


@pytest_asyncio.fixture()
async def drive_integration(db_session, test_user):
    integration = Integration(
        user_id=test_user.id,
        service_type="google_drive_mcp",
        name="Drive MCP",
        config_json=json.dumps({"server_url": "https://drivemcp.googleapis.com/mcp/v1"}),
    )
    db_session.add(integration)
    await db_session.commit()
    await db_session.refresh(integration)
    return integration


def test_drive_document_cache_round_trip_and_clear(monkeypatch):
    current_time = [1000.0]
    monkeypatch.setattr(platform_tools.time, "time", lambda: current_time[0])

    clear_document_cache("conv-1")
    platform_tools._cache_document("conv-1", "invoice.pdf", "invoice contents")

    cached = get_cached_documents("conv-1")
    assert len(cached) == 1
    assert cached[0]["filename"] == "invoice.pdf"
    assert cached[0]["content"] == "invoice contents"

    current_time[0] = 1701.0
    assert get_cached_documents("conv-1") == []

    platform_tools._cache_document("conv-1", "invoice.pdf", "invoice contents")
    clear_document_cache("conv-1")
    assert get_cached_documents("conv-1") == []


@pytest.mark.asyncio
async def test_build_mcp_tool_actions_for_server_resolves_google_oauth_and_caches_tools(monkeypatch):
    class FakeMcpClient:
        list_tools_calls = 0

        def __init__(self, server_url: str, auth_token: str | None = None, timeout: float = 10.0):
            self.server_url = server_url
            self.auth_token = auth_token
            self.timeout = timeout

        async def list_tools(self):
            FakeMcpClient.list_tools_calls += 1
            return [
                {
                    "name": "search_files",
                    "description": "Search Drive files",
                    "inputSchema": {"type": "object", "properties": {}},
                }
            ]

        async def aclose(self):
            return None

    async def fake_get_credentials(user_id: int):
        return SimpleNamespace(token="google-access-token")

    monkeypatch.setattr("voice_platform.integrations.mcp_client.McpClient", FakeMcpClient)
    monkeypatch.setattr("voice_platform.integrations.google_oauth.GoogleOAuthManager.get_credentials", fake_get_credentials)

    actions_first = await build_mcp_tool_actions_for_server(
        "https://drivemcp.googleapis.com/mcp/v1",
        None,
        123,
    )
    actions_second = await build_mcp_tool_actions_for_server(
        "https://drivemcp.googleapis.com/mcp/v1",
        None,
        123,
    )

    assert len(actions_first) == 1
    assert len(actions_second) == 1
    assert FakeMcpClient.list_tools_calls == 1
    assert actions_first[0].tool_name == "search_files"
    assert actions_first[0].mcp_auth_token == "google-access-token"
    assert actions_second[0].mcp_auth_token == "google-access-token"


@pytest.mark.asyncio
async def test_platform_tool_action_caches_drive_file_reads(monkeypatch):
    class FakeMcpClient:
        def __init__(self, server_url: str, auth_token: str | None = None, timeout: float = 30.0):
            self.server_url = server_url
            self.auth_token = auth_token

        async def call_tool(self, tool_name: str, params: dict):
            assert tool_name == "read_file_content"
            assert params["file_id"] == "file-123"
            return "Drive file contents"

        async def aclose(self):
            return None

    monkeypatch.setattr("voice_platform.integrations.mcp_client.McpClient", FakeMcpClient)

    action = PlatformToolAction(
        PlatformToolActionConfig(
            tool_name="read_file_content",
            tool_description="Read a Drive file",
            tool_parameters_schema=json.dumps({"type": "object", "properties": {"file_id": {"type": "string"}}}),
            integration_type="mcp",
            integration_action="call_tool",
            user_id=7,
            mcp_server_url="https://drivemcp.googleapis.com/mcp/v1",
            mcp_auth_token="google-access-token",
        )
    )

    response = await action.run(
        ActionInput(
            action_config=action.action_config,
            conversation_id="conv-drive-1",
            params=PlatformToolParameters(payload={"file_id": "file-123"}),
        )
    )

    assert response.response.success is True
    assert response.response.result == "Drive file contents"
    cached_docs = get_cached_documents("conv-drive-1")
    assert len(cached_docs) == 1
    assert cached_docs[0]["filename"] == "file-123"
    assert cached_docs[0]["content"] == "Drive file contents"


@pytest.mark.asyncio
async def test_build_agent_config_appends_drive_prompt_appendix(monkeypatch, db_session, test_agent, drive_integration):
    test_agent.google_drive_integration_id = drive_integration.id

    class _SessionShim:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("voice_platform.agents.agent_factory.async_session", lambda: _SessionShim(db_session))
    monkeypatch.setattr("voice_platform.agents.agent_factory._resolve_llm_api_key", lambda *args, **kwargs: "test-openai-key")

    config = await build_agent_config(test_agent)

    assert config.actions is not None
    assert len(config.actions) == 1
    assert config.actions[0].tool_name == "read_drive_file"
    assert "Google Drive Access" in config.prompt_preamble
    assert "When the caller mentions documents" in config.prompt_preamble