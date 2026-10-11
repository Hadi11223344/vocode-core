"""WebSocketTransport — dumb I/O adapter for FastAPI WebSocket.

Responsibilities:
- Socket lifecycle (accept, close)
- JSON encoding (SessionEvent → JSON dict)
- JSON decoding (JSON dict → TransportEvent)
- Heartbeat (timeout → None, caller sends ping)
- Disconnect handling
- Rate limiting / message size limits

No runtime, executor, session, or plugin registry imports.
Transport only sees SessionEvent and TransportEvent.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from voice_platform.middleware.ws_tracker import ws_tracker
from voice_platform.runtime.session.events import (
    SessionEvent,
    SessionEventFactory,
    SessionEventType,
    TransportEvent,
    TransportEventType,
)

PLAYGROUND_MAX_MESSAGE_CHARS = 4000
_RECEIVE_TIMEOUT = 300.0


class WebSocketTransport:
    """Dumb WebSocket I/O adapter.

    Converts between wire JSON and domain events.
    SessionEvent is never serialized by runtime — this transport
    owns the SessionEvent → JSON mapping.
    """

    def __init__(
        self,
        websocket: WebSocket,
        user_id: int,
        max_message_chars: int = PLAYGROUND_MAX_MESSAGE_CHARS,
        receive_timeout: float = _RECEIVE_TIMEOUT,
    ) -> None:
        self._ws = websocket
        self._user_id = user_id
        self._max_chars = max_message_chars
        self._timeout = receive_timeout
        self._started = False
        self._closed = False

    async def start(self) -> None:
        """Accept the WebSocket connection and register with tracker."""
        from voice_platform.middleware.auth_middleware import _wants_bearer_subprotocol

        subprotocol = "bearer" if _wants_bearer_subprotocol(self._ws) else None
        if subprotocol:
            await self._ws.accept(subprotocol=subprotocol)
        else:
            await self._ws.accept()
        await ws_tracker.add(self._user_id, self._ws)
        self._started = True

    async def receive(self) -> TransportEvent | None:
        """Receive next wire message and decode to TransportEvent.

        Returns None on timeout (caller should send ping).
        Raises WebSocketDisconnect when client disconnects.
        """
        try:
            raw = await asyncio.wait_for(
                self._ws.receive_text(),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            return None
        except WebSocketDisconnect:
            raise
        except Exception as e:
            logger.debug(f"WebSocketTransport receive error: {e}")
            raise

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"WebSocketTransport: invalid JSON from client: {raw[:100]}")
            return None

        msg_type = data.get("type", "")

        if msg_type == "message":
            text = data.get("text", "").strip()
            if not text:
                return None
            if len(text) > self._max_chars:
                await self._ws.send_json({
                    "type": "error",
                    "text": f"Message too long. Maximum {self._max_chars} characters.",
                })
                return None
            return TransportEvent(TransportEventType.TEXT, {"text": text})

        elif msg_type == "start":
            payload: dict[str, Any] = {}
            thread_id = data.get("thread_id")
            if thread_id and isinstance(thread_id, str):
                payload["thread_id"] = thread_id
            return TransportEvent(TransportEventType.START, payload)

        elif msg_type == "set_context":
            return TransportEvent(
                TransportEventType.SET_CONTEXT,
                {"context": data.get("context", {})},
            )

        elif msg_type == "reset":
            return TransportEvent(TransportEventType.RESET, {})

        elif msg_type == "ping":
            return TransportEvent(TransportEventType.PING, {})

        elif msg_type == "hangup":
            return TransportEvent(TransportEventType.HANGUP, {})

        else:
            logger.warning(f"WebSocketTransport: unknown message type: {msg_type}")
            return None

    async def send(self, event: SessionEvent) -> None:
        """Encode SessionEvent to JSON and send to client.

        This is the sole place where SessionEvent is serialized.
        """
        payload = self._encode(event)
        try:
            await asyncio.wait_for(
                self._ws.send_json(payload),
                timeout=10.0,
            )
        except Exception as e:
            logger.warning(f"WebSocketTransport: failed to send event: {e}")

    async def close(self) -> None:
        """Disconnect and remove from tracker."""
        if self._closed:
            return
        self._closed = True
        await ws_tracker.remove(self._user_id, self._ws)
        try:
            await self._ws.close()
        except Exception:
            pass

    def _encode(self, event: SessionEvent) -> dict[str, Any]:
        """Map SessionEvent → JSON dict for wire transmission."""
        et = event.type
        data = dict(event.data)

        if et == SessionEventType.TOKEN:
            out: dict[str, Any] = {"type": "agent_token", "text": data.get("text", "")}
            if "node_id" in data and data["node_id"]:
                out["node_id"] = data["node_id"]
            return out
        elif et == SessionEventType.MESSAGE_END:
            return {"type": "message_end"}
        elif et == SessionEventType.ASSISTANT_MESSAGE:
            out_am: dict[str, Any] = {"type": "agent_response", "text": data.get("text", "")}
            if "node_id" in data and data["node_id"]:
                out_am["node_id"] = data["node_id"]
            return out_am
        elif et == SessionEventType.FLOW_START:
            return {
                "type": "flow_start",
                "node_count": data.get("node_count", 0),
                "edge_count": data.get("edge_count", 0),
            }
        elif et == SessionEventType.NODE_START:
            result: dict[str, Any] = {"type": "node_start", "node_id": data.get("node_id", "")}
            if "node_type" in data and data["node_type"] is not None:
                result["node_type"] = data["node_type"]
            if "label" in data and data["label"] is not None:
                result["label"] = data["label"]
            return result
        elif et == SessionEventType.NODE_RESULT:
            r: dict[str, Any] = {"type": "node_result", "node_id": data.get("node_id", "")}
            for k in ("node_type", "label", "status", "duration_ms", "error"):
                if k in data and data[k] is not None:
                    r[k] = data[k]
            if "result" in data and data["result"] is not None:
                r["result"] = data["result"]
            return r
        elif et == SessionEventType.EDGE_TRAVERSED:
            out2: dict[str, Any] = {
                "type": "edge_traversed",
                "source": data.get("source", ""),
                "target": data.get("target", ""),
            }
            if "label" in data and data["label"]:
                out2["label"] = data["label"]
            return out2
        elif et == SessionEventType.FLOW_END:
            return {"type": "flow_end", "total_nodes": data.get("total_nodes", 0)}
        elif et == SessionEventType.ERROR:
            return {"type": "error", "text": data.get("text", "")}
        elif et == SessionEventType.PONG:
            return {"type": "pong"}
        elif et == SessionEventType.CONTEXT:
            r2: dict[str, Any] = {"type": "context", "context": data.get("context")}
            if "thread_id" in data:
                r2["thread_id"] = data["thread_id"]
            return r2
        elif et == SessionEventType.CONTEXT_UPDATED:
            return {"type": "context_updated", "context": data.get("context")}
        elif et == SessionEventType.RESET_ACK:
            return {"type": "reset_ack"}
        elif et == SessionEventType.AGENT_INFO:
            return {
                "type": "agent_info",
                "agent": {
                    "name": data.get("name", ""),
                    "model": data.get("model", ""),
                    "provider": data.get("provider", ""),
                },
            }
        elif et == SessionEventType.RUNTIME_IDENTITY:
            return {"type": "runtime_identity", "runtime_identity": data}
        elif et == SessionEventType.INITIAL_MESSAGE:
            return {"type": "initial_message", "text": data.get("text", "")}
        elif et == SessionEventType.METRICS:
            return {"type": "metrics", "metrics": data.get("metrics", data)}
        elif et == SessionEventType.INFO:
            return {"type": "info", "text": data.get("text", "")}
        elif et == SessionEventType.CONDITION_BRANCH:
            return {
                "type": "condition_branch",
                "node_id": data.get("node_id", ""),
                "condition_met": data.get("condition_met", False),
            }
        elif et == SessionEventType.VARIABLES_EXTRACTED:
            return {
                "type": "variables_extracted",
                "node_id": data.get("node_id", ""),
                "variables": data.get("variables"),
            }
        elif et == SessionEventType.EXTRACTION_FAILED:
            return {
                "type": "extraction_failed",
                "node_id": data.get("node_id", ""),
                "variables": data.get("variables", []),
                "text": data.get("text", ""),
            }
        elif et == SessionEventType.SLOT_VALIDATION:
            return {
                "type": "slot_validation",
                "node_id": data.get("node_id", ""),
                "slot": data.get("slot", ""),
                "raw_value": data.get("raw_value", ""),
                "normalized_value": data.get("normalized_value", ""),
                "status": data.get("status", ""),
                "error": data.get("error", ""),
            }
        elif et == SessionEventType.SLOT_EXHAUSTED:
            return {
                "type": "slot_exhausted",
                "node_id": data.get("node_id", ""),
                "slot": data.get("slot", ""),
                "text": data.get("text", ""),
            }
        elif et == SessionEventType.DEBUG:
            return {"type": "debug", "text": data.get("text", "")}
        else:
            return {"type": et.value, **data}
