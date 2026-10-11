"""Immutable value objects for the tool execution pipeline.

ToolExecutionRequest / ToolExecutionResult mirror PluginExecutionRequest /
PluginResult but carry trace context and caller identity. ToolDefinition
uses service_type (the PluginRegistry key) instead of a separate plugin_alias.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Generic, Mapping, TypeVar

from voice_platform.integrations.plugins.base import IntegrationConfiguration

T = TypeVar("T")


class ToolCallerType(Enum):
    """Identifies which subsystem is invoking a tool."""
    FLOW = "flow"
    PLAYGROUND = "playground"
    PLATFORM = "platform"


@dataclass(frozen=True)
class ToolCaller:
    """Who is invoking the tool."""
    caller_type: ToolCallerType
    conversation_id: str = ""
    user_id: int | None = None


@dataclass(frozen=True)
class TraceContext:
    """Bundles trace identifiers. Future additions (parent_span, request_id,
    correlation_id) don't touch ToolExecutionRequest."""
    trace_id: str = ""
    span_id: str | None = None


@dataclass(frozen=True)
class ToolExecutionRequest:
    """Immutable request for tool execution. tool_name is NOT included —
    definition.name from ToolDefinition is the single source of truth."""
    arguments: Mapping[str, Any]
    caller: ToolCaller
    execution_id: str
    trace: TraceContext = field(default_factory=TraceContext)
    integration_id: int | None = None
    integration_overrides: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    agent_timezone: str | None = None


@dataclass(frozen=True)
class ToolExecutionResult(Generic[T]):
    """Immutable result from tool execution."""
    success: bool
    output: T | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def success(
        cls,
        output: T | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ToolExecutionResult[T]":
        return cls(success=True, output=output, metadata=MappingProxyType(metadata or {}))

    @classmethod
    def failure(
        cls,
        error: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ToolExecutionResult[T]":
        return cls(success=False, error=error, metadata=MappingProxyType(metadata or {}))

    def to_dict(self) -> dict:
        """Backward-compatible dict serialization."""
        if not self.success:
            return {"success": False, "error": self.error or "Unknown error"}
        output = self.output
        if isinstance(output, dict):
            result = dict(output)
            result.setdefault("success", True)
            return result
        return {"success": True, "output": output}


@dataclass(frozen=True)
class ToolDefinition:
    """Static metadata for a tool. service_type IS the PluginRegistry key."""
    name: str
    description: str
    schema: Mapping[str, Any]
    service_type: str
    action: str
    required_context: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class AvailableTool:
    """Richer result from discovery — carries availability metadata."""
    definition: ToolDefinition
    integration_id: int | None = None
    enabled: bool = True
    reason: str | None = None


@dataclass(frozen=True)
class ResolvedIntegration:
    """Result of IntegrationResolver.resolve() — richer than IntegrationConfiguration."""
    configuration: IntegrationConfiguration
    integration_id: int
    display_name: str
    provider: str
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True)
class ValidationResult:
    """Structured validation result. Future: warnings, coerced_values, normalized_arguments."""
    valid: bool
    error: str | None = None


@dataclass(frozen=True)
class AuthorizationResult:
    """Structured authorization result. Future: billing_limit, quota_remaining, scope."""
    allowed: bool
    reason: str | None = None


@dataclass(frozen=True)
class ToolDiscoveryRequest:
    """Immutable request for tool discovery."""
    user_id: int
    tools_config: list[str]
    mcp_bindings: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    integration_overrides: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    agent_timezone: str | None = None
