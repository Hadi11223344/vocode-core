"""ToolAuthorizer — minimal authorization returning AuthorizationResult.

Today: allow all.
Future: RBAC, conversation permissions, workspace permissions, billing limits, rate limits.
"""

from __future__ import annotations

from voice_platform.runtime.tools.types import (
    AuthorizationResult,
    ToolDefinition,
    ToolExecutionRequest,
)


class ToolAuthorizer:
    """Authorizes tool execution requests."""

    async def authorize(
        self,
        request: ToolExecutionRequest,
        tool: ToolDefinition,
    ) -> AuthorizationResult:
        """Returns AuthorizationResult(allowed=bool, reason=str|None)."""
        return AuthorizationResult(allowed=True)
