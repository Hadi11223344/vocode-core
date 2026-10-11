"""Tests for the plugin registry and base types."""

import pytest

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginContext,
    PluginExecutionRequest,
    PluginResult,
)
from voice_platform.integrations.plugins.registry import (
    DefaultPluginRegistry,
    UnknownPluginError,
    build_default_plugin_registry,
)


class TestPluginResult:
    def test_success_dict_output(self):
        r = PluginResult(success=True, output={"key": "value"})
        d = r.to_dict()
        assert d["success"] is True
        assert d["key"] == "value"

    def test_success_non_dict_output(self):
        r = PluginResult(success=True, output="hello")
        d = r.to_dict()
        assert d["success"] is True
        assert d["output"] == "hello"

    def test_failure(self):
        r = PluginResult(success=False, error="something went wrong")
        d = r.to_dict()
        assert d["success"] is False
        assert d["error"] == "something went wrong"

    def test_immutable(self):
        r = PluginResult(success=True, output={"key": "value"})
        with pytest.raises(Exception):
            r.success = False  # type: ignore[misc]


class TestIntegrationConfiguration:
    def test_immutable(self):
        c = IntegrationConfiguration(service_type="google_calendar", api_key="secret")
        with pytest.raises(Exception):
            c.api_key = "other"  # type: ignore[misc]

    def test_defaults(self):
        c = IntegrationConfiguration(service_type="sms")
        assert c.api_key is None
        assert c.api_secret is None
        assert c.user_id is None
        assert c.agent_timezone is None


class TestDefaultPluginRegistry:
    def test_register_and_get(self):
        class FakePlugin:
            kinds = ("test_service",)

            async def execute(self, request):
                return PluginResult(success=True, output={"ok": True})

        reg = DefaultPluginRegistry()
        plugin = FakePlugin()
        reg.register("test_service", plugin)
        assert reg.get("test_service") is plugin

    def test_get_missing_raises_unknown_plugin_error(self):
        reg = DefaultPluginRegistry()
        with pytest.raises(UnknownPluginError):
            reg.get("nonexistent")

    def test_supports(self):
        class FakePlugin:
            kinds = ("test_service",)

            async def execute(self, request):
                return PluginResult(success=True)

        reg = DefaultPluginRegistry()
        reg.register("test_service", FakePlugin())
        assert reg.supports("test_service") is True
        assert reg.supports("nonexistent") is False

    def test_aliases(self):
        class FakePlugin:
            kinds = ("a", "b")

            async def execute(self, request):
                return PluginResult(success=True)

        reg = DefaultPluginRegistry()
        plugin = FakePlugin()
        reg.register("a", plugin)
        reg.register("b", plugin)
        aliases = reg.aliases()
        assert "a" in aliases
        assert "b" in aliases

    def test_plugins_dedup(self):
        class FakePlugin:
            kinds = ("a", "b")

            async def execute(self, request):
                return PluginResult(success=True)

        reg = DefaultPluginRegistry()
        plugin = FakePlugin()
        reg.register("a", plugin)
        reg.register("b", plugin)
        plugins = reg.plugins()
        assert len(plugins) == 1


class TestBuildDefaultPluginRegistry:
    def test_registry_has_all_standard_plugins(self):
        reg = build_default_plugin_registry()

        expected_aliases = [
            "google_calendar",
            "google_sheets",
            "google_drive",
            "google_drive_mcp",
            "sms",
            "email",
            "knowledge_base",
            "cal_com",
            "calendly",
            "salesforce",
            "pipedrive",
            "gohighlevel",
            "hubspot",
            "stripe",
            "shopify",
            "zendesk",
            "freshdesk",
            "intercom",
            "notion",
            "airtable",
            "jira",
            "linear",
            "webhook",
            "zapier",
            "slack",
            "make",
            "discord",
            "microsoft_teams",
            "whatsapp_cloud",
            "telegram_bot",
            "transfer_call",
            "mcp_tool",
        ]

        for alias in expected_aliases:
            assert reg.supports(alias), f"Missing plugin for alias: {alias}"

    def test_registry_returns_same_plugin_for_aliases(self):
        reg = build_default_plugin_registry()
        # CRMPlugin handles hubspot, salesforce, pipedrive, gohighlevel
        hubspot = reg.get("hubspot")
        salesforce = reg.get("salesforce")
        assert hubspot is salesforce

    def test_unknown_alias_not_supported(self):
        reg = build_default_plugin_registry()
        assert not reg.supports("nonexistent_service")
