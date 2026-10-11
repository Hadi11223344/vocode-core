"""Tests for WebSocketTransport and TelephonyTransport.

Verifies:
- WebSocketTransport protocol conformance
- JSON encoding/decoding (SessionEvent ↔ wire format)
- TransportEvent type mapping
- TelephonyTransport stub protocol conformance
- No runtime/executor imports in transport modules
"""

from __future__ import annotations

import inspect
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from voice_platform.runtime.session.events import (
    SessionEvent,
    SessionEventFactory,
    SessionEventType,
    TransportEvent,
    TransportEventType,
)
from voice_platform.runtime.transport.protocol import ConversationTransport
from voice_platform.runtime.transport.telephony import TelephonyTransport
from voice_platform.runtime.transport.websocket import WebSocketTransport


class TestWebSocketTransportEncoding:
    """Test SessionEvent → JSON encoding."""

    def test_encode_token(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        event = SessionEventFactory.token("hello")
        result = transport._encode(event)
        assert result == {"type": "agent_token", "text": "hello"}

    def test_encode_message_end(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        event = SessionEventFactory.message_end()
        result = transport._encode(event)
        assert result == {"type": "message_end"}

    def test_encode_assistant_message(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        event = SessionEventFactory.assistant_message("response text")
        result = transport._encode(event)
        assert result == {"type": "agent_response", "text": "response text"}

    def test_encode_error(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        event = SessionEventFactory.error("something broke")
        result = transport._encode(event)
        assert result == {"type": "error", "text": "something broke"}

    def test_encode_pong(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        event = SessionEventFactory.pong()
        result = transport._encode(event)
        assert result == {"type": "pong"}

    def test_encode_flow_start(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        event = SessionEventFactory.flow_start(node_count=5, edge_count=3)
        result = transport._encode(event)
        assert result["type"] == "flow_start"
        assert result["node_count"] == 5
        assert result["edge_count"] == 3

    def test_encode_node_start(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        event = SessionEventFactory.node_start("node_1", node_type="agent")
        result = transport._encode(event)
        assert result["type"] == "node_start"
        assert result["node_id"] == "node_1"
        assert result["node_type"] == "agent"

    def test_encode_edge_traversed(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        event = SessionEventFactory.edge_traversed("a", "b")
        result = transport._encode(event)
        assert result == {"type": "edge_traversed", "source": "a", "target": "b"}

    def test_encode_reset_ack(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        event = SessionEventFactory.reset_ack()
        result = transport._encode(event)
        assert result == {"type": "reset_ack"}

    def test_encode_initial_message(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        event = SessionEventFactory.initial_message("Welcome!")
        result = transport._encode(event)
        assert result == {"type": "initial_message", "text": "Welcome!"}

    def test_encode_agent_info(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        event = SessionEventFactory.agent_info("Bot", "gpt-4o", "openai")
        result = transport._encode(event)
        assert result["type"] == "agent_info"
        assert result["agent"]["name"] == "Bot"

    def test_encode_context_with_thread_id(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        event = SessionEventFactory.context({"key": "val"}, thread_id="t-123")
        result = transport._encode(event)
        assert result["type"] == "context"
        assert result["thread_id"] == "t-123"

    def test_encode_metrics(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        event = SessionEventFactory.metrics({"tokens": 100})
        result = transport._encode(event)
        assert result["type"] == "metrics"
        assert result["metrics"]["tokens"] == 100


class TestWebSocketTransportDecoding:
    """Test wire JSON → TransportEvent decoding."""

    @pytest.mark.asyncio
    async def test_decode_message(self):
        ws = MagicMock()
        ws.receive_text = AsyncMock(return_value=json.dumps({
            "type": "message", "text": "hello world"
        }))
        transport = WebSocketTransport(websocket=ws, user_id=1, receive_timeout=1.0)
        event = await transport.receive()
        assert event is not None
        assert event.type == TransportEventType.TEXT
        assert event.payload["text"] == "hello world"

    @pytest.mark.asyncio
    async def test_decode_start(self):
        ws = MagicMock()
        ws.receive_text = AsyncMock(return_value=json.dumps({
            "type": "start", "thread_id": "t-abc"
        }))
        transport = WebSocketTransport(websocket=ws, user_id=1, receive_timeout=1.0)
        event = await transport.receive()
        assert event is not None
        assert event.type == TransportEventType.START
        assert event.payload["thread_id"] == "t-abc"

    @pytest.mark.asyncio
    async def test_decode_reset(self):
        ws = MagicMock()
        ws.receive_text = AsyncMock(return_value=json.dumps({"type": "reset"}))
        transport = WebSocketTransport(websocket=ws, user_id=1, receive_timeout=1.0)
        event = await transport.receive()
        assert event is not None
        assert event.type == TransportEventType.RESET

    @pytest.mark.asyncio
    async def test_decode_ping(self):
        ws = MagicMock()
        ws.receive_text = AsyncMock(return_value=json.dumps({"type": "ping"}))
        transport = WebSocketTransport(websocket=ws, user_id=1, receive_timeout=1.0)
        event = await transport.receive()
        assert event is not None
        assert event.type == TransportEventType.PING

    @pytest.mark.asyncio
    async def test_decode_set_context(self):
        ws = MagicMock()
        ws.receive_text = AsyncMock(return_value=json.dumps({
            "type": "set_context", "context": {"foo": "bar"}
        }))
        transport = WebSocketTransport(websocket=ws, user_id=1, receive_timeout=1.0)
        event = await transport.receive()
        assert event is not None
        assert event.type == TransportEventType.SET_CONTEXT
        assert event.payload["context"] == {"foo": "bar"}

    @pytest.mark.asyncio
    async def test_decode_empty_text_returns_none(self):
        ws = MagicMock()
        ws.receive_text = AsyncMock(return_value=json.dumps({
            "type": "message", "text": "  "
        }))
        transport = WebSocketTransport(websocket=ws, user_id=1, receive_timeout=1.0)
        event = await transport.receive()
        assert event is None

    @pytest.mark.asyncio
    async def test_decode_invalid_json_returns_none(self):
        ws = MagicMock()
        ws.receive_text = AsyncMock(return_value="not json at all")
        transport = WebSocketTransport(websocket=ws, user_id=1, receive_timeout=1.0)
        event = await transport.receive()
        assert event is None

    @pytest.mark.asyncio
    async def test_decode_unknown_type_returns_none(self):
        ws = MagicMock()
        ws.receive_text = AsyncMock(return_value=json.dumps({"type": "unknown"}))
        transport = WebSocketTransport(websocket=ws, user_id=1, receive_timeout=1.0)
        event = await transport.receive()
        assert event is None

    @pytest.mark.asyncio
    async def test_message_too_long_sends_error(self):
        ws = MagicMock()
        ws.receive_text = AsyncMock(return_value=json.dumps({
            "type": "message", "text": "x" * 5000
        }))
        ws.send_json = AsyncMock()
        transport = WebSocketTransport(websocket=ws, user_id=1, max_message_chars=100, receive_timeout=1.0)
        event = await transport.receive()
        assert event is None
        ws.send_json.assert_called_once()
        error_msg = ws.send_json.call_args[0][0]
        assert error_msg["type"] == "error"


class TestWebSocketTransportProtocol:
    """Test WebSocketTransport conforms to ConversationTransport protocol."""

    def test_protocol_conformance(self):
        ws = MagicMock()
        transport = WebSocketTransport(websocket=ws, user_id=1)
        assert hasattr(transport, "start")
        assert hasattr(transport, "receive")
        assert hasattr(transport, "send")
        assert hasattr(transport, "close")

    def test_no_runtime_imports(self):
        source = inspect.getsource(WebSocketTransport)
        forbidden = [
            "ExecutionRuntime",
            "ConversationSession",
            "LangGraphFlowExecutor",
            "PlaygroundConversation",
            "FlowRuntime",
            "PlaygroundRuntime",
            "ConversationSessionFactory",
        ]
        for name in forbidden:
            assert name not in source, f"WebSocketTransport references runtime class: {name}"


class TestTelephonyTransport:
    """Test TelephonyTransport stub."""

    @pytest.mark.asyncio
    async def test_start_noop(self):
        transport = TelephonyTransport()
        await transport.start()

    @pytest.mark.asyncio
    async def test_receive_returns_none(self):
        transport = TelephonyTransport()
        result = await transport.receive()
        assert result is None

    @pytest.mark.asyncio
    async def test_send_noop(self):
        transport = TelephonyTransport()
        event = SessionEventFactory.token("test")
        await transport.send(event)

    @pytest.mark.asyncio
    async def test_close_noop(self):
        transport = TelephonyTransport()
        await transport.close()

    def test_protocol_conformance(self):
        transport = TelephonyTransport()
        assert hasattr(transport, "start")
        assert hasattr(transport, "receive")
        assert hasattr(transport, "send")
        assert hasattr(transport, "close")

    def test_no_runtime_imports(self):
        source = inspect.getsource(TelephonyTransport)
        forbidden_imports = [
            "from voice_platform.runtime.session.execution",
            "from voice_platform.runtime.session.session",
            "from voice_platform.flow.executor",
            "from voice_platform.runtime.session.adapters",
            "import ExecutionRuntime",
            "import ConversationSession",
        ]
        for keyword in forbidden_imports:
            assert keyword not in source, f"TelephonyTransport contains forbidden import: {keyword}"
