"""Plugin base types — IntegrationPlugin Protocol, PluginResult, PluginExecutionRequest.

Defines the unified interface for all integration plugins. Each plugin
declares its service type aliases via `kinds` and receives an immutable
PluginExecutionRequest. Plugins are stateless — no client caching across
calls, preventing cross-tenant credential leakage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Generic, Mapping, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


@dataclass(frozen=True)
class IntegrationConfiguration:
    """Immutable integration configuration passed to plugins.

    Attributes:
        service_type: The service type alias (e.g. "google_calendar", "hubspot").
        api_key: Decrypted API key, if applicable.
        api_secret: Decrypted API secret / webhook URL, if applicable.
        config: Integration-specific configuration mapping.
        user_id: User ID for OAuth resolution and per-user client creation.
        agent_timezone: Agent timezone for date/time normalization.
    """

    service_type: str
    api_key: str | None = None
    api_secret: str | None = None
    config: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    user_id: int | None = None
    agent_timezone: str | None = None
    # Future: credentials: ResolvedCredentials | None = None
    #         to align with CredentialProvider from M5.


@dataclass(frozen=True)
class PluginContext:
    """Immutable context passed to plugins — follows M4+ immutability pattern.

    Attributes:
        variables: Template-resolved flow variables (caller_name, transcript, etc.).
        conversation_id: Active conversation ID, if any.
        execution_id: Unique execution ID for this workflow run.
        user_id: User ID who owns this workflow.
    """

    variables: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    conversation_id: str = ""
    execution_id: str = ""
    user_id: int | None = None


@dataclass(frozen=True)
class PluginExecutionRequest:
    """Immutable request object passed to every plugin execute() call.

    Attributes:
        action: The action to perform (e.g. "create_event", "send_sms").
        params: Action parameters (template-resolved).
        integration: Integration configuration with credentials.
        context: Optional flow context with variables and metadata.
    """

    action: str
    params: Mapping[str, Any]
    integration: IntegrationConfiguration
    context: PluginContext | None = None


@dataclass(frozen=True)
class PluginResult(Generic[T]):
    """Typed, immutable result from a plugin execution.

    Attributes:
        success: Whether the action succeeded.
        output: The action output (typed by generic parameter T).
        error: Error message if success is False.
        metadata: Additional metadata (e.g. extracted values, response headers).
    """

    success: bool
    output: T | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def to_dict(self) -> dict:
        """Backward-compatible dict serialization for existing callers.

        Returns a dict with the same shape that callers expect today.
        """
        if not self.success:
            return {"success": False, "error": self.error or "Unknown error"}
        output = self.output
        if isinstance(output, dict):
            result = dict(output)
            result.setdefault("success", True)
            return result
        return {"success": True, "output": output}


@runtime_checkable
class IntegrationPlugin(Protocol):
    """Protocol for all integration plugins.

    Plugins are stateless — any request-specific state (credentials, parameters,
    execution context) flows exclusively through PluginExecutionRequest. No
    client caching across calls.
    """

    kinds: tuple[str, ...]

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[Any]:
        """Execute the requested action and return a typed result."""
        ...
