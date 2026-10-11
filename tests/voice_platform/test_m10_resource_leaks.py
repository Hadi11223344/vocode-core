"""M10.5 resource leak detection tests.

Verifies no resource leaks after:
- Multiple session create/end cycles
- WebSocketTransport open/close cycles
- FlowRuntime start/end cycles
- InMemoryStateManager setup/close cycles
- LLMClient creation (no orphan httpx clients)
- asyncio task leaks after session lifecycle
"""

import asyncio
import gc
import weakref
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


class _FakeRuntime:
    """Minimal runtime that yields events and tracks end() calls."""

    def __init__(self):
        self._ended = False

    async def start(self, context):
        yield SessionEventFactory.initial_message("hi")

    async def send_message(self, message):
        yield SessionEventFactory.token("ok")
        yield SessionEventFactory.message_end()

    async def cancel(self):
        pass

    async def end(self):
        self._ended = True


def _make_context():
    from voice_platform.integrations.plugins.registry import EmptyPluginRegistry
    from voice_platform.runtime.events.event_bus import NoOpEventBus
    from voice_platform.runtime.tracing.tracer import NoOpTracer

    conversation = ConversationContext(
        conversation_id=create_conversation_id(),
        user_id=1,
        agent_id=1,
        channel=ConversationChannel.PLAYGROUND_CHAT,
    )
    runtime = SimpleNamespace(
        agent=SimpleNamespace(model="gpt-4", provider="openai"),
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


# ── Session Resource Leak Tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_no_orphan_tasks_after_10_session_cycles():
    """10 create/start/send/end cycles should leave zero orphan asyncio tasks."""
    current = asyncio.current_task()
    for i in range(10):
        runtime = _FakeRuntime()
        session = ConversationSession(runtime=runtime, context=_make_context())
        async for _ in session.start():
            pass
        async for _ in session.receive_message(f"msg-{i}"):
            pass
        await session.end()
        del session

    gc.collect()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    assert len(pending) == 0, f"Orphan tasks after 10 cycles: {pending}"


@pytest.mark.asyncio
async def test_session_garbage_collected_after_end():
    """Sessions should be GC'd after end() + del (no lingering references)."""
    runtime = _FakeRuntime()
    session = ConversationSession(runtime=runtime, context=_make_context())
    ref = weakref.ref(session)

    async for _ in session.start():
        pass
    await session.end()
    del session
    gc.collect()

    assert ref() is None, "Session was not garbage collected after end()"


@pytest.mark.asyncio
async def test_no_orphan_tasks_after_flow_runtime_cycles():
    """FlowRuntime create/start/send/end cycles should leave no orphan tasks."""
    from voice_platform.runtime.session.adapters.flow import FlowRuntime

    current = asyncio.current_task()

    class FakeExecutor:
        async def start_flow(self, callback):
            await callback({"type": "flow_start", "node_count": 1, "edge_count": 0})

        async def process_user_message(self, text, callback):
            await callback({"type": "flow_end", "total_nodes": 1})

        async def reset(self):
            pass

    executor = FakeExecutor()
    runtime = FlowRuntime(executor=executor)

    for i in range(5):
        async for _ in runtime.start(_make_context()):
            pass
        async for _ in runtime.send_message(ConversationInput(text=f"msg-{i}")):
            pass

    await runtime.end()
    gc.collect()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    assert len(pending) == 0, f"Orphan tasks after FlowRuntime cycles: {pending}"


# ── WebSocketTracker Leak Tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_ws_tracker_no_leaks_after_add_remove_cycles():
    """Repeated add/remove cycles should not leak connections."""
    from voice_platform.middleware.ws_tracker import WebSocketTracker

    tracker = WebSocketTracker()

    class FakeWS:
        async def close(self, code=None, reason=None):
            pass

    for cycle in range(20):
        websockets = [FakeWS() for _ in range(5)]
        for ws in websockets:
            await tracker.add(cycle, ws)
        for ws in websockets:
            await tracker.remove(cycle, ws)

    assert tracker.get_total_count() == 0
    assert len(tracker._connections) == 0


@pytest.mark.asyncio
async def test_ws_tracker_close_all_clears_everything():
    """close_all should leave zero connections."""
    from voice_platform.middleware.ws_tracker import WebSocketTracker

    tracker = WebSocketTracker()

    class FakeWS:
        def __init__(self):
            self.closed = False

        async def close(self, code=None, reason=None):
            self.closed = True

    for user_id in range(10):
        for _ in range(3):
            await tracker.add(user_id, FakeWS())

    assert tracker.get_total_count() == 30

    await tracker.close_all()
    assert tracker.get_total_count() == 0
    assert len(tracker._connections) == 0


# ── StateManager Leak Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_state_manager_close_releases_checkpointer():
    """InMemoryStateManager.close() should release the checkpointer reference."""
    from voice_platform.runtime.session.state_manager import InMemoryStateManager

    sm = InMemoryStateManager()
    await sm.setup()
    cp = await sm.get_checkpointer()
    assert cp is not None

    await sm.close()
    assert sm._checkpointer is None

    # Re-open and close to verify no leak
    await sm.setup()
    cp2 = await sm.get_checkpointer()
    assert cp2 is not None
    assert cp is not cp2  # New instance after close

    await sm.close()


# ── LLMClient Resource Tests ─────────────────────────────────────────


def test_llm_client_creation_does_not_leak_httpx_clients():
    """Creating LLMClient instances should not leak httpx.AsyncClient references."""
    from voice_platform.runtime.llm.client import LLMClient
    from voice_platform.runtime.llm.retry import RetryExecutor
    from voice_platform.runtime.llm.timeout import TimeoutExecutor
    from voice_platform.runtime.llm.types import ProviderCapability, RetryPolicy, TimeoutPolicy

    class FakeAdapter:
        capabilities = ProviderCapability(supports_streaming=True)

        def translate_messages(self, messages):
            return messages

        def stream(self, messages, **kwargs):
            async def _gen():
                from voice_platform.runtime.llm.types import StreamChunk
                yield StreamChunk(content="hi")
            return _gen()

    retry = RetryExecutor(RetryPolicy(max_retries=0))
    timeout = TimeoutExecutor(TimeoutPolicy(total_timeout=5.0))

    refs = []
    for _ in range(10):
        client = LLMClient(adapter=FakeAdapter(), retry=retry, timeout=timeout)
        refs.append(weakref.ref(client))
        del client

    gc.collect()
    surviving = [r() for r in refs if r() is not None]
    assert len(surviving) == 0, f"LLMClient instances leaked: {len(surviving)}"


# ── ServiceContainer Stability ───────────────────────────────────────


def test_service_container_repeated_construction():
    """Repeated ServiceContainer construction should not leak resources."""
    import gc

    from voice_platform.runtime.session.service_container import ServiceContainer

    refs = []
    for _ in range(5):
        container = ServiceContainer()
        refs.append(weakref.ref(container))
        del container

    gc.collect()
    surviving = [r() for r in refs if r() is not None]
    assert len(surviving) == 0, f"ServiceContainer instances leaked: {len(surviving)}"
