"""FlowRuntime — thin adapter wrapping LangGraphFlowExecutor.

Translates ExecutionRuntime interface to LangGraphFlowExecutor's methods.
Uses a callback-to-generator bridge: FlowExecutor still uses callbacks internally
(passed into LangGraph's ainvoke() config), but FlowRuntime yields SessionEvent
via async generators.

Queue bridge is necessary because ainvoke() is a single blocking await —
we cannot yield from inside it. Events are collected via callback during
ainvoke() and yielded after.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from voice_platform.runtime.session.context import ExecutionContext
from voice_platform.runtime.session.events import (
    SessionEvent,
    SessionEventFactory,
    SessionEventType,
)
from voice_platform.runtime.session.execution import ConversationInput, ExecutionRuntime

_SENTINEL = object()


def _map_flow_event(event_dict: dict) -> SessionEvent:
    """Map a FlowExecutor callback dict to a SessionEvent."""
    event_type = event_dict.get("event") or event_dict.get("type", "")

    if event_type == "flow_start":
        return SessionEventFactory.flow_start(
            node_count=event_dict.get("node_count", 0),
            edge_count=event_dict.get("edge_count", 0),
        )
    elif event_type == "flow_end":
        return SessionEventFactory.flow_end(total_nodes=event_dict.get("total_nodes", 0))
    elif event_type == "node_start":
        return SessionEventFactory.node_start(
            node_id=event_dict.get("node_id", ""),
            node_type=event_dict.get("node_type"),
            label=event_dict.get("label"),
        )
    elif event_type == "node_result":
        return SessionEventFactory.node_result(
            node_id=event_dict.get("node_id", ""),
            node_type=event_dict.get("node_type"),
            label=event_dict.get("label"),
            status=event_dict.get("status"),
            result=event_dict.get("result"),
            duration_ms=event_dict.get("duration_ms"),
            error=event_dict.get("error"),
        )
    elif event_type == "edge_traversed":
        return SessionEventFactory.edge_traversed(
            source=event_dict.get("source", ""),
            target=event_dict.get("target", ""),
            label=event_dict.get("label", ""),
        )
    elif event_type == "agent_response":
        return SessionEventFactory.assistant_message(
            text=event_dict.get("text", ""),
            node_id=event_dict.get("node_id", ""),
        )
    elif event_type == "agent_token":
        return SessionEventFactory.token(
            text=event_dict.get("text", ""),
            node_id=event_dict.get("node_id", ""),
        )
    elif event_type == "error":
        return SessionEventFactory.error(text=event_dict.get("text", ""))
    elif event_type == "info":
        return SessionEventFactory.info(text=event_dict.get("text", ""))
    elif event_type == "condition_branch":
        return SessionEventFactory.condition_branch(
            node_id=event_dict.get("node_id", ""),
            condition_met=event_dict.get("condition_met", False),
        )
    elif event_type == "variables_extracted":
        return SessionEventFactory.variables_extracted(
            node_id=event_dict.get("node_id", ""),
            variables=event_dict.get("variables"),
        )
    elif event_type == "extraction_failed":
        return SessionEventFactory.extraction_failed(
            node_id=event_dict.get("node_id", ""),
            variables=event_dict.get("variables", []),
            text=event_dict.get("text", ""),
        )
    elif event_type == "slot_validation":
        return SessionEventFactory.slot_validation(
            node_id=event_dict.get("node_id", ""),
            slot=event_dict.get("slot", ""),
            raw_value=event_dict.get("raw_value", ""),
            normalized_value=event_dict.get("normalized_value", ""),
            status=event_dict.get("status", ""),
            error=event_dict.get("error", ""),
        )
    elif event_type == "slot_exhausted":
        return SessionEventFactory.slot_exhausted(
            node_id=event_dict.get("node_id", ""),
            slot=event_dict.get("slot", ""),
            text=event_dict.get("text", ""),
        )
    elif event_type == "debug":
        return SessionEventFactory.debug(text=event_dict.get("text", ""))
    else:
        return SessionEvent(SessionEventType.INFO, {"raw": event_dict})


class FlowRuntime(ExecutionRuntime):
    """Wraps LangGraphFlowExecutor for playground flow WebSocket.

    Flow execution is interrupt-based — the graph runs until it hits a
    conversation node, then waits.  cancel() is a no-op because there's
    no active long-running execution between user messages.

    Uses a callback-to-generator bridge: the executor's event_callback
    pushes events to an asyncio.Queue, and the generator yields them.
    """

    def __init__(self, executor: Any) -> None:
        self._executor = executor

    async def start(self, context: ExecutionContext) -> AsyncGenerator[SessionEvent, None]:
        events: asyncio.Queue[SessionEvent] = asyncio.Queue()

        async def callback(event_dict: dict) -> None:
            session_event = _map_flow_event(event_dict)
            await events.put(session_event)

        async def run() -> None:
            try:
                await self._executor.start_flow(callback)
            except Exception as e:
                await events.put(SessionEventFactory.error(str(e)[:200]))
            finally:
                await events.put(_SENTINEL)  # type: ignore[arg-type]

        task = asyncio.create_task(run())
        try:
            while True:
                event = await events.get()
                if event is _SENTINEL:
                    break
                yield event
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def send_message(self, message: ConversationInput) -> AsyncGenerator[SessionEvent, None]:
        events: asyncio.Queue[SessionEvent] = asyncio.Queue()

        async def callback(event_dict: dict) -> None:
            session_event = _map_flow_event(event_dict)
            await events.put(session_event)

        async def run() -> None:
            try:
                await self._executor.process_user_message(message.text, callback)
            except Exception as e:
                await events.put(SessionEventFactory.error(str(e)[:200]))
            finally:
                await events.put(_SENTINEL)  # type: ignore[arg-type]

        task = asyncio.create_task(run())
        try:
            while True:
                event = await events.get()
                if event is _SENTINEL:
                    break
                yield event
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def cancel(self) -> None:
        pass

    async def end(self) -> None:
        await self._executor.reset()
