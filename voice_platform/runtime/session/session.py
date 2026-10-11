"""ConversationSession — pure façade lifecycle coordinator.

Owns lifecycle state, and delegates execution to an ExecutionRuntime abstraction.
Contains no business logic beyond lifecycle coordination. Never imports provider
SDKs, LangGraph, or concrete runtime implementations.

ExecutionContext is treated as immutable input — ConversationSession never
mutates it. conversation_id is read from context.conversation.conversation_id.

Session exposes semantic methods (start, receive_message, cancel, end).
No handle(TransportEvent) — route owns protocol mapping.
SessionEvent is never serialized — transports handle wire format.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

from voice_platform.integrations.plugins.registry import EmptyPluginRegistry, PluginRegistry
from voice_platform.runtime.events.event_bus import EventBus, NoOpEventBus
from voice_platform.runtime.session.context import ExecutionContext
from voice_platform.runtime.session.events import SessionEvent
from voice_platform.runtime.session.execution import ConversationInput, ExecutionRuntime
from voice_platform.runtime.session.lifecycle import (
    ConversationCancelled,
    ConversationEnded,
    ConversationFailed,
    ConversationStarted,
    SessionState,
    TerminationReason,
)
from voice_platform.runtime.tracing.tracer import NoOpTracer, Tracer


class ConversationSession:
    """Lifecycle coordinator for a single conversation.

    Depends only on abstractions (ExecutionRuntime, EventBus, Tracer,
    PluginRegistry). Never imports concrete runtime implementations,
    provider SDKs, or LangGraph. Never imports TransportEvent or
    ConversationTransport — session is transport-agnostic.

    ExecutionContext is immutable input. ConversationSession reads
    conversation_id from context.conversation.conversation_id.

    Semantic API: start(), receive_message(text), cancel(), end().
    No handle(TransportEvent) — route owns protocol mapping.

    Lifecycle:
        CREATED → STARTING → RUNNING → ENDED
                              ↓
                        CANCELLING → RUNNING (or ENDED)
    """

    def __init__(
        self,
        runtime: ExecutionRuntime,
        context: ExecutionContext,
        event_bus: EventBus | None = None,
        tracer: Tracer | None = None,
        plugin_registry: PluginRegistry | None = None,
    ) -> None:
        self._runtime = runtime
        self._context = context
        # Pull infra from context if available, fall back to explicit args, then no-ops
        infra = context.infrastructure
        self._event_bus: EventBus = event_bus or (infra.event_bus if infra else None) or NoOpEventBus()
        self._tracer: Tracer = tracer or (infra.tracer if infra else None) or NoOpTracer()
        self._plugin_registry: PluginRegistry = plugin_registry or (infra.plugin_registry if infra else None) or EmptyPluginRegistry()
        self._state: SessionState = SessionState.CREATED
        self._termination_reason: TerminationReason | None = None

    # ── Properties ────────────────────────────────────────────────────

    @property
    def conversation_id(self) -> str:
        return self._context.conversation.conversation_id

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def termination_reason(self) -> TerminationReason | None:
        return self._termination_reason

    @property
    def context(self) -> ExecutionContext:
        return self._context

    # ── Lifecycle Methods ─────────────────────────────────────────────

    async def start(self) -> AsyncGenerator[SessionEvent, None]:
        """Start the conversation, yielding SessionEvent from the runtime.

        Idempotent — if already RUNNING or ENDED, yields nothing.
        """
        if self._state in (SessionState.RUNNING, SessionState.ENDED):
            return
        await self._transition(SessionState.STARTING)
        try:
            async for event in self._runtime.start(self._context):
                yield event
        except Exception as exc:
            await self._transition(
                SessionState.ENDED, reason=TerminationReason.ERROR, error=str(exc)
            )
            raise
        await self._transition(SessionState.RUNNING)

    async def receive_message(self, text: str) -> AsyncGenerator[SessionEvent, None]:
        """Send a user message through the runtime, yielding SessionEvent."""
        if self._state == SessionState.ENDED:
            raise RuntimeError("Cannot send message to an ended session")
        message = ConversationInput(text=text)
        try:
            async for event in self._runtime.send_message(message):
                yield event
        except Exception as exc:
            await self._transition(
                SessionState.ENDED, reason=TerminationReason.ERROR, error=str(exc)
            )
            raise

    async def cancel(self) -> None:
        """Cancel the current active execution (not the entire conversation)."""
        if self._state != SessionState.RUNNING:
            return
        await self._transition(SessionState.CANCELLING)
        try:
            await self._runtime.cancel()
        except Exception as exc:
            await self._transition(
                SessionState.ENDED, reason=TerminationReason.ERROR, error=str(exc)
            )
            raise
        await self._transition(SessionState.RUNNING)

    async def end(self) -> None:
        """Dispose the entire conversation.  Idempotent."""
        if self._state == SessionState.ENDED:
            return
        reason = self._termination_reason or TerminationReason.NORMAL
        try:
            await self._runtime.end()
        except Exception as exc:
            reason = TerminationReason.ERROR
            await self._transition(SessionState.ENDED, reason=reason, error=str(exc))
            raise
        await self._transition(SessionState.ENDED, reason=reason)

    async def close(self) -> None:
        """Alias for end() — for framework compatibility."""
        await self.end()

    # ── Internal ──────────────────────────────────────────────────────

    async def _transition(
        self,
        new_state: SessionState,
        reason: TerminationReason | None = None,
        error: str | None = None,
    ) -> None:
        """Centralized state transition: update state, emit tracer, publish event."""
        self._state = new_state
        if reason is not None:
            self._termination_reason = reason

        await self._tracer.emit(
            "session_state",
            state=new_state.value,
            reason=reason.value if reason else None,
            conversation_id=self.conversation_id,
        )

        if new_state == SessionState.RUNNING:
            await self._event_bus.publish(
                ConversationStarted(conversation_id=self.conversation_id)
            )
        elif new_state == SessionState.CANCELLING:
            await self._event_bus.publish(
                ConversationCancelled(conversation_id=self.conversation_id)
            )
        elif new_state == SessionState.ENDED:
            if reason == TerminationReason.ERROR and error:
                await self._event_bus.publish(
                    ConversationFailed(
                        conversation_id=self.conversation_id, error=error
                    )
                )
            await self._event_bus.publish(
                ConversationEnded(
                    conversation_id=self.conversation_id,
                    reason=reason or TerminationReason.NORMAL,
                )
            )


def create_conversation_id() -> str:
    """Generate a conversation ID.

    Uses UUID4.  When Python stdlib supports UUIDv7 (sortable, trace-friendly),
    prefer that instead.
    """
    return str(uuid.uuid4())
