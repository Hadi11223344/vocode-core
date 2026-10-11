"""M10.5 stress test — 100-session lifecycle simulation.

Simulates 100 session create/start/send/end cycles and verifies:
- No orphan asyncio tasks remain
- No memory leaks (weakrefs die after GC)
- All sessions complete the full lifecycle
- No exceptions during stress
"""

import asyncio
import gc
import weakref
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from voice_platform.runtime.session.conversation_context import (
    ConversationChannel,
    ConversationContext,
)
from voice_platform.runtime.session.context import ExecutionContext
from voice_platform.runtime.session.events import SessionEventFactory
from voice_platform.runtime.session.infrastructure_context import InfrastructureContext
from voice_platform.runtime.session.session import (
    ConversationSession,
    SessionState,
    create_conversation_id,
)


class _StressRuntime:
    """Minimal runtime for stress testing — no I/O, just yields events."""

    def __init__(self):
        self._ended = False

    async def start(self, context):
        yield SessionEventFactory.initial_message("hi")
        yield SessionEventFactory.agent_info(name="Stress", model="gpt-4", provider="openai")

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


@pytest.mark.asyncio
async def test_100_session_lifecycle_no_leaks():
    """100 sequential session lifecycles should complete with no orphan tasks."""
    current = asyncio.current_task()
    ended_count = 0

    for i in range(100):
        runtime = _StressRuntime()
        session = ConversationSession(runtime=runtime, context=_make_context())

        # Full lifecycle: start → send → end
        async for _ in session.start():
            pass

        async for _ in session.receive_message(f"stress-msg-{i}"):
            pass

        await session.end()

        assert session.state == SessionState.ENDED
        assert runtime._ended is True
        ended_count += 1
        del session

    assert ended_count == 100

    gc.collect()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    assert len(pending) == 0, f"Orphan tasks after 100 sessions: {pending}"


@pytest.mark.asyncio
async def test_10_concurrent_sessions_no_deadlock():
    """10 concurrent session lifecycles should complete without deadlock."""
    current = asyncio.current_task()

    async def run_session(idx: int):
        runtime = _StressRuntime()
        session = ConversationSession(runtime=runtime, context=_make_context())

        async for _ in session.start():
            pass
        async for _ in session.receive_message(f"concurrent-{idx}"):
            pass
        await session.end()
        return session.state

    results = await asyncio.gather(*[run_session(i) for i in range(10)])

    assert all(r == SessionState.ENDED for r in results), "All sessions should be ENDED"

    gc.collect()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    assert len(pending) == 0, f"Orphan tasks after concurrent sessions: {pending}"


@pytest.mark.asyncio
async def test_100_sessions_garbage_collected():
    """All 100 sessions should be GC'd after end() + del."""
    refs = []

    for i in range(100):
        runtime = _StressRuntime()
        session = ConversationSession(runtime=runtime, context=_make_context())
        async for _ in session.start():
            pass
        await session.end()
        refs.append(weakref.ref(session))
        del session

    gc.collect()
    surviving = [r() for r in refs if r() is not None]
    assert len(surviving) == 0, f"Sessions not GC'd: {len(surviving)}/{len(refs)}"


@pytest.mark.asyncio
async def test_50_sessions_with_cancel_no_leaks():
    """50 sessions with cancel mid-lifecycle should not leak tasks."""
    current = asyncio.current_task()

    for i in range(50):
        runtime = _StressRuntime()
        session = ConversationSession(runtime=runtime, context=_make_context())

        async for _ in session.start():
            pass

        # Cancel then end
        await session.cancel()
        await session.end()

        assert session.state == SessionState.ENDED
        del session

    gc.collect()
    pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
    assert len(pending) == 0, f"Orphan tasks after cancel cycles: {pending}"
