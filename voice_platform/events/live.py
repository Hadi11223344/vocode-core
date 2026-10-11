"""Live dashboard manager singleton.

Moved from api/live_routes.py to fix upward dependency (events → api).
Both api and events now import from here.
"""

import asyncio
from typing import Dict, Set

from fastapi import WebSocket
from loguru import logger


class LiveDashboardManager:
    """Manages WebSocket connections for the live call dashboard.

    Clients connect via /api/live/ws and receive real-time events:
    - transcript: New message from human or bot
    - call_started: A new call connected
    - call_ended: A call disconnected
    - action: A tool/action executed during the call
    - stats_update: Periodic stats refresh
    """

    def __init__(self):
        self._connections: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, user_id: int, subprotocol: str | None = None):
        """Register a new WebSocket connection."""
        if subprotocol:
            await websocket.accept(subprotocol=subprotocol)
        else:
            await websocket.accept()
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = set()
            self._connections[user_id].add(websocket)
        logger.info(f"Live dashboard: user {user_id} connected ({len(self._connections.get(user_id, set()))} total)")

    async def disconnect(self, websocket: WebSocket, user_id: int):
        """Remove a WebSocket connection."""
        async with self._lock:
            if user_id in self._connections:
                self._connections[user_id].discard(websocket)
                if not self._connections[user_id]:
                    del self._connections[user_id]
        logger.info(f"Live dashboard: user {user_id} disconnected")

    async def broadcast_to_user(self, user_id: int, event: dict):
        """Send an event to all of a user's connected dashboards."""
        connections = self._connections.get(user_id, set()).copy()
        dead = []
        for ws in connections:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.get(user_id, set()).discard(ws)

    async def broadcast_transcript(self, user_id: int, conversation_id: str,
                                   sender: str, message: str, timestamp: float):
        """Broadcast a new transcript message to the user's live dashboard."""
        await self.broadcast_to_user(user_id, {
            "type": "transcript",
            "conversation_id": conversation_id,
            "sender": sender,
            "message": message,
            "timestamp": timestamp,
        })

    async def broadcast_call_event(self, user_id: int, event_type: str, call_data: dict):
        """Broadcast call lifecycle events (started, ended)."""
        await self.broadcast_to_user(user_id, {
            "type": event_type,
            **call_data,
        })

    async def broadcast_action(self, user_id: int, conversation_id: str, action_data: dict):
        """Broadcast tool/action execution events to the live dashboard."""
        await self.broadcast_to_user(user_id, {
            "type": "action",
            "conversation_id": conversation_id,
            **action_data,
        })

    def has_listeners(self, user_id: int) -> bool:
        """Check if a user has any active dashboard connections."""
        return bool(self._connections.get(user_id))

    @property
    def total_connections(self) -> int:
        return sum(len(conns) for conns in self._connections.values())


live_manager = LiveDashboardManager()
