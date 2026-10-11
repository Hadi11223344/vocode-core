"""Tests for tool runtime value objects and factory methods."""

from types import MappingProxyType

import pytest

from voice_platform.runtime.tools.types import (
    AuthorizationResult,
    AvailableTool,
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


class TestToolExecutionResultFactoryMethods:
    """ToolExecutionResult.success() and .failure() factory methods."""

    def test_success_with_output(self):
        result = ToolExecutionResult.success(output={"key": "value"})
        assert result.success is True
        assert result.output == {"key": "value"}
        assert result.error is None

    def test_success_with_metadata(self):
        result = ToolExecutionResult.success(output="done", metadata={"latency_ms": 42.0})
        assert result.success is True
        assert result.output == "done"
        assert result.metadata["latency_ms"] == 42.0

    def test_success_no_output(self):
        result = ToolExecutionResult.success()
        assert result.success is True
        assert result.output is None

    def test_failure_with_error(self):
        result = ToolExecutionResult.failure("Something went wrong")
        assert result.success is False
        assert result.error == "Something went wrong"
        assert result.output is None

    def test_failure_with_metadata(self):
        result = ToolExecutionResult.failure("error", metadata={"retry_count": 3})
        assert result.success is False
        assert result.error == "error"
        assert result.metadata["retry_count"] == 3

    def test_to_dict_success_with_dict_output(self):
        result = ToolExecutionResult.success(output={"data": 123})
        d = result.to_dict()
        assert d["success"] is True
        assert d["data"] == 123

    def test_to_dict_failure(self):
        result = ToolExecutionResult.failure("bad request")
        d = result.to_dict()
        assert d["success"] is False
        assert d["error"] == "bad request"


class TestToolExecutionResultImmutability:
    """ToolExecutionResult is frozen."""

    def test_cannot_mutate_success(self):
        result = ToolExecutionResult.success(output="ok")
        with pytest.raises(Exception):
            result.success = False

    def test_cannot_mutate_error(self):
        result = ToolExecutionResult.failure("err")
        with pytest.raises(Exception):
            result.error = "new error"


class TestToolDefinition:
    """ToolDefinition uses service_type, not integration_type."""

    def test_service_type_field(self):
        tool = ToolDefinition(
            name="check_calendar",
            description="Check calendar",
            schema={"type": "object"},
            service_type="google_calendar",
            action="check_availability",
        )
        assert tool.service_type == "google_calendar"
        assert tool.action == "check_availability"

    def test_required_context_default_empty(self):
        tool = ToolDefinition(
            name="test",
            description="test",
            schema={},
            service_type="test",
            action="test",
        )
        assert len(tool.required_context) == 0


class TestAvailableTool:
    """AvailableTool carries definition + availability metadata."""

    def test_defaults(self):
        definition = ToolDefinition(
            name="test", description="", schema={},
            service_type="test", action="test",
        )
        tool = AvailableTool(definition=definition)
        assert tool.enabled is True
        assert tool.reason is None
        assert tool.integration_id is None

    def test_disabled_with_reason(self):
        definition = ToolDefinition(
            name="test", description="", schema={},
            service_type="test", action="test",
        )
        tool = AvailableTool(
            definition=definition,
            enabled=False,
            reason="OAuth required",
        )
        assert tool.enabled is False
        assert tool.reason == "OAuth required"


class TestTraceContext:
    """TraceContext is a frozen value object."""

    def test_defaults(self):
        ctx = TraceContext()
        assert ctx.trace_id == ""
        assert ctx.span_id is None

    def test_with_values(self):
        ctx = TraceContext(trace_id="abc123", span_id="span456")
        assert ctx.trace_id == "abc123"
        assert ctx.span_id == "span456"


class TestToolCallerType:
    """ToolCallerType enum has expected values."""

    def test_values(self):
        assert ToolCallerType.FLOW.value == "flow"
        assert ToolCallerType.PLAYGROUND.value == "playground"
        assert ToolCallerType.PLATFORM.value == "platform"


class TestValidationResult:
    """ValidationResult structured return."""

    def test_valid(self):
        result = ValidationResult(valid=True)
        assert result.valid is True
        assert result.error is None

    def test_invalid_with_error(self):
        result = ValidationResult(valid=False, error="Missing field")
        assert result.valid is False
        assert result.error == "Missing field"


class TestAuthorizationResult:
    """AuthorizationResult structured return."""

    def test_allowed(self):
        result = AuthorizationResult(allowed=True)
        assert result.allowed is True
        assert result.reason is None

    def test_denied_with_reason(self):
        result = AuthorizationResult(allowed=False, reason="Insufficient permissions")
        assert result.allowed is False
        assert result.reason == "Insufficient permissions"


class TestToolDiscoveryRequest:
    """ToolDiscoveryRequest immutable discovery request."""

    def test_construction(self):
        req = ToolDiscoveryRequest(
            user_id=1,
            tools_config=["check_calendar", "send_email"],
        )
        assert req.user_id == 1
        assert req.tools_config == ["check_calendar", "send_email"]
        assert len(req.mcp_bindings) == 0
        assert len(req.integration_overrides) == 0
