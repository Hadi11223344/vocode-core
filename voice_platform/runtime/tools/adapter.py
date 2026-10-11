"""ToolAdapter — stateless bridge between tool runtime and plugin execution.

Like a serializer — no execution state, no caching, no logging, no events.
Just translation: ToolExecutionRequest → PluginExecutionRequest → Plugin.execute() → ToolExecutionResult.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

from voice_platform.integrations.plugins.base import (
    PluginContext,
    PluginExecutionRequest,
    PluginResult,
)
from voice_platform.integrations.plugins.registry import PluginRegistry
from voice_platform.runtime.tools.types import (
    ResolvedIntegration,
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionResult,
)


class ToolAdapter:
    """Stateless bridge: translates between tool runtime and plugin execution model."""

    def __init__(self, plugin_registry: PluginRegistry) -> None:
        self._plugin_registry = plugin_registry

    async def execute(
        self,
        request: ToolExecutionRequest,
        tool: ToolDefinition,
        integration: ResolvedIntegration,
    ) -> ToolExecutionResult[Any]:
        """Build PluginExecutionRequest, call plugin, wrap result. Pure translation."""
        plugin = self._plugin_registry.get(tool.service_type)
        plugin_request = PluginExecutionRequest(
            action=tool.action,
            params=dict(request.arguments),
            integration=integration.configuration,
            context=PluginContext(
                variables=MappingProxyType({}),
                conversation_id=request.caller.conversation_id,
                execution_id=request.execution_id,
                user_id=request.caller.user_id,
            ),
        )
        result: PluginResult[Any] = await plugin.execute(plugin_request)
        return ToolExecutionResult(
            success=result.success,
            output=result.output,
            error=result.error,
            metadata=result.metadata,
        )
