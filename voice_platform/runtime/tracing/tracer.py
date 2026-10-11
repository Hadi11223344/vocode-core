"""Tracer protocol, no-op default, and adapter for flow.tracer.Tracer.

The Tracer is injected into ConversationSession for lifecycle event tracing.
NoOpTracer is the default — emit() does nothing.
FlowTracerAdapter wraps the existing flow.tracer.Tracer to satisfy this protocol.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Tracer(Protocol):
    """Protocol for emitting trace events."""

    async def emit(self, event_type: str, **fields: Any) -> None:
        ...


class NoOpTracer:
    """Default no-op tracer. emit() does nothing."""

    async def emit(self, event_type: str, **fields: Any) -> None:
        pass


class FlowTracerAdapter:
    """Adapts existing flow.tracer.Tracer to the session-level Tracer protocol."""

    def __init__(self, flow_tracer: Any) -> None:
        self._flow_tracer = flow_tracer

    async def emit(self, event_type: str, **fields: Any) -> None:
        await self._flow_tracer.emit(event_type, **fields)
