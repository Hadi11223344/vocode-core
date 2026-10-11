"""ConversationContext — immutable identity of a conversation.

Carries who, which agent, which channel, and caller identity.
Separated from runtime configuration and infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class ConversationChannel(Enum):
    """Channel through which the conversation arrives."""
    TELEPHONY = "telephony"
    PLAYGROUND_CHAT = "playground_chat"
    PLAYGROUND_FLOW = "playground_flow"


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True)
class ConversationContext:
    """Immutable conversation identity.

    Attributes:
        conversation_id: Unique identifier (UUID4).
        user_id: Optional platform user ID.
        agent_id: Optional agent ID.
        caller_phone: Optional caller phone number (telephony only).
        caller_name: Optional caller display name.
        channel: Channel enum (telephony, playground_chat, playground_flow).
        metadata: Read-only mapping of extra context fields.
    """

    conversation_id: str
    user_id: int | None = None
    agent_id: int | None = None
    caller_phone: str | None = None
    caller_name: str | None = None
    channel: ConversationChannel = ConversationChannel.TELEPHONY
    metadata: Mapping[str, Any] = field(default_factory=_empty_mapping, hash=False)
