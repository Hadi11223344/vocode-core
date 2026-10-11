"""
Voice Platform — Scheduled Call API Routes
==========================================

CRUD for individually scheduled outbound phone calls.
A background scheduler (in main.py lifespan) picks up pending calls
and executes them via Twilio at their scheduled_at time.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.config import settings
from voice_platform.database import Agent, CallLog, ScheduledCall, UserApiKey, async_session, get_db
from voice_platform.errors import AgentNotFoundError, NotFoundError, ValidationError
from voice_platform.middleware.auth_middleware import get_current_user

router = APIRouter(prefix="/api/schedule", tags=["Scheduled Calls"])
EXECUTING_STALE_TIMEOUT = timedelta(hours=2)

# O-4: Cache from_phone per Twilio account SID to avoid repeated API lookups.
# Maps: twilio_sid -> (phone_number, timestamp). TTL: 5 minutes.
_from_phone_cache: dict[str, tuple[str, float]] = {}


# ── Request/Response Schemas ───────────────────────────────────

class CreateScheduledCallRequest(BaseModel):
    agent_id: int = Field(..., description="Agent to use for the call")
    contact_name: Optional[str] = Field(None, description="Name of the contact")
    phone_number: str = Field(..., pattern=r"^\+[1-9]\d{1,14}$", description="E.164 phone number")
    scheduled_at: datetime = Field(..., description="When to place the call (ISO 8601)")
    timezone: str = Field(default="UTC", description="Timezone for display (e.g. America/New_York)")
    recurrence: str = Field(default="none", description="none, daily, weekly, monthly")
    from_phone: Optional[str] = Field(None, pattern=r"^\+[1-9]\d{1,14}$", description="Override caller ID")


class UpdateScheduledCallRequest(BaseModel):
    contact_name: Optional[str] = None
    phone_number: Optional[str] = Field(None, pattern=r"^\+[1-9]\d{1,14}$")
    scheduled_at: Optional[datetime] = None
    timezone: Optional[str] = None
    recurrence: Optional[str] = None
    from_phone: Optional[str] = Field(None, pattern=r"^\+[1-9]\d{1,14}$")
    status: Optional[str] = None  # For cancelling: set to "cancelled"


# ── Routes ──────────────────────────────────────────────────────

@router.get("")
async def list_scheduled_calls(
    status: Optional[str] = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List scheduled calls for the current user."""
    query = select(ScheduledCall).where(ScheduledCall.user_id == user.id)
    if status:
        query = query.where(ScheduledCall.status == status)
    query = query.order_by(ScheduledCall.scheduled_at.desc())
    result = await db.execute(query)
    items = result.scalars().all()
    return {"scheduled_calls": [sc.to_dict() for sc in items]}


@router.get("/{call_id}")
async def get_scheduled_call(
    call_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single scheduled call."""
    result = await db.execute(
        select(ScheduledCall).where(
            ScheduledCall.id == call_id,
            ScheduledCall.user_id == user.id,
        )
    )
    sc = result.scalar_one_or_none()
    if not sc:
        raise NotFoundError(resource="Scheduled call", resource_id=call_id)
    return {"scheduled_call": sc.to_dict()}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_scheduled_call(
    request: CreateScheduledCallRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Schedule a future outbound phone call."""
    # Validate agent ownership
    agent_result = await db.execute(
        select(Agent).where(Agent.id == request.agent_id, Agent.user_id == user.id)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise AgentNotFoundError(request.agent_id)

    # Ensure scheduled time is in the future
    if request.scheduled_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise ValidationError(
            field="scheduled_at",
            message="Scheduled time must be in the future.",
            suggestion="Pick a date and time that is at least a few minutes from now.",
        )

    sc = ScheduledCall(
        user_id=user.id,
        agent_id=request.agent_id,
        contact_name=request.contact_name,
        phone_number=request.phone_number,
        scheduled_at=request.scheduled_at,
        timezone=request.timezone,
        recurrence=request.recurrence,
        from_phone=request.from_phone,
        status="pending",
    )
    db.add(sc)
    await db.commit()
    await db.refresh(sc)
    return {"scheduled_call": sc.to_dict(), "message": "Call scheduled"}


@router.put("/{call_id}")
async def update_scheduled_call(
    call_id: int,
    request: UpdateScheduledCallRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a scheduled call. Can be used to cancel (status -> cancelled)."""
    result = await db.execute(
        select(ScheduledCall).where(
            ScheduledCall.id == call_id,
            ScheduledCall.user_id == user.id,
        )
    )
    sc = result.scalar_one_or_none()
    if not sc:
        raise NotFoundError(resource="Scheduled call", resource_id=call_id)

    # Only allow updates on pending calls
    if sc.status not in ("pending", "failed"):
        raise ValidationError(
            field="status",
            message=f"Cannot update scheduled call with status '{sc.status}'.",
            suggestion="Only pending or failed scheduled calls can be updated.",
        )

    if request.contact_name is not None:
        sc.contact_name = request.contact_name
    if request.phone_number is not None:
        sc.phone_number = request.phone_number
    if request.scheduled_at is not None:
        sc.scheduled_at = request.scheduled_at
    if request.timezone is not None:
        sc.timezone = request.timezone
    if request.recurrence is not None:
        sc.recurrence = request.recurrence
    if request.from_phone is not None:
        sc.from_phone = request.from_phone
    if request.status is not None:
        sc.status = request.status

    await db.commit()
    await db.refresh(sc)
    return {"scheduled_call": sc.to_dict(), "message": "Scheduled call updated"}


@router.delete("/{call_id}")
async def delete_scheduled_call(
    call_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a scheduled call."""
    result = await db.execute(
        select(ScheduledCall).where(
            ScheduledCall.id == call_id,
            ScheduledCall.user_id == user.id,
        )
    )
    sc = result.scalar_one_or_none()
    if not sc:
        raise NotFoundError(resource="Scheduled call", resource_id=call_id)
    await db.delete(sc)
    await db.commit()
    return {"message": "Scheduled call deleted"}


# ── Scheduler Helper ───────────────────────────────────────────

async def execute_pending_scheduled_calls():
    """
    Background task: find and execute scheduled calls whose time has come.

    Called periodically from main.py lifespan.  Uses the same Twilio
    outbound path as the manual outbound-call endpoint.
    """
    try:
        async with async_session() as db:
            now = datetime.now(timezone.utc)
            stale_cutoff = now - EXECUTING_STALE_TIMEOUT
            stale_result = await db.execute(
                select(ScheduledCall).where(
                    ScheduledCall.status == "executing",
                    ScheduledCall.updated_at <= stale_cutoff,
                )
            )
            stale_calls = stale_result.scalars().all()
            if stale_calls:
                for sc in stale_calls:
                    sc.status = "failed"
                    sc.last_error = (
                        "Scheduled call timed out waiting for the completion callback."
                    )
                    sc.retry_count = (sc.retry_count or 0) + 1
                await db.commit()
                logger.warning(
                    f"Reaped {len(stale_calls)} stale executing scheduled calls older than {EXECUTING_STALE_TIMEOUT}."
                )

            result = await db.execute(
                select(ScheduledCall)
                .where(
                    ScheduledCall.status == "pending",
                    ScheduledCall.scheduled_at <= now,
                )
                .order_by(ScheduledCall.scheduled_at.asc())
            )
            pending = result.scalars().all()

            for sc in pending:
                sc_id = sc.id
                try:
                    sc.status = "executing"
                    await db.commit()
                except Exception as e:
                    logger.error(f"Failed to mark scheduled call #{sc_id} as executing: {e}")
                    continue

                try:
                    async with async_session() as call_db:
                        fresh_sc = await call_db.get(ScheduledCall, sc_id)
                        if not fresh_sc:
                            continue
                        await _execute_single_call(call_db, fresh_sc)
                except Exception as e:
                    logger.error(f"Scheduled call #{sc_id} failed: {e}")
                    try:
                        async with async_session() as err_db:
                            err_sc = await err_db.get(ScheduledCall, sc_id)
                            if err_sc:
                                err_sc.status = "failed"
                                err_sc.last_error = str(e)[:500]
                                err_sc.retry_count = (err_sc.retry_count or 0) + 1
                                await err_db.commit()
                    except Exception:
                        pass

            if len(pending) > 0:
                logger.info(f"ScheduledCall scheduler: executed {len(pending)} calls")
    except Exception as e:
        logger.error(f"ScheduledCall scheduler loop error: {e}")


async def _execute_single_call(db: AsyncSession, sc: ScheduledCall):
    """Place a single Twilio outbound call for a ScheduledCall record."""
    from twilio.rest import Client

    from voice_platform.api.telephony_utils import resolve_public_base_url
    from voice_platform.compliance import validate_call_eligibility
    from voice_platform.telephony.outbound_throttle import OutboundCallThrottler

    # Resolve Twilio credentials
    twilio_sid, twilio_token = None, None
    user_key_result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == sc.user_id,
            UserApiKey.service == "twilio",
            UserApiKey.is_active == True,
        )
    )
    user_key = user_key_result.scalar_one_or_none()
    if user_key:
        from voice_platform.encryption import decrypt
        twilio_sid = decrypt(user_key.api_key)
        twilio_token = decrypt(user_key.api_secret) if user_key.api_secret else None
    else:
        # BUG-11: Only fall back to platform Twilio credentials if the
        # platform explicitly allows it — don't silently use platform creds.
        if settings.allow_platform_twilio_fallback_for_campaigns:
            twilio_sid = settings.twilio_account_sid
            twilio_token = settings.twilio_auth_token
        else:
            raise ValueError(
                "No user Twilio credentials and platform fallback disabled"
            )

    if not twilio_sid or not twilio_token:
        raise ValueError("No Twilio credentials available")

    # BUG-10: Compliance check BEFORE throttle — don't waste rate limit
    # tokens on calls that will be rejected for DNC or calling hours.
    await validate_call_eligibility(
        sc.phone_number,
        user_id=sc.user_id,
        campaign_type="informational",
        require_consent=False,
    )

    # Throttle
    throttler = OutboundCallThrottler()
    if not await throttler.acquire(user_id=sc.user_id, max_cps=1):
        raise ValueError("Outbound rate limit exceeded")

    # B2: Verify the agent is configured for outbound calls
    if sc.agent_id:
        agent_result = await db.execute(
            select(Agent).where(Agent.id == sc.agent_id)
        )
        agent_obj = agent_result.scalar_one_or_none()
        if agent_obj and not agent_obj.outbound_ready:
            raise ValueError(
                f"Agent '{agent_obj.name}' is not configured for outbound calls. "
                "Enable 'Outbound Ready' in agent settings."
            )

    client = Client(twilio_sid, twilio_token)

    # O-4: Cache from_phone per Twilio account to avoid repeated API calls.
    # Cache for 5 minutes — phone numbers don't change mid-batch.
    import time as _time
    cache_key = twilio_sid
    cached = _from_phone_cache.get(cache_key)
    if cached and _time.time() - cached[1] < 300:
        from_phone = cached[0]
    else:
        from_phone = sc.from_phone
        if not from_phone:
            numbers = await __import__("asyncio").to_thread(
                lambda: list(client.incoming_phone_numbers.list(limit=1))
            )
            if numbers:
                from_phone = numbers[0].phone_number
        if from_phone:
            _from_phone_cache[cache_key] = (from_phone, _time.time())

    if not from_phone:
        raise ValueError("No from_phone available")

    # BUG-19: resolve_public_base_url can raise HTTPException in a background
    # task where it won't be caught by FastAPI's exception handler.
    try:
        public_base_url = resolve_public_base_url(None, settings.base_url)
    except Exception as e:
        logger.error(f"Scheduled call #{sc.id}: failed to resolve public base URL: {e}")
        raise ValueError(f"Failed to resolve public base URL: {e}")
    voice_url = f"https://{public_base_url}/inbound_call"
    status_url = f"https://{public_base_url}/call_status"
    recording_status_url = f"https://{public_base_url}/api/twilio/recording-status"

    twilio_call = await __import__("asyncio").to_thread(
        client.calls.create,
        to=sc.phone_number,
        from_=from_phone,
        url=voice_url,
        method="POST",
        status_callback=status_url,
        status_callback_method="POST",
        status_callback_event=["initiated", "ringing", "answered", "completed"],
        record=True,
        recording_status_callback=recording_status_url,
        recording_status_callback_event=["completed"],
        timeout=60,
    )

    # Create CallLog — use raw Twilio SID so /call_status and /inbound_call
    # webhooks can look it up by CallSid (same as manual outbound calls).
    call_log = CallLog(
        conversation_id=twilio_call.sid,
        twilio_call_sid=twilio_call.sid,
        agent_id=sc.agent_id,
        user_id=sc.user_id,
        from_phone=from_phone,
        to_phone=sc.phone_number,
        direction="outbound",
        status="initiated",
        started_at=datetime.now(timezone.utc),
    )
    db.add(call_log)
    await db.flush()

    sc.call_log_id = call_log.id
    await db.commit()

    logger.info(
        f"Scheduled call #{sc.id} executed: {from_phone} -> {sc.phone_number} (SID: {twilio_call.sid})"
    )
