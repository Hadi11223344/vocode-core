"""Phase 5.6 tests for the flow tracing layer."""

import asyncio
import pytest

from voice_platform.flow.tracer import Tracer, get_tracer


@pytest.mark.asyncio
async def test_tracer_emits_event_and_awaits_callback():
    """Tracer.emit should append to events and await an async callback."""
    received = []

    async def _cb(event):
        received.append(event)

    tracer = Tracer(event_callback=_cb, workflow_id="wf-1", agent_id=1)
    event = await tracer.emit("test", node_id="n1")

    assert event["event"] == "test"
    assert event["node_id"] == "n1"
    assert event["workflow_id"] == "wf-1"
    assert len(tracer.events) == 1
    assert len(received) == 1


@pytest.mark.asyncio
async def test_tracer_caps_max_events():
    """Tracer should drop oldest events once max_events is exceeded."""
    tracer = Tracer(max_events=3)
    for i in range(5):
        await tracer.emit("slot_filled", slot=f"slot-{i}")
    assert len(tracer.events) == 3
    assert tracer.events[0]["slot"] == "slot-2"


@pytest.mark.asyncio
async def test_get_tracer_prefers_internal_tracer():
    """get_tracer should return the _tracer set by the compiler wrapper."""
    inner = Tracer()
    config = {"configurable": {"_tracer": inner, "tracer": Tracer()}}
    assert get_tracer(config) is inner


def test_get_tracer_returns_null_tracer_by_default():
    """get_tracer should return a no-op tracer when none is configured."""
    tracer = get_tracer({})
    assert tracer.__class__.__name__ == "_NullTracer"
