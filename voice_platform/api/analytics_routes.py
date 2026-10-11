"""
Voice Platform — Analytics Routes
====================================

Post-call analysis and aggregate analytics endpoints.

Features:
    - Automatic post-call analysis via LLM (sentiment, summary, topics, action items)
    - Aggregate analytics (call volume, duration trends, sentiment distribution)
    - Per-agent performance metrics
    - Time-series data for charts

Routes:
    POST /api/analytics/analyze/{call_id}   — Run LLM analysis on a call
    GET  /api/analytics/call/{call_id}      — Get analysis for a specific call
    GET  /api/analytics/overview            — Aggregate analytics overview
    GET  /api/analytics/agent/{agent_id}    — Per-agent performance metrics
    GET  /api/analytics/trends              — Time-series data for charts
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlalchemy import Float as SAFloat
from sqlalchemy import case, cast, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import Agent, CallLog, PromptVersion, Transcript, _is_sqlite, get_db
from voice_platform.middleware.auth_middleware import get_current_user
from voice_platform.runtime.observability.analysis import basic_analysis as _basic_analysis
from voice_platform.runtime.observability.analysis import (
    build_transcript_text as _build_transcript_text,
)
from voice_platform.runtime.observability.analysis import (
    get_or_create_analysis as _get_or_create_analysis,
)
from voice_platform.runtime.observability.analysis import (
    redact_sensitive_text as _redact_sensitive_text,
)
from voice_platform.runtime.observability.analysis import run_llm_analysis as _run_llm_analysis


def _date_expr(column):
    """Cross-DB date extraction: SQLite uses date(col), PostgreSQL uses date(timezone('UTC', col))."""
    if _is_sqlite:
        return func.date(column)
    return func.date(func.timezone(literal_column("'UTC'"), column))

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


# ── AN-10: Analytics caching layer ────────────────────────────────────
# TTL cache for expensive aggregate queries. 60-second stale window
# strikes a balance between dashboard responsiveness and data freshness.

class _AnalyticsCache:
    def __init__(self, ttl_seconds: int = 60, max_entries: int = 500):
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._store: dict[str, tuple[float, dict]] = {}

    def _key(self, prefix: str, *parts) -> str:
        return f"{prefix}:{':'.join(str(p) for p in parts)}"

    def _evict_expired(self) -> None:
        now = datetime.now(timezone.utc).timestamp()
        expired = [k for k, (exp, _) in self._store.items() if now >= exp]
        for k in expired:
            del self._store[k]

    def get(self, prefix: str, *parts) -> dict | None:
        key = self._key(prefix, *parts)
        expires_at, value = self._store.get(key, (0, None))
        if value is not None and datetime.now(timezone.utc).timestamp() < expires_at:
            return value
        if key in self._store:
            del self._store[key]
        return None

    def set(self, prefix: str, *parts, value: dict):
        self._evict_expired()
        if len(self._store) >= self._max_entries:
            oldest = sorted(self._store.items(), key=lambda kv: kv[1][0])[:1]
            if oldest:
                del self._store[oldest[0][0]]
        key = self._key(prefix, *parts)
        self._store[key] = (datetime.now(timezone.utc).timestamp() + self._ttl, value)

    def clear(self):
        self._store.clear()


_analytics_cache = _AnalyticsCache(ttl_seconds=60)


# ── Routes ─────────────────────────────────────────────────────────────

@router.post("/analyze/{call_id}")
async def analyze_call(
    call_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Run LLM-based analysis on a specific call.
    
    Analyzes the transcript for sentiment, summary, topics, action items,
    talk ratios, and resolution status. Results are cached.
    """
    # Get the call
    result = await db.execute(
        select(CallLog).where(CallLog.id == call_id, CallLog.user_id == user.id)
    )
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(404, "Call not found")
    
    # Build transcript
    transcript_text = await _build_transcript_text(db, call_id)
    if not transcript_text:
        raise HTTPException(400, "No transcript available for this call")
    
    # Run analysis
    analysis = await _run_llm_analysis(transcript_text, user.id)

    # D-1: Store analysis as JSON in call_log to avoid re-running LLM on every view
    analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
    analysis["call_id"] = call_id
    call.analysis_json = json.dumps(analysis)
    await db.commit()

    return {
        "call_id": call_id,
        "analysis": analysis,
    }


@router.post("/reanalyze/{call_id}")
async def reanalyze_call(
    call_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-run analysis on a call using Deepgram Audio Intelligence if a recording
    URL is available, falling back to LLM-based analysis otherwise.

    Useful when the original auto-analysis failed or produced poor results.
    """
    from voice_platform.config import settings
    from voice_platform.integrations.deepgram_intelligence import analyze_call_recording

    result = await db.execute(
        select(CallLog).where(CallLog.id == call_id, CallLog.user_id == user.id)
    )
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(404, "Call not found")

    # Determine analysis provider preference from agent config
    analysis_provider = "auto"
    if call.agent_id:
        from voice_platform.database import Agent
        agent = await db.get(Agent, call.agent_id)
        if agent:
            analysis_provider = getattr(agent, 'analysis_provider', 'auto') or 'auto'

    # Try Deepgram Audio Intelligence first if recording URL exists and provider allows it
    recording_url = getattr(call, 'recording_url', None)
    use_deepgram = recording_url and analysis_provider in ("auto", "deepgram")
    if use_deepgram:
        analysis = await analyze_call_recording(
            recording_url, api_key=settings.deepgram_api_key
        )
        if analysis:
            analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
            analysis["call_id"] = call_id
            call.analysis_json = json.dumps(analysis)
            await db.commit()
            return {
                "call_id": call_id,
                "analysis": analysis,
                "provider": "deepgram",
            }

    # Fallback to LLM analysis
    transcript_text = await _build_transcript_text(db, call_id)
    if not transcript_text:
        raise HTTPException(400, "No transcript or recording available for this call")

    analysis = await _run_llm_analysis(transcript_text, user.id)
    analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()
    analysis["call_id"] = call_id
    call.analysis_json = json.dumps(analysis)
    await db.commit()

    return {
        "call_id": call_id,
        "analysis": analysis,
        "provider": "llm",
    }


@router.get("/call/{call_id}")
async def get_call_analysis(
    call_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get cached analysis for a specific call, or run it if not available."""
    result = await db.execute(
        select(CallLog).where(CallLog.id == call_id, CallLog.user_id == user.id)
    )
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(404, "Call not found")

    # D-1: Return cached analysis if available
    cached = await _get_or_create_analysis(db, call)
    if cached:
        return {"call_id": call_id, "analysis": cached, "cached": True}

    transcript_text = await _build_transcript_text(db, call_id)
    if not transcript_text:
        return {"call_id": call_id, "analysis": None, "message": "No transcript available"}

    analysis = await _run_llm_analysis(transcript_text, user.id)
    analysis["call_id"] = call_id
    analysis["analyzed_at"] = datetime.now(timezone.utc).isoformat()

    # D-1: Cache the result
    call.analysis_json = json.dumps(analysis)
    await db.commit()

    return {"call_id": call_id, "analysis": analysis, "cached": False}


@router.get("/overview")
async def get_analytics_overview(
    days: int = Query(default=30, ge=1, le=365),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get aggregate analytics overview for the user's calls.
    
    Results are cached for 60 seconds (AN-10).
    """
    cached = _analytics_cache.get("overview", user.id, days)
    if cached:
        return cached

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    base_filter = [CallLog.user_id == user.id, CallLog.started_at >= cutoff]
    
    # Total calls
    total = (await db.execute(
        select(func.count(CallLog.id)).where(*base_filter)
    )).scalar() or 0
    
    # By status
    status_result = await db.execute(
        select(CallLog.status, func.count(CallLog.id))
        .where(*base_filter)
        .group_by(CallLog.status)
    )
    by_status = {row[0]: row[1] for row in status_result.all()}
    
    # By direction
    dir_result = await db.execute(
        select(CallLog.direction, func.count(CallLog.id))
        .where(*base_filter)
        .group_by(CallLog.direction)
    )
    by_direction = {row[0] or "inbound": row[1] for row in dir_result.all()}
    
    # Duration stats
    dur_result = await db.execute(
        select(
            func.sum(CallLog.duration_secs),
            func.avg(CallLog.duration_secs),
            func.min(CallLog.duration_secs),
            func.max(CallLog.duration_secs),
        ).where(*base_filter, CallLog.duration_secs.isnot(None))
    )
    dur_row = dur_result.one()
    
    # Top agents
    agent_result = await db.execute(
        select(
            Agent.name,
            Agent.id,
            func.count(CallLog.id).label("call_count"),
            func.avg(CallLog.duration_secs).label("avg_duration"),
        )
        .join(Agent, CallLog.agent_id == Agent.id)
        .where(*base_filter)
        .group_by(Agent.id, Agent.name)
        .order_by(func.count(CallLog.id).desc())
        .limit(10)
    )
    top_agents = [
        {"name": row[0], "id": row[1], "call_count": row[2], "avg_duration": round(row[3] or 0, 1)}
        for row in agent_result.all()
    ]
    
    # Completion rate
    completed = by_status.get("completed", 0)
    completion_rate = round(completed / total * 100, 1) if total > 0 else 0

    result = {
        "period_days": days,
        "total_calls": total,
        "by_status": by_status,
        "by_direction": by_direction,
        "completion_rate": completion_rate,
        "duration": {
            "total_mins": round((dur_row[0] or 0) / 60, 1),
            "avg_secs": round(dur_row[1] or 0, 1),
            "min_secs": round(dur_row[2] or 0, 1),
            "max_secs": round(dur_row[3] or 0, 1),
        },
        "top_agents": top_agents,
    }
    _analytics_cache.set("overview", user.id, days, value=result)
    return result


@router.get("/agent/{agent_id}")
async def get_agent_analytics(
    agent_id: int,
    days: int = Query(default=30, ge=1, le=365),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get performance metrics for a specific agent."""
    # Verify agent belongs to user
    agent_result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    base_filter = [CallLog.agent_id == agent_id, CallLog.user_id == user.id, CallLog.started_at >= cutoff]
    
    # Call count
    total = (await db.execute(
        select(func.count(CallLog.id)).where(*base_filter)
    )).scalar() or 0
    
    # Completed
    completed = (await db.execute(
        select(func.count(CallLog.id)).where(*base_filter, CallLog.status == "completed")
    )).scalar() or 0
    
    # Duration
    dur_result = await db.execute(
        select(
            func.avg(CallLog.duration_secs),
            func.sum(CallLog.duration_secs),
        ).where(*base_filter, CallLog.duration_secs.isnot(None))
    )
    dur_row = dur_result.one()
    
    # Message count (avg messages per call)
    msg_result = await db.execute(
        select(func.count(Transcript.id))
        .join(CallLog, Transcript.call_log_id == CallLog.id)
        .where(*base_filter)
    )
    total_messages = msg_result.scalar() or 0
    avg_messages = round(total_messages / total, 1) if total > 0 else 0
    
    return {
        "agent": {"id": agent.id, "name": agent.name},
        "period_days": days,
        "total_calls": total,
        "completed_calls": completed,
        "completion_rate": round(completed / total * 100, 1) if total > 0 else 0,
        "avg_duration_secs": round(dur_row[0] or 0, 1),
        "total_duration_mins": round((dur_row[1] or 0) / 60, 1),
        "total_messages": total_messages,
        "avg_messages_per_call": avg_messages,
    }


@router.get("/summary")
async def get_analytics_summary(
    days: int = Query(default=7, ge=1, le=90),
    agent_id: Optional[int] = Query(default=None),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregate analytics summary from call analysis JSON. Cached for 60s (AN-10)."""
    cached = _analytics_cache.get("summary", user.id, days, agent_id or "all")
    if cached:
        return cached

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    base_filter = [
        CallLog.user_id == user.id,
        CallLog.started_at >= cutoff,
        CallLog.analysis_json.isnot(None),
    ]
    if agent_id:
        base_filter.append(CallLog.agent_id == agent_id)

    # --- Call Volume ---
    total_result = await db.execute(
        select(func.count(CallLog.id)).where(*base_filter)
    )
    total_calls = total_result.scalar() or 0

    total_dur_result = await db.execute(
        select(func.sum(CallLog.duration_secs)).where(*base_filter)
    )
    total_duration = total_dur_result.scalar() or 0
    avg_duration = total_duration / total_calls if total_calls else 0

    # --- Aggregate analysis_json ---
    analysis_result = await db.execute(
        select(CallLog.analysis_json).where(*base_filter)
    )

    sentiment_counts: dict[str, int] = {"positive": 0, "negative": 0, "neutral": 0, "unknown": 0}
    outcome_counts: dict[str, int] = {"resolved": 0, "escalated": 0, "abandoned": 0, "unresolved": 0, "unknown": 0}
    topic_counts: dict[str, int] = {}
    total_sentiment_score = 0.0
    scored_calls = 0

    for (analysis_json,) in analysis_result.all():
        if not analysis_json:
            continue
        try:
            analysis = json.loads(analysis_json)
        except json.JSONDecodeError:
            continue

        # Sentiment
        sentiment = analysis.get("sentiment", "unknown").lower()
        sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1

        # Sentiment score average
        score = analysis.get("sentiment_score")
        if isinstance(score, (int, float)):
            total_sentiment_score += score
            scored_calls += 1

        # Outcome
        outcome = analysis.get("resolution_status", "unknown").lower()
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

        # Topics
        for topic in analysis.get("topics", []):
            if isinstance(topic, str):
                topic_counts[topic] = topic_counts.get(topic, 0) + 1

    # Top 10 topics by frequency
    top_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # --- Daily Breakdown (calls with analysis only) ---
    # AN-03: Timezone-aware date extraction (SQLite/PostgreSQL compatible)
    _date_col = _date_expr(CallLog.started_at)
    daily_result = await db.execute(
        select(
            _date_col.label("date"),
            func.count(CallLog.id).label("count"),
            func.avg(CallLog.duration_secs).label("avg_duration"),
        )
        .where(*base_filter)
        .group_by(_date_col)
        .order_by(_date_col)
    )
    daily_stats = [
        {
            "date": str(row.date),
            "calls": row.count,
            "avg_duration_secs": round(row.avg_duration or 0, 1),
        }
        for row in daily_result.all()
    ]

    # --- Per-Agent Breakdown ---
    agent_result = await db.execute(
        select(
            Agent.id,
            Agent.name,
            func.count(CallLog.id).label("call_count"),
            func.avg(CallLog.duration_secs).label("avg_duration"),
        )
        .join(Agent, CallLog.agent_id == Agent.id)
        .where(*base_filter)
        .group_by(Agent.id, Agent.name)
    )
    agent_stats = [
        {
            "agent_id": row.id,
            "agent_name": row.name,
            "calls": row.call_count,
            "avg_duration_secs": round(row.avg_duration or 0, 1),
        }
        for row in agent_result.all()
    ]

    result = {
        "period_days": days,
        "total_calls": total_calls,
        "avg_duration_secs": round(avg_duration, 1),
        "avg_sentiment_score": round(total_sentiment_score / scored_calls, 2) if scored_calls else None,
        "sentiment_distribution": sentiment_counts,
        "outcome_distribution": outcome_counts,
        "top_topics": [{"topic": t, "count": c} for t, c in top_topics],
        "daily_breakdown": daily_stats,
        "agent_performance": agent_stats,
    }
    _analytics_cache.set("summary", user.id, days, agent_id or "all", value=result)
    return result


@router.get("/trends")
async def get_analytics_trends(
    days: int = Query(default=30, ge=1, le=365),
    granularity: str = Query(default="day", pattern="^(hour|day|week)$"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get time-series data for analytics charts. Cached for 60s (AN-10)."""
    cached = _analytics_cache.get("trends", user.id, days, granularity)
    if cached:
        return cached

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    
    # Get all calls in the period
    result = await db.execute(
        select(CallLog.started_at, CallLog.duration_secs, CallLog.status)
        .where(CallLog.user_id == user.id, CallLog.started_at >= cutoff)
        .order_by(CallLog.started_at.asc())
    )
    calls = result.all()
    
    # Build time series
    from collections import defaultdict
    buckets: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "completed": 0, "total_duration": 0, "failed": 0})
    
    for started_at, duration, status in calls:
        if started_at is None:
            continue
        if granularity == "hour":
            key = started_at.strftime("%Y-%m-%d %H:00")
        elif granularity == "week":
            # ISO week start
            week_start = started_at - timedelta(days=started_at.weekday())
            key = week_start.strftime("%Y-%m-%d")
        else:
            key = started_at.strftime("%Y-%m-%d")
        
        buckets[key]["calls"] += 1
        if status == "completed":
            buckets[key]["completed"] += 1
            if duration:
                buckets[key]["total_duration"] += duration
        elif status == "failed":
            buckets[key]["failed"] += 1
    
    # Convert to sorted list
    trend_data = []
    for date_key in sorted(buckets.keys()):
        b = buckets[date_key]
        avg_dur = round(b["total_duration"] / b["completed"], 1) if b["completed"] > 0 else 0
        trend_data.append({
            "date": date_key,
            "calls": b["calls"],
            "completed": b["completed"],
            "failed": b["failed"],
            "avg_duration_secs": avg_dur,
        })
    
    result = {
        "period_days": days,
        "granularity": granularity,
        "data": trend_data,
    }
    _analytics_cache.set("trends", user.id, days, granularity, value=result)
    return result


@router.get("/latency")
async def get_latency_metrics(
    days: int = Query(default=7, ge=1, le=30),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get aggregate latency metrics for dashboard (GAP-12).

    Returns average first response time, P95 turn latency, per-component
    breakdown, and daily latency trend.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    base_filter = [
        CallLog.user_id == user.id,
        CallLog.started_at >= cutoff,
        CallLog.first_response_ms.isnot(None),
    ]

    # Overall stats
    overall_result = await db.execute(
        select(
            func.avg(CallLog.first_response_ms).label("avg_first_ms"),
            func.avg(CallLog.avg_turn_latency_ms).label("avg_turn_ms"),
            func.avg(CallLog.llm_latency_ms).label("avg_llm_ms"),
            func.avg(CallLog.stt_latency_ms).label("avg_stt_ms"),
            func.avg(CallLog.tts_latency_ms).label("avg_tts_ms"),
        ).where(*base_filter)
    )
    row = overall_result.one()

    # Real p95: fetch individual first_response_ms values and compute percentile
    # Using Python-side computation since SQLite doesn't support percentile_cont
    first_response_values_result = await db.execute(
        select(CallLog.first_response_ms).where(*base_filter)
    )
    first_response_values = [v[0] for v in first_response_values_result.all() if v[0] is not None]
    if first_response_values:
        sorted_vals = sorted(first_response_values)
        p95_idx = int(len(sorted_vals) * 0.95)
        real_p95 = sorted_vals[min(p95_idx, len(sorted_vals) - 1)]
    else:
        real_p95 = 0

    # Daily trend
    # AN-03: Timezone-aware date extraction (SQLite/PostgreSQL compatible)
    _date_col = _date_expr(CallLog.started_at)
    daily_result = await db.execute(
        select(
            _date_col.label("date"),
            func.avg(CallLog.first_response_ms).label("avg_first_ms"),
            func.avg(CallLog.avg_turn_latency_ms).label("avg_turn_ms"),
            func.count(CallLog.id).label("call_count"),
        )
        .where(*base_filter)
        .group_by(_date_col)
        .order_by(_date_col)
    )

    # Per-agent stats
    agent_result = await db.execute(
        select(
            Agent.id,
            Agent.name,
            func.count(CallLog.id).label("call_count"),
            func.avg(CallLog.first_response_ms).label("avg_first_ms"),
            func.avg(CallLog.avg_turn_latency_ms).label("avg_turn_ms"),
        )
        .join(Agent, CallLog.agent_id == Agent.id)
        .where(*base_filter)
        .group_by(Agent.id, Agent.name)
    )

    avg_first = row.avg_first_ms or 0
    is_competitive = avg_first < 600

    return {
        "period_days": days,
        "overall": {
            "avg_first_response_ms": round(avg_first, 0),
            "p95_first_response_ms": round(real_p95, 0),
            "avg_turn_latency_ms": round(row.avg_turn_ms or 0, 0),
            "avg_llm_ms": round(row.avg_llm_ms or 0, 0),
            "avg_stt_ms": round(row.avg_stt_ms or 0, 0),
            "avg_tts_ms": round(row.avg_tts_ms or 0, 0),
            "is_sub_600ms": is_competitive,
        },
        "daily_trend": [
            {
                "date": str(d.date),
                "avg_first_response_ms": round(d.avg_first_ms or 0, 0),
                "avg_turn_latency_ms": round(d.avg_turn_ms or 0, 0),
                "calls": d.call_count,
            }
            for d in daily_result.all()
        ],
        "by_agent": [
            {
                "agent_id": a.id,
                "agent_name": a.name,
                "calls": a.call_count,
                "avg_first_response_ms": round(a.avg_first_ms or 0, 0),
                "avg_turn_latency_ms": round(a.avg_turn_ms or 0, 0),
            }
            for a in agent_result.all()
        ],
    }


# ═══════════════════════════════════════════════════════════════════
# Phase 5: AI Quality Assurance
# ═══════════════════════════════════════════════════════════════════

def _compute_quality_score(call: CallLog) -> tuple[float, str | None]:
    """
    Compute a 0-100 quality score for a completed call.

    Factors (weighted):
      - Latency (35%): first response + avg turn latency
      - Sentiment (25%): from cached analysis_json
      - Duration (15%): ideal range 60-300s
      - Interruptions (15%): fewer is better
      - Completion (10%): completed vs failed

    Returns (score, flag_reason) where flag_reason is set if score < 60.
    """
    if call.status != "completed":
        return 30.0, "call_failed"

    score = 0.0
    reasons: list[str] = []

    # 1. Latency (35 points)
    latency_score = 35.0
    first_ms = call.first_response_ms or 0
    turn_ms = call.avg_turn_latency_ms or 0
    if first_ms > 0:
        # Ideal: < 500ms first response = full points, > 3000ms = 0
        first_penalty = min((first_ms - 500) / 2500, 1.0) * 17.5
        latency_score -= max(0, first_penalty)
    if turn_ms > 0:
        # Ideal: < 1000ms avg turn = full points, > 5000ms = 0
        turn_penalty = min((turn_ms - 1000) / 4000, 1.0) * 17.5
        latency_score -= max(0, turn_penalty)
    score += max(0, latency_score)

    # 2. Sentiment (25 points)
    sentiment_score = 20.0  # neutral default
    if call.analysis_json:
        try:
            analysis = json.loads(call.analysis_json)
            sentiment = analysis.get("sentiment", "neutral").lower()
            sentiment_score = {
                "positive": 25.0,
                "neutral": 20.0,
                "mixed": 15.0,
                "negative": 5.0,
            }.get(sentiment, 20.0)
        except Exception:
            pass
    score += sentiment_score

    # 3. Duration (15 points)
    dur = call.duration_secs or 0
    if 60 <= dur <= 300:
        dur_score = 15.0
    elif dur < 30:
        dur_score = 5.0
        reasons.append("very_short_call")
    elif dur < 60:
        dur_score = 10.0
    elif dur <= 600:
        dur_score = 10.0
    else:
        dur_score = 5.0
        reasons.append("very_long_call")
    score += dur_score

    # 4. Interruptions (15 points)
    interruptions = call.interruption_count or 0
    if interruptions == 0:
        int_score = 15.0
    elif interruptions <= 2:
        int_score = 10.0
    elif interruptions <= 5:
        int_score = 5.0
    else:
        int_score = 0.0
        reasons.append("many_interruptions")
    score += int_score

    # 5. Completion (10 points) — already known completed
    score += 10.0

    # Clamp and round
    score = round(max(0.0, min(100.0, score)), 1)

    # Auto-flag low scores
    flag_reason = None
    if score < 40:
        flag_reason = reasons[0] if reasons else "very_low_quality"
    elif score < 60:
        flag_reason = reasons[0] if reasons else "low_quality_score"

    return score, flag_reason


@router.post("/quality/score/{call_id}")
async def score_call_quality(
    call_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Compute and store quality score for a specific call.
    """
    result = await db.execute(
        select(CallLog).where(CallLog.id == call_id, CallLog.user_id == user.id)
    )
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(404, "Call not found")

    score, flag_reason = _compute_quality_score(call)
    call.quality_score = score
    if flag_reason:
        call.review_flag = True
        call.review_reason = flag_reason
    await db.commit()

    return {
        "call_id": call_id,
        "quality_score": score,
        "review_flag": bool(flag_reason),
        "review_reason": flag_reason,
    }


@router.get("/quality/overview")
async def get_quality_overview(
    days: int = Query(default=30, ge=1, le=90),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get aggregate quality metrics for the user's calls. Cached for 60s (AN-10).
    """
    cached = _analytics_cache.get("quality_overview", user.id, days)
    if cached:
        return cached

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    base_filter = [CallLog.user_id == user.id, CallLog.started_at >= cutoff]

    # Average quality score
    avg_score_result = await db.execute(
        select(func.avg(CallLog.quality_score))
        .where(*base_filter, CallLog.quality_score.isnot(None))
    )
    avg_score = avg_score_result.scalar() or 0

    # Score distribution
    score_buckets = {
        "excellent": 0,  # 80-100
        "good": 0,       # 60-79
        "needs_work": 0, # 40-59
        "poor": 0,       # 0-39
    }
    scored_calls_result = await db.execute(
        select(CallLog.quality_score)
        .where(*base_filter, CallLog.quality_score.isnot(None))
    )
    for (sc,) in scored_calls_result.all():
        if sc >= 80:
            score_buckets["excellent"] += 1
        elif sc >= 60:
            score_buckets["good"] += 1
        elif sc >= 40:
            score_buckets["needs_work"] += 1
        else:
            score_buckets["poor"] += 1

    # Flagged calls
    flagged_result = await db.execute(
        select(func.count(CallLog.id))
        .where(*base_filter, CallLog.review_flag == True)
    )
    flagged_count = flagged_result.scalar() or 0

    # Top issues
    issue_result = await db.execute(
        select(CallLog.review_reason, func.count(CallLog.id))
        .where(*base_filter, CallLog.review_flag == True)
        .group_by(CallLog.review_reason)
    )
    top_issues = [
        {"reason": row[0] or "unknown", "count": row[1]}
        for row in issue_result.all()
    ]

    # Per-agent quality
    agent_quality_result = await db.execute(
        select(
            Agent.id,
            Agent.name,
            func.count(CallLog.id).label("call_count"),
            func.avg(CallLog.quality_score).label("avg_score"),
        )
        .join(Agent, CallLog.agent_id == Agent.id)
        .where(*base_filter, CallLog.quality_score.isnot(None))
        .group_by(Agent.id, Agent.name)
        .order_by(func.avg(CallLog.quality_score).desc())
    )
    agent_quality = [
        {
            "agent_id": row.id,
            "agent_name": row.name,
            "calls": row.call_count,
            "avg_score": round(row.avg_score or 0, 1),
        }
        for row in agent_quality_result.all()
    ]

    result = {
        "period_days": days,
        "avg_quality_score": round(avg_score, 1),
        "score_distribution": score_buckets,
        "flagged_calls": flagged_count,
        "top_issues": top_issues,
        "agent_quality": agent_quality,
    }
    _analytics_cache.set("quality_overview", user.id, days, value=result)
    return result


@router.get("/quality/flagged")
async def get_flagged_calls(
    days: int = Query(default=30, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=200),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List calls flagged for human review."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(CallLog)
        .where(
            CallLog.user_id == user.id,
            CallLog.started_at >= cutoff,
            CallLog.review_flag == True,
        )
        .order_by(CallLog.started_at.desc())
        .limit(limit)
    )
    calls = result.scalars().all()
    return {
        "calls": [c.to_dict() for c in calls],
        "count": len(calls),
    }


@router.get("/funnel")
async def get_conversion_funnel(
    days: int = Query(default=30, ge=1, le=365),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get conversion funnel stages for calls.

    Stages:
      1. Initiated — all calls started
      2. Connected — calls that reached active/completed (not failed immediately)
      3. Completed — calls that finished successfully
      4. Resolved — calls with positive outcome (analysis_json says 'resolved')
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    base_filter = [CallLog.user_id == user.id, CallLog.started_at >= cutoff]

    # Initiated
    initiated = (await db.execute(
        select(func.count(CallLog.id)).where(*base_filter)
    )).scalar() or 0

    # Connected (active or completed — anything that got past the initial connection)
    connected = (await db.execute(
        select(func.count(CallLog.id))
        .where(*base_filter, CallLog.status.in_(["active", "completed"]))
    )).scalar() or 0

    # Completed
    completed = (await db.execute(
        select(func.count(CallLog.id))
        .where(*base_filter, CallLog.status == "completed")
    )).scalar() or 0

    # Resolved (positive outcome from LLM analysis)
    resolved = 0
    if completed > 0:
        analysis_result = await db.execute(
            select(CallLog.analysis_json)
            .where(*base_filter, CallLog.status == "completed")
        )
        for (json_str,) in analysis_result.all():
            if not json_str:
                continue
            try:
                data = json.loads(json_str)
                if data.get("resolution_status", "").lower() == "resolved":
                    resolved += 1
            except Exception:
                pass

    def _pct(n: int, d: int) -> float:
        return round(n / d * 100, 1) if d > 0 else 0.0

    return {
        "period_days": days,
        "stages": [
            {"stage": "initiated", "count": initiated, "pct_of_total": 100.0, "drop_off": 0.0},
            {"stage": "connected", "count": connected, "pct_of_total": _pct(connected, initiated), "drop_off": _pct(initiated - connected, initiated)},
            {"stage": "completed", "count": completed, "pct_of_total": _pct(completed, initiated), "drop_off": _pct(connected - completed, connected)},
            {"stage": "resolved", "count": resolved, "pct_of_total": _pct(resolved, initiated), "drop_off": _pct(completed - resolved, completed)},
        ],
    }


@router.get("/cohorts")
async def get_cohort_retention(
    days: int = Query(default=30, ge=7, le=365),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get caller retention cohorts.

    Groups callers by the week of their first call, then tracks what
    percentage of them called back within 7 / 14 / 30 days.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(CallLog.from_phone, CallLog.started_at)
        .where(
            CallLog.user_id == user.id,
            CallLog.started_at >= cutoff,
            CallLog.from_phone.isnot(None),
        )
        .order_by(CallLog.started_at.asc())
    )
    rows = result.all()

    from collections import defaultdict

    # Map phone -> list of call dates
    phone_calls: defaultdict[str, list[datetime]] = defaultdict(list)
    for phone, started_at in rows:
        if phone and started_at:
            phone_calls[phone].append(started_at)

    # Map cohort_week -> {total, returned_7d, returned_14d, returned_30d}
    cohorts: dict[str, dict[str, int]] = {}
    for phone, dates in phone_calls.items():
        dates_sorted = sorted(dates)
        first = dates_sorted[0]
        # ISO week as cohort key
        week_key = first.strftime("%Y-W%W")
        if week_key not in cohorts:
            cohorts[week_key] = {"total": 0, "returned_7d": 0, "returned_14d": 0, "returned_30d": 0}
        cohorts[week_key]["total"] += 1
        if len(dates_sorted) > 1:
            second = dates_sorted[1]
            delta = (second - first).days
            if delta <= 7:
                cohorts[week_key]["returned_7d"] += 1
            if delta <= 14:
                cohorts[week_key]["returned_14d"] += 1
            if delta <= 30:
                cohorts[week_key]["returned_30d"] += 1

    cohort_list = []
    for week_key in sorted(cohorts.keys()):
        c = cohorts[week_key]
        total = c["total"]
        cohort_list.append({
            "cohort": week_key,
            "total_callers": total,
            "retention_7d": round(c["returned_7d"] / total * 100, 1) if total else 0,
            "retention_14d": round(c["returned_14d"] / total * 100, 1) if total else 0,
            "retention_30d": round(c["returned_30d"] / total * 100, 1) if total else 0,
        })

    return {
        "period_days": days,
        "cohorts": cohort_list,
        "overall": {
            "total_unique_callers": len(phone_calls),
            "repeat_callers": sum(1 for d in phone_calls.values() if len(d) > 1),
        },
    }


@router.get("/ab-test/{agent_id}")
async def get_ab_test_results(
    agent_id: int,
    days: int = Query(default=30, ge=1, le=90),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get A/B test results comparing prompt versions for an agent.
    """
    agent_result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Get all versions for this agent
    versions_result = await db.execute(
        select(PromptVersion).where(PromptVersion.agent_id == agent_id)
    )
    versions = versions_result.scalars().all()

    version_ids = [v.id for v in versions]
    if not version_ids:
        return {"agent_id": agent_id, "versions": [], "period_days": days}

    # Aggregate metrics per version from call_logs
    result = await db.execute(
        select(
            CallLog.prompt_version_id,
            func.count(CallLog.id).label("call_count"),
            func.avg(CallLog.duration_secs).label("avg_duration"),
            func.avg(CallLog.quality_score).label("avg_quality"),
            func.sum(case((CallLog.status == "completed", 1), else_=0)).label("completed_count"),
        )
        .where(
            CallLog.agent_id == agent_id,
            CallLog.started_at >= cutoff,
            CallLog.prompt_version_id.in_(version_ids),
        )
        .group_by(CallLog.prompt_version_id)
    )

    version_stats: dict[int, dict] = {}
    for row in result.all():
        vid = row.prompt_version_id
        total = row.call_count or 0
        completed = row.completed_count or 0
        version_stats[vid] = {
            "call_count": total,
            "avg_duration_secs": round(row.avg_duration or 0, 1),
            "avg_quality_score": round(row.avg_quality or 0, 1),
            "completion_rate": round(completed / total * 100, 1) if total else 0,
        }

    # Build version list with stats
    versions_out = []
    for v in versions:
        stats = version_stats.get(v.id, {
            "call_count": 0,
            "avg_duration_secs": 0,
            "avg_quality_score": 0,
            "completion_rate": 0,
        })
        versions_out.append({
            "version_id": v.id,
            "version_number": v.version,
            "is_active": v.is_active,
            "traffic_percentage": v.traffic_percentage,
            **stats,
        })

    return {
        "agent_id": agent_id,
        "agent_name": agent.name,
        "period_days": days,
        "versions": versions_out,
    }


@router.post("/quality/flag/{call_id}")
async def flag_call_for_review(
    call_id: int,
    reason: str = Query(default="manual_review", max_length=100),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually flag or unflag a call for review."""
    result = await db.execute(
        select(CallLog).where(CallLog.id == call_id, CallLog.user_id == user.id)
    )
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(404, "Call not found")

    call.review_flag = not call.review_flag
    call.review_reason = reason if call.review_flag else None
    await db.commit()

    return {
        "call_id": call_id,
        "review_flag": call.review_flag,
        "review_reason": call.review_reason,
    }
