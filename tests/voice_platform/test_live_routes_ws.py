"""WebSocket auth/transport behavior tests for live routes."""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import WebSocketDisconnect

from voice_platform.database import ActionLog

pytestmark = pytest.mark.asyncio


class _FakeWebSocket:
    def __init__(self, incoming_text: list[str] | None = None, headers: dict[str, str] | None = None):
        self._incoming_text = list(incoming_text or [])
        self.headers = headers or {}
        self.accepted = False
        self.accept_subprotocol: str | None = None
        self.closed = False
        self.close_code = None
        self.close_reason = None
        self.sent: list[dict[str, Any]] = []

    async def accept(self, subprotocol: str | None = None):
        self.accepted = True
        self.accept_subprotocol = subprotocol

    async def close(self, code=None, reason=None):
        self.closed = True
        self.close_code = code
        self.close_reason = reason

    async def receive_text(self) -> str:
        if self._incoming_text:
            return self._incoming_text.pop(0)
        raise WebSocketDisconnect()

    async def send_json(self, payload: dict[str, Any]):
        self.sent.append(payload)


class _FakeLiveManager:
    def __init__(self):
        self.connected: list[tuple[int, str | None]] = []
        self.disconnected: list[int] = []

    async def connect(self, websocket, user_id: int, subprotocol: str | None = None):
        await websocket.accept(subprotocol=subprotocol)
        self.connected.append((user_id, subprotocol))

    async def disconnect(self, _websocket, user_id: int):
        self.disconnected.append(user_id)


async def test_live_ws_unauthorized_closes_with_4001(monkeypatch):
    from voice_platform.api import live_routes

    async def _fake_get_current_user_ws(_websocket):
        raise RuntimeError("nope")

    monkeypatch.setattr(live_routes, "get_current_user_ws", _fake_get_current_user_ws)

    ws = _FakeWebSocket()
    await live_routes.live_dashboard_ws(cast(Any, ws))

    assert ws.accepted is False
    assert ws.closed is True
    assert ws.close_code == 4001
    assert ws.close_reason == "Unauthorized"


async def test_live_ws_accepts_bearer_subprotocol_and_replies_pong(monkeypatch):
    from voice_platform.api import live_routes

    async def _fake_get_current_user_ws(_websocket):
        return SimpleNamespace(id=7)

    fake_manager = _FakeLiveManager()

    monkeypatch.setattr(live_routes, "get_current_user_ws", _fake_get_current_user_ws)
    monkeypatch.setattr(live_routes, "live_manager", fake_manager)

    ws = _FakeWebSocket(
        incoming_text=["ping"],
        headers={"sec-websocket-protocol": "bearer,abc.def.ghi"},
    )

    await live_routes.live_dashboard_ws(cast(Any, ws))

    assert ws.accepted is True
    assert ws.accept_subprotocol == "bearer"
    assert {"type": "pong"} in ws.sent
    assert fake_manager.connected == [(7, "bearer")]
    assert fake_manager.disconnected == [7]


async def test_live_active_snapshot_includes_recent_actions(client, test_call, db_session):
    action = ActionLog(
        call_log_id=test_call.id,
        action_type="read_file_content",
        params_json='{"file_id": "file_123"}',
        result_json='{"text": "verified"}',
        timestamp=123.0,
    )
    db_session.add(action)
    await db_session.commit()
    await db_session.refresh(action)

    resp = await client.get("/api/live/active")

    assert resp.status_code == 200
    active_calls = resp.json()["active_calls"]
    assert len(active_calls) == 1
    assert active_calls[0]["conversation_id"] == test_call.conversation_id
    assert active_calls[0]["recent_actions"][0]["action_type"] == "read_file_content"
    assert active_calls[0]["recent_actions"][0]["params_json"] == '{"file_id": "file_123"}'
