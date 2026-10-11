"""TelephonyRuntime — thin adapter wrapping FlowAgent.

Translates ExecutionRuntime interface to FlowAgent's methods.
Telephony uses an audio pipeline, not text, so send_message() raises.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from voice_platform.runtime.session.context import ExecutionContext
from voice_platform.runtime.session.events import SessionEvent
from voice_platform.runtime.session.execution import ConversationInput, ExecutionRuntime


class TelephonyRuntime(ExecutionRuntime):
    """Wraps FlowAgent for telephony inbound calls.

    Telephony conversations use the vocode audio pipeline (STT/TTS).
    The vocode TelephonyServer calls agent.start() and agent.terminate()
    directly, so start() and end() are no-ops here — the ConversationSession
    only tracks lifecycle state.  cancel() delegates to agent.terminate()
    for explicit mid-call cancellation.
    """

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def start(self, context: ExecutionContext) -> AsyncGenerator[SessionEvent, None]:
        return
        yield  # type: ignore[misc]  # make this an async generator

    async def send_message(self, message: ConversationInput) -> AsyncGenerator[SessionEvent, None]:
        raise NotImplementedError(
            "TelephonyRuntime uses an audio pipeline, not text send_message"
        )
        yield  # type: ignore[misc]  # pragma: no cover

    async def cancel(self) -> None:
        await self._agent.terminate()

    async def end(self) -> None:
        pass
