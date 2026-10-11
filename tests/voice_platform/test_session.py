"""Unit tests for ConversationSession lifecycle, dependency injection, and runtime adapters.

Tests verify:
- Idempotency of start() and end()
- cancel() only affects active execution
- State transitions through _transition()
- Runtime exception propagation
- No LLMClient exposure
- No provider SDK / LangGraph imports in session module
- EventBus lifecycle event publishing
- close() alias
- ExecutionContext metadata immutability
- Runtime adapter delegation (async generators yielding SessionEvent)
- No ConversationTransport or TransportEvent imports in session module
- No handle() or reset() methods on ConversationSession
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from types import MappingProxyType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from voice_platform.integrations.plugins.registry import EmptyPluginRegistry, PluginRegistry
from voice_platform.runtime.events.event_bus import EventBus, NoOpEventBus
from voice_platform.runtime.session.adapters.flow import FlowRuntime
from voice_platform.runtime.session.adapters.playground import PlaygroundRuntime
from voice_platform.runtime.session.adapters.telephony import TelephonyRuntime
from voice_platform.runtime.session.context import ExecutionContext
from voice_platform.runtime.session.conversation_context import (
    ConversationChannel,
    ConversationContext,
)
from voice_platform.runtime.session.events import (
    SessionEvent,
    SessionEventFactory,
    SessionEventType,
)
from voice_platform.runtime.session.execution import (
    ConversationInput,
    ExecutionRuntime,
    RuntimeKind,
)
from voice_platform.runtime.session.infrastructure_context import InfrastructureContext
from voice_platform.runtime.session.lifecycle import (
    ConversationEnded,
    ConversationStarted,
    SessionState,
    TerminationReason,
)
from voice_platform.runtime.session.runtime_config import (
    AgentConfig,
    EnrichmentContext,
    ModelReference,
    PromptContext,
    RuntimeConfig,
    ToolContext,
)
from voice_platform.runtime.session.session import ConversationSession, create_conversation_id
from voice_platform.runtime.tracing.tracer import NoOpTracer, Tracer

# ── Helpers ───────────────────────────────────────────────────────────


class _NoOpDB:
    async def execute(self, stmt): raise RuntimeError("No DB in tests")
    async def commit(self): pass
    async def rollback(self): pass
    async def close(self): pass


class _NoOpCache:
    async def get(self, key): return None
    async def set(self, key, value, ttl=None): pass
    async def delete(self, key): pass


def make_context(**kwargs) -> ExecutionContext:
    """Build an ExecutionContext composition root for tests."""
    conv_id = kwargs.pop("conversation_id", create_conversation_id())
    agent_id = kwargs.pop("agent_id", None)
    user_id = kwargs.pop("user_id", None)

    return ExecutionContext(
        conversation=ConversationContext(
            conversation_id=conv_id,
            agent_id=agent_id,
            user_id=user_id,
        ),
        runtime=RuntimeConfig(
            agent=AgentConfig(model_ref=ModelReference(provider="openai", model="gpt-4o-mini")),
            prompt=PromptContext(system_prompt=""),
            tools=ToolContext(),
            enrichment=EnrichmentContext(),
        ),
        infrastructure=InfrastructureContext(
            db=_NoOpDB(),
            cache=_NoOpCache(),
            event_bus=NoOpEventBus(),
            tracer=NoOpTracer(),
            plugin_registry=EmptyPluginRegistry(),
        ),
    )


async def _collect_events(gen) -> list[SessionEvent]:
    """Collect all SessionEvents from an async generator."""
    events = []
    async for event in gen:
        events.append(event)
    return events


def make_mock_runtime() -> MagicMock:
    """Create a mock ExecutionRuntime with async generator methods."""

    async def _empty_gen(*args, **kwargs):
        return
        yield  # type: ignore[unreachable]

    runtime = MagicMock(spec=ExecutionRuntime)
    runtime.start = MagicMock(return_value=_empty_gen())
    runtime.send_message = MagicMock(return_value=_empty_gen())
    runtime.cancel = AsyncMock(return_value=None)
    runtime.end = AsyncMock(return_value=None)
    return runtime


def make_mock_runtime_with_events(start_events: list[SessionEvent] | None = None,
                                   msg_events: list[SessionEvent] | None = None) -> MagicMock:
    """Create a mock ExecutionRuntime that yields specific events."""
    runtime = MagicMock(spec=ExecutionRuntime)
    start_events = start_events or []
    msg_events = msg_events or []

    async def _start_gen(ctx):
        for e in start_events:
            yield e

    async def _send_gen(msg):
        for e in msg_events:
            yield e

    runtime.start = MagicMock(side_effect=_start_gen)
    runtime.send_message = MagicMock(side_effect=_send_gen)
    runtime.cancel = AsyncMock(return_value=None)
    runtime.end = AsyncMock(return_value=None)
    return runtime


class CollectingEventBus:
    """Test event bus that collects published events."""

    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)


class CollectingTracer:
    """Test tracer that collects emit calls."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def emit(self, event_type: str, **fields: Any) -> None:
        self.calls.append({"event_type": event_type, **fields})


# ── Lifecycle Tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_idempotent():
    """start() called twice → runtime.start() called once."""
    runtime = make_mock_runtime()
    session = ConversationSession(runtime=runtime, context=make_context())
    await _collect_events(session.start())
    await _collect_events(session.start())
    assert runtime.start.call_count == 1
    assert session.state == SessionState.RUNNING


@pytest.mark.asyncio
async def test_end_idempotent():
    """end() called twice → runtime.end() called once."""
    runtime = make_mock_runtime()
    session = ConversationSession(runtime=runtime, context=make_context())
    await _collect_events(session.start())
    await session.end()
    await session.end()
    assert runtime.end.call_count == 1
    assert session.state == SessionState.ENDED


@pytest.mark.asyncio
async def test_cancel_calls_runtime_cancel():
    """cancel() → runtime.cancel() called."""
    runtime = make_mock_runtime()
    session = ConversationSession(runtime=runtime, context=make_context())
    await _collect_events(session.start())
    await session.cancel()
    runtime.cancel.assert_called_once()
    assert session.state == SessionState.RUNNING


@pytest.mark.asyncio
async def test_end_disposes_resources():
    """end() → runtime.end() called (resources disposed)."""
    runtime = make_mock_runtime()
    session = ConversationSession(runtime=runtime, context=make_context())
    await _collect_events(session.start())
    await session.end()
    runtime.end.assert_called_once()
    assert session.state == SessionState.ENDED


@pytest.mark.asyncio
async def test_context_uuid_propagated():
    """Session creates UUID → ExecutionContext receives same UUID."""
    conv_id = create_conversation_id()
    ctx = make_context(conversation_id=conv_id)
    runtime = make_mock_runtime()
    session = ConversationSession(runtime=runtime, context=ctx)
    assert session.conversation_id == conv_id
    await _collect_events(session.start())
    runtime.start.assert_called_once_with(ctx)


@pytest.mark.asyncio
async def test_dependency_injection():
    """Session receives ExecutionRuntime instance, no concrete impl imported."""
    runtime = make_mock_runtime()
    session = ConversationSession(runtime=runtime, context=make_context())
    assert isinstance(session._runtime, ExecutionRuntime) or hasattr(
        session._runtime, "start"
    )


@pytest.mark.asyncio
async def test_state_transitions():
    """CREATED → STARTING → RUNNING → ENDED."""
    runtime = make_mock_runtime()
    session = ConversationSession(runtime=runtime, context=make_context())
    assert session.state == SessionState.CREATED
    await _collect_events(session.start())
    assert session.state == SessionState.RUNNING
    await session.end()
    assert session.state == SessionState.ENDED


@pytest.mark.asyncio
async def test_cancel_state_transition():
    """RUNNING → CANCELLING → RUNNING (cancel resolved, still active)."""
    runtime = make_mock_runtime()
    session = ConversationSession(runtime=runtime, context=make_context())
    await _collect_events(session.start())
    assert session.state == SessionState.RUNNING
    await session.cancel()
    assert session.state == SessionState.RUNNING


@pytest.mark.asyncio
async def test_runtime_exception_propagation():
    """runtime.send_message() raises → session re-raises, state → ENDED with reason ERROR."""

    async def _error_gen(msg):
        raise ValueError("boom")
        yield  # type: ignore[unreachable]

    runtime = make_mock_runtime()
    runtime.send_message = MagicMock(side_effect=_error_gen)
    session = ConversationSession(runtime=runtime, context=make_context())
    await _collect_events(session.start())
    with pytest.raises(ValueError, match="boom"):
        await _collect_events(session.receive_message("hi"))
    assert session.state == SessionState.ENDED
    assert session.termination_reason == TerminationReason.ERROR


@pytest.mark.asyncio
async def test_no_llmclient_exposed():
    """Session has no llm_client attribute."""
    runtime = make_mock_runtime()
    session = ConversationSession(runtime=runtime, context=make_context())
    assert not hasattr(session, "llm_client")
    assert not hasattr(session, "_llm_client")


def test_no_provider_imports():
    """Session module imports no SDK/LangGraph."""
    from voice_platform.runtime.session import session as session_module

    source = inspect.getsource(session_module)
    forbidden = [
        "import openai",
        "import groq",
        "import ollama",
        "import anthropic",
        "from langgraph",
        "import langgraph",
        "from openai",
        "from groq",
        "from ollama",
    ]
    for keyword in forbidden:
        assert keyword not in source, f"Session module contains forbidden import: {keyword}"


def test_imports_only_abstractions():
    """Session module imports only ABCs/Protocols, never concrete runtime classes."""
    from voice_platform.runtime.session import session as session_module

    source = inspect.getsource(session_module)
    forbidden_concrete = [
        "PlaygroundRuntime",
        "FlowRuntime",
        "TelephonyRuntime",
        "PlaygroundConversation",
        "LangGraphFlowExecutor",
        "FlowAgent",
    ]
    for name in forbidden_concrete:
        assert name not in source, f"Session module references concrete class: {name}"


def test_no_transport_imports():
    """Session module does not import TransportEvent or ConversationTransport."""
    from voice_platform.runtime.session import session as session_module

    source = inspect.getsource(session_module)
    forbidden_imports = [
        "from voice_platform.runtime.transport",
        "import voice_platform.runtime.transport",
        "from voice_platform.runtime.session.events import TransportEvent",
        "WebSocketTransport",
        "TelephonyTransport",
    ]
    for keyword in forbidden_imports:
        assert keyword not in source, f"Session module contains forbidden import: {keyword}"


def test_no_handle_method():
    """Session module does not define handle() or reset() methods."""
    from voice_platform.runtime.session import session as session_module

    source = inspect.getsource(session_module)
    assert "def handle" not in source, "Session module defines handle() method"
    assert "def reset" not in source, "Session module defines reset() method"


@pytest.mark.asyncio
async def test_event_bus_publishes_lifecycle():
    """Lifecycle events published to EventBus on each transition."""
    bus = CollectingEventBus()
    runtime = make_mock_runtime()
    session = ConversationSession(
        runtime=runtime, context=make_context(), event_bus=bus
    )
    await _collect_events(session.start())
    started_events = [e for e in bus.events if isinstance(e, ConversationStarted)]
    assert len(started_events) == 1

    await session.end()
    ended_events = [e for e in bus.events if isinstance(e, ConversationEnded)]
    assert len(ended_events) == 1
    assert ended_events[0].reason == TerminationReason.NORMAL


@pytest.mark.asyncio
async def test_close_alias():
    """close() calls end()."""
    runtime = make_mock_runtime()
    session = ConversationSession(runtime=runtime, context=make_context())
    await _collect_events(session.start())
    await session.close()
    assert session.state == SessionState.ENDED
    runtime.end.assert_called_once()


def test_metadata_immutable():
    """ExecutionContext is frozen — mutation raises FrozenInstanceError."""
    ctx = make_context()
    with pytest.raises(Exception):
        ctx.conversation = None  # type: ignore


def test_conversation_context_frozen():
    """ConversationContext is frozen — mutation raises FrozenInstanceError."""
    ctx = make_context()
    with pytest.raises(Exception):
        ctx.conversation.conversation_id = "hacked"  # type: ignore


def test_runtime_config_frozen():
    """RuntimeConfig is frozen — mutation raises FrozenInstanceError."""
    ctx = make_context()
    with pytest.raises(Exception):
        ctx.runtime.agent = None  # type: ignore


def test_agent_config_frozen():
    """AgentConfig is frozen — mutation raises FrozenInstanceError."""
    ctx = make_context()
    with pytest.raises(Exception):
        ctx.runtime.agent.model = "hacked"  # type: ignore


@pytest.mark.asyncio
async def test_start_yields_events():
    """start() yields SessionEvents from the runtime."""
    events = [SessionEventFactory.token("hello"), SessionEventFactory.message_end()]
    runtime = make_mock_runtime_with_events(start_events=events)
    session = ConversationSession(runtime=runtime, context=make_context())
    yielded = await _collect_events(session.start())
    assert len(yielded) == 2
    assert yielded[0].type == SessionEventType.TOKEN
    assert yielded[1].type == SessionEventType.MESSAGE_END


@pytest.mark.asyncio
async def test_receive_message_yields_events():
    """receive_message() yields SessionEvents from the runtime."""
    events = [SessionEventFactory.token("world"), SessionEventFactory.message_end()]
    runtime = make_mock_runtime_with_events(msg_events=events)
    session = ConversationSession(runtime=runtime, context=make_context())
    await _collect_events(session.start())
    yielded = await _collect_events(session.receive_message("hi"))
    assert len(yielded) == 2
    assert yielded[0].type == SessionEventType.TOKEN
    assert yielded[1].type == SessionEventType.MESSAGE_END


# ── Runtime Adapter Tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_playground_runtime_delegates():
    """PlaygroundRuntime delegates to PlaygroundConversation and yields SessionEvent."""
    conv = MagicMock()
    conv.initial_message = "Hello!"

    async def _stream(msg):
        yield "tok1"
        yield "tok2"
        yield {"_metrics": {"tokens": 10}}

    conv.stream_message = MagicMock(return_value=_stream("hi"))
    conv.aclose = AsyncMock()
    conv.agent_id = 42
    conv.model = "gpt-4o-mini"

    runtime = PlaygroundRuntime(conv=conv)
    ctx = make_context()

    start_events = await _collect_events(runtime.start(ctx))
    assert len(start_events) == 2
    assert start_events[0].type == SessionEventType.INITIAL_MESSAGE
    assert start_events[1].type == SessionEventType.AGENT_INFO

    msg_events = await _collect_events(runtime.send_message(ConversationInput(text="hi")))
    assert any(e.type == SessionEventType.TOKEN for e in msg_events)
    assert any(e.type == SessionEventType.METRICS for e in msg_events)
    assert msg_events[-1].type == SessionEventType.MESSAGE_END

    await runtime.cancel()
    await runtime.end()
    conv.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_flow_runtime_delegates():
    """FlowRuntime delegates to LangGraphFlowExecutor via callback-to-generator bridge."""
    executor = MagicMock()
    executor.start_flow = AsyncMock()
    executor.process_user_message = AsyncMock()
    executor.reset = AsyncMock()

    runtime = FlowRuntime(executor=executor)
    ctx = make_context()

    start_events = await _collect_events(runtime.start(ctx))
    executor.start_flow.assert_called_once()

    msg_events = await _collect_events(runtime.send_message(ConversationInput(text="hello")))
    executor.process_user_message.assert_called_once()

    await runtime.cancel()
    await runtime.end()
    executor.reset.assert_called_once()


@pytest.mark.asyncio
async def test_telephony_runtime_delegates():
    """TelephonyRuntime delegates cancel() to FlowAgent. start()/end() are no-ops."""
    agent = MagicMock()
    agent.start = MagicMock()
    agent.terminate = AsyncMock()

    runtime = TelephonyRuntime(agent=agent)
    ctx = make_context()

    start_events = await _collect_events(runtime.start(ctx))
    assert len(start_events) == 0
    agent.start.assert_not_called()

    with pytest.raises(NotImplementedError):
        await _collect_events(runtime.send_message(ConversationInput(text="hi")))

    await runtime.cancel()
    agent.terminate.assert_called_once()

    await runtime.end()
    assert agent.terminate.call_count == 1
