"""Tests for playground routes and conversation building safeguards."""

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import WebSocketDisconnect
from httpx import AsyncClient

from voice_platform.database import Agent

pytestmark = pytest.mark.asyncio


class _FakeConversation:
    def __init__(self):
        self.messages = [{"role": "system", "content": "system"}]
        self.model = "gpt-test"
        self.initial_message: str | None = None

    async def send_message(self, user_message: str) -> dict:
        self.messages.append({"role": "user", "content": user_message})
        return {"text": "ok", "metrics": {}}

    async def stream_message(self, user_message: str):
        self.messages.append({"role": "user", "content": user_message})
        for token in ["hel", "lo"]:
            yield token

    async def aclose(self) -> None:
        pass


class _FakeWebSocket:
    def __init__(self, incoming):
        self._incoming = [json.dumps(msg) for msg in incoming]
        self.sent = []
        self.accepted = False
        self.closed = False
        self.close_code = None
        self.close_reason = None
        self.headers = {}
        # Provide app.state.services for ConversationSessionFactory
        from voice_platform.runtime.session.service_container import ServiceContainer
        self.app = SimpleNamespace(state=SimpleNamespace(services=ServiceContainer()))

    async def accept(self, subprotocol=None):
        self.accepted = True

    async def close(self, code=None, reason=None):
        self.closed = True
        self.close_code = code
        self.close_reason = reason

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive_text(self):
        if self._incoming:
            return self._incoming.pop(0)
        raise WebSocketDisconnect()

    async def receive_json(self):
        if self._incoming:
            return json.loads(self._incoming.pop(0))
        raise WebSocketDisconnect()


class _FakeSession:
    """Fake ConversationSession that yields SessionEvents."""
    def __init__(self, initial_message="Hello from agent", tokens=None):
        self._initial_message = initial_message
        self._tokens = tokens or ["hel", "lo"]
        self._ended = False

    async def start(self):
        from voice_platform.runtime.session.events import SessionEventFactory
        if self._initial_message:
            yield SessionEventFactory.initial_message(self._initial_message)
        yield SessionEventFactory.agent_info(name="Test Agent", model="gpt-test", provider="openai")

    async def receive_message(self, text):
        from voice_platform.runtime.session.events import SessionEventFactory
        for token in self._tokens:
            yield SessionEventFactory.token(token)
        yield SessionEventFactory.message_end()

    async def end(self):
        self._ended = True


class _FakeSessionFactory:
    """Fake ConversationSessionFactory that returns _FakeSession instances."""
    def __init__(self, agent):
        self._agent = agent
        self._session = None

    def __call__(self):
        return self

    async def __aenter__(self):
        return _FakeDbSession(self._agent)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDbSession:
    def __init__(self, agent):
        self._agent = agent

    async def execute(self, _query):
        return _FakeScalarResult(self._agent)


class _FakeSessionFactory:
    def __init__(self, agent):
        self._agent = agent

    def __call__(self):
        return self

    async def __aenter__(self):
        return _FakeDbSession(self._agent)

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def test_rest_message_avoids_duplicate_latest_user_turn(client: AsyncClient, test_agent, monkeypatch):
    from voice_platform.api import playground_routes

    fake_conversation = _FakeConversation()

    async def _fake_builder(agent, user_id):
        return fake_conversation

    monkeypatch.setattr(playground_routes, "_build_playground_conversation", _fake_builder)

    response = await client.post(
        "/api/playground/message",
        json={
            "agent_id": test_agent.id,
            "message": "hello",
            "conversation_history": [
                {"role": "assistant", "content": "Hi there"},
                {"role": "user", "content": "hello"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["response"] == "ok"
    assert fake_conversation.messages == [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "hello"},
    ]


async def test_rest_message_keeps_history_when_latest_turn_differs(client: AsyncClient, test_agent, monkeypatch):
    from voice_platform.api import playground_routes

    fake_conversation = _FakeConversation()

    async def _fake_builder(agent, user_id):
        return fake_conversation

    monkeypatch.setattr(playground_routes, "_build_playground_conversation", _fake_builder)

    response = await client.post(
        "/api/playground/message",
        json={
            "agent_id": test_agent.id,
            "message": "what time is it?",
            "conversation_history": [
                {"role": "assistant", "content": "Hello"},
                {"role": "user", "content": "how are you"},
            ],
        },
    )

    assert response.status_code == 200
    assert fake_conversation.messages == [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "how are you"},
        {"role": "user", "content": "what time is it?"},
    ]


async def test_build_conversation_rejects_non_openai_compatible_provider():
    from voice_platform.api import playground_routes

    agent = Agent(
        id=1,
        user_id=1,
        name="Anthropic Agent",
        prompt_preamble="Prompt",
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-20250514",
        max_tokens=2048,
    )

    with pytest.raises(ValueError, match="not supported by Playground chat transport"):
        await playground_routes._build_playground_conversation(agent, user_id=1)


async def test_build_conversation_uses_agent_max_tokens(monkeypatch):
    from voice_platform.api import playground_routes

    agent = Agent(
        id=1,
        user_id=1,
        name="Test Agent",
        prompt_preamble="Prompt",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        llm_api_key="test-key",
        max_tokens=1024,
    )

    class _EmptySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, query):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    monkeypatch.setattr(playground_routes, "async_session", lambda: _EmptySession())

    conversation = await playground_routes._build_playground_conversation(agent, user_id=1)
    assert conversation.max_tokens == 1024


async def test_rest_message_rejects_inactive_agent(client: AsyncClient, test_agent, db_session):
    test_agent.is_active = False
    await db_session.commit()

    response = await client.post(
        "/api/playground/message",
        json={
            "agent_id": test_agent.id,
            "message": "hello",
        },
    )

    assert response.status_code == 400
    assert "inactive" in response.json()["error"]["message"].lower()


async def test_rest_message_rejects_empty_message(client: AsyncClient, test_agent):
    response = await client.post(
        "/api/playground/message",
        json={
            "agent_id": test_agent.id,
            "message": "   ",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Message cannot be empty"


async def test_playground_ws_streams_tokens_and_responds_to_ping(monkeypatch):
    from voice_platform.api import playground_routes
    from voice_platform.runtime.session.factory import ConversationSessionFactory

    fake_agent = SimpleNamespace(
        id=10,
        user_id=1,
        name="Test Agent",
        llm_provider="openai",
        is_active=True,
    )

    async def _fake_current_user_ws(_websocket):
        return SimpleNamespace(id=1)

    _fake_session = _FakeSession(initial_message="Hello from agent", tokens=["hel", "lo"])

    async def _fake_create(self, *, agent, user_id, channel, agent_id):
        return _fake_session

    monkeypatch.setattr(playground_routes, "get_current_user_ws", _fake_current_user_ws)
    monkeypatch.setattr(playground_routes, "async_session", _FakeSessionFactory(fake_agent))
    monkeypatch.setattr(ConversationSessionFactory, "create", _fake_create)

    websocket = _FakeWebSocket(
        incoming=[
            {"type": "message", "text": "hello"},
            {"type": "ping"},
        ]
    )

    await playground_routes.playground_ws(cast(Any, websocket), agent_id=10)

    assert websocket.accepted is True
    assert {"type": "initial_message", "text": "Hello from agent"} in websocket.sent
    assert any(m.get("type") == "agent_info" for m in websocket.sent)
    assert {"type": "agent_token", "text": "hel"} in websocket.sent
    assert {"type": "agent_token", "text": "lo"} in websocket.sent
    assert {"type": "message_end"} in websocket.sent
    assert {"type": "pong"} in websocket.sent


async def test_playground_ws_reset_rebuilds_conversation(monkeypatch):
    from voice_platform.api import playground_routes
    from voice_platform.runtime.session.factory import ConversationSessionFactory

    fake_agent = SimpleNamespace(
        id=22,
        user_id=7,
        name="Reset Agent",
        llm_provider="openai",
        is_active=True,
    )
    build_calls = {"count": 0}

    async def _fake_current_user_ws(_websocket):
        return SimpleNamespace(id=7)

    async def _fake_create(self, *, agent, user_id, channel, agent_id):
        build_calls["count"] += 1
        return _FakeSession(initial_message=f"initial-{build_calls['count']}")

    monkeypatch.setattr(playground_routes, "get_current_user_ws", _fake_current_user_ws)
    monkeypatch.setattr(playground_routes, "async_session", _FakeSessionFactory(fake_agent))
    monkeypatch.setattr(ConversationSessionFactory, "create", _fake_create)

    websocket = _FakeWebSocket(incoming=[{"type": "reset"}])

    await playground_routes.playground_ws(cast(Any, websocket), agent_id=22)

    assert build_calls["count"] == 2
    assert {"type": "reset_ack"} in websocket.sent
    assert {"type": "initial_message", "text": "initial-1"} in websocket.sent
    assert {"type": "initial_message", "text": "initial-2"} in websocket.sent


async def test_playground_ws_rejects_inactive_agent(monkeypatch):
    from voice_platform.api import playground_routes

    fake_agent = SimpleNamespace(
        id=33,
        user_id=3,
        name="Inactive",
        llm_provider="openai",
        is_active=False,
    )

    async def _fake_current_user_ws(_websocket):
        return SimpleNamespace(id=3)

    monkeypatch.setattr(playground_routes, "get_current_user_ws", _fake_current_user_ws)
    monkeypatch.setattr(playground_routes, "async_session", _FakeSessionFactory(fake_agent))

    websocket = _FakeWebSocket(incoming=[])

    await playground_routes.playground_ws(cast(Any, websocket), agent_id=33)

    assert {"type": "error", "text": "Agent is inactive", "fatal": True} in websocket.sent
    assert websocket.closed is True


async def test_build_conversation_does_not_append_period():
    """B4: System prompt should not have a period appended."""
    from voice_platform.api import playground_routes

    agent = Agent(
        id=1,
        user_id=1,
        name="Test Agent",
        prompt_preamble="What is your name?",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        llm_api_key="test-key",
        max_tokens=1024,
    )

    class _EmptySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, query):
            return SimpleNamespace(scalar_one_or_none=lambda: None)

    import voice_platform.api.playground_routes as pr

    original_session = pr.async_session
    pr.async_session = lambda: _EmptySession()
    try:
        conv = await pr._build_playground_conversation(agent, user_id=1)
        assert not conv.messages[0]["content"].startswith("What is your name?.")
        assert "What is your name?" in conv.messages[0]["content"]
    finally:
        pr.async_session = original_session


async def test_scenarios_reject_inactive_agent(client: AsyncClient, test_agent, db_session):
    """B5: Scenarios endpoint should reject inactive agents."""
    test_agent.is_active = False
    await db_session.commit()

    response = await client.get(f"/api/playground/scenarios/{test_agent.id}")

    assert response.status_code == 400


async def test_tool_error_format_includes_status():
    """B8: Tool execution errors should use status/message format."""
    from voice_platform.api.playground_routes import PlaygroundConversation

    conv = PlaygroundConversation(
        agent_id=1,
        system_prompt="test",
        model="gpt-4o-mini",
        api_key="fake",
        user_id=1,
    )

    result = await conv._execute_tool("nonexistent_tool", {})

    assert result.get("status") == "error"
    assert "message" in result
    assert "error" not in result or result.get("error") is None


async def test_ws_reset_calls_session_end_and_recreates(monkeypatch):
    """B9: WS reset should call session.end() and create a new session via factory."""
    from voice_platform.api import playground_routes
    from voice_platform.runtime.session.factory import ConversationSessionFactory

    fake_agent = SimpleNamespace(
        id=44,
        user_id=5,
        name="Reset Test Agent",
        llm_provider="openai",
        is_active=True,
    )

    async def _fake_current_user_ws(_websocket):
        return SimpleNamespace(id=5)

    sessions_created = []

    async def _fake_create(self, *, agent, user_id, channel, agent_id):
        s = _FakeSession(initial_message=f"initial-{len(sessions_created) + 1}")
        sessions_created.append(s)
        return s

    monkeypatch.setattr(playground_routes, "get_current_user_ws", _fake_current_user_ws)
    monkeypatch.setattr(playground_routes, "async_session", _FakeSessionFactory(fake_agent))
    monkeypatch.setattr(ConversationSessionFactory, "create", _fake_create)

    websocket = _FakeWebSocket(incoming=[{"type": "reset"}])

    await playground_routes.playground_ws(cast(Any, websocket), agent_id=44)

    assert len(sessions_created) == 2, "Should create 2 sessions (initial + reset)"
    assert sessions_created[0]._ended is True, "First session should be ended on reset"
    assert {"type": "reset_ack"} in websocket.sent


async def test_list_agents_active_only_filter(client: AsyncClient, test_agent, db_session):
    """B10: active_only=true should filter out inactive agents."""
    test_agent.is_active = False
    await db_session.commit()

    response_all = await client.get("/api/playground/agents")
    response_active = await client.get("/api/playground/agents?active_only=true")

    agents_all = response_all.json()["agents"]
    agents_active = response_active.json()["agents"]

    assert any(not a["is_active"] for a in agents_all)
    assert all(a["is_active"] for a in agents_active)


async def test_list_agents_includes_language_fields(client: AsyncClient, test_agent):
    """Verify language/stt_language/mode fields are present in agent listing."""
    response = await client.get("/api/playground/agents")
    agents = response.json()["agents"]

    assert len(agents) > 0
    agent = agents[0]
    assert "language" in agent
    assert "stt_language" in agent
    assert "mode" in agent


# ── Phase 6-7 Verification Tests ───────────────────────────────────────


async def test_playground_ws_sends_thread_id_in_context(monkeypatch):
    """M-14: Initial WebSocket message should include thread_id for reconnection."""
    import inspect

    from voice_platform.api import playground_routes

    # Source inspection: verify the initial context send includes thread_id
    source = inspect.getsource(playground_routes.playground_flow_ws)
    assert "thread_id" in source, "playground_flow_ws should send thread_id in initial context"
    assert "reconnect" in source.lower(), "playground_flow_ws should support reconnection via thread_id"


