"""PlaygroundRuntime — thin adapter wrapping PlaygroundConversation.

Translates ExecutionRuntime interface to PlaygroundConversation's methods.
Yields SessionEvent via async generators — no callbacks, no **kwargs.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from voice_platform.runtime.session.context import ExecutionContext
from voice_platform.runtime.session.events import SessionEvent, SessionEventFactory
from voice_platform.runtime.session.execution import ConversationInput, ExecutionRuntime


class PlaygroundRuntime(ExecutionRuntime):
    """Wraps PlaygroundConversation for playground chat WebSocket.

    PlaygroundConversation is stateless per-request (no long-running execution),
    so start() yields initial events and cancel() is a no-op.
    """

    def __init__(self, conv: Any) -> None:
        self._conv = conv

    async def start(self, context: ExecutionContext) -> AsyncGenerator[SessionEvent, None]:
        if getattr(self._conv, "initial_message", None):
            yield SessionEventFactory.initial_message(self._conv.initial_message)
        yield SessionEventFactory.agent_info(
            name=getattr(self._conv, "agent_id", ""),
            model=getattr(self._conv, "model", ""),
            provider="",
        )

    async def send_message(self, message: ConversationInput) -> AsyncGenerator[SessionEvent, None]:
        async for token in self._conv.stream_message(message.text):
            if isinstance(token, dict) and "_metrics" in token:
                yield SessionEventFactory.metrics(token["_metrics"])
            else:
                yield SessionEventFactory.token(token)
        yield SessionEventFactory.message_end()

    async def cancel(self) -> None:
        pass

    async def end(self) -> None:
        if hasattr(self._conv, "aclose"):
            await self._conv.aclose()
