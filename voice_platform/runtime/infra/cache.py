"""Cache Protocol — abstraction over Redis or any cache backend.

Keeps the runtime layer decoupled from Redis. Any async key-value store
with get/set/delete satisfies this protocol.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Cache(Protocol):
    """Async cache protocol."""

    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
