"""Lifecycle state, termination reason, and lifecycle event dataclasses.

SessionState tracks where the session is in its lifecycle.
TerminationReason explains *why* a session ended.

Lifecycle events are published to EventBus by ConversationSession._transition().
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class SessionState(Enum):
    """Lifecycle states for a ConversationSession."""
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    CANCELLING = "cancelling"
    ENDED = "ended"


class TerminationReason(Enum):
    """Why a session transitioned to ENDED."""
    NORMAL = "normal"
    ERROR = "error"
    CLIENT_DISCONNECT = "client_disconnect"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


# ── Lifecycle Events ──────────────────────────────────────────────────

@dataclass(frozen=True)
class ConversationStarted:
    """Published when session transitions to RUNNING."""
    conversation_id: str


@dataclass(frozen=True)
class ConversationCancelled:
    """Published when session transitions to CANCELLING."""
    conversation_id: str


@dataclass(frozen=True)
class ConversationEnded:
    """Published when session transitions to ENDED."""
    conversation_id: str
    reason: TerminationReason


@dataclass(frozen=True)
class ConversationFailed:
    """Published when session ends due to an error."""
    conversation_id: str
    error: str
