"""Structured tracing for flow execution.

Phase 5.6: A lightweight Tracer emits events for node lifecycle, slot filling,
action/condition execution, LLM calls, and errors. Events are written to the
configured event_callback and to the debug logger so external analytics can
consume them without changing business logic.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable, Optional, Union

from vocode.streaming.utils.pii_redaction import redact_pii

logger = logging.getLogger(__name__)


def _safe_trace_value(value: Any, key: str = "") -> Any:
    """Create a redacted diagnostic copy; never mutate runtime state values."""
    lowered_key = key.lower()
    if any(part in lowered_key for part in ("api_key", "token", "secret", "password", "credential")):
        return "[REDACTED]" if value not in (None, "") else value
    if lowered_key == "rows" and isinstance(value, list):
        return {"row_count": len(value)}
    if isinstance(value, dict):
        return {str(k): _safe_trace_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_trace_value(item, lowered_key) for item in list(value)[:20]]
    if isinstance(value, str):
        if "email" in lowered_key and value:
            return "[EMAIL]"
        if any(part in lowered_key for part in ("phone", "mobile")) and value:
            return "[PHONE]"
        redacted = redact_pii(value)
        def _replace_phone(match: re.Match) -> str:
            digits = re.sub(r"\D", "", match.group(0))
            return "[PHONE]" if 10 <= len(digits) <= 15 else match.group(0)
        return re.sub(
            r"(?<!\d)(?:\+?\d[\d\s().-]{5,}\d)(?!\d)",
            _replace_phone,
            redacted,
        )[:1000]
    return value


class Tracer:
    """Collects structured trace events for a single flow execution.

    The tracer is intentionally decoupled from business logic: handlers receive
    it via ``RunnableConfig["configurable"]["tracer"]`` and call ``emit`` to
    record events. If no tracer is configured a shared ``NULL_TRACER`` is used.
    """

    def __init__(
        self,
        event_callback: Optional[Callable[[dict], Union[Any, Awaitable[Any]]]] = None,
        workflow_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        agent_id: Optional[int] = None,
        thread_id: Optional[str] = None,
        max_events: int = 500,
    ):
        self.event_callback = event_callback
        self.workflow_id = workflow_id
        self.conversation_id = conversation_id
        self.agent_id = agent_id
        self.thread_id = thread_id
        self.max_events = max(max_events, 1)
        self.events: list[dict] = []

    def _base_event(self, event_type: str) -> dict:
        return {
            "event": event_type,
            "timestamp": time.time(),
            "workflow_id": self.workflow_id,
            "conversation_id": self.conversation_id,
            "agent_id": self.agent_id,
            "thread_id": self.thread_id,
        }

    async def emit(self, event_type: str, **fields: Any) -> dict:
        """Record and dispatch a structured trace event."""
        slot_name = str(fields.get("slot") or "")
        safe_fields = {
            key: _safe_trace_value(value, slot_name if key == "value" and slot_name else key)
            for key, value in fields.items()
        }
        event = self._base_event(event_type)
        event.update(safe_fields)
        self.events.append(event)
        if len(self.events) > self.max_events:
            self.events.pop(0)
        logger.debug("trace: %s", event)
        if self.event_callback is not None:
            try:
                result = self.event_callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # pragma: no cover - tracing must not break flow
                logger.exception("event_callback failed for trace event")
        return event

    @asynccontextmanager
    async def node(self, node_id: str, node_type: str, label: Optional[str] = None):
        """Context manager that emits ``node_enter`` and ``node_exit`` events."""
        start = time.time()
        await self.emit("node_enter", node_id=node_id, node_type=node_type, label=label or node_id)
        try:
            yield self
        except Exception as exc:
            await self.emit(
                "node_exit",
                node_id=node_id,
                node_type=node_type,
                label=label or node_id,
                duration_ms=round((time.time() - start) * 1000, 1),
                error=str(exc),
                status="error",
            )
            raise
        else:
            await self.emit(
                "node_exit",
                node_id=node_id,
                node_type=node_type,
                label=label or node_id,
                duration_ms=round((time.time() - start) * 1000, 1),
                status="success",
            )

    async def transition(
        self,
        source: str,
        target: str,
        branch: Optional[str] = None,
    ) -> dict:
        return await self.emit(
            "transition",
            source=source,
            target=target,
            branch=branch,
        )

    async def slot_filled(
        self,
        node_id: str,
        slot: str,
        value: Any,
        source: str = "extraction",
    ) -> dict:
        return await self.emit(
            "slot_filled",
            node_id=node_id,
            slot=slot,
            value=str(value)[:200] if value is not None else None,
            source=source,
        )

    async def slot_invalid(
        self,
        node_id: str,
        slot: str,
        value: Any,
        reason: str,
    ) -> dict:
        return await self.emit(
            "slot_invalid",
            node_id=node_id,
            slot=slot,
            value=str(value)[:200] if value is not None else None,
            reason=reason,
        )

    async def llm_request(
        self,
        node_id: str,
        model: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
    ) -> dict:
        return await self.emit(
            "llm_request",
            node_id=node_id,
            model=model,
            prompt_tokens=prompt_tokens,
        )

    async def llm_response(
        self,
        node_id: str,
        model: Optional[str] = None,
        duration_ms: Optional[float] = None,
        response_length: Optional[int] = None,
        cached: bool = False,
    ) -> dict:
        return await self.emit(
            "llm_response",
            node_id=node_id,
            model=model,
            duration_ms=duration_ms,
            response_length=response_length,
            cached=cached,
        )

    async def action_executed(
        self,
        node_id: str,
        action: str,
        integration_type: str,
        duration_ms: Optional[float] = None,
        input_vars: Optional[dict] = None,
        output: Optional[Any] = None,
    ) -> dict:
        return await self.emit(
            "action_executed",
            node_id=node_id,
            action=action,
            integration_type=integration_type,
            duration_ms=duration_ms,
            input_vars=input_vars,
            output=output,
        )

    async def action_failed(
        self,
        node_id: str,
        action: str,
        error: str,
        duration_ms: Optional[float] = None,
    ) -> dict:
        return await self.emit(
            "action_failed",
            node_id=node_id,
            action=action,
            error=error,
            duration_ms=duration_ms,
        )

    async def action_missing_inputs(
        self,
        node_id: str,
        action: str,
        missing_inputs: list[str],
        collected_inputs: Optional[dict] = None,
    ) -> dict:
        return await self.emit(
            "action_missing_inputs",
            node_id=node_id,
            action=action,
            missing_inputs=missing_inputs,
            collected_inputs=collected_inputs or {},
            branch="on_missing",
        )

    async def llm_empty_response(
        self,
        node_id: str,
        node_label: str,
        streaming: bool,
        messages_count: int,
        system_prompt_len: int,
        node_prompt_present: bool,
    ) -> dict:
        return await self.emit(
            "llm_empty_response",
            node_id=node_id,
            node_label=node_label,
            streaming=streaming,
            messages_count=messages_count,
            system_prompt_len=system_prompt_len,
            node_prompt_present=node_prompt_present,
        )

    async def condition_evaluated(
        self,
        node_id: str,
        expression: str,
        result: bool,
        branch: Optional[str] = None,
    ) -> dict:
        return await self.emit(
            "condition_evaluated",
            node_id=node_id,
            expression=expression,
            result=result,
            branch=branch,
        )

    async def error(
        self,
        node_id: str,
        node_type: str,
        error: str,
    ) -> dict:
        return await self.emit(
            "error",
            node_id=node_id,
            node_type=node_type,
            error=error,
        )


class _NullTracer:
    """No-op tracer used when tracing is disabled."""

    events: list[dict] = []

    async def emit(self, event_type: str, **fields: Any) -> dict:
        return {}

    @asynccontextmanager
    async def node(self, node_id: str, node_type: str, label: Optional[str] = None):
        yield self

    async def transition(self, *args, **kwargs) -> dict:
        return {}

    async def slot_filled(self, *args, **kwargs) -> dict:
        return {}

    async def slot_invalid(self, *args, **kwargs) -> dict:
        return {}

    async def llm_request(self, *args, **kwargs) -> dict:
        return {}

    async def llm_response(self, *args, **kwargs) -> dict:
        return {}

    async def action_executed(self, *args, **kwargs) -> dict:
        return {}

    async def action_failed(self, *args, **kwargs) -> dict:
        return {}

    async def action_missing_inputs(self, *args, **kwargs) -> dict:
        return {}

    async def llm_empty_response(self, *args, **kwargs) -> dict:
        return {}

    async def condition_evaluated(self, *args, **kwargs) -> dict:
        return {}

    async def error(self, *args, **kwargs) -> dict:
        return {}


NULL_TRACER = _NullTracer()


def get_tracer(config: dict) -> Tracer:
    """Return the tracer from RunnableConfig, preferring the per-node _tracer set by the compiler wrapper."""
    configurable = config.get("configurable") or {}
    tracer = configurable.get("_tracer") or configurable.get("tracer")
    if tracer is not None:
        return tracer
    return NULL_TRACER
