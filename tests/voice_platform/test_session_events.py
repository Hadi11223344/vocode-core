"""Tests for SessionEvent, TransportEvent, SessionEventFactory.

Verifies:
- Event types are enums
- Events are frozen (immutable)
- SessionEventFactory produces correct events
- SessionEventFactory is not instantiable
- SessionEvent.data is shallow-immutable (MappingProxyType)
- No serialization methods on SessionEvent
"""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from voice_platform.runtime.session.events import (
    SessionEvent,
    SessionEventFactory,
    SessionEventType,
    TransportEvent,
    TransportEventType,
)


class TestTransportEvent:
    def test_type_is_enum(self):
        assert isinstance(TransportEventType.TEXT, TransportEventType)

    def test_event_is_frozen(self):
        event = TransportEvent(TransportEventType.TEXT, {"text": "hi"})
        with pytest.raises(FrozenInstanceError):
            event.type = TransportEventType.PING  # type: ignore[misc]

    def test_default_payload_is_empty_mapping(self):
        event = TransportEvent(TransportEventType.PING)
        assert len(event.payload) == 0
        assert isinstance(event.payload, MappingProxyType)


class TestSessionEvent:
    def test_type_is_enum(self):
        assert isinstance(SessionEventType.TOKEN, SessionEventType)

    def test_event_is_frozen(self):
        event = SessionEvent(SessionEventType.TOKEN, {"text": "hi"})
        with pytest.raises(FrozenInstanceError):
            event.type = SessionEventType.ERROR  # type: ignore[misc]

    def test_data_is_mapping_proxy(self):
        event = SessionEvent(SessionEventType.TOKEN, {"text": "hi"})
        assert isinstance(event.data, MappingProxyType)

    def test_default_data_is_empty_mapping(self):
        event = SessionEvent(SessionEventType.PONG)
        assert len(event.data) == 0
        assert isinstance(event.data, MappingProxyType)

    def test_no_serialization_methods(self):
        source = inspect.getsource(SessionEvent)
        assert "def to_json" not in source
        assert "def to_dict" not in source
        assert "def serialize" not in source
        assert "def to_wire" not in source
        assert "def encode" not in source


class TestSessionEventFactory:
    def test_not_instantiable(self):
        with pytest.raises(TypeError, match="static namespace"):
            SessionEventFactory()

    def test_token(self):
        event = SessionEventFactory.token("hello")
        assert event.type == SessionEventType.TOKEN
        assert event.data["text"] == "hello"

    def test_message_end(self):
        event = SessionEventFactory.message_end()
        assert event.type == SessionEventType.MESSAGE_END

    def test_assistant_message(self):
        event = SessionEventFactory.assistant_message("response")
        assert event.type == SessionEventType.ASSISTANT_MESSAGE
        assert event.data["text"] == "response"

    def test_error(self):
        event = SessionEventFactory.error("boom")
        assert event.type == SessionEventType.ERROR
        assert event.data["text"] == "boom"

    def test_pong(self):
        event = SessionEventFactory.pong()
        assert event.type == SessionEventType.PONG

    def test_flow_start(self):
        event = SessionEventFactory.flow_start(node_count=5, edge_count=4)
        assert event.type == SessionEventType.FLOW_START
        assert event.data["node_count"] == 5
        assert event.data["edge_count"] == 4

    def test_node_start(self):
        event = SessionEventFactory.node_start("node_1", node_type="agent")
        assert event.type == SessionEventType.NODE_START
        assert event.data["node_id"] == "node_1"
        assert event.data["node_type"] == "agent"

    def test_node_result(self):
        event = SessionEventFactory.node_result("node_1", result={"output": "done"})
        assert event.type == SessionEventType.NODE_RESULT
        assert event.data["node_id"] == "node_1"

    def test_edge_traversed(self):
        event = SessionEventFactory.edge_traversed("node_a", "node_b")
        assert event.type == SessionEventType.EDGE_TRAVERSED
        assert event.data["source"] == "node_a"
        assert event.data["target"] == "node_b"

    def test_flow_end(self):
        event = SessionEventFactory.flow_end(total_nodes=10)
        assert event.type == SessionEventType.FLOW_END
        assert event.data["total_nodes"] == 10

    def test_agent_info(self):
        event = SessionEventFactory.agent_info("Agent1", "gpt-4o", "openai")
        assert event.type == SessionEventType.AGENT_INFO
        assert event.data["name"] == "Agent1"

    def test_initial_message(self):
        event = SessionEventFactory.initial_message("Welcome!")
        assert event.type == SessionEventType.INITIAL_MESSAGE
        assert event.data["text"] == "Welcome!"

    def test_context_with_thread_id(self):
        event = SessionEventFactory.context({"key": "val"}, thread_id="thread-123")
        assert event.type == SessionEventType.CONTEXT
        assert event.data["thread_id"] == "thread-123"

    def test_context_without_thread_id(self):
        event = SessionEventFactory.context({"key": "val"})
        assert event.type == SessionEventType.CONTEXT
        assert "thread_id" not in event.data

    def test_context_updated(self):
        event = SessionEventFactory.context_updated({"key": "val"})
        assert event.type == SessionEventType.CONTEXT_UPDATED

    def test_reset_ack(self):
        event = SessionEventFactory.reset_ack()
        assert event.type == SessionEventType.RESET_ACK

    def test_metrics(self):
        event = SessionEventFactory.metrics({"tokens": 100, "latency": 50.0})
        assert event.type == SessionEventType.METRICS
        assert event.data["tokens"] == 100

    def test_info(self):
        event = SessionEventFactory.info("something happened")
        assert event.type == SessionEventType.INFO
        assert event.data["text"] == "something happened"

    def test_all_events_are_frozen(self):
        """All factory methods return frozen SessionEvent instances."""
        events = [
            SessionEventFactory.token("test"),
            SessionEventFactory.message_end(),
            SessionEventFactory.assistant_message("test"),
            SessionEventFactory.error("test"),
            SessionEventFactory.pong(),
            SessionEventFactory.flow_start(1, 1),
            SessionEventFactory.node_start("n"),
            SessionEventFactory.node_result("n"),
            SessionEventFactory.edge_traversed("a", "b"),
            SessionEventFactory.flow_end(1),
            SessionEventFactory.agent_info("n", "m", "p"),
            SessionEventFactory.initial_message("test"),
            SessionEventFactory.context({}),
            SessionEventFactory.context_updated({}),
            SessionEventFactory.reset_ack(),
            SessionEventFactory.metrics({"k": 1}),
            SessionEventFactory.info("test"),
        ]
        for event in events:
            with pytest.raises(FrozenInstanceError):
                event.type = SessionEventType.ERROR  # type: ignore[misc]
