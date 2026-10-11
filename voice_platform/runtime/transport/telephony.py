"""TelephonyTransport — stub adapter delegating to existing vocode pipeline.

This is a protocol-conforming stub for M9. Real telephony decoupling
is deferred to M9.5, where FlowAgent becomes a runtime adapter and
TelephonyTransport becomes a real implementation.
"""

from __future__ import annotations

from voice_platform.runtime.session.events import SessionEvent, TransportEvent, TransportEventType


class TelephonyTransport:
    """Stub telephony transport — protocol-conforming but non-functional.

    M9.5 will replace this with a real implementation that bridges
    the vocode audio pipeline (STT/TTS) to ConversationSession.
    """

    def __init__(self) -> None:
        self._closed = False

    async def start(self) -> None:
        """No-op — vocode pipeline manages connection lifecycle."""
        pass

    async def receive(self) -> TransportEvent | None:
        """No-op — vocode pipeline handles audio input directly."""
        return None

    async def send(self, event: SessionEvent) -> None:
        """No-op — vocode pipeline handles audio output directly."""
        pass

    async def close(self) -> None:
        """No-op — vocode pipeline manages disconnection."""
        self._closed = True
