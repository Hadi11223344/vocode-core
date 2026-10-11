"""Tests for ToolAdapter — stateless bridge, request bridging, result wrapping."""

from types import MappingProxyType
from typing import Any

import pytest

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)
from voice_platform.runtime.tools.adapter import ToolAdapter
from voice_platform.runtime.tools.types import (
    ResolvedIntegration,
    ToolCaller,
    ToolCallerType,
    ToolDefinition,
    ToolExecutionRequest,
)


class FakePlugin:
    """Captures the request it receives and returns a configurable result."""

    def __init__(self, result: PluginResult):
        self._result = result
        self.received_request: PluginExecutionRequest | None = None
        self.kinds = ("test_service",)

    async def execute(self, request: PluginExecutionRequest) -> PluginResult:
        self.received_request = request
        return self._result


class FakePluginRegistry:
    def __init__(self, plugin):
        self._plugin = plugin

    def register(self, alias, plugin): pass
    def get(self, alias): return self._plugin
    def supports(self, alias): return True
    def aliases(self): return ["test_service"]
    def plugins(self): return [self._plugin]


class TestToolAdapterTranslation:
    """ToolAdapter translates ToolExecutionRequest → PluginExecutionRequest → ToolExecutionResult."""

    @pytest.mark.asyncio
    async def test_request_bridging(self):
        plugin = FakePlugin(PluginResult(success=True, output={"data": 123}))
        adapter = ToolAdapter(FakePluginRegistry(plugin))

        definition = ToolDefinition(
            name="test_tool",
            description="test",
            schema={},
            service_type="test_service",
            action="do_thing",
        )
        request = ToolExecutionRequest(
            arguments={"param1": "value1"},
            caller=ToolCaller(caller_type=ToolCallerType.FLOW, user_id=42, conversation_id="conv-1"),
            execution_id="exec-1",
        )
        integration = ResolvedIntegration(
            configuration=IntegrationConfiguration(
                service_type="test_service",
                api_key="key123",
            ),
            integration_id=1,
            display_name="Test",
            provider="test",
        )

        result = await adapter.execute(request, definition, integration)

        # Check result wrapping
        assert result.success is True
        assert result.output == {"data": 123}

        # Check request bridging
        assert plugin.received_request is not None
        assert plugin.received_request.action == "do_thing"
        assert plugin.received_request.params == {"param1": "value1"}
        assert plugin.received_request.integration.api_key == "key123"
        assert plugin.received_request.context.user_id == 42
        assert plugin.received_request.context.conversation_id == "conv-1"

    @pytest.mark.asyncio
    async def test_failure_result_wrapping(self):
        plugin = FakePlugin(PluginResult(success=False, error="API timeout"))
        adapter = ToolAdapter(FakePluginRegistry(plugin))

        definition = ToolDefinition(
            name="test", description="", schema={},
            service_type="test_service", action="fail",
        )
        request = ToolExecutionRequest(
            arguments={},
            caller=ToolCaller(caller_type=ToolCallerType.PLATFORM, user_id=1),
            execution_id="exec-2",
        )
        integration = ResolvedIntegration(
            configuration=IntegrationConfiguration(service_type="test_service"),
            integration_id=1,
            display_name="Test",
            provider="test",
        )

        result = await adapter.execute(request, definition, integration)
        assert result.success is False
        assert result.error == "API timeout"


class TestToolAdapterStateless:
    """ToolAdapter holds no execution state."""

    def test_no_caching_fields(self):
        plugin = FakePlugin(PluginResult(success=True))
        adapter = ToolAdapter(FakePluginRegistry(plugin))
        # Should only have the plugin_registry field
        attrs = {k for k in vars(adapter)}
        assert attrs == {"_plugin_registry"}
