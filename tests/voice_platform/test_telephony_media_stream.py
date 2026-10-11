"""Regression test for FlowAgent.start() TypeError — async generator passed to create_task().

Verifies that FlowAgent.start() does not crash when _conversation_session is attached,
and that the session transitions to RUNNING via the _consume_session_events wrapper.
"""

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from voice_platform.integrations.plugins.registry import EmptyPluginRegistry
from voice_platform.runtime.events.event_bus import NoOpEventBus
from voice_platform.runtime.session.adapters.telephony import TelephonyRuntime
from voice_platform.runtime.session.context import ExecutionContext
from voice_platform.runtime.session.conversation_context import (
    ConversationChannel,
    ConversationContext,
)
from voice_platform.runtime.session.infrastructure_context import InfrastructureContext
from voice_platform.runtime.session.lifecycle import SessionState
from voice_platform.runtime.session.runtime_config import AgentConfig as RuntimeAgentConfig
from voice_platform.runtime.session.runtime_config import (
    EnrichmentContext,
    ModelReference,
    PromptContext,
    RuntimeConfig,
    ToolContext,
)
from voice_platform.runtime.session.session import ConversationSession
from voice_platform.runtime.tracing.tracer import NoOpTracer


class _NoOpDB:
    async def get(self, key): return None
    async def set(self, key, value): pass
    async def delete(self, key): pass


class _NoOpCache:
    async def get(self, key): return None
    async def set(self, key, value, ttl=None): pass
    async def delete(self, key): pass


def _make_test_session() -> ConversationSession:
    """Build a minimal ConversationSession for telephony (TelephonyRuntime is a no-op)."""
    agent_mock = MagicMock()
    return ConversationSession(
        runtime=TelephonyRuntime(agent=agent_mock),
        context=ExecutionContext(
            conversation=ConversationContext(
                conversation_id="test-conv-001",
                agent_id=18,
                channel=ConversationChannel.TELEPHONY,
            ),
            runtime=RuntimeConfig(
                agent=RuntimeAgentConfig(
                    model_ref=ModelReference(provider="test", model="test"),
                ),
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
        ),
    )


@pytest.mark.asyncio
async def test_conversation_session_start_is_async_generator():
    """ConversationSession.start() must be an async generator, not a coroutine."""
    assert inspect.isasyncgenfunction(ConversationSession.start), \
        "ConversationSession.start should be an async generator"


@pytest.mark.asyncio
async def test_create_task_on_async_generator_raises_type_error():
    """asyncio.create_task() on an async generator must raise TypeError."""
    async def gen():
        yield 1

    with pytest.raises(TypeError, match="coroutine was expected"):
        asyncio.create_task(gen())


@pytest.mark.asyncio
async def test_consume_session_events_transitions_to_running():
    """_consume_session_events should drain the async generator and transition session to RUNNING."""
    from voice_platform.agents.flow_agent import FlowAgent

    session = _make_test_session()
    assert session.state == SessionState.CREATED

    # Create a minimal FlowAgent-like object with just the method we need
    agent = FlowAgent.__new__(FlowAgent)
    await agent._consume_session_events(session)

    assert session.state == SessionState.RUNNING, \
        f"Expected RUNNING, got {session.state}"


@pytest.mark.asyncio
async def test_flow_agent_start_does_not_crash_with_session():
    """FlowAgent.start() must not raise TypeError when _conversation_session is set.

    This is the direct regression test for the bug that caused the WebSocket
    to close immediately on inbound calls.
    """
    from voice_platform.agents.flow_agent import FlowAgent

    session = _make_test_session()

    from vocode.streaming.agent.base_agent import BaseAgent

    # Create a minimal FlowAgent with required attrs for start()
    agent = FlowAgent.__new__(FlowAgent)
    agent._greeting_task = None
    agent._conversation_session = session

    # Mock super().start() — BaseAgent.start()
    with pytest.MonkeyPatch.context() as m:
        m.setattr(BaseAgent, "start", lambda self: None)

        # Mock _start_flow_and_greet to avoid actual flow execution
        async def _mock_greet(self):
            pass
        m.setattr(FlowAgent, "_start_flow_and_greet", _mock_greet)

        # This should NOT raise TypeError
        try:
            agent.start()
        except TypeError as e:
            pytest.fail(f"FlowAgent.start() raised TypeError: {e}")

        # Give the background tasks a chance to run
        await asyncio.sleep(0.1)

        # Session should transition to RUNNING
        assert session.state == SessionState.RUNNING, \
            f"Expected RUNNING, got {session.state}"

        # Clean up tasks
        if agent._greeting_task and not agent._greeting_task.done():
            agent._greeting_task.cancel()
            try:
                await agent._greeting_task
            except asyncio.CancelledError:
                pass
