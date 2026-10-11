"""
Voice Platform — Live Call Dashboard Routes
=============================================

WebSocket-based real-time call monitoring + REST endpoints for live data.

Routes:
    WS   /api/live/ws                   — Real-time transcript stream for ALL active calls
    GET  /api/live/active               — Snapshot of all active calls with metadata
    GET  /api/live/stats                — Real-time platform stats (active calls, today's calls, etc.)
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, Set

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from voice_platform.database import ActionLog, Agent, CallLog, Transcript, get_db
from voice_platform.events.live import live_manager
from voice_platform.middleware.auth_middleware import (
    _wants_bearer_subprotocol,
    get_current_user,
    get_current_user_ws,
)
from voice_platform.middleware.ws_tracker import ws_tracker

router = APIRouter(prefix="/api/live", tags=["Live Dashboard"])


# ── WebSocket Endpoint ────────────────────────────────────────────────

@router.websocket("/ws")
async def live_dashboard_ws(websocket: WebSocket):
    """
    WebSocket endpoint for real-time call monitoring.
    
    Auth (preferred): use websocket subprotocol bearer,<JWT_TOKEN>
    Legacy auth is still accepted via query token: /api/live/ws?token=JWT_TOKEN
    
    Events sent to client:
        {"type": "transcript", "conversation_id": "...", "sender": "human|bot", "message": "...", "timestamp": 1234}
        {"type": "call_started", "conversation_id": "...", "from_phone": "...", "to_phone": "...", "agent_name": "..."}
        {"type": "call_ended", "conversation_id": "...", "duration_secs": 123.4}
        {"type": "action", "conversation_id": "...", "action_type": "...", "params_json": "...", "result_json": "..."}
        {"type": "ping"}
    """
    # Authenticate via query param
    try:
        user = await get_current_user_ws(websocket)
    except Exception as e:
        logger.warning(f"Live WS auth failed: {e}")
        await websocket.close(code=4001, reason="Unauthorized")
        return

    user_id = int(getattr(user, "id"))
    if not ws_tracker.can_connect(user_id):
        await websocket.close(code=1013, reason="Too many concurrent connections")
        return

    subprotocol = "bearer" if _wants_bearer_subprotocol(websocket) else None
    await live_manager.connect(websocket, user_id, subprotocol=subprotocol)
    await ws_tracker.add(user_id, websocket)
    
    try:
        # Keep connection alive — listen for client pings
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Send server ping to keep connection alive
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"Live WS error: {e}")
    finally:
        await live_manager.disconnect(websocket, user_id)
        await ws_tracker.remove(user_id, websocket)


# ── REST Endpoints ─────────────────────────────────────────────────────

@router.get("/active")
async def get_active_calls(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get snapshot of all currently active calls with full metadata.
    
    Includes agent name, caller info, duration so far, and latest messages.
    """
    result = await db.execute(
        select(CallLog)
        .where(
            CallLog.user_id == user.id,
            CallLog.status.in_(["active", "ringing", "initiated"]),
        )
        .order_by(CallLog.started_at.desc())
    )
    calls = result.scalars().all()

    if not calls:
        return {"active_calls": [], "total": 0}

    call_ids = [c.id for c in calls]

    # R2-P2: Batch fetch recent transcripts and actions for all active calls
    # in 2 queries instead of 2*N per-call queries.
    t_result = await db.execute(
        select(Transcript)
        .where(Transcript.call_log_id.in_(call_ids))
        .order_by(Transcript.timestamp.desc())
    )
    # Group transcripts by call_log_id, keep last 5 per call
    transcripts_by_call: dict = {}
    for t in t_result.scalars().all():
        lst = transcripts_by_call.setdefault(t.call_log_id, [])
        if len(lst) < 5:
            lst.append(t.to_dict())
    # Reverse each list to chronological order
    for k in transcripts_by_call:
        transcripts_by_call[k].reverse()

    a_result = await db.execute(
        select(ActionLog)
        .where(ActionLog.call_log_id.in_(call_ids))
        .order_by(ActionLog.timestamp.desc())
    )
    actions_by_call: dict = {}
    for a in a_result.scalars().all():
        lst = actions_by_call.setdefault(a.call_log_id, [])
        if len(lst) < 5:
            lst.append(a.to_dict())
    for k in actions_by_call:
        actions_by_call[k].reverse()

    active_calls = []
    for call in calls:
        recent_messages = transcripts_by_call.get(call.id, [])
        recent_actions = actions_by_call.get(call.id, [])

        # Calculate live duration
        duration = None
        if call.started_at:
            started = call.started_at.replace(tzinfo=timezone.utc) if call.started_at.tzinfo is None else call.started_at
            duration = (datetime.now(timezone.utc) - started).total_seconds()

        active_calls.append({
            **call.to_dict(),
            "live_duration_secs": duration,
            "recent_messages": recent_messages,
            "recent_actions": recent_actions,
            "message_count": len(recent_messages),
        })

    return {"active_calls": active_calls, "total": len(active_calls)}


@router.get("/stats")
async def get_live_stats(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get real-time platform statistics for the live dashboard.
    """
    from datetime import timedelta
    
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())
    
    # Active calls
    active_result = await db.execute(
        select(func.count(CallLog.id)).where(
            CallLog.user_id == user.id,
            CallLog.status.in_(["active", "ringing", "initiated"]),
        )
    )
    active_count = active_result.scalar() or 0
    
    # Today's calls
    today_result = await db.execute(
        select(func.count(CallLog.id)).where(
            CallLog.user_id == user.id,
            CallLog.started_at >= today_start,
        )
    )
    today_count = today_result.scalar() or 0
    
    # This week's calls
    week_result = await db.execute(
        select(func.count(CallLog.id)).where(
            CallLog.user_id == user.id,
            CallLog.started_at >= week_start,
        )
    )
    week_count = week_result.scalar() or 0
    
    # Average duration today
    avg_result = await db.execute(
        select(func.avg(CallLog.duration_secs)).where(
            CallLog.user_id == user.id,
            CallLog.started_at >= today_start,
            CallLog.duration_secs.isnot(None),
        )
    )
    avg_duration = avg_result.scalar() or 0
    
    # Total calls
    total_result = await db.execute(
        select(func.count(CallLog.id)).where(CallLog.user_id == user.id)
    )
    total_count = total_result.scalar() or 0
    
    # Active agents
    agent_result = await db.execute(
        select(func.count(Agent.id)).where(
            Agent.user_id == user.id,
            Agent.is_active == True,
        )
    )
    agent_count = agent_result.scalar() or 0
    
    # WebSocket listeners
    ws_count = live_manager.total_connections
    
    return {
        "active_calls": active_count,
        "calls_today": today_count,
        "calls_this_week": week_count,
        "total_calls": total_count,
        "avg_duration_today": round(avg_duration, 1),
        "active_agents": agent_count,
        "ws_connections": ws_count,
        "server_time": now.isoformat(),
    }
