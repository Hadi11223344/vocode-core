"""Tool lifecycle events.

Registry events (emitted by ToolRegistry):
  ToolDiscovered

Runtime events (emitted by ToolRuntime):
  ToolValidated → ToolAuthorized → ToolStarted → ToolRetried(0..N) → ToolCompleted|Failed

ToolRuntime never emits ToolDiscovered — it doesn't discover.
Duration is measured internally by ToolRuntime via time.monotonic().
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolDiscovered:
    """Emitted by ToolRegistry when a tool is found during discovery."""
    tool_name: str
    caller: str
    user_id: int


@dataclass(frozen=True)
class ToolValidated:
    """Emitted by ToolRuntime after validation."""
    tool_name: str
    execution_id: str
    valid: bool


@dataclass(frozen=True)
class ToolAuthorized:
    """Emitted by ToolRuntime after authorization."""
    tool_name: str
    execution_id: str
    allowed: bool


@dataclass(frozen=True)
class ToolStarted:
    """Emitted by ToolRuntime before execution begins."""
    tool_name: str
    execution_id: str


@dataclass(frozen=True)
class ToolCompleted:
    """Emitted by ToolRuntime after successful or failed execution."""
    tool_name: str
    execution_id: str
    success: bool
    duration_ms: float


@dataclass(frozen=True)
class ToolRetried:
    """Emitted by ToolRuntime when retrying plugin execution."""
    tool_name: str
    execution_id: str
    attempt: int
    error: str
    delay: float


@dataclass(frozen=True)
class ToolFailed:
    """Emitted by ToolRuntime when execution fails permanently."""
    tool_name: str
    execution_id: str
    error: str
    duration_ms: float
