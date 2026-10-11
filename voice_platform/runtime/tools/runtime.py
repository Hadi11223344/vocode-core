"""ToolRuntime — pure execution orchestration.

No discovery, no registry lookup, no execute_raw. Receives a resolved
ToolDefinition from the caller. Does NOT depend on ToolRegistry.
Single API: execute(definition, request).

Lifecycle: validate → authorize → resolve → execute (with retry) → observe.
Retry wraps ONLY plugin execution — not the full lifecycle.
Duration measured internally via time.monotonic().
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from voice_platform.runtime.events.event_bus import EventBus, NoOpEventBus
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
from voice_platform.runtime.tools.retry import NoRetryPolicy, RetryPolicy
from voice_platform.runtime.tools.types import (
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from voice_platform.runtime.tools.validator import ToolValidator


class ToolRuntime:
    """Pure execution orchestration. No discovery, no registry lookup, no execute_raw.
    Receives a resolved ToolDefinition from the caller. Does NOT depend on ToolRegistry.
    Single API: execute(definition, request)."""

    def __init__(
        self,
        adapter: ToolAdapter,
        resolver: IntegrationResolver,
        validator: ToolValidator | None = None,
        authorizer: ToolAuthorizer | None = None,
        retry_policy: RetryPolicy | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._adapter = adapter
        self._resolver = resolver
        self._validator = validator or ToolValidator()
        self._authorizer = authorizer or ToolAuthorizer()
        self._retry = retry_policy or NoRetryPolicy()
        self._event_bus: EventBus = event_bus or NoOpEventBus()

    async def execute(
        self,
        definition: ToolDefinition,
        request: ToolExecutionRequest,
    ) -> ToolExecutionResult[Any]:
        """Full lifecycle. Retry wraps ONLY plugin execution."""
        tool_name = definition.name
        exec_id = request.execution_id

        # 1. Validate
        validation = await self._validator.validate(request, definition)
        await self._event_bus.publish(
            ToolValidated(tool_name=tool_name, execution_id=exec_id, valid=validation.valid)
        )
        if not validation.valid:
            return ToolExecutionResult.failure(
                validation.error or "Validation failed"
            )

        # 2. Authorize
        authorization = await self._authorizer.authorize(request, definition)
        await self._event_bus.publish(
            ToolAuthorized(
                tool_name=tool_name,
                execution_id=exec_id,
                allowed=authorization.allowed,
            )
        )
        if not authorization.allowed:
            return ToolExecutionResult.failure(
                authorization.reason or "Authorization denied"
            )

        # 3. Emit ToolStarted
        await self._event_bus.publish(
            ToolStarted(tool_name=tool_name, execution_id=exec_id)
        )

        # 4. Resolve integration
        integration = await self._resolver.resolve(
            integration_id=request.integration_id,
            service_type=definition.service_type,
            overrides=request.integration_overrides,
            agent_timezone=request.agent_timezone,
        )
        if integration is None:
            duration_ms = 0.0
            await self._event_bus.publish(
                ToolFailed(
                    tool_name=tool_name,
                    execution_id=exec_id,
                    error=f"No integration found for service_type={definition.service_type}",
                    duration_ms=duration_ms,
                )
            )
            return ToolExecutionResult.failure(
                f"No integration found for service_type={definition.service_type}"
            )

        # 5. Retry loop (wraps ONLY adapter.execute)
        start = time.monotonic()
        attempt = 0
        result: ToolExecutionResult[Any] = ToolExecutionResult.failure("Not executed")

        while True:
            try:
                result = await self._adapter.execute(request, definition, integration)
            except Exception as exc:
                logger.exception(f"Tool '{tool_name}' execution error (attempt {attempt}): {exc}")
                result = ToolExecutionResult.failure(str(exc))

            if result.success:
                break

            attempt += 1
            should_retry = await self._retry.should_retry(attempt, result.error or "")
            if not should_retry:
                break

            delay = self._retry.delay(attempt)
            await self._event_bus.publish(
                ToolRetried(
                    tool_name=tool_name,
                    execution_id=exec_id,
                    attempt=attempt,
                    error=result.error or "",
                    delay=delay,
                )
            )
            if delay > 0:
                await asyncio.sleep(delay)

        # 6. Emit completion
        duration_ms = (time.monotonic() - start) * 1000.0
        if result.success:
            await self._event_bus.publish(
                ToolCompleted(
                    tool_name=tool_name,
                    execution_id=exec_id,
                    success=True,
                    duration_ms=duration_ms,
                )
            )
        else:
            await self._event_bus.publish(
                ToolFailed(
                    tool_name=tool_name,
                    execution_id=exec_id,
                    error=result.error or "Unknown error",
                    duration_ms=duration_ms,
                )
            )

        return result
