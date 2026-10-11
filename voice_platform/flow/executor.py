"""
LangGraphFlowExecutor — WebSocket-compatible flow executor.

Replaces FlowPlaygroundConversation with a LangGraph-backed state machine.
Provides the same interface (start_flow, process_user_message, reset, update_context)
so the WebSocket endpoint doesn't need to change.

Key difference: instead of a BFS queue, it uses LangGraph's graph.ainvoke()
with interrupt() at conversation nodes for pause/resume.
"""

import asyncio
import json
import uuid
from typing import Any, Callable, Dict, List, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphRecursionError
from loguru import logger

from voice_platform.database import DATABASE_URL
from voice_platform.flow.compiler import compile_flow, create_initial_state, get_cycle_warnings
from voice_platform.flow.slots import mirror_aliases
from voice_platform.flow.state import FlowState

# Global checkpointer state. A single AsyncPostgresSaver pool is shared across the
# process; MemorySaver is still used for SQLite/development fallback.
_checkpointer_lock = asyncio.Lock()
_checkpointer_singleton: Optional[Any] = None
_checkpointer_pool: Optional[Any] = None
_checkpointer_setup_complete: bool = False

_PLAYGROUND_PLACEHOLDER_NAMES = {
    "test caller",
    "test user",
    "test patient",
    "caller",
    "patient",
}
_PLAYGROUND_PLACEHOLDER_PHONE_DIGITS = {
    "10000000000",
    "0000000000",
    "1111111111",
}


def _sanitize_playground_context(context: dict) -> dict:
    """Remove playground mock placeholders that poison identity collection."""
    import re

    cleaned: dict[str, Any] = {}
    for key, value in (context or {}).items():
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        key_l = str(key).strip().lower()
        if key_l in {"caller_name", "patient_name", "name"} and text.lower() in _PLAYGROUND_PLACEHOLDER_NAMES:
            continue
        if key_l in {"caller_phone", "phone", "mobile"}:
            digits = re.sub(r"\D", "", text)
            if digits in _PLAYGROUND_PLACEHOLDER_PHONE_DIGITS:
                continue
        cleaned[str(key)] = value
    return cleaned


def _strip_placeholder_identity(extracted: dict) -> dict:
    """Drop placeholder identity values already present in extracted_vars."""
    import re

    out = dict(extracted or {})
    for key in list(out.keys()):
        key_l = str(key).strip().lower()
        text = str(out.get(key) or "").strip()
        if not text:
            continue
        if key_l in {"caller_name", "patient_name", "name"} and text.lower() in _PLAYGROUND_PLACEHOLDER_NAMES:
            out.pop(key, None)
            continue
        if key_l in {"caller_phone", "phone", "mobile"}:
            digits = re.sub(r"\D", "", text)
            if digits in _PLAYGROUND_PLACEHOLDER_PHONE_DIGITS:
                out.pop(key, None)
    return out


async def get_checkpointer() -> Any:
    """Return a process-scoped LangGraph checkpointer.

    Uses AsyncPostgresSaver when DATABASE_URL is PostgreSQL; otherwise falls
    back to an in-memory MemorySaver.
    """
    global _checkpointer_singleton, _checkpointer_pool

    if _checkpointer_singleton is not None:
        return _checkpointer_singleton

    async with _checkpointer_lock:
        if _checkpointer_singleton is not None:
            return _checkpointer_singleton

        if DATABASE_URL.startswith("postgresql+asyncpg://") or DATABASE_URL.startswith("postgresql://"):
            dsn = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg_pool.pool_async import AsyncConnectionPool

            pool = AsyncConnectionPool(conninfo=dsn, min_size=1, max_size=10, open=False)
            await pool.open()
            _checkpointer_pool = pool
            _checkpointer_singleton = AsyncPostgresSaver(conn=pool)
            logger.info("LangGraph checkpointer: using AsyncPostgresSaver")
        else:
            _checkpointer_singleton = MemorySaver()
            logger.info("LangGraph checkpointer: using MemorySaver (non-PostgreSQL DATABASE_URL)")

    return _checkpointer_singleton


async def setup_checkpointer() -> None:
    """Create checkpointer tables if using Postgres. Safe to call multiple times."""
    global _checkpointer_setup_complete

    if not DATABASE_URL.startswith("postgresql"):
        _checkpointer_setup_complete = True
        return

    if _checkpointer_setup_complete:
        return

    async with _checkpointer_lock:
        if _checkpointer_setup_complete:
            return

        dsn = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
        import psycopg
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        # Run setup in an autocommit connection. LangGraph's migrations include
        # CREATE INDEX CONCURRENTLY, which cannot run inside a transaction block.
        conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        try:
            temp_saver = AsyncPostgresSaver(conn=conn)
            await temp_saver.setup()
            logger.info("LangGraph checkpointer tables initialized")
        finally:
            await conn.close()

        _checkpointer_setup_complete = True


async def close_checkpointer() -> None:
    """Close the shared Postgres pool on application shutdown."""
    global _checkpointer_singleton, _checkpointer_pool, _checkpointer_setup_complete

    async with _checkpointer_lock:
        if _checkpointer_pool is not None:
            try:
                await _checkpointer_pool.close()
                logger.info("LangGraph checkpointer pool closed")
            except Exception as e:
                logger.warning(f"Error closing LangGraph checkpointer pool: {e}")
            _checkpointer_pool = None
        _checkpointer_singleton = None
        _checkpointer_setup_complete = False


class LangGraphFlowExecutor:
    """
    LangGraph-backed flow executor for the playground WebSocket.

    Same interface as the old FlowPlaygroundConversation:
    - start_flow(event_callback) → runs until first interrupt (conversation node)
    - process_user_message(user_text, event_callback) → resumes from interrupt
    - reset() → re-initializes state
    - update_context(ctx) → updates state
    """

    def __init__(
        self,
        agent,
        graph: dict,
        playground_conv,
        user_id: int,
    ):
        self.agent = agent
        self.graph = graph
        self.conv = playground_conv
        self.user_id = user_id
        self.started = False

        # Thread ID for LangGraph checkpointing
        self._thread_id = str(uuid.uuid4())
        self._config = {"configurable": {"thread_id": self._thread_id}, "recursion_limit": 50}

        # Checkpointer is created lazily by _ensure_compiled() so it can be
        # shared (AsyncPostgresSaver) or per-instance (MemorySaver fallback).
        self._checkpointer: Optional[Any] = None

        # Flag for detecting broken WebSocket sends
        self._event_callback_failed = False

        # Build initial state
        self._state: FlowState = create_initial_state(
            graph_json=graph,
            user_id=user_id,
            agent_id=int(getattr(agent, "id", 0)),
            agent_timezone=getattr(agent, "timezone", None) or "",
        )

        # Compiled graph will be created on first use
        self._compiled_graph = None

    async def _ensure_compiled(self, event_callback: Callable = None):
        """Lazily compile the graph."""
        if self._compiled_graph is not None:
            return

        # Resolve the process-level checkpointer (Postgres if configured, else MemorySaver)
        self._checkpointer = await get_checkpointer()

        # Mark conv as being in flow mode so LLM calls skip tool definitions
        # (the flow handler manages all actions — LLM should not call tools itself)
        setattr(self.conv, "_flow_mode", True)

        # Compile the graph (handlers created internally with builder caching)
        self._compiled_graph = compile_flow(
            graph_json=self.graph,
            checkpointer=self._checkpointer,
        )

    async def start_flow(self, event_callback=None) -> None:
        """Initialize and run the flow from trigger to first conversation node."""
        # Emit cycle warnings
        true_cycles, conditional_retries = get_cycle_warnings(self.graph)
        if true_cycles and event_callback:
            await event_callback({
                "event": "error",
                "text": f"Warning: graph contains cycles at nodes: {', '.join(true_cycles[:5])}. Execution may loop.",
            })
        if conditional_retries and event_callback:
            await event_callback({
                "event": "info",
                "text": f"Note: graph has conditional retry loops at nodes: {', '.join(conditional_retries[:5])}. These are safe — only one branch executes at runtime.",
            })

        await self._ensure_compiled(event_callback)
        self.started = True

        if event_callback:
            await event_callback({
                "event": "flow_start",
                "node_count": len(self.graph.get("nodes", [])),
                "edge_count": len(self.graph.get("edges", [])),
            })

        snapshot = await self._compiled_graph.aget_state(self._config)
        if snapshot.values:
            self._state = {**self._state, **snapshot.values}
            has_pending = bool(
                snapshot.next
                or (snapshot.tasks and any(task.interrupts for task in snapshot.tasks))
            )
            logger.info(
                f"LangGraphFlowExecutor: restored thread_id={self._thread_id[:8]} "
                f"(pending={has_pending})"
            )
            if not has_pending and event_callback:
                await event_callback({
                    "event": "flow_end",
                    "total_nodes": self._state.get("total_steps", 0),
                })
            return

        # Run the graph until it hits an interrupt (conversation node) or END
        try:
            from voice_platform.database import async_session
            async with async_session() as db_session:
                invoke_config = {"configurable": {"thread_id": self._thread_id,
                    "event_callback": event_callback, "playground_conv": self.conv,
                    "agent": self.agent, "user_id": self.user_id, "db_session": db_session},
                    "recursion_limit": 50}
                result = await self._compiled_graph.ainvoke(
                    self._state,
                    config=invoke_config,
                )
            self._state = {**self._state, **result}

            if getattr(self, '_event_callback_failed', False):
                logger.warning("FlowAgent: event callback failed during start_flow, aborting further execution")
                return

            # Check whether the graph is paused at an interrupt or has finished
            snapshot = await self._compiled_graph.aget_state(self._config)
            is_interrupted = bool(
                snapshot.next
                or (
                    snapshot.tasks
                    and any(task.interrupts for task in snapshot.tasks)
                )
            )
            if not is_interrupted and event_callback:
                await event_callback({
                    "event": "flow_end",
                    "total_nodes": self._state.get("total_steps", 0),
                })
        except GraphRecursionError:
            logger.error("Flow execution hit recursion limit (50) — graph too deep or cycle detected")
            if event_callback:
                await event_callback({
                    "event": "error",
                    "text": "Flow execution hit recursion limit. The flow graph may have a cycle.",
                })
        except Exception as e:
            logger.error(f"Flow execution error: {e}")
            if event_callback:
                await event_callback({
                    "event": "error",
                    "text": f"Flow execution error: {str(e)[:200]}",
                })

    async def process_user_message(
        self, user_text: str, event_callback=None
    ) -> None:
        """Process a user message and continue the flow.

        This resumes the graph from the interrupt at the conversation node.
        The user's text is passed via Command(resume=user_text).
        """
        from langgraph.types import Command

        if not self.started:
            # Auto-start flow on first message
            await self.start_flow(event_callback)

        await self._ensure_compiled(event_callback)

        # MH-6: Check if flow has already ended before trying to resume
        if self._compiled_graph is not None:
            try:
                snapshot = await self._compiled_graph.aget_state(self._config)
                has_pending = bool(
                    snapshot.next
                    or (snapshot.tasks and any(task.interrupts for task in snapshot.tasks))
                )
                if not has_pending:
                    logger.info("LangGraphFlowExecutor: flow has already ended, using LLM fallback")
                    if event_callback:
                        await event_callback({
                            "event": "info",
                            "text": "The flow has ended. You can continue chatting freely.",
                        })
                    await self._post_flow_llm_fallback(user_text, event_callback)
                    return
            except Exception as e:
                logger.warning(f"LangGraphFlowExecutor: could not check flow state: {e}, proceeding with resume")

        # Resume the graph from the interrupt with the user's text
        try:
            from voice_platform.database import async_session
            async with async_session() as db_session:
                invoke_config = {"configurable": {"thread_id": self._thread_id,
                    "event_callback": event_callback, "playground_conv": self.conv,
                    "agent": self.agent, "user_id": self.user_id, "db_session": db_session},
                    "recursion_limit": 50}
                result = await self._compiled_graph.ainvoke(
                    Command(resume=user_text),
                    config=invoke_config,
                )
            self._state = {**self._state, **result}

            if getattr(self, '_event_callback_failed', False):
                logger.warning("FlowAgent: event callback failed during process_user_message, aborting further execution")
                return

            # Check whether the graph finished or is waiting at another interrupt
            snapshot = await self._compiled_graph.aget_state(self._config)
            is_interrupted = bool(
                snapshot.next
                or (
                    snapshot.tasks
                    and any(task.interrupts for task in snapshot.tasks)
                )
            )
            if not is_interrupted and event_callback:
                await event_callback({
                    "event": "flow_end",
                    "total_nodes": self._state.get("total_steps", 0),
                })
        except GraphRecursionError:
            logger.error("Flow resume hit recursion limit (50) — graph too deep or cycle detected")
            if event_callback:
                await event_callback({
                    "event": "error",
                    "text": "Flow execution hit recursion limit. The flow graph may have a cycle.",
                })
        except Exception as e:
            logger.error(f"Flow resume error: {e}")
            if event_callback:
                await event_callback({
                    "event": "error",
                    "text": f"Flow execution error: {str(e)[:200]}",
                })

    async def _post_flow_llm_fallback(self, user_text: str, event_callback=None) -> None:
        """Fallback: call LLM directly when the flow has already ended.

        Uses the playground conversation to generate a response, bypassing
        the LangGraph flow entirely so the user can continue chatting.
        """
        try:
            messages = list(self.conv.messages)
            messages.append({"role": "user", "content": user_text})
            from voice_platform.flow.nodes import _call_ollama, _call_openai, _sanitize_token
            if self.conv._is_ollama():
                response = await _call_ollama(self.conv, messages, "fallback", event_callback)
            else:
                response = await _call_openai(self.conv, messages, "fallback", event_callback)
            if response and event_callback:
                await event_callback({
                    "event": "agent_response",
                    "node_id": "fallback",
                    "text": _sanitize_token(response).strip(),
                })
        except Exception as e:
            logger.error(f"Post-flow LLM fallback error: {e}")
            if event_callback:
                await event_callback({
                    "event": "error",
                    "text": f"Could not generate response: {str(e)[:200]}",
                })

    def update_context(self, new_context: dict) -> None:
        """Update context variables in the flow state.

        All variables are routed to extracted_vars (which has a merge_dicts
        reducer) so they persist across ainvoke() calls. Updating top-level
        state fields directly would be overwritten by LangGraph on the next
        ainvoke() because those fields lack reducers.

        Playground mock placeholders like ``Test Caller`` / ``+10000000000`` are
        stripped so Contact Details asks for real identity instead of confirming
        fake defaults.
        """
        cleaned = _sanitize_playground_context(new_context or {})
        merged = {
            **self._state.get("extracted_vars", {}),
            **cleaned,
        }
        # Explicit clears: if the client sent a placeholder/empty for an identity
        # field, remove any prior mirrored value too.
        for key in ("caller_name", "patient_name", "caller_phone", "phone", "mobile"):
            if key in (new_context or {}) and key not in cleaned:
                merged.pop(key, None)
        self._state["extracted_vars"] = mirror_aliases(_strip_placeholder_identity(merged))

    async def update_context_async(self, new_context: dict) -> None:
        """Async version of update_context that also persists to the checkpointer.

        Use this when updating context mid-flow (between interrupts) so that
        the next ainvoke(Command(resume=...)) picks up the new context from
        the checkpoint rather than the stale snapshot.
        """
        self.update_context(new_context)
        if self._compiled_graph is not None:
            try:
                await self._compiled_graph.aupdate_state(
                    self._config,
                    {"extracted_vars": self._state["extracted_vars"]},
                )
            except Exception as e:
                logger.warning(f"Failed to update checkpoint context: {e}")

    async def reset(self) -> None:
        """Reset the flow to start over."""
        # Close any existing playground conversation resources
        if hasattr(self.conv, "aclose"):
            await self.conv.aclose()

        # Reset state
        self._state = create_initial_state(
            graph_json=self.graph,
            user_id=self.user_id,
            agent_id=int(getattr(self.agent, "id", 0)),
            agent_timezone=getattr(self.agent, "timezone", None) or "",
        )

        # New thread ID for fresh checkpoint
        self._thread_id = str(uuid.uuid4())
        self._config = {"configurable": {"thread_id": self._thread_id}, "recursion_limit": 50}

        self._compiled_graph = None
        self._event_callback_failed = False
        self.started = False

    @property
    def context(self) -> dict:
        """Compatibility property — returns a dict-like view of the state."""
        extracted_vars = self._state.get("extracted_vars", {})
        return {
            **extracted_vars,
            "transcript": self._state.get("transcript", ""),
            "caller_name": extracted_vars.get("caller_name") or self._state.get("caller_name", ""),
            "caller_phone": extracted_vars.get("caller_phone") or self._state.get("caller_phone", ""),
            "user_id": self._state.get("user_id", 0),
            "result": self._state.get("result", {}),
            "last_result": self._state.get("last_result", {}),
        }
