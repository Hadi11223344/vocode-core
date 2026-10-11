"""Tests for ToolRegistry — registration, lookup, schemas, discover()."""

import pytest
from types import MappingProxyType

from voice_platform.runtime.tools.types import (
    AvailableTool,
    ToolDefinition,
    ToolDiscoveryRequest,
)


class TestToolRegistryRegistration:
    """ToolRegistry register/get/supports/list/schemas."""

    def _make_tool(self, name="test_tool", service_type="test_service"):
        return ToolDefinition(
            name=name,
            description="A test tool",
            schema={"type": "object", "properties": {}},
            service_type=service_type,
            action="test_action",
        )

    def test_register_and_get(self):
        from voice_platform.runtime.tools.registry import ToolRegistry

        registry = ToolRegistry()
        tool = self._make_tool()
        registry.register(tool)
        assert registry.get("test_tool") is tool

    def test_get_unknown_raises(self):
        from voice_platform.runtime.tools.registry import ToolRegistry

        registry = ToolRegistry()
        with pytest.raises(KeyError):
            registry.get("nonexistent")

    def test_supports(self):
        from voice_platform.runtime.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(self._make_tool())
        assert registry.supports("test_tool") is True
        assert registry.supports("nonexistent") is False

    def test_list(self):
        from voice_platform.runtime.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(self._make_tool("tool_a"))
        registry.register(self._make_tool("tool_b"))
        names = {t.name for t in registry.list()}
        assert names == {"tool_a", "tool_b"}

    def test_schemas(self):
        from voice_platform.runtime.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(self._make_tool())
        schemas = registry.schemas()
        assert "test_tool" in schemas
        assert schemas["test_tool"]["type"] == "object"


class TestBuildDefaultToolRegistry:
    """build_default_tool_registry() populates from PLATFORM_TOOLS."""

    def test_returns_registry_with_tools(self):
        from voice_platform.runtime.tools.registry import build_default_tool_registry

        registry = build_default_tool_registry()
        tools = registry.list()
        assert len(tools) > 0

    def test_contains_check_calendar(self):
        from voice_platform.runtime.tools.registry import build_default_tool_registry

        registry = build_default_tool_registry()
        assert registry.supports("check_calendar")

    def test_definitions_use_service_type(self):
        from voice_platform.runtime.tools.registry import build_default_tool_registry

        registry = build_default_tool_registry()
        tool = registry.get("check_calendar")
        assert hasattr(tool, "service_type")
        assert tool.service_type == "google_calendar"
        assert not hasattr(tool, "integration_type")
