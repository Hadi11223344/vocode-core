"""
Voice Platform — Call Log API Routes
=======================================

Endpoints for viewing call history, transcripts, and managing active calls.

Routes:
    GET  /api/calls            — List calls with pagination/filtering
    GET  /api/calls/active     — List currently active calls
    GET  /api/calls/{id}       — Get call details with transcript
    POST /api/calls/{id}/end   — Force-end an active call
"""

import asyncio
import json
from datetime import datetime, timezone  # For date filtering
from typing import Optional  # For optional query params

from fastapi import APIRouter, Depends, HTTPException, Query  # Routing + query params
from loguru import logger  # Logging
from pydantic import BaseModel, Field
from sqlalchemy import func, select  # Database query building
from sqlalchemy.ext.asyncio import AsyncSession  # Async DB session

from voice_platform.database import ActionLog, Agent, CallLog, Transcript, User, get_db
from voice_platform.errors import AppError, NotFoundError, ValidationError
from voice_platform.middleware.auth_middleware import get_current_user

# Create router
router = APIRouter(prefix="/api/calls", tags=["Call Logs"])


async def _safe_bg_task(name: str, coro):
    """Wrap a background task so exceptions are logged instead of silently lost."""
    try:
        await coro
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Background task '{name}' failed: {type(e).__name__}: {e}")


@router.get("")
async def list_calls(
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(default=None, description="Filter by status"),
    agent_id: Optional[int] = Query(default=None, description="Filter by agent"),
    team_id: Optional[int] = Query(default=None, description="Filter by team"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List call history with pagination and optional filtering.

    GAP-06: When team_id is provided and user is a team member,
    returns calls for the team. Otherwise returns only the user's calls.
    """
    from voice_platform.rbac import get_team_membership

    # Determine scope: team or personal
    if team_id:
        user_id: int = user.id  # type: ignore[assignment]
        membership = await get_team_membership(user_id, team_id)
        if membership:
            query = select(CallLog).where(CallLog.agent_id.in_(
                select(Agent.id).where(Agent.team_id == team_id)
            ))
            count_query = select(func.count(CallLog.id)).where(
                CallLog.agent_id.in_(
                    select(Agent.id).where(Agent.team_id == team_id)
                )
            )
        else:
            query = select(CallLog).where(CallLog.user_id == user.id)
            count_query = select(func.count(CallLog.id)).where(CallLog.user_id == user.id)
    else:
        query = select(CallLog).where(CallLog.user_id == user.id)
        count_query = select(func.count(CallLog.id)).where(CallLog.user_id == user.id)
    
    # Apply optional filters
    _VALID_STATUSES = {"active", "completed", "failed", "ringing", "initiated", "busy", "no-answer", "canceled"}
    if status is not None:
        if status not in _VALID_STATUSES:
            raise HTTPException(400, f"Invalid status '{status}'. Must be one of: {sorted(_VALID_STATUSES)}")
        query = query.where(CallLog.status == status)
        count_query = count_query.where(CallLog.status == status)
    if agent_id is not None:
        query = query.where(CallLog.agent_id == agent_id)
        count_query = count_query.where(CallLog.agent_id == agent_id)
    
    # Get total count for pagination metadata
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination:
    # OFFSET = (page - 1) * per_page: skip items from previous pages
    # LIMIT = per_page: only return this many items
    offset = (page - 1) * per_page
    query = query.order_by(CallLog.started_at.desc()).offset(offset).limit(per_page)
    
    # Execute the query
    result = await db.execute(query)
    calls = result.scalars().all()
    
    return {
        "calls": [call.to_dict() for call in calls],
        "total": total,         # Total matching records
        "page": page,           # Current page
        "per_page": per_page,   # Items per page
        "pages": (total + per_page - 1) // per_page,  # Total pages (ceiling division)
    }


@router.get("/active")
async def list_active_calls(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all currently active (ongoing) calls.
    
    Includes calls with status 'active', 'ringing', or 'initiated'
    (any live/in-progress call).
    Useful for the dashboard to show live call monitoring.
    
    Returns:
        List of active call objects
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
    
    return {"active_calls": [call.to_dict() for call in calls]}


@router.get("/{call_id}")
async def get_call_detail(
    call_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get full details of a specific call, including transcript and actions.
    
    This is the detail view — returns the complete conversation
    transcript (every message) and all actions that were executed.
    
    Args:
        call_id: Database ID of the call
        user: Authenticated user
        db: Database session
        
    Returns:
        Call metadata + full transcript array + action logs
        
    Raises:
        404: If call not found or doesn't belong to user
    """
    # Find the call with ownership check
    result = await db.execute(
        select(CallLog).where(CallLog.id == call_id, CallLog.user_id == user.id)
    )
    call = result.scalar_one_or_none()
    
    if call is None:
        raise NotFoundError(resource="Call", resource_id=call_id)

    # Get transcript messages ordered by timestamp
    transcript_result = await db.execute(
        select(Transcript)
        .where(Transcript.call_log_id == call_id)
        .order_by(Transcript.timestamp.asc())
    )
    transcripts = transcript_result.scalars().all()
    
    # Get action logs ordered by timestamp
    action_result = await db.execute(
        select(ActionLog)
        .where(ActionLog.call_log_id == call_id)
        .order_by(ActionLog.timestamp.asc())
    )
    actions = action_result.scalars().all()
    
    return {
        "call": call.to_dict(),
        "transcript": [t.to_dict() for t in transcripts],
        "actions": [a.to_dict() for a in actions],
    }


@router.get("/{call_id}/tools")
async def get_call_tool_traces(
    call_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get detailed tool call traces for a specific call.

    Returns all action logs with parsed params/results, tool names,
    latency, and error information for debugging and analytics.
    """
    result = await db.execute(
        select(CallLog).where(CallLog.id == call_id, CallLog.user_id == user.id)
    )
    call = result.scalar_one_or_none()
    if call is None:
        raise NotFoundError(resource="Call", resource_id=call_id)

    action_result = await db.execute(
        select(ActionLog)
        .where(ActionLog.call_log_id == call_id)
        .order_by(ActionLog.timestamp.asc())
    )
    actions = action_result.scalars().all()

    tool_traces = []
    for a in actions:
        trace = a.to_dict()
        try:
            trace["params"] = json.loads(a.params_json) if a.params_json else None
        except (json.JSONDecodeError, TypeError):
            trace["params"] = a.params_json
        try:
            trace["result"] = json.loads(a.result_json) if a.result_json else None
        except (json.JSONDecodeError, TypeError):
            trace["result"] = a.result_json
        tool_traces.append(trace)

    total = len(tool_traces)
    errors = sum(1 for t in tool_traces if t.get("is_error"))
    avg_latency = (
        round(sum(t["latency_ms"] for t in tool_traces if t.get("latency_ms")) / max(1, total), 1)
        if any(t.get("latency_ms") for t in tool_traces)
        else None
    )

    return {
        "call_id": call_id,
        "conversation_id": call.conversation_id,
        "tool_traces": tool_traces,
        "summary": {
            "total_calls": total,
            "errors": errors,
            "success_rate": round((total - errors) / max(1, total) * 100, 1) if total else None,
            "avg_latency_ms": avg_latency,
        },
    }


@router.get("/{call_id}/recording")
async def get_call_recording(
    call_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch the call recording URL from Twilio for playback.

    Returns a redirect to the recording audio file if available.
    """
    result = await db.execute(
        select(CallLog).where(CallLog.id == call_id, CallLog.user_id == user.id)
    )
    call = result.scalar_one_or_none()
    if call is None:
        raise NotFoundError(resource="Call", resource_id=call_id)

    if not call.conversation_id:
        raise HTTPException(status_code=404, detail="No Twilio SID for this call")

    if call.recording_url:
        return {"recording_url": call.recording_url}

    try:
        from voice_platform.api.twilio_routes import _get_twilio_client
        client, account_sid, _, _ = await _get_twilio_client(user, db)

        recordings = await asyncio.to_thread(
            client.calls(call.conversation_id).recordings.list
        )

        if not recordings:
            raise NotFoundError(
                resource="Recording",
                message="No recording found for this call.",
                suggestion="Recordings may take a few moments to process after a call ends.",
            )

        # Return the most recent recording URL
        rec = recordings[0]
        # rec.uri is a RELATIVE API path like /2010-04-01/Accounts/.../Recordings/RE....json
        # It is NOT a playable audio URL. Construct the full media URL from the SID.
        media_url = (
            f"https://api.twilio.com/2010-04-01/Accounts/"
            f"{account_sid}/Recordings/{rec.sid}.mp3"
        )
        return {
            "recording_url": media_url,
            "duration_secs": rec.duration,
            "sid": rec.sid,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch recording: {e}")
        raise HTTPException(500, f"Failed to fetch recording: {str(e)}")


@router.post("/{call_id}/end")
async def end_call(
    call_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Force-end an active call.

    Updates the call status to 'completed' and sets the end time.
    Also signals Twilio to hang up the live call.

    Args:
        call_id: Database ID of the call to end
        user: Authenticated user
        db: Database session

    Returns:
        Updated call object

    Raises:
        404: If call not found
        400: If call is not currently active
    """
    # Find the call with ownership check
    result = await db.execute(
        select(CallLog).where(CallLog.id == call_id, CallLog.user_id == user.id)
    )
    call = result.scalar_one_or_none()
    
    if call is None:
        raise NotFoundError(resource="Call", resource_id=call_id)

    if call.status in ("completed", "failed"):
        raise HTTPException(status_code=400, detail=f"Call is already {call.status}")
    
    # Update call status
    call.status = "completed"  # type: ignore[assignment]
    call.ended_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    
    # Calculate duration
    if call.started_at:
        # SQLite strips timezone info, so normalize both to naive UTC for subtraction
        ended = call.ended_at.replace(tzinfo=None) if call.ended_at.tzinfo else call.ended_at
        started = call.started_at.replace(tzinfo=None) if call.started_at.tzinfo else call.started_at
        duration = (ended - started).total_seconds()
        call.duration_secs = duration
    
    await db.commit()
    await db.refresh(call)

    # Phase 6: Evaluate alert rules after call ends
    try:
        from voice_platform.api.alert_routes import evaluate_alert_rule
        from voice_platform.database import AlertRule, async_session

        async def _eval_alerts():
            async with async_session() as alert_db:
                rules_result = await alert_db.execute(
                    select(AlertRule).where(
                        AlertRule.user_id == user.id,
                        AlertRule.is_active == True,
                    )
                )
                for rule in rules_result.scalars().all():
                    await evaluate_alert_rule(rule, alert_db)

        asyncio.create_task(_safe_bg_task("alert_evaluation", _eval_alerts()))
    except Exception as e:
        logger.warning(f"Alert evaluation failed after call end: {e}")

    # Phase 7: Log usage metrics after call ends
    try:
        from voice_platform.api.usage_routes import (
            estimate_llm_cost,
            estimate_stt_cost,
            estimate_telephony_cost,
            estimate_tts_cost,
        )
        from voice_platform.database import Agent as _Agent
        from voice_platform.database import UsageLog, async_session

        async def _log_usage():
            for attempt in range(3):
                try:
                    async with async_session() as usage_db:
                        # Deduplication: skip if usage already logged for this call
                        dup_check = await usage_db.execute(
                            select(UsageLog).where(UsageLog.call_id == call.id)
                        )
                        if dup_check.scalar_one_or_none():
                            logger.info(f"Usage already logged for call {call.id}, skipping duplicate")
                            return

                        # Fetch agent config
                        agent_result = await usage_db.execute(
                            select(_Agent).where(_Agent.id == call.agent_id)
                        )
                        agent = agent_result.scalar_one_or_none()

                        # Count transcript messages for token estimation
                        transcript_result = await usage_db.execute(
                            select(Transcript).where(Transcript.call_log_id == call.id)
                        )
                        messages = transcript_result.scalars().all()
                        human_text = "\n".join(m.message for m in messages if m.sender == "human")
                        bot_text = "\n".join(m.message for m in messages if m.sender == "bot")

                        # TEL-06: Use tiktoken for accurate token count when available
                        def _count_tokens(text: str, model: str | None) -> int:
                            try:
                                import tiktoken
                                enc = tiktoken.encoding_for_model(model or "gpt-4o-mini")
                                return len(enc.encode(text))
                            except Exception:
                                # Fallback: ~4 chars per token
                                return max(1, len(text) // 4)

                        input_tokens = _count_tokens(human_text, agent.llm_model if agent else None)
                        output_tokens = _count_tokens(bot_text, agent.llm_model if agent else None)
                        tts_chars = len(bot_text)
                        duration = call.duration_secs or 0

                        llm_cost = estimate_llm_cost(
                            agent.llm_model if agent else None, input_tokens, output_tokens
                        )
                        stt_cost = estimate_stt_cost(
                            agent.stt_provider if agent else None, duration,
                            agent.stt_model if agent else None,
                        )
                        tts_cost = estimate_tts_cost(
                            agent.tts_provider if agent else None, tts_chars
                        )
                        tel_cost = estimate_telephony_cost(
                            call.direction or "inbound", duration
                        )

                        usage = UsageLog(
                            user_id=user.id,
                            call_id=call.id,
                            agent_id=call.agent_id,
                            llm_provider=agent.llm_provider if agent else None,
                            llm_model=agent.llm_model if agent else None,
                            stt_provider=agent.stt_provider if agent else None,
                            tts_provider=agent.tts_provider if agent else None,
                            duration_seconds=duration,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            stt_seconds=duration,
                            tts_characters=tts_chars,
                            estimated_cost_usd=round(llm_cost + stt_cost + tts_cost + tel_cost, 6),
                        )
                        usage_db.add(usage)
                        await usage_db.commit()
                    return  # Success — exit retry loop
                except Exception as exc:
                    if attempt < 2:
                        logger.warning(f"Usage log attempt {attempt + 1} failed for call {call.id}: {exc}")
                        await asyncio.sleep(2)
                    else:
                        logger.error(f"Usage log failed after 3 attempts for call {call.id}: {exc}")

        asyncio.create_task(_safe_bg_task("usage_logging", _log_usage()))
    except Exception as e:
        logger.warning(f"Usage logging failed after call end: {e}")

    # Signal Twilio to actually hang up the live call
    try:
        from voice_platform.api.twilio_routes import _get_twilio_client
        twilio_client, _, _, _ = await _get_twilio_client(user, db, allow_platform_fallback=True)
        # BUG-5: Use twilio_call_sid (the actual Twilio SID) for the Twilio API
        # call, not conversation_id which may be a non-SID identifier.
        twilio_sid = call.twilio_call_sid or call.conversation_id
        await asyncio.to_thread(
            twilio_client.calls(twilio_sid).update,
            status="completed",
        )
        logger.info(f"Signalled Twilio to end call {twilio_sid}")
    except Exception as e:
        # Log but don't fail — DB state is already updated
        logger.warning(f"Could not signal Twilio to end call: {e}")
    
    return {"call": call.to_dict(), "message": "Call ended successfully"}
