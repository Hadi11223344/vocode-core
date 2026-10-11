"""ToolValidator — minimal validation returning ValidationResult.

Today: checks required_context gate (min_values, required_params).
Future: JSON schema validation, argument coercion, defaults, enum checking.
"""

from __future__ import annotations

from typing import Any, Mapping

from voice_platform.runtime.tools.types import (
    ToolDefinition,
    ToolExecutionRequest,
    ValidationResult,
)


class ToolValidator:
    """Validates tool execution requests against tool definitions."""

    async def validate(
        self,
        request: ToolExecutionRequest,
        tool: ToolDefinition,
    ) -> ValidationResult:
        """Returns ValidationResult(valid=bool, error=str|None)."""
        ctx = tool.required_context
        if not ctx:
            return ValidationResult(valid=True)

        # Check min_values gate
        min_values = ctx.get("min_values")
        if min_values is not None:
            non_empty = sum(
                1 for v in request.arguments.values()
                if v is not None and v != ""
            )
            if non_empty < min_values:
                gate_msg = ctx.get("gate_message", "Insufficient parameters")
                return ValidationResult(valid=False, error=gate_msg)

        # Check required_params gate
        required_params: list[str] | None = ctx.get("required_params")
        if required_params:
            missing = [
                p for p in required_params
                if not request.arguments.get(p)
            ]
            if missing:
                gate_msg = ctx.get("gate_message", f"Missing required: {', '.join(missing)}")
                return ValidationResult(valid=False, error=gate_msg)

        return ValidationResult(valid=True)
