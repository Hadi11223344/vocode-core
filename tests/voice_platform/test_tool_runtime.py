"""Tests for ToolRuntime — execute lifecycle, events, retry, no registry dependency."""

import asyncio
from types import MappingProxyType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)
from voice_platform.integrations.plugins.registry import PluginRegistry
from voice_platform.runtime.tools.adapter import ToolAdapter
from voice_platform.runtime.tools.authorizer import ToolAuthorizer
from voice_platform.runtime.tools.events import (
    ToolAuthorized,
    ToolCompleted,
    ToolFailed,
    ToolRetried,
    ToolStarted,
    ToolValidated,
)
from voice_platform.runtime.tools.resolver import IntegrationResolver
from voice_platform.runtime.tools.retry import NoRetryPolicy
from voice_platform.runtime.tools.runtime import ToolRuntime
from voice_platform.runtime.tools.types import (
    AuthorizationResult,
    ResolvedIntegration,
    ToolCaller,
    ToolCallerType,
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionResult,
    ValidationResult,
)


class FakePluginRegistry:
    """Minimal PluginRegistry for testing."""

    def __init__(self, plugin):
        self._plugin = plugin

    def register(self, alias, plugin):
        pass

    def get(self, alias):
        return self._plugin

    def supports(self, alias):
        return True

    def aliases(self):
        return ["test_service"]

    def plugins(self):
        return [self._plugin]


class FakePlugin:
    """Fake plugin that returns a configurable result."""

    def __init__(self, result: PluginResult):
        self._result = result
        self.kinds = ("test_service",)

    async def execute(self, request: PluginExecutionRequest) -> PluginResult:
        return self._result


class FakeResolver:
    """Fake IntegrationResolver that returns a pre-built ResolvedIntegration."""

    def __init__(self, resolved: ResolvedIntegration | None):
        self._resolved = resolved

    async def resolve(self, integration_id, service_type, overrides=MappingProxyType({}), agent_timezone=None):
        return self._resolved


class FakeValidator:
    """Fake validator with configurable result."""

    def __init__(self, result: ValidationResult):
        self._result = result

    async def validate(self, request, tool):
        return self._result


class FakeAuthorizer:
    """Fake authorizer with configurable result."""

    def __init__(self, result: AuthorizationResult):
        self._result = result

    async def authorize(self, request, tool):
        return self._result


class CollectingEventBus:
    """EventBus that collects all published events."""

    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _make_definition():
    return ToolDefinition(
        name="test_tool",
        description="Test tool",
        schema={"type": "object"},
        service_type="test_service",
        action="test_action",
    )


def _make_request():
    return ToolExecutionRequest(
        arguments={"key": "value"},
        caller=ToolCaller(caller_type=ToolCallerType.FLOW, user_id=1),
        execution_id="exec-123",
    )


def _make_resolved_integration():
    return ResolvedIntegration(
        configuration=IntegrationConfiguration(
            service_type="test_service",
            api_key="key123",
        ),
        integration_id=1,
        display_name="Test Integration",
        provider="test",
    )


class TestToolRuntimeExecute:
    """ToolRuntime.execute() full lifecycle."""

    @pytest.mark.asyncio
    async def test_successful_execution(self):
        plugin = FakePlugin(PluginResult(success=True, output={"result": "ok"}))
        adapter = ToolAdapter(FakePluginRegistry(plugin))
        resolver = FakeResolver(_make_resolved_integration())
        bus = CollectingEventBus()
        runtime = ToolRuntime(adapter=adapter, resolver=resolver, event_bus=bus)

        result = await runtime.execute(_make_definition(), _make_request())

        assert result.success is True
        assert result.output == {"result": "ok"}

        # Check event ordering: Validated → Authorized → Started → Completed
        event_types = [type(e).__name__ for e in bus.events]
        assert event_types == ["ToolValidated", "ToolAuthorized", "ToolStarted", "ToolCompleted"]
        assert bus.events[0].valid is True
        assert bus.events[1].allowed is True
        assert bus.events[3].success is True
        assert bus.events[3].duration_ms >= 0.0

        # Invariant: successful execution emits ToolCompleted, NOT ToolFailed
        assert not any(isinstance(e, ToolFailed) for e in bus.events)

    @pytest.mark.asyncio
    async def test_validation_failure_no_started(self):
        plugin = FakePlugin(PluginResult(success=True))
        adapter = ToolAdapter(FakePluginRegistry(plugin))
        resolver = FakeResolver(_make_resolved_integration())
        bus = CollectingEventBus()
        runtime = ToolRuntime(
            adapter=adapter,
            resolver=resolver,
            validator=FakeValidator(ValidationResult(valid=False, error="Bad params")),
            event_bus=bus,
        )

        result = await runtime.execute(_make_definition(), _make_request())

        assert result.success is False
        assert result.error == "Bad params"

        # Should NOT emit ToolStarted
        event_types = [type(e).__name__ for e in bus.events]
        assert "ToolStarted" not in event_types
        assert "ToolCompleted" not in event_types
        assert event_types == ["ToolValidated"]

    @pytest.mark.asyncio
    async def test_authorization_failure_no_started(self):
        plugin = FakePlugin(PluginResult(success=True))
        adapter = ToolAdapter(FakePluginRegistry(plugin))
        resolver = FakeResolver(_make_resolved_integration())
        bus = CollectingEventBus()
        runtime = ToolRuntime(
            adapter=adapter,
            resolver=resolver,
            authorizer=FakeAuthorizer(AuthorizationResult(allowed=False, reason="Denied")),
            event_bus=bus,
        )

        result = await runtime.execute(_make_definition(), _make_request())

        assert result.success is False
        assert result.error == "Denied"

        event_types = [type(e).__name__ for e in bus.events]
        assert "ToolStarted" not in event_types
        assert event_types == ["ToolValidated", "ToolAuthorized"]

    @pytest.mark.asyncio
    async def test_integration_not_found(self):
        plugin = FakePlugin(PluginResult(success=True))
        adapter = ToolAdapter(FakePluginRegistry(plugin))
        resolver = FakeResolver(None)  # No integration found
        bus = CollectingEventBus()
        runtime = ToolRuntime(adapter=adapter, resolver=resolver, event_bus=bus)

        result = await runtime.execute(_make_definition(), _make_request())

        assert result.success is False
        assert "No integration found" in result.error

        event_types = [type(e).__name__ for e in bus.events]
        assert "ToolFailed" in event_types

    @pytest.mark.asyncio
    async def test_plugin_failure_emits_tool_failed(self):
        plugin = FakePlugin(PluginResult(success=False, error="API error"))
        adapter = ToolAdapter(FakePluginRegistry(plugin))
        resolver = FakeResolver(_make_resolved_integration())
        bus = CollectingEventBus()
        runtime = ToolRuntime(adapter=adapter, resolver=resolver, event_bus=bus)

        result = await runtime.execute(_make_definition(), _make_request())

        assert result.success is False
        assert result.error == "API error"

        event_types = [type(e).__name__ for e in bus.events]
        assert "ToolFailed" in event_types
        failed_event = [e for e in bus.events if isinstance(e, ToolFailed)][0]
        assert failed_event.error == "API error"
        assert failed_event.duration_ms >= 0.0

        # Invariant: failed execution emits ToolFailed, NOT ToolCompleted
        assert not any(isinstance(e, ToolCompleted) for e in bus.events)


class TestToolRuntimeNoRegistryDependency:
    """ToolRuntime must not depend on ToolRegistry."""

    def test_no_registry_in_constructor(self):
        import inspect
        sig = inspect.signature(ToolRuntime.__init__)
        params = set(sig.parameters.keys())
        assert "registry" not in params
        assert "tool_registry" not in params

    def test_no_execute_raw_method(self):
        assert not hasattr(ToolRuntime, "execute_raw")


class TestToolRuntimeRetry:
    """Retry wraps ONLY plugin execution."""

    @pytest.mark.asyncio
    async def test_retry_emits_tool_retried(self):
        call_count = 0

        class RetryOncePlugin:
            kinds = ("test_service",)

            async def execute(self, request):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return PluginResult(success=False, error="transient")
                return PluginResult(success=True, output={"ok": True})

        class RetryOncePolicy:
            async def should_retry(self, attempt, error):
                return attempt == 1
            def delay(self, attempt):
                return 0.0

        adapter = ToolAdapter(FakePluginRegistry(RetryOncePlugin()))
        resolver = FakeResolver(_make_resolved_integration())
        bus = CollectingEventBus()
        runtime = ToolRuntime(
            adapter=adapter,
            resolver=resolver,
            retry_policy=RetryOncePolicy(),
            event_bus=bus,
        )

        result = await runtime.execute(_make_definition(), _make_request())

        assert result.success is True
        assert call_count == 2

        event_types = [type(e).__name__ for e in bus.events]
        assert "ToolRetried" in event_types
        retried = [e for e in bus.events if isinstance(e, ToolRetried)][0]
        assert retried.attempt == 1
        assert retried.error == "transient"
        assert retried.delay == 0.0
