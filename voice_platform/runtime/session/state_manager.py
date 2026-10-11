"""StateManager — abstraction over LangGraph checkpointer lifecycle.

Decouples FlowAgent from direct imports of flow/executor.py and
compile_flow, enforcing the downward dependency graph.

Protocol:
    StateManager.get_checkpointer() -> Any
    StateManager.setup() -> None
    StateManager.close() -> None

Default implementation:
    LangGraphStateManager — wraps the existing global checkpointer
    functions from flow/executor.py.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from loguru import logger


@runtime_checkable
class StateManager(Protocol):
    """Abstract interface for LangGraph state persistence."""

    async def get_checkpointer(self) -> Any:
        """Return a process-scoped LangGraph checkpointer."""
        ...

    async def setup(self) -> None:
        """Create checkpointer tables if needed. Safe to call multiple times."""
        ...

    async def close(self) -> None:
        """Close any underlying connections on shutdown."""
        ...


class LangGraphStateManager:
    """Default StateManager backed by the global checkpointer in flow/executor.py.

    Wraps the existing get_checkpointer / setup_checkpointer / close_checkpointer
    functions so callers don't need to import flow/executor.py directly.
    """

    def __init__(self) -> None:
        self._checkpointer: Optional[Any] = None

    async def get_checkpointer(self) -> Any:
        if self._checkpointer is not None:
            return self._checkpointer
        from voice_platform.flow.executor import get_checkpointer

        self._checkpointer = await get_checkpointer()
        return self._checkpointer

    async def setup(self) -> None:
        from voice_platform.flow.executor import setup_checkpointer

        await setup_checkpointer()

    async def close(self) -> None:
        from voice_platform.flow.executor import close_checkpointer

        await close_checkpointer()
        self._checkpointer = None


class InMemoryStateManager:
    """StateManager backed by MemorySaver — for tests and SQLite dev."""

    def __init__(self) -> None:
        self._checkpointer: Optional[Any] = None

    async def get_checkpointer(self) -> Any:
        if self._checkpointer is None:
            from langgraph.checkpoint.memory import MemorySaver

            self._checkpointer = MemorySaver()
            logger.info("StateManager: using MemorySaver (in-memory)")
        return self._checkpointer

    async def setup(self) -> None:
        pass

    async def close(self) -> None:
        self._checkpointer = None
