"""ExecutionRuntime ABC, RuntimeKind enum, and ConversationInput wrapper.

ExecutionRuntime is the abstraction that ConversationSession depends on.
Concrete runtime adapters (PlaygroundRuntime, FlowRuntime, TelephonyRuntime)
implement this interface by delegating to existing execution engines.

start() and send_message() are async generators yielding SessionEvent.
No callbacks — runtime yields events, session forwards them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from voice_platform.runtime.session.context import ExecutionContext
from voice_platform.runtime.session.events import SessionEvent


class RuntimeKind(Enum):
    """Identifies which runtime adapter to construct."""
    PLAYGROUND_CHAT = "playground_chat"
    PLAYGROUND_FLOW = "playground_flow"
    TELEPHONY = "telephony"


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True)
class ConversationInput:
    """Typed wrapper for a message sent into a conversation.

    Attributes:
        text: The user's message text.
        metadata: Read-only extra fields (e.g. context overrides, source info).
    """
    text: str
    metadata: Mapping[str, Any] = field(default_factory=_empty_mapping)


class ExecutionRuntime(ABC):
    """Abstract interface for conversation execution backends.

    ConversationSession depends only on this interface, never on concrete
    implementations.  Each adapter translates these methods into calls on
    its wrapped execution engine.

    start() and send_message() are async generators yielding SessionEvent.
    No callbacks, no **kwargs — runtime yields events, session forwards them.
    """

    @abstractmethod
    def start(self, context: ExecutionContext) -> AsyncGenerator[SessionEvent, None]:
        """Start the runtime, yielding SessionEvent for each event."""
        ...

    @abstractmethod
    def send_message(self, message: ConversationInput) -> AsyncGenerator[SessionEvent, None]:
        """Send a user message, yielding SessionEvent for each event."""
        ...

    @abstractmethod
    async def cancel(self) -> None:
        """Cancel the current active execution (not the entire conversation)."""
        ...

    @abstractmethod
    async def end(self) -> None:
        """Dispose all resources held by this runtime."""
        ...
