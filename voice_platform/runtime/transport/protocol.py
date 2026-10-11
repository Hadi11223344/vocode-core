"""ConversationTransport protocol — abstract transport interface.

Transports handle only I/O: socket lifecycle, encoding, decoding,
heartbeat, disconnect, rate limiting. No runtime, executor, or
session imports.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from voice_platform.runtime.session.events import SessionEvent, TransportEvent


@runtime_checkable
class ConversationTransport(Protocol):
    """Abstract transport interface.

    Transports are dumb I/O adapters:
    - start(): accept connection, send hello
    - receive(): decode wire message → TransportEvent (or None for timeout/heartbeat)
    - send(): encode SessionEvent → wire format (JSON, audio, etc.)
    - close(): disconnect, release resources

    Transports never import runtime, executor, or session classes.
    """

    async def start(self) -> None:
        """Accept connection and initialize transport."""
        ...

    async def receive(self) -> TransportEvent | None:
        """Receive next wire event. Returns None on timeout/heartbeat."""
        ...

    async def send(self, event: SessionEvent) -> None:
        """Send a SessionEvent to the client (transport handles serialization)."""
        ...

    async def close(self) -> None:
        """Disconnect and release resources."""
        ...
