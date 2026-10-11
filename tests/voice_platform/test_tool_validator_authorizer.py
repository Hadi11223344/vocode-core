"""Tests for ToolValidator and ToolAuthorizer."""

from types import MappingProxyType

import pytest

from voice_platform.runtime.tools.authorizer import ToolAuthorizer
from voice_platform.runtime.tools.types import (
    AuthorizationResult,
    ToolCaller,
    ToolCallerType,
    ToolDefinition,
    ToolExecutionRequest,
    ValidationResult,
)
from voice_platform.runtime.tools.validator import ToolValidator


def _make_request(args: dict | None = None):
    return ToolExecutionRequest(
        arguments=args or {},
        caller=ToolCaller(caller_type=ToolCallerType.FLOW, user_id=1),
        execution_id="exec-1",
    )


def _make_tool(required_context: dict | None = None):
    return ToolDefinition(
        name="test",
        description="test",
        schema={},
        service_type="test",
        action="test",
        required_context=MappingProxyType(required_context) if required_context else MappingProxyType({}),
    )


class TestToolValidator:
    """ToolValidator checks required_context gates."""

    @pytest.mark.asyncio
    async def test_no_required_context_passes(self):
        validator = ToolValidator()
        result = await validator.validate(_make_request({"a": "1"}), _make_tool())
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_min_values_passes(self):
        validator = ToolValidator()
        result = await validator.validate(
            _make_request({"a": "1", "b": "2"}),
            _make_tool({"min_values": 2}),
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_min_values_fails(self):
        validator = ToolValidator()
        result = await validator.validate(
            _make_request({"a": "1"}),
            _make_tool({"min_values": 2, "gate_message": "Need more info"}),
        )
        assert result.valid is False
        assert result.error == "Need more info"

    @pytest.mark.asyncio
    async def test_required_params_passes(self):
        validator = ToolValidator()
        result = await validator.validate(
            _make_request({"date": "2024-01-01", "time": "10:00", "purpose": "meeting"}),
            _make_tool({"required_params": ["date", "time", "purpose"]}),
        )
        assert result.valid is True

    @pytest.mark.asyncio
    async def test_required_params_fails(self):
        validator = ToolValidator()
        result = await validator.validate(
            _make_request({"date": "2024-01-01"}),
            _make_tool({
                "required_params": ["date", "time", "purpose"],
                "gate_message": "Missing details",
            }),
        )
        assert result.valid is False
        assert result.error == "Missing details"

    @pytest.mark.asyncio
    async def test_empty_values_count_as_missing(self):
        validator = ToolValidator()
        result = await validator.validate(
            _make_request({"a": "", "b": None, "c": "value"}),
            _make_tool({"min_values": 2}),
        )
        assert result.valid is False


class TestToolAuthorizer:
    """ToolAuthorizer — allow-all by default."""

    @pytest.mark.asyncio
    async def test_allow_all(self):
        authorizer = ToolAuthorizer()
        result = await authorizer.authorize(_make_request(), _make_tool())
        assert result.allowed is True
        assert result.reason is None
