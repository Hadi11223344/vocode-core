"""
Voice Platform — Dashboard API Routes
========================================

Analytics and statistics endpoints for the dashboard view.

Routes:
    GET /api/dashboard/stats   — Aggregate call statistics
    GET /api/dashboard/recent  — Most recent calls
"""

from datetime import datetime, timedelta, timezone  # For date range calculations

from fastapi import APIRouter, Depends, HTTPException, Query  # Routing
from loguru import logger
from sqlalchemy import func, select  # Aggregate queries
from sqlalchemy.ext.asyncio import AsyncSession  # Async DB session

from voice_platform.database import Agent, CallLog, User, get_db
from voice_platform.middleware.auth_middleware import get_current_user

# Create router
router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def get_dashboard_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get aggregate statistics for the user's dashboard.
    
    Returns counts and metrics across all of the user's calls:
    - Total calls ever
    - Total duration in minutes
    - Average call duration
    - Currently active calls
    - Calls in the last 24 hours
    - Calls in the last 7 days
    - Number of agents
    
    All stats are scoped to the authenticated user's data only.
    
    Returns:
        Dictionary of aggregate statistics
    """
    try:
        return await _compute_stats(user, db)
    except Exception as e:
        logger.error(f"Failed to compute dashboard stats for user {user.id}: {e}")
        raise HTTPException(500, "Failed to load dashboard statistics. Please try again.")


async def _compute_stats(user: User, db: AsyncSession):
    # ── Total Calls ────────────────────────────────────────────────
    # COUNT(*) of all call_logs belonging to this user
    total_result = await db.execute(
        select(func.count(CallLog.id)).where(CallLog.user_id == user.id)
    )
    total_calls = total_result.scalar() or 0
    
    # ── Total Duration ─────────────────────────────────────────────
    # SUM(duration_secs) across all completed calls
    duration_result = await db.execute(
        select(func.sum(CallLog.duration_secs)).where(
            CallLog.user_id == user.id,
            CallLog.duration_secs.isnot(None),  # Only completed calls have duration
        )
    )
    total_duration_secs = duration_result.scalar() or 0
    total_duration_mins = round(total_duration_secs / 60, 1)  # Convert to minutes
    
    # ── Average Duration ───────────────────────────────────────────
    avg_result = await db.execute(
        select(func.avg(CallLog.duration_secs)).where(
            CallLog.user_id == user.id,
            CallLog.duration_secs.isnot(None),
        )
    )
    avg_duration = round(avg_result.scalar() or 0, 1)
    
    # ── Active Calls ───────────────────────────────────────────────
    active_result = await db.execute(
        select(func.count(CallLog.id)).where(
            CallLog.user_id == user.id,
            CallLog.status.in_(["active", "ringing", "initiated"]),
        )
    )
    active_calls = active_result.scalar() or 0
    
    # ── Calls Today ────────────────────────────────────────────────
    # Calls started in the last 24 hours
    today_start = datetime.now(timezone.utc) - timedelta(hours=24)
    today_result = await db.execute(
        select(func.count(CallLog.id)).where(
            CallLog.user_id == user.id,
            CallLog.started_at >= today_start,
        )
    )
    calls_today = today_result.scalar() or 0
    
    # ── Calls This Week ────────────────────────────────────────────
    week_start = datetime.now(timezone.utc) - timedelta(days=7)
    week_result = await db.execute(
        select(func.count(CallLog.id)).where(
            CallLog.user_id == user.id,
            CallLog.started_at >= week_start,
        )
    )
    calls_this_week = week_result.scalar() or 0
    
    # ── Success Rate ───────────────────────────────────────────────
    completed_result = await db.execute(
        select(func.count(CallLog.id)).where(
            CallLog.user_id == user.id,
            CallLog.status == "completed",
        )
    )
    completed_count = completed_result.scalar() or 0
    success_rate = round((completed_count / total_calls) * 100, 1) if total_calls > 0 else 0

    # ── Agent Count ────────────────────────────────────────────────
    agent_result = await db.execute(
        select(func.count(Agent.id)).where(
            Agent.user_id == user.id,
            Agent.is_active == True,  # Only count active agents
        )
    )
    agents_count = agent_result.scalar() or 0

    return {
        "total_calls": total_calls,
        "total_duration_mins": total_duration_mins,
        "avg_duration_secs": avg_duration,
        "active_calls": active_calls,
        "calls_today": calls_today,
        "calls_this_week": calls_this_week,
        "agents_count": agents_count,
        "success_rate": success_rate,
        "completed_calls": completed_count,
    }


@router.get("/recent")
async def get_recent_calls(
    limit: int = Query(default=10, ge=1, le=100, description="Number of recent calls"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the most recent calls for the dashboard quick view.
    
    Returns a compact list of recent calls with basic metadata.
    For full details (transcripts, actions), use GET /api/calls/{id}.
    
    Args:
        limit: Number of calls to return (1-100, default 10)
    
    Returns:
        List of recent call objects
    """
    try:
        result = await db.execute(
            select(CallLog)
            .where(CallLog.user_id == user.id)
            .order_by(CallLog.started_at.desc())
            .limit(limit)
        )
        calls = result.scalars().all()
        return {"recent_calls": [call.to_dict() for call in calls]}
    except Exception as e:
        logger.error(f"Failed to load recent calls for user {user.id}: {e}")
        raise HTTPException(500, "Failed to load recent calls. Please try again.")
