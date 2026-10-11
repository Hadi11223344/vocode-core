"""Domain event types for transport and session communication.

TransportEvent: wire-level events from the transport layer (WebSocket, telephony).
SessionEvent: internal domain events from ConversationSession / ExecutionRuntime.

SessionEvent is never serialized. Transports convert SessionEvent → wire format
(JSON, audio, SSE, etc.). Runtime is completely unaware of JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class TransportEventType(Enum):
    """Wire-level event types produced by transports."""
    CONNECTED = "connected"
    TEXT = "text"
    PING = "ping"
    HANGUP = "hangup"
    INTERRUPT = "interrupt"
    RESET = "reset"
    SET_CONTEXT = "set_context"
    START = "start"


class SessionEventType(Enum):
    """Internal domain event types yielded by ConversationSession."""
    ASSISTANT_MESSAGE = "assistant_message"
    TOKEN = "token"
    MESSAGE_END = "message_end"
    FLOW_START = "flow_start"
    NODE_START = "node_start"
    NODE_RESULT = "node_result"
    EDGE_TRAVERSED = "edge_traversed"
    FLOW_END = "flow_end"
    ERROR = "error"
    PONG = "pong"
    CONTEXT = "context"
    CONTEXT_UPDATED = "context_updated"
    RESET_ACK = "reset_ack"
    AGENT_INFO = "agent_info"
    RUNTIME_IDENTITY = "runtime_identity"
    INITIAL_MESSAGE = "initial_message"
    METRICS = "metrics"
    INFO = "info"
    CONDITION_BRANCH = "condition_branch"
    VARIABLES_EXTRACTED = "variables_extracted"
    EXTRACTION_FAILED = "extraction_failed"
    SLOT_VALIDATION = "slot_validation"
    SLOT_EXHAUSTED = "slot_exhausted"
    DEBUG = "debug"


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True)
class TransportEvent:
    """Wire-level event from a transport (WebSocket, telephony, etc.).

    Attributes:
        type: The transport event type.
        payload: Shallow-immutable mapping of event-specific fields.
    """
    type: TransportEventType
    payload: Mapping[str, Any] = field(default_factory=_empty_mapping)  # type: ignore[misc]

    def __post_init__(self) -> None:
        if not isinstance(self.payload, MappingProxyType):
            object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True)
class SessionEvent:
    """Internal domain event from ConversationSession.

    Never serialized — transports convert this to wire format.
    Attributes:
        type: The session event type.
        data: Shallow-immutable mapping of event-specific fields.
    """
    type: SessionEventType
    data: Mapping[str, Any] = field(default_factory=_empty_mapping)  # type: ignore[misc]

    def __post_init__(self) -> None:
        if not isinstance(self.data, MappingProxyType):
            object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


class SessionEventFactory:
    """Static-only factory for common SessionEvent types.

    Not instantiable — use static methods directly.
    Keeps runtimes cleaner and makes eventual migration to typed
    events (M12) almost mechanical.
    """

    def __new__(cls) -> "SessionEventFactory":
        raise TypeError("SessionEventFactory is a static namespace, not instantiable")

    @staticmethod
    def token(text: str, **extra: Any) -> SessionEvent:
        return SessionEvent(SessionEventType.TOKEN, {"text": text, **extra})

    @staticmethod
    def message_end() -> SessionEvent:
        return SessionEvent(SessionEventType.MESSAGE_END, {})

    @staticmethod
    def assistant_message(text: str, **extra: Any) -> SessionEvent:
        return SessionEvent(SessionEventType.ASSISTANT_MESSAGE, {"text": text, **extra})

    @staticmethod
    def error(text: str) -> SessionEvent:
        return SessionEvent(SessionEventType.ERROR, {"text": text})

    @staticmethod
    def info(text: str) -> SessionEvent:
        return SessionEvent(SessionEventType.INFO, {"text": text})

    @staticmethod
    def pong() -> SessionEvent:
        return SessionEvent(SessionEventType.PONG, {})

    @staticmethod
    def flow_start(node_count: int, edge_count: int) -> SessionEvent:
        return SessionEvent(
            SessionEventType.FLOW_START,
            {"node_count": node_count, "edge_count": edge_count},
        )

    @staticmethod
    def node_start(node_id: str, **extra: Any) -> SessionEvent:
        return SessionEvent(SessionEventType.NODE_START, {"node_id": node_id, **extra})

    @staticmethod
    def node_result(node_id: str, **extra: Any) -> SessionEvent:
        return SessionEvent(SessionEventType.NODE_RESULT, {"node_id": node_id, **extra})

    @staticmethod
    def edge_traversed(source: str, target: str, **extra: Any) -> SessionEvent:
        return SessionEvent(
            SessionEventType.EDGE_TRAVERSED,
            {"source": source, "target": target, **extra},
        )

    @staticmethod
    def flow_end(total_nodes: int) -> SessionEvent:
        return SessionEvent(SessionEventType.FLOW_END, {"total_nodes": total_nodes})

    @staticmethod
    def agent_info(name: str, model: str, provider: str) -> SessionEvent:
        return SessionEvent(
            SessionEventType.AGENT_INFO,
            {"name": name, "model": model, "provider": provider},
        )

    @staticmethod
    def runtime_identity(identity: Mapping[str, Any]) -> SessionEvent:
        return SessionEvent(SessionEventType.RUNTIME_IDENTITY, dict(identity))

    @staticmethod
    def initial_message(text: str) -> SessionEvent:
        return SessionEvent(SessionEventType.INITIAL_MESSAGE, {"text": text})

    @staticmethod
    def context(context: Any, thread_id: str | None = None) -> SessionEvent:
        data: dict[str, Any] = {"context": context}
        if thread_id is not None:
            data["thread_id"] = thread_id
        return SessionEvent(SessionEventType.CONTEXT, data)

    @staticmethod
    def context_updated(context: Any) -> SessionEvent:
        return SessionEvent(SessionEventType.CONTEXT_UPDATED, {"context": context})

    @staticmethod
    def reset_ack() -> SessionEvent:
        return SessionEvent(SessionEventType.RESET_ACK, {})

    @staticmethod
    def metrics(data: Mapping[str, Any]) -> SessionEvent:
        return SessionEvent(SessionEventType.METRICS, dict(data))

    @staticmethod
    def condition_branch(node_id: str, condition_met: bool) -> SessionEvent:
        return SessionEvent(
            SessionEventType.CONDITION_BRANCH,
            {"node_id": node_id, "condition_met": condition_met},
        )

    @staticmethod
    def variables_extracted(node_id: str, variables: Any) -> SessionEvent:
        return SessionEvent(
            SessionEventType.VARIABLES_EXTRACTED,
            {"node_id": node_id, "variables": variables},
        )

    @staticmethod
    def extraction_failed(node_id: str, variables: list[str], text: str) -> SessionEvent:
        return SessionEvent(
            SessionEventType.EXTRACTION_FAILED,
            {"node_id": node_id, "variables": variables, "text": text},
        )

    @staticmethod
    def slot_validation(
        node_id: str, slot: str, raw_value: str, normalized_value: str,
        status: str, error: str = "",
    ) -> SessionEvent:
        return SessionEvent(
            SessionEventType.SLOT_VALIDATION,
            {
                "node_id": node_id,
                "slot": slot,
                "raw_value": raw_value,
                "normalized_value": normalized_value,
                "status": status,
                "error": error,
            },
        )

    @staticmethod
    def slot_exhausted(node_id: str, slot: str, text: str = "") -> SessionEvent:
        return SessionEvent(
            SessionEventType.SLOT_EXHAUSTED,
            {"node_id": node_id, "slot": slot, "text": text},
        )

    @staticmethod
    def debug(text: str) -> SessionEvent:
        return SessionEvent(SessionEventType.DEBUG, {"text": text})
