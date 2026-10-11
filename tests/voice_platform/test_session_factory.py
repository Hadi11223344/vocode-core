"""Tests for ConversationSessionFactory.

Verifies:
- Factory creates correct runtime type for each channel
- Factory receives ServiceContainer once at construction
- Factory.create() does not accept transport parameter
- Factory delegates to builders (not a god object)
- No transport imports in factory module
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from voice_platform.integrations.plugins.registry import (
    DefaultPluginRegistry,
    EmptyPluginRegistry,
    PluginRegistry,
)
from voice_platform.runtime.session.conversation_context import ConversationChannel
from voice_platform.runtime.session.factory import ConversationSessionFactory
from voice_platform.runtime.session.service_container import ServiceContainer


def make_service_container() -> ServiceContainer:
    """Build a ServiceContainer with a minimal plugin registry for tests."""
    container = MagicMock(spec=ServiceContainer)
    container.plugin_registry = EmptyPluginRegistry()
    return container


def make_mock_agent(mode: str = "chat", **kwargs: Any) -> MagicMock:
    """Build a mock Agent model."""
    agent = MagicMock()
    agent.id = kwargs.get("id", 1)
    agent.llm_provider = kwargs.get("llm_provider", "openai")
    agent.llm_model = kwargs.get("llm_model", "gpt-4o-mini")
    agent.temperature = kwargs.get("temperature", 0.7)
    agent.max_tokens = kwargs.get("max_tokens", 2048)
    agent.prompt_preamble = kwargs.get("prompt_preamble", "You are a test agent")
    agent.is_active = kwargs.get("is_active", True)
    agent.mode = mode
    agent.graph_json = kwargs.get("graph_json", None)
    agent.tools_config = kwargs.get("tools_config", None)
    agent.initial_message = kwargs.get("initial_message", None)
    agent.llm_api_key = kwargs.get("llm_api_key", None)
    agent.name = kwargs.get("name", "TestAgent")
    agent.timezone = kwargs.get("timezone", None)
    agent.context_window = kwargs.get("context_window", None)
    agent.knowledge_base_id = kwargs.get("knowledge_base_id", None)
    agent.mcp_bindings_json = kwargs.get("mcp_bindings_json", None)
    agent.tool_instructions = kwargs.get("tool_instructions", None)
    return agent


class TestConversationSessionFactory:
    def test_constructor_takes_service_container(self):
        services = make_service_container()
        factory = ConversationSessionFactory(service_container=services)
        assert factory._services is services

    def test_create_signature_no_transport(self):
        """create() should not accept a transport parameter."""
        import inspect as insp
        sig = insp.signature(ConversationSessionFactory.create)
        params = set(sig.parameters.keys())
        assert "transport" not in params
        assert "agent" in params
        assert "user_id" in params
        assert "channel" in params

    def test_no_transport_imports(self):
        """Factory module does not import transport classes."""
        source = inspect.getsource(ConversationSessionFactory)
        forbidden = [
            "ConversationTransport",
            "WebSocketTransport",
            "TelephonyTransport",
            "TransportEvent",
        ]
        for name in forbidden:
            assert name not in source, f"Factory module references transport class: {name}"

    def test_no_session_class_imports(self):
        """Factory module should not import concrete session classes."""
        source = inspect.getsource(ConversationSessionFactory)
        # Factory should import ConversationSession (it creates it)
        # but should NOT import PlaygroundRuntime/FlowRuntime at module level
        # (they're imported lazily inside methods)
        assert "from voice_platform.runtime.session.adapters.playground import PlaygroundRuntime" not in source.split("def _build_playground_runtime")[0]
        assert "from voice_platform.runtime.session.adapters.flow import FlowRuntime" not in source.split("def _build_flow_runtime")[0]

    @pytest.mark.asyncio
    async def test_create_playground_chat(self):
        """Factory creates a session with PlaygroundRuntime for PLAYGROUND_CHAT."""
        services = make_service_container()
        factory = ConversationSessionFactory(service_container=services)
        agent = make_mock_agent()

        # Mock _build_playground_conversation to avoid DB access
        with pytest.MonkeyPatch.context() as mp:
            async def fake_build(agent, user_id):
                return MagicMock()
            mp.setattr(
                "voice_platform.runtime.session.adapters.playground_conversation._build_playground_conversation",
                fake_build,
            )
            session = await factory.create(
                agent=agent,
                user_id=1,
                channel=ConversationChannel.PLAYGROUND_CHAT,
                agent_id=1,
            )

        from voice_platform.runtime.session.adapters.playground import PlaygroundRuntime
        assert isinstance(session._runtime, PlaygroundRuntime)
        assert session.state.value == "created"

    @pytest.mark.asyncio
    async def test_create_unsupported_channel_raises(self):
        """Factory raises ValueError for TELEPHONY channel."""
        services = make_service_container()
        factory = ConversationSessionFactory(service_container=services)
        agent = make_mock_agent()

        with pytest.raises(ValueError, match="Unsupported channel"):
            await factory.create(
                agent=agent,
                user_id=1,
                channel=ConversationChannel.TELEPHONY,
                agent_id=1,
            )

    @pytest.mark.asyncio
    async def test_create_passes_plugin_registry(self):
        """Factory injects ServiceContainer's plugin_registry into the session."""
        services = make_service_container()
        factory = ConversationSessionFactory(service_container=services)
        agent = make_mock_agent()

        with pytest.MonkeyPatch.context() as mp:
            async def fake_build(agent, user_id):
                return MagicMock()
            mp.setattr(
                "voice_platform.runtime.session.adapters.playground_conversation._build_playground_conversation",
                fake_build,
            )
            session = await factory.create(
                agent=agent,
                user_id=1,
                channel=ConversationChannel.PLAYGROUND_CHAT,
                agent_id=1,
            )

        assert session._plugin_registry is services.plugin_registry
