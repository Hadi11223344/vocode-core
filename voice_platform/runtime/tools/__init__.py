"""Tool runtime package — ToolRuntime, ToolRegistry, and supporting types.

ToolRuntime is a pure execution layer: execute(definition, request).
ToolRegistry owns discovery: discover(ToolDiscoveryRequest) → list[AvailableTool].
ToolRuntime does NOT depend on ToolRegistry.
"""

from voice_platform.runtime.tools.adapter import ToolAdapter
from voice_platform.runtime.tools.authorizer import ToolAuthorizer
from voice_platform.runtime.tools.events import (
    ToolAuthorized,
    ToolCompleted,
    ToolDiscovered,
    ToolFailed,
    ToolRetried,
    ToolStarted,
    ToolValidated,
)
from voice_platform.runtime.tools.registry import ToolRegistry, build_default_tool_registry
from voice_platform.runtime.tools.resolver import IntegrationResolver
from voice_platform.runtime.tools.retry import NoRetryPolicy, RetryPolicy
from voice_platform.runtime.tools.runtime import ToolRuntime
from voice_platform.runtime.tools.types import (
    AvailableTool,
    AuthorizationResult,
    ResolvedIntegration,
    ToolCaller,
    ToolCallerType,
    ToolDefinition,
    ToolDiscoveryRequest,
    ToolExecutionRequest,
    ToolExecutionResult,
    TraceContext,
    ValidationResult,
)
from voice_platform.runtime.tools.validator import ToolValidator

__all__ = [
    "AvailableTool",
    "AuthorizationResult",
    "IntegrationResolver",
    "NoRetryPolicy",
    "ResolvedIntegration",
    "RetryPolicy",
    "ToolAdapter",
    "ToolAuthorizer",
    "ToolCaller",
    "ToolCallerType",
    "ToolCompleted",
    "ToolDefinition",
    "ToolDiscovered",
    "ToolDiscoveryRequest",
    "ToolExecutionRequest",
    "ToolExecutionResult",
    "ToolFailed",
    "ToolRegistry",
    "ToolRetried",
    "ToolRuntime",
    "ToolStarted",
    "ToolValidated",
    "ToolAuthorized",
    "ToolValidator",
    "TraceContext",
    "ValidationResult",
    "build_default_tool_registry",
]
