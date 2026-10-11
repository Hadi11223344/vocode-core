"""DatabaseSession Protocol — abstraction over SQLAlchemy AsyncSession.

Keeps the runtime layer decoupled from SQLAlchemy. Any async session-like
object with execute/commit/rollback/close satisfies this protocol.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DatabaseSession(Protocol):
    """Async database session protocol."""

    async def execute(self, stmt: Any) -> Any: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def close(self) -> None: ...
