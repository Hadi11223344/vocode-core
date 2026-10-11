"""EventBus protocol and no-op default implementation.

The EventBus is injected into ConversationSession for publishing lifecycle events.
NoOpEventBus is the default — it does nothing, satisfying dependency injection
without committing to an event architecture.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventBus(Protocol):
    """Protocol for publishing lifecycle events."""

    async def publish(self, event: Any) -> None:
        ...


class NoOpEventBus:
    """Default no-op event bus. publish() does nothing."""

    async def publish(self, event: Any) -> None:
        pass
