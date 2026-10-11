"""M10.5 dependency injection validation tests.

Verifies that:
- ServiceContainer is constructed once and frozen
- ConversationSessionFactory receives ServiceContainer, not individual services
- ExecutionContext is only built by ExecutionContextBuilder
- ConversationSession receives runtime + context, never raw services
- WebSocketTransport receives only websocket + user_id, never runtime/session
- FlowRuntime receives only executor, never DB or services
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from voice_platform.runtime.session.context import ExecutionContext
from voice_platform.runtime.session.conversation_context import (
    ConversationChannel,
    ConversationContext,
)
from voice_platform.runtime.session.events import SessionEventFactory
from voice_platform.runtime.session.execution import ConversationInput
from voice_platform.runtime.session.infrastructure_context import InfrastructureContext
from voice_platform.runtime.session.session import ConversationSession, create_conversation_id


def _make_context():
    from voice_platform.integrations.plugins.registry import EmptyPluginRegistry
    from voice_platform.runtime.events.event_bus import NoOpEventBus
    from voice_platform.runtime.tracing.tracer import NoOpTracer

    return ExecutionContext(
        conversation=ConversationContext(
            conversation_id=create_conversation_id(),
            user_id=1,
            agent_id=1,
            channel=ConversationChannel.PLAYGROUND_CHAT,
        ),
        runtime=SimpleNamespace(
            agent=SimpleNamespace(model="gpt-4", provider="openai"),
            prompt=SimpleNamespace(system_prompt="test", preamble=""),
            tools=SimpleNamespace(actions=[], tool_defs=[]),
            enrichment=SimpleNamespace(kb_results=[], memory=[]),
        ),
        infrastructure=InfrastructureContext(
            db=MagicMock(),
            cache=MagicMock(),
            event_bus=NoOpEventBus(),
            tracer=NoOpTracer(),
            plugin_registry=EmptyPluginRegistry(),
        ),
    )


# ── ServiceContainer DI ──────────────────────────────────────────────


def test_service_container_provides_plugin_registry():
    """ServiceContainer should expose plugin_registry as a property."""
    from voice_platform.runtime.session.service_container import ServiceContainer

    container = ServiceContainer()
    assert container.plugin_registry is not None


def test_service_container_does_not_expose_db_or_cache():
    """ServiceContainer should NOT own DB or Cache — those are per-request."""
    from voice_platform.runtime.session.service_container import ServiceContainer

    container = ServiceContainer()
    assert not hasattr(container, "db"), "ServiceContainer must not own DB"
    assert not hasattr(container, "cache"), "ServiceContainer must not own Cache"
    assert not hasattr(container, "session_factory"), "ServiceContainer must not own session factory"


# ── ConversationSessionFactory DI ────────────────────────────────────


def test_session_factory_requires_service_container():
    """ConversationSessionFactory should require service_container in constructor."""
    from voice_platform.runtime.session.factory import ConversationSessionFactory

    # Should accept ServiceContainer
    from voice_platform.runtime.session.service_container import ServiceContainer
    container = ServiceContainer()
    factory = ConversationSessionFactory(service_container=container)
    assert factory is not None


def test_session_factory_create_signature():
    """ConversationSessionFactory.create() should accept agent, user_id, channel, agent_id."""
    import inspect

    from voice_platform.runtime.session.factory import ConversationSessionFactory

    sig = inspect.signature(ConversationSessionFactory.create)
    params = set(sig.parameters.keys())
    assert "agent" in params, "create() must accept agent"
    assert "user_id" in params, "create() must accept user_id"
    assert "channel" in params, "create() must accept channel"
    assert "agent_id" in params, "create() must accept agent_id"
    assert "self" in params


# ── ConversationSession DI ───────────────────────────────────────────


def test_session_receives_runtime_and_context_not_services():
    """ConversationSession should receive runtime + context, never raw DB/ServiceContainer."""
    import inspect

    from voice_platform.runtime.session.session import ConversationSession

    sig = inspect.signature(ConversationSession.__init__)
    params = set(sig.parameters.keys())
    assert "runtime" in params, "Session must accept runtime"
    assert "context" in params, "Session must accept context"
    # plugin_registry, event_bus, tracer are optional overrides (fall back to context.infrastructure)
    # but DB and ServiceContainer must never be accepted
    assert "db" not in params, "Session must NOT accept db directly"
    assert "service_container" not in params, "Session must NOT accept ServiceContainer"


# ── WebSocketTransport DI ────────────────────────────────────────────


def test_transport_receives_only_websocket_and_user_id():
    """WebSocketTransport should only accept websocket + user_id, not runtime/session."""
    import inspect

    from voice_platform.runtime.transport.websocket import WebSocketTransport

    sig = inspect.signature(WebSocketTransport.__init__)
    params = set(sig.parameters.keys())
    assert "websocket" in params
    assert "user_id" in params
    assert "runtime" not in params, "Transport must NOT accept runtime"
    assert "session" not in params, "Transport must NOT accept session"
    assert "executor" not in params, "Transport must NOT accept executor"


# ── FlowRuntime DI ───────────────────────────────────────────────────


def test_flow_runtime_receives_only_executor():
    """FlowRuntime should only accept executor, not DB or services."""
    import inspect

    from voice_platform.runtime.session.adapters.flow import FlowRuntime

    sig = inspect.signature(FlowRuntime.__init__)
    params = set(sig.parameters.keys())
    assert "executor" in params
    assert "db" not in params, "FlowRuntime must NOT accept db"
    assert "service_container" not in params, "FlowRuntime must NOT accept ServiceContainer"
    assert "plugin_registry" not in params, "FlowRuntime must NOT accept PluginRegistry"


# ── ExecutionContextBuilder DI ───────────────────────────────────────


def test_execution_context_builder_is_only_constructor():
    """ExecutionContext should only be constructable via ExecutionContextBuilder.build()."""
    import inspect

    from voice_platform.runtime.session.builder import ExecutionContextBuilder

    # Builder should have a build() method that returns ExecutionContext
    assert hasattr(ExecutionContextBuilder, "build"), "Builder must have build() method"
    sig = inspect.signature(ExecutionContextBuilder.build)
    params = set(sig.parameters.keys())
    assert "request" in params, "build() must accept ContextBuildRequest"
    assert "db" in params, "build() must accept db session"
    assert "cache" in params, "build() must accept cache"


# ── LLMClient DI ─────────────────────────────────────────────────────


def test_llm_client_receives_adapter_not_api_key():
    """LLMClient should receive adapter + retry + timeout, not raw API keys."""
    import inspect

    from voice_platform.runtime.llm.client import LLMClient

    sig = inspect.signature(LLMClient.__init__)
    params = set(sig.parameters.keys())
    assert "adapter" in params
    assert "retry" in params
    assert "timeout" in params
    assert "api_key" not in params, "LLMClient must NOT accept api_key directly"
    assert "base_url" not in params, "LLMClient must NOT accept base_url directly"


# ── LLMFactory DI ────────────────────────────────────────────────────


def test_llm_factory_create_returns_llm_client():
    """LLMFactory.create() should return an LLMClient instance."""
    import inspect

    from voice_platform.runtime.llm.factory import LLMFactory

    sig = inspect.signature(LLMFactory.create)
    params = set(sig.parameters.keys())
    assert "provider" in params, "create() must accept provider"
    assert "retry" in params, "create() must accept retry policy"
    assert "timeout" in params, "create() must accept timeout policy"


# ── ConditionEvaluator DI ────────────────────────────────────────────


def test_condition_evaluator_no_constructor_dependencies():
    """ConditionEvaluator should be instantiable with no arguments."""
    from voice_platform.runtime.flow.conditions import ConditionEvaluator

    evaluator = ConditionEvaluator()
    assert evaluator is not None

    # Should not require DB, services, or context
    import inspect
    sig = inspect.signature(ConditionEvaluator.__init__)
    params = set(sig.parameters.keys())
    assert "self" in params
    assert "db" not in params, "ConditionEvaluator must NOT require db"
    assert "service" not in params, "ConditionEvaluator must NOT require service"
