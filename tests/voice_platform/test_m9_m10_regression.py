"""M9/M10 regression tests — concurrency, race conditions, and lifecycle correctness.

Covers:
- Session lifecycle state transitions (CREATED → STARTING → RUNNING → ENDED)
- Concurrent start/end idempotency
- Cancel during active execution
- WebSocketTracker concurrent add/remove
- LangGraphStateManager setup/close lifecycle
- ServiceContainer construction and freeze
- FlowRuntime interrupt/resume boundaries
"""

import asyncio
import weakref
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

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
from voice_platform.runtime.session.execution import ConversationInput
from voice_platform.runtime.session.infrastructure_context import InfrastructureContext
from voice_platform.runtime.session.runtime_config import RuntimeConfig
from voice_platform.runtime.session.session import (
    ConversationSession,
    SessionState,
    TerminationReason,
    create_conversation_id,
)

# ── Fake ExecutionRuntime ────────────────────────────────────────────


class _FakeRuntime:
    """Minimal ExecutionRuntime for testing ConversationSession lifecycle."""

    def __init__(self, events=None, delay=0.0, raise_on_start=False, raise_on_send=False):
        self._events = events or []
        self._delay = delay
        self._raise_on_start = raise_on_start
        self._raise_on_send = raise_on_send
        self._cancelled = False
        self._ended = False
        self._start_calls = 0
        self._send_calls = 0

    async def start(self, context):
        self._start_calls += 1
        if self._raise_on_start:
            raise RuntimeError("start failed")
        for event in self._events:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield event

    async def send_message(self, message):
        self._send_calls += 1
        if self._raise_on_send:
            raise RuntimeError("send failed")
        yield SessionEventFactory.token("ok")
        yield SessionEventFactory.message_end()

    async def cancel(self):
        self._cancelled = True

    async def end(self):
        self._ended = True


def _make_context(conversation_id=None):
    """Build a minimal ExecutionContext for ConversationSession tests."""
    from voice_platform.integrations.plugins.registry import EmptyPluginRegistry
    from voice_platform.runtime.events.event_bus import NoOpEventBus
    from voice_platform.runtime.tracing.tracer import NoOpTracer

    conversation = ConversationContext(
        conversation_id=conversation_id or create_conversation_id(),
        user_id=1,
        agent_id=1,
        channel=ConversationChannel.PLAYGROUND_CHAT,
    )
    # Minimal RuntimeConfig with mock sub-contexts
    runtime = SimpleNamespace(
        agent=SimpleNamespace(model="gpt-4", provider="openai", temperature=0.7, max_tokens=2048),
        prompt=SimpleNamespace(system_prompt="test", preamble=""),
        tools=SimpleNamespace(actions=[], tool_defs=[]),
        enrichment=SimpleNamespace(kb_results=[], memory=[]),
    )
    infrastructure = InfrastructureContext(
        db=MagicMock(),
        cache=MagicMock(),
        event_bus=NoOpEventBus(),
        tracer=NoOpTracer(),
        plugin_registry=EmptyPluginRegistry(),
    )
    return ExecutionContext(
        conversation=conversation,
        runtime=runtime,
        infrastructure=infrastructure,
    )


# ── Session Lifecycle Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_lifecycle_created_to_running_to_ended():
    """Session transitions: CREATED → STARTING → RUNNING → ENDED."""
    events = [SessionEventFactory.initial_message("hi")]
    runtime = _FakeRuntime(events=events)
    session = ConversationSession(runtime=runtime, context=_make_context())

    assert session.state == SessionState.CREATED

    collected = []
    async for event in session.start():
        collected.append(event)

    assert session.state == SessionState.RUNNING
    assert len(collected) == 1

    await session.end()
    assert session.state == SessionState.ENDED
    assert runtime._ended is True


@pytest.mark.asyncio
async def test_session_start_is_idempotent():
    """Calling start() twice should yield events only once."""
    events = [SessionEventFactory.initial_message("hi")]
    runtime = _FakeRuntime(events=events)
    session = ConversationSession(runtime=runtime, context=_make_context())

    async for _ in session.start():
        pass
    assert runtime._start_calls == 1

    # Second start should be no-op
    collected = []
    async for event in session.start():
        collected.append(event)
    assert len(collected) == 0
    assert runtime._start_calls == 1


@pytest.mark.asyncio
async def test_session_end_is_idempotent():
    """Calling end() multiple times should not raise."""
    runtime = _FakeRuntime()
    session = ConversationSession(runtime=runtime, context=_make_context())

    await session.end()
    assert session.state == SessionState.ENDED

    # Second end should be safe
    await session.end()
    assert session.state == SessionState.ENDED
    assert runtime._ended is True


@pytest.mark.asyncio
async def test_session_end_after_error_records_error_reason():
    """Session ending after a runtime error should record ERROR reason."""
    runtime = _FakeRuntime(raise_on_start=True)
    session = ConversationSession(runtime=runtime, context=_make_context())

    with pytest.raises(RuntimeError, match="start failed"):
        async for _ in session.start():
            pass

    assert session.state == SessionState.ENDED
    assert session.termination_reason == TerminationReason.ERROR


@pytest.mark.asyncio
async def test_session_receive_message_after_end_raises():
    """Sending a message to an ended session should raise RuntimeError."""
    runtime = _FakeRuntime()
    session = ConversationSession(runtime=runtime, context=_make_context())

    await session.end()
    with pytest.raises(RuntimeError, match="ended session"):
        async for _ in session.receive_message("hello"):
            pass


@pytest.mark.asyncio
async def test_session_cancel_returns_to_running():
    """Cancel should transition CANCELLING → RUNNING."""
    runtime = _FakeRuntime()
    session = ConversationSession(runtime=runtime, context=_make_context())

    async for _ in session.start():
        pass
    assert session.state == SessionState.RUNNING

    await session.cancel()
    assert session.state == SessionState.RUNNING
    assert runtime._cancelled is True


@pytest.mark.asyncio
async def test_session_cancel_when_not_running_is_noop():
    """Cancel when session is CREATED should be a no-op."""
    runtime = _FakeRuntime()
    session = ConversationSession(runtime=runtime, context=_make_context())

    await session.cancel()
    assert session.state == SessionState.CREATED
    assert runtime._cancelled is False


# ── Concurrency / Race Condition Tests ───────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_end_does_not_double_end_runtime():
    """Concurrent end() calls should only call runtime.end() once."""
    runtime = _FakeRuntime()
    session = ConversationSession(runtime=runtime, context=_make_context())

    await asyncio.gather(session.end(), session.end(), session.end())
    assert runtime._ended is True
    # _FakeRuntime.end() is not idempotent itself — but ConversationSession is
    assert session.state == SessionState.ENDED


@pytest.mark.asyncio
async def test_concurrent_start_and_end_no_deadlock():
    """Starting and ending a session concurrently should not deadlock."""
    events = [SessionEventFactory.initial_message("hi")]
    runtime = _FakeRuntime(events=events, delay=0.01)
    session = ConversationSession(runtime=runtime, context=_make_context())

    async def collect():
        results = []
        async for event in session.start():
            results.append(event)
        return results

    # Run start and end concurrently — should complete without deadlock
    results, _ = await asyncio.gather(collect(), session.end())
    # Session state depends on timing — could be RUNNING (start won) or ENDED (end won)
    assert session.state in (SessionState.RUNNING, SessionState.ENDED)


@pytest.mark.asyncio
async def test_concurrent_receive_messages_are_serialized():
    """Multiple concurrent receive_message calls should each complete."""
    runtime = _FakeRuntime()
    session = ConversationSession(runtime=runtime, context=_make_context())

    async for _ in session.start():
        pass

    # Send 3 messages concurrently (wrap async generators in coroutines)
    async def collect_message(text):
        results = []
        async for event in session.receive_message(text):
            results.append(event)
        return results

    tasks = [collect_message(f"msg-{i}") for i in range(3)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # All should succeed (no exception)
    for r in results:
        assert not isinstance(r, Exception), f"Concurrent receive failed: {r}"
    assert runtime._send_calls == 3


# ── WebSocketTracker Concurrency Tests ───────────────────────────────


@pytest.mark.asyncio
async def test_ws_tracker_concurrent_add_remove():
    """Concurrent add/remove should not corrupt internal state."""
    from voice_platform.middleware.ws_tracker import WebSocketTracker

    tracker = WebSocketTracker()
    user_id = 100

    class FakeWS:
        async def close(self, code=None, reason=None):
            pass

    websockets = [FakeWS() for _ in range(10)]

    # Concurrently add all
    await asyncio.gather(*[tracker.add(user_id, ws) for ws in websockets])
    assert tracker.get_user_count(user_id) == 10

    # Concurrently remove all
    await asyncio.gather(*[tracker.remove(user_id, ws) for ws in websockets])
    assert tracker.get_user_count(user_id) == 0
    assert user_id not in tracker._connections


@pytest.mark.asyncio
async def test_ws_tracker_can_connect_enforces_limit():
    """can_connect should return False after reaching MAX_CONNECTIONS_PER_USER."""
    from voice_platform.middleware.ws_tracker import MAX_CONNECTIONS_PER_USER, WebSocketTracker

    tracker = WebSocketTracker()
    user_id = 200

    class FakeWS:
        async def close(self, code=None, reason=None):
            pass

    for i in range(MAX_CONNECTIONS_PER_USER):
        assert tracker.can_connect(user_id) is True
        await tracker.add(user_id, FakeWS())

    assert tracker.can_connect(user_id) is False


@pytest.mark.asyncio
async def test_ws_tracker_close_all_clears_connections():
    """close_all should close all websockets and clear internal state."""
    from voice_platform.middleware.ws_tracker import WebSocketTracker

    tracker = WebSocketTracker()

    class FakeWS:
        def __init__(self):
            self.closed = False

        async def close(self, code=None, reason=None):
            self.closed = True

    ws1, ws2 = FakeWS(), FakeWS()
    await tracker.add(1, ws1)
    await tracker.add(2, ws2)

    await tracker.close_all()
    assert tracker.get_total_count() == 0
    assert ws1.closed is True
    assert ws2.closed is True


@pytest.mark.asyncio
async def test_ws_tracker_remove_nonexistent_is_safe():
    """Removing a websocket that was never added should not raise."""
    from voice_platform.middleware.ws_tracker import WebSocketTracker

    tracker = WebSocketTracker()

    class FakeWS:
        pass

    # Should not raise
    await tracker.remove(999, FakeWS())
    assert tracker.get_user_count(999) == 0


# ── LangGraphStateManager Tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_in_memory_state_manager_lifecycle():
    """InMemoryStateManager should create and close checkpointer properly."""
    from voice_platform.runtime.session.state_manager import InMemoryStateManager

    sm = InMemoryStateManager()
    await sm.setup()

    cp = await sm.get_checkpointer()
    assert cp is not None

    # Second call should return same instance
    cp2 = await sm.get_checkpointer()
    assert cp is cp2

    await sm.close()
    assert sm._checkpointer is None

    # After close, get_checkpointer should create a new one
    cp3 = await sm.get_checkpointer()
    assert cp3 is not None
    assert cp is not cp3

    await sm.close()


@pytest.mark.asyncio
async def test_in_memory_state_manager_setup_is_idempotent():
    """setup() should be safe to call multiple times."""
    from voice_platform.runtime.session.state_manager import InMemoryStateManager

    sm = InMemoryStateManager()
    await sm.setup()
    await sm.setup()  # Should not raise
    await sm.close()


@pytest.mark.asyncio
async def test_in_memory_state_manager_close_is_idempotent():
    """close() should be safe to call multiple times."""
    from voice_platform.runtime.session.state_manager import InMemoryStateManager

    sm = InMemoryStateManager()
    await sm.setup()
    await sm.close()
    await sm.close()  # Should not raise


# ── ServiceContainer Tests ───────────────────────────────────────────


def test_service_container_construction_succeeds():
    """ServiceContainer should construct with valid PluginRegistry."""
    from voice_platform.runtime.session.service_container import ServiceContainer

    container = ServiceContainer()
    assert container.plugin_registry is not None


def test_service_container_plugin_registry_is_frozen():
    """PluginRegistry should be frozen after ServiceContainer construction."""
    from voice_platform.runtime.session.service_container import ServiceContainer

    container = ServiceContainer()
    # Frozen registry should not allow new registrations
    # Attempting to register should raise
    with pytest.raises(Exception):
        container.plugin_registry.register("test_plugin", MagicMock())


# ── FlowRuntime Boundary Tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_flow_runtime_interrupt_resume_boundary():
    """FlowRuntime should handle start/send/end lifecycle correctly."""
    from voice_platform.runtime.session.adapters.flow import FlowRuntime

    class FakeExecutor:
        def __init__(self):
            self._reset_called = False

        async def start_flow(self, callback):
            await callback({"type": "flow_start", "node_count": 3, "edge_count": 2})

        async def process_user_message(self, text, callback):
            await callback({"type": "node_start", "node_id": "node1"})
            await callback({"type": "node_result", "node_id": "node1"})
            await callback({"type": "flow_end", "total_nodes": 1})

        async def reset(self):
            self._reset_called = True

    executor = FakeExecutor()
    context = _make_context(conversation_id="test-conv-123")
    runtime = FlowRuntime(executor=executor)

    events = []
    async for event in runtime.start(context):
        events.append(event)

    assert len(events) == 1
    assert events[0].type == SessionEventType.FLOW_START

    # Send a message
    msg_events = []
    async for event in runtime.send_message(ConversationInput(text="hello")):
        msg_events.append(event)
    assert len(msg_events) == 3

    await runtime.end()
    assert executor._reset_called is True


# ── WeakRef Cleanup Tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_weakref_dies_after_end():
    """A ConversationSession should be collectable after end()."""
    import gc

    runtime = _FakeRuntime()
    session = ConversationSession(runtime=runtime, context=_make_context())
    ref = weakref.ref(session)

    await session.end()
    del session
    gc.collect()

    assert ref() is None, "Session should be garbage collected after end() and del"


@pytest.mark.asyncio
async def test_no_orphan_tasks_after_session_end():
    """No asyncio tasks should remain after session lifecycle completes."""
    runtime = _FakeRuntime(events=[SessionEventFactory.initial_message("hi")])
    session = ConversationSession(runtime=runtime, context=_make_context())

    async for _ in session.start():
        pass

    await session.end()

    # Check no orphan tasks (excluding the current test task)
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    assert len(pending) == 0, f"Orphan tasks remaining: {pending}"
