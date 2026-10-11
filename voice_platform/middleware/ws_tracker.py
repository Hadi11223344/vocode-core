"""
Voice Platform — WebSocket Connection Tracker

Tracks active WebSocket connections per user to enforce concurrent
connection limits and enable graceful shutdown.

Usage in WebSocket handlers:
  from voice_platform.middleware.ws_tracker import ws_tracker

  # On connect
  ws_tracker.add(user_id, websocket)

  # On disconnect
  ws_tracker.remove(user_id, websocket)

  # Check limit
  if not ws_tracker.can_connect(user_id):
      await websocket.close(code=1013, reason="Too many concurrent connections")
      return

  # Graceful shutdown
  await ws_tracker.close_all()
"""

import asyncio
from typing import Dict, Set

from fastapi import WebSocket
from loguru import logger

MAX_CONNECTIONS_PER_USER = 5


class WebSocketTracker:
    """Tracks active WebSocket connections per user."""

    def __init__(self) -> None:
        self._connections: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    def can_connect(self, user_id: int) -> bool:
        """Check if user can open another connection."""
        current = len(self._connections.get(user_id, set()))
        return current < MAX_CONNECTIONS_PER_USER

    async def add(self, user_id: int, websocket: WebSocket) -> None:
        """Register a new WebSocket connection for a user."""
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = set()
            self._connections[user_id].add(websocket)
        logger.debug(
            f"WS tracker: added connection for user {user_id} "
            f"(total: {len(self._connections[user_id])})"
        )

    async def remove(self, user_id: int, websocket: WebSocket) -> None:
        """Remove a WebSocket connection for a user."""
        async with self._lock:
            conns = self._connections.get(user_id)
            if conns:
                conns.discard(websocket)
                if not conns:
                    del self._connections[user_id]
        logger.debug(f"WS tracker: removed connection for user {user_id}")

    def get_user_count(self, user_id: int) -> int:
        """Get the number of active connections for a user."""
        return len(self._connections.get(user_id, set()))

    def get_total_count(self) -> int:
        """Get the total number of active connections across all users."""
        return sum(len(conns) for conns in self._connections.values())

    async def close_all(self, reason: str = "Server shutting down") -> None:
        """Close all active WebSocket connections. Used during graceful shutdown."""
        async with self._lock:
            total = self.get_total_count()
            if total == 0:
                return
            logger.info(f"WS tracker: closing {total} active connections...")
            for user_id, conns in self._connections.items():
                for ws in conns:
                    try:
                        await ws.close(code=1001, reason=reason)
                    except Exception:
                        pass
            self._connections.clear()
            logger.info("WS tracker: all connections closed")


ws_tracker = WebSocketTracker()
