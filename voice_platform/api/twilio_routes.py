"""
Voice Platform — Twilio Management API Routes
================================================

Endpoints for the frontend to manage Twilio resources:
- List available phone numbers
- Get current phone number
- Purchase/release phone numbers
- Configure webhook URLs
- Initiate outbound calls

All endpoints use the user's Twilio credentials from user_api_keys.
If no user-level Twilio credentials exist, falls back to platform defaults.
"""

import json
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from voice_platform.api.telephony_utils import resolve_public_base_url
from voice_platform.config import settings
from voice_platform.database import CallLog, UsageLog, User, UserApiKey, get_db
from voice_platform.encryption import decrypt
from voice_platform.middleware.auth_middleware import get_current_user

router = APIRouter(prefix="/api/twilio", tags=["Twilio"])

# BIL-04: Plan-based monthly call limits
_PLAN_LIMITS = {
    "free": 100,
    "pro": 1000,
    "enterprise": None,  # unlimited
}


async def _check_call_quota(user: User, db: AsyncSession) -> None:
    """Raise HTTPException(429) if user has exceeded their monthly call quota."""
    plan = getattr(user, "plan", "free") or "free"
    limit = _PLAN_LIMITS.get(plan)
    if limit is None:
        return  # unlimited

    # Count calls initiated this month
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.count(CallLog.id))
        .where(
            CallLog.user_id == user.id,
            CallLog.direction == "outbound",
            CallLog.started_at >= month_start,
        )
    )
    count = result.scalar() or 0
    if count >= limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Monthly outbound call limit reached ({limit}/{limit}). "
            f"Upgrade your plan to make more calls.",
        )


def _safe_twilio_error(e: Exception, action: str) -> str:
    """Create a user-friendly error message from a Twilio exception."""
    import re as _re_inner
    msg = str(e)
    # Log raw error for diagnostics (never exposed to frontend)
    logger.warning(f"Raw Twilio error [{action}]: {msg[:300]}")

    # Specific Twilio error patterns — codes first for precision
    if "21201" in msg or "invalid phone" in msg.lower():
        return "Invalid phone number format. Use E.164 format (e.g. +12025551234)."
    # 21214: not a valid number  |  21215: geo permission / not reachable
    if "21215" in msg or "geo permission" in msg.lower() or "not reachable" in msg.lower():
        return "Calls to this country are not enabled. Enable geo permissions in your Twilio console (https://console.twilio.com/us1/develop/voice/settings/geo-permissions)."
    if "21214" in msg or "not a valid" in msg.lower():
        return "This phone number is not valid or cannot be reached. If the format looks correct, it may be a geo-permission issue — enable the country in your Twilio console."
    if "21610" in msg.lower():
        return "This number has been blocked or opted out."
    if "20003" in msg or "authenticate" in msg.lower():
        return "Twilio authentication failed. Check your Account SID and Auth Token in API Keys."
    if "20404" in msg or "not found" in msg.lower():
        return "Resource not found in Twilio. It may have been already deleted."
    if "21608" in msg:
        return "This number is not owned by your Twilio account."
    if "insufficient" in msg.lower() or "balance" in msg.lower():
        return "Insufficient Twilio account balance. Please top up your account."
    # Scrub secrets from generic messages
    safe = _re_inner.sub(r'AC[a-f0-9]{32}', '[ACCOUNT]', msg)
    safe = _re_inner.sub(r'SK[a-f0-9]{32}', '[KEY]', safe)
    safe = _re_inner.sub(r'[a-f0-9]{32}', '', safe)
    return f"Failed to {action}: {safe[:150].strip()}"


# ── Request Schemas ────────────────────────────────────────────────────

class SearchNumbersRequest(BaseModel):
    country: str = Field(default="US", description="Country code (US, GB, etc.)")
    area_code: Optional[str] = Field(None, description="Filter by area code")
    contains: Optional[str] = Field(None, description="Search for numbers containing this string")
    limit: int = Field(default=10, ge=1, le=20)


import re as _re

# E.164 phone number regex: + followed by 1-15 digits
_E164_PATTERN = _re.compile(r"^\+[1-9]\d{1,14}$")

def _validate_e164(phone: str, field_name: str = "phone_number"):
    """Raise HTTPException if phone number is not valid E.164 format."""
    if not _E164_PATTERN.match(phone):
        raise HTTPException(
            400,
            f"Invalid {field_name}: must be E.164 format (e.g. +12025551234). Got: {phone}"
        )


class PurchaseNumberRequest(BaseModel):
    phone_number: str = Field(..., pattern=r"^\+[1-9]\d{1,14}$", description="Phone number to purchase (E.164 format)")


class ConfigureWebhookRequest(BaseModel):
    phone_number_sid: str = Field(..., pattern=r"^PN[a-f0-9]{32}$", description="Twilio Phone Number SID (PN...)")
    voice_url: Optional[str] = Field(None, description="URL for incoming voice calls")
    status_callback: Optional[str] = Field(None, description="URL for call status updates")


class OutboundCallRequest(BaseModel):
    to_phone: str = Field(..., pattern=r"^\+[1-9]\d{1,14}$", description="Destination phone number (E.164)")
    agent_id: Optional[int] = Field(None, description="Agent to use for this call (null=default)")
    from_phone: Optional[str] = Field(None, pattern=r"^\+[1-9]\d{1,14}$", description="Override caller ID (null=use configured)")


# ── Helpers ────────────────────────────────────────────────────────────

async def _get_twilio_client(
    user: User,
    db: AsyncSession,
    *,
    allow_platform_fallback: bool | None = None,
):
    """
    Get a Twilio client using the user's credentials, or fallback to platform defaults.
    
    Returns:
        (client, account_sid, auth_token, phone_number)
    """
    if allow_platform_fallback is None:
        allow_platform_fallback = settings.allow_platform_twilio_fallback
    
    # Try user's Twilio credentials first
    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user.id,
            UserApiKey.service == "twilio",
            UserApiKey.is_active == True,
        )
    )
    user_key = result.scalar_one_or_none()
    
    account_sid = None
    auth_token = None
    phone_number = None

    if user_key:
        account_sid = decrypt(user_key.api_key)  # SID stored as api_key
        auth_token = decrypt(user_key.api_secret)
        metadata = {}
        if user_key.metadata_json:
            try:
                metadata = json.loads(user_key.metadata_json)
            except json.JSONDecodeError:
                pass
        phone_number = metadata.get("phone_number")

    # Fallback to platform defaults only when explicitly allowed.
    elif allow_platform_fallback:
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            raise HTTPException(
                400,
                "No Twilio credentials configured. Add your Twilio keys at /api/keys"
            )
        account_sid = settings.twilio_account_sid
        auth_token = settings.twilio_auth_token
        phone_number = settings.twilio_phone_number
    else:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "User Twilio credentials are required for this action. Add your Twilio keys at /api/keys.",
        )

    try:
        from twilio.rest import Client
    except ImportError:
        raise HTTPException(
            500,
            "Twilio SDK not installed. Run: pip install twilio"
        )

    client = Client(account_sid, auth_token)
    return client, account_sid, auth_token, phone_number


# ── Routes ─────────────────────────────────────────────────────────────

@router.get("/status")
async def twilio_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check Twilio connection status and return the configured phone number.
    """
    try:
        client, account_sid, _, phone_number = await _get_twilio_client(user, db)
        
        # Verify credentials by fetching account info
        # Wrap sync Twilio SDK call in thread to avoid blocking the event loop
        import asyncio
        account = await asyncio.to_thread(client.api.accounts(account_sid).fetch)
        
        return {
            "connected": True,
            "account_sid": account_sid[:6] + "..." + account_sid[-4:],
            "account_name": account.friendly_name,
            "phone_number": phone_number,
            "status": account.status,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Twilio status check failed: {e}")
        return {
            "connected": False,
            "error": _safe_twilio_error(e, "check Twilio status"),
        }


@router.get("/numbers")
async def list_phone_numbers(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all phone numbers owned by the user's Twilio account.
    """
    try:
        client, account_sid, _, _ = await _get_twilio_client(user, db)
        
        import asyncio
        incoming_numbers = await asyncio.to_thread(client.incoming_phone_numbers.list, limit=50)
        
        numbers = []
        for num in incoming_numbers:
            numbers.append({
                "sid": num.sid,
                "phone_number": num.phone_number,
                "friendly_name": num.friendly_name,
                "voice_url": num.voice_url,
                "status_callback": num.status_callback,
                "capabilities": {
                    "voice": num.capabilities.get("voice", False),
                    "sms": num.capabilities.get("sms", False),
                },
            })
        
        return {"numbers": numbers}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list Twilio numbers: {e}")
        raise HTTPException(500, _safe_twilio_error(e, "list phone numbers"))


@router.post("/numbers/search")
async def search_available_numbers(
    request: SearchNumbersRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Search for available phone numbers to purchase.
    """
    try:
        client, _, _, _ = await _get_twilio_client(user, db)
        
        kwargs = {"limit": request.limit}
        if request.area_code:
            kwargs["area_code"] = request.area_code
        if request.contains:
            kwargs["contains"] = request.contains
        
        import asyncio
        available = await asyncio.to_thread(
            client.available_phone_numbers(request.country).local.list, **kwargs
        )
        
        numbers = []
        for num in available:
            numbers.append({
                "phone_number": num.phone_number,
                "friendly_name": num.friendly_name,
                "locality": num.locality,
                "region": num.region,
                "capabilities": {
                    "voice": num.capabilities.get("voice", False),
                    "sms": num.capabilities.get("sms", False),
                },
            })
        
        return {"available_numbers": numbers}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to search numbers: {e}")
        raise HTTPException(500, _safe_twilio_error(e, "search available numbers"))


@router.post("/numbers/purchase")
async def purchase_number(
    request: PurchaseNumberRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Purchase a phone number and configure it for the platform.
    """
    try:
        client, _, _, _ = await _get_twilio_client(user, db, allow_platform_fallback=False)
        
        import asyncio
        incoming_number = await asyncio.to_thread(
            client.incoming_phone_numbers.create,
            phone_number=request.phone_number,
        )
        
        return {
            "message": f"Purchased {incoming_number.phone_number}",
            "number": {
                "sid": incoming_number.sid,
                "phone_number": incoming_number.phone_number,
                "friendly_name": incoming_number.friendly_name,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to purchase number: {e}")
        raise HTTPException(500, _safe_twilio_error(e, "purchase phone number"))


@router.put("/numbers/webhook")
async def configure_webhook(
    request: ConfigureWebhookRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Configure webhook URLs for a phone number.
    This tells Twilio where to send incoming call notifications.
    """
    try:
        client, _, _, _ = await _get_twilio_client(user, db, allow_platform_fallback=False)
        
        update_kwargs = {}
        if request.voice_url:
            update_kwargs["voice_url"] = request.voice_url
            update_kwargs["voice_method"] = "POST"
        if request.status_callback:
            update_kwargs["status_callback"] = request.status_callback
            update_kwargs["status_callback_method"] = "POST"
        
        if not update_kwargs:
            raise HTTPException(400, "Provide at least one of: voice_url, status_callback")
        
        import asyncio
        number = await asyncio.to_thread(
            client.incoming_phone_numbers(request.phone_number_sid).update, **update_kwargs
        )
        
        return {
            "message": f"Updated webhooks for {number.phone_number}",
            "number": {
                "sid": number.sid,
                "phone_number": number.phone_number,
                "voice_url": number.voice_url,
                "status_callback": number.status_callback,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to configure webhook: {e}")
        raise HTTPException(500, _safe_twilio_error(e, "update webhook"))


@router.delete("/numbers/{phone_number_sid}")
async def release_number(
    phone_number_sid: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Release (delete) a phone number from the Twilio account.
    """
    try:
        client, _, _, _ = await _get_twilio_client(user, db, allow_platform_fallback=False)
        
        import asyncio
        await asyncio.to_thread(client.incoming_phone_numbers(phone_number_sid).delete)
        
        return {"message": f"Released phone number {phone_number_sid}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to release number: {e}")
        raise HTTPException(500, _safe_twilio_error(e, "release phone number"))


@router.get("/calls")
async def list_twilio_calls(
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List recent calls from the Twilio account (for debugging/monitoring).
    """
    try:
        client, _, _, _ = await _get_twilio_client(user, db)
        
        import asyncio
        calls = await asyncio.to_thread(client.calls.list, limit=min(limit, 50))
        
        call_list = []
        for call in calls:
            call_list.append({
                "sid": call.sid,
                "from": call.from_formatted,
                "to": call.to_formatted,
                "direction": call.direction,
                "status": call.status,
                "duration": call.duration,
                "start_time": str(call.start_time) if call.start_time else None,
                "end_time": str(call.end_time) if call.end_time else None,
            })
        
        return {"calls": call_list}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list calls: {e}")
        raise HTTPException(500, _safe_twilio_error(e, "list calls"))


@router.post("/calls/outbound")
async def initiate_outbound_call(
    request: OutboundCallRequest,
    req: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Initiate an outbound phone call via Twilio.

    The call is placed from the platform's (or user's) Twilio number to
    the specified destination.  Twilio will POST back to our /inbound_call
    webhook so the vocode pipeline handles the conversation.
    """
    try:
        # BIL-04: Enforce monthly outbound call quota before placing call
        await _check_call_quota(user, db)

        # Phase 1: Check DNC list before placing call
        from voice_platform.compliance import validate_call_eligibility
        await validate_call_eligibility(
            request.to_phone,
            user_id=user.id,  # type: ignore[arg-type]
            campaign_type="informational",
            require_consent=False,  # Single ad-hoc calls don't require explicit consent record
        )

        # Phase 2: Enforce outbound CPS rate limit before placing call
        from voice_platform.telephony.outbound_throttle import OutboundCallThrottler
        throttler = OutboundCallThrottler()
        if not await throttler.acquire(user_id=user.id, max_cps=1):  # type: ignore[arg-type]
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Outbound call rate limit exceeded. Please wait a moment and retry.",
            )

        # B1: Validate that the selected agent is configured for outbound calls
        from voice_platform.database import Agent
        agent_id = request.agent_id
        if not agent_id:
            result = await db.execute(
                select(Agent).where(Agent.user_id == user.id, Agent.is_active == True)
                .order_by(Agent.updated_at.desc()).limit(1)
            )
            agent_row = result.scalar_one_or_none()
            agent_id = agent_row.id if agent_row else None
        if agent_id:
            agent_result = await db.execute(select(Agent).where(Agent.id == agent_id))
            agent_obj = agent_result.scalar_one_or_none()
            if agent_obj and not agent_obj.outbound_ready:
                raise HTTPException(
                    400,
                    "Selected agent is not configured for outbound calls. "
                    "Enable 'Outbound Ready' in agent settings.",
                )

        client, account_sid, _, default_phone = await _get_twilio_client(
            user,
            db,
            allow_platform_fallback=False,
        )

        from_phone = request.from_phone or default_phone
        if not from_phone:
            raise HTTPException(
                400,
                "No caller ID available. Set a phone_number in your Twilio key metadata "
                "or provide from_phone in the request.",
            )

        public_base_url = resolve_public_base_url(
            getattr(req.app.state, "base_url", None),
            settings.base_url,
        )
        voice_url = f"https://{public_base_url}/inbound_call"
        status_url = f"https://{public_base_url}/call_status"

        logger.info(f"📞 Outbound call webhook URLs: voice={voice_url}, status={status_url}")

        import asyncio
        recording_status_url = f"https://{public_base_url}/api/twilio/recording-status"
        try:
            call = await asyncio.to_thread(
                client.calls.create,
                to=request.to_phone,
                from_=from_phone,
                url=voice_url,
                method="POST",
                status_callback=status_url,
                status_callback_method="POST",
                status_callback_event=["initiated", "ringing", "answered", "completed"],
                record=True,
                recording_status_callback=recording_status_url,
                recording_status_callback_event=["completed"],
                timeout=60,  # Ring for up to 60 seconds before giving up
                machine_detection="Enable",  # AMD: detect voicemail/machine on answer
            )
        except Exception as twilio_err:
            # O-2: Release the throttle token on Twilio failure so it's not wasted
            try:
                await throttler.release(user_id=user.id)  # type: ignore[arg-type]
            except Exception:
                pass
            logger.error(f"Twilio calls.create failed: {twilio_err}")
            raise HTTPException(502, _safe_twilio_error(twilio_err, "create Twilio call"))

        # Pre-create a CallLog entry for this outbound call
        from datetime import datetime
        from datetime import timezone as tz

        from voice_platform.database import CallLog

        log = CallLog(
            conversation_id=call.sid,
            twilio_call_sid=call.sid,
            from_phone=from_phone,
            to_phone=request.to_phone,
            agent_id=agent_id,
            user_id=user.id,
            direction="outbound",
            status="initiated",
            started_at=datetime.now(tz.utc),
        )
        db.add(log)
        await db.commit()

        logger.info(f"📞 Outbound call initiated: {from_phone} → {request.to_phone} (SID: {call.sid})")

        return {
            "message": f"Call initiated to {request.to_phone}",
            "call": {
                "sid": call.sid,
                "from": from_phone,
                "to": request.to_phone,
                "status": call.status,
                "direction": "outbound",
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to initiate outbound call: {e}")
        raise HTTPException(500, _safe_twilio_error(e, "initiate outbound call"))


# ── Call Transfer (Dial TwiML) ─────────────────────────────────────────

@router.post("/transfer/dial")
async def transfer_dial_twiML(
    request: Request,
):
    """Return TwiML <Dial> to transfer an active call to another number.

    Twilio POSTs here when redirecting an in-progress call.
    The 'To' form field contains the destination number.
    """
    from twilio.twiml.voice_response import Connect, Dial, VoiceResponse

    form = await request.form()
    # P1: Prefer query param (set by action_executor with actual transfer destination)
    # over form "To" (which is the original Twilio dialed number)
    destination = str(request.query_params.get("To", "")) or str(form.get("To", ""))
    conv_id = str(request.query_params.get("conversation_id", ""))

    if not destination:
        logger.warning("Transfer dial called without destination number")
        resp = VoiceResponse()
        resp.say("Unable to complete transfer. Destination not configured.")
        return Response(content=str(resp), media_type="application/xml")

    resp = VoiceResponse()

    # GAP-02: Brief announcement to the caller before connecting.
    # NOTE: Do NOT use <Play loop=0> here — Twilio processes TwiML sequentially,
    # so an infinite <Play> would block the <Dial> from ever executing.
    resp.say("Please hold while I connect you to a specialist.", voice="Polly.Joanna")

    dial = Dial(
        timeout=30,
        ring_tone="us",  # Play US ring-back tone to caller while destination is ringing
        record="record-from-answer-dual",  # Record both legs for QA
        # GAP-02: Status callback so we can handle failed transfers (busy/no-answer)
        action=f"/api/twilio/transfer/status?conversation_id={conv_id}",
        method="POST",
    )

    # GAP-02: The whisper URL is called when the destination answers.
    # Twilio plays the returned TwiML to the RECEIVER (human agent) ONLY.
    # After the whisper finishes, the caller is bridged in.
    dial.number(
        destination,
        url=f"/api/twilio/transfer/whisper?conversation_id={conv_id}",
        method="POST",
    )
    resp.append(dial)

    logger.info(f"Transferring call to {destination} (whisper enabled)")
    return Response(content=str(resp), media_type="application/xml")


class TransferCallRequest(BaseModel):
    """Request to transfer an active call to another number."""
    call_sid: str = Field(..., description="Twilio Call SID to transfer")
    destination: str = Field(..., pattern=r"^\+[1-9]\d{1,14}$", description="Destination phone number (E.164)")


@router.post("/calls/transfer")
async def transfer_call(
    request: TransferCallRequest,
    req: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Transfer an active Twilio call to a new destination.

    Uses the Twilio REST API to redirect the in-progress call
    to /transfer/dial, which returns <Dial> TwiML.
    """
    try:
        client, _, _, _ = await _get_twilio_client(user, db)

        import asyncio

        public_base_url = resolve_public_base_url(
            getattr(req.app.state, "base_url", None),
            settings.base_url,
        )
        transfer_query = urlencode(
            {"To": request.destination, "conversation_id": request.call_sid}
        )
        transfer_url = (
            f"https://{public_base_url}/api/twilio/transfer/dial?{transfer_query}"
        )

        # Update the live call to redirect to our dial TwiML
        await asyncio.to_thread(
            client.calls(request.call_sid).update,
            url=transfer_url,
            method="POST",
            fallback_url=transfer_url,
        )

        logger.info(f"Call {request.call_sid[:12]} redirected to transfer dial → {request.destination}")
        return {
            "success": True,
            "call_sid": request.call_sid,
            "destination": request.destination,
            "message": f"Call transferred to {request.destination}",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transfer failed: {e}")
        raise HTTPException(500, _safe_twilio_error(e, "transfer call"))


# ── Warm Transfer Whisper & Status Callbacks ─────────────────────────────

@router.post("/transfer/whisper")
async def transfer_whisper(request: Request):
    """Play a context summary to the human agent before connecting the caller.

    Twilio calls this URL when the destination number answers.
    The response TwiML is played to the DESTINATION (human agent) ONLY.
    After it completes, the caller is bridged in.
    """
    from twilio.twiml.voice_response import VoiceResponse

    conv_id = str(request.query_params.get("conversation_id", ""))

    resp = VoiceResponse()

    if not conv_id:
        resp.say("Incoming transfer. No context available.")
        return Response(content=str(resp), media_type="application/xml")

    try:
        from sqlalchemy import select

        from voice_platform.database import CallLog, Transcript, async_session

        async with async_session() as session:
            # Find call_log by conversation_id
            result = await session.execute(
                select(CallLog).where(CallLog.conversation_id == conv_id)
            )
            call_log = result.scalar_one_or_none()

            if not call_log:
                resp.say("Incoming transfer. Context not found.")
                return Response(content=str(resp), media_type="application/xml")

            # Fetch transcript messages for this call
            transcript_result = await session.execute(
                select(Transcript)
                .where(Transcript.call_log_id == call_log.id)
                .order_by(Transcript.timestamp.asc())
            )
            transcripts = transcript_result.scalars().all()

            # Build conversation text from last 20 messages
            if transcripts:
                conversation_text = "\n".join([
                    f"{'Agent' if t.sender == 'bot' else 'Customer'}: {t.message}"
                    for t in transcripts[-20:]
                ])
                summary = await _generate_transfer_summary(conversation_text)
            else:
                summary = "No transcript available."

            resp.say(
                f"Incoming transferred call. Context: {summary}",
                voice="Polly.Joanna",
            )

    except Exception as e:
        logger.error(f"Transfer whisper generation failed: {e}")
        resp.say("Incoming transfer. Please check dashboard for context.")

    return Response(content=str(resp), media_type="application/xml")


async def _generate_transfer_summary(conversation_text: str) -> str:
    """Generate a 2-sentence summary of the call for the human agent.

    Tries Groq (fast + cheap) → OpenAI → transcript excerpt fallback.
    """
    if not conversation_text or not conversation_text.strip():
        return "No transcript available."

    prompt = (
        "Summarize this customer service call in exactly 2 sentences for a human agent "
        "who is about to receive a transferred call.\n"
        "Focus on: what the customer wants, what was already discussed, and what still needs to be resolved.\n\n"
        f"Call transcript:\n{conversation_text[:3000]}\n\nSummary:"
    )

    # Try OpenRouter first (platform default), then Groq, then OpenAI
    import os

    api_key = os.environ.get("OPENROUTER_API_KEY")
    base_url = "https://openrouter.ai/api/v1"
    model = "deepseek/deepseek-v4-flash"

    if not api_key:
        api_key = os.environ.get("GROQ_API_KEY")
        base_url = "https://api.groq.com/openai/v1"
        model = "llama-3.1-8b-instant"

    if not api_key:
        # Fallback to OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        base_url = "https://api.openai.com/v1"
        model = "gpt-4o-mini"

    if not api_key:
        # No LLM keys available — return raw transcript excerpt
        logger.warning("No OPENROUTER_API_KEY, GROQ_API_KEY, or OPENAI_API_KEY set; using transcript excerpt for whisper")
        excerpt = conversation_text[:200].replace("\n", " ")
        return excerpt + ("..." if len(conversation_text) > 200 else "")

    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You generate concise call summaries for human agents."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 150,
                    "temperature": 0.3,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"Summary generation failed, falling back to transcript excerpt: {e}")
        # Fallback: return first ~200 chars of transcript as rough context
        return conversation_text[:200].replace("\n", " ") + "..." if len(conversation_text) > 200 else conversation_text


@router.post("/transfer/status")
async def transfer_status(request: Request):
    """Handle transfer completion or failure.

    Twilio calls this when the <Dial> completes (answered, busy, no-answer, failed).
    On failure, redirect the caller back to the AI agent so the call isn't dropped.
    """
    from twilio.twiml.voice_response import Connect, VoiceResponse

    form = await request.form()
    dial_status = str(form.get("DialCallStatus", ""))
    conv_id = str(request.query_params.get("conversation_id", ""))

    if dial_status in ("completed", "answered"):
        logger.info(f"Transfer completed for conversation {conv_id[:12]}")
        # Empty response — both parties are connected, nothing more to do
        return Response(content="", media_type="application/xml")

    # Failed transfer — busy, no-answer, failed
    logger.warning(f"Transfer failed ({dial_status}) for conversation {conv_id[:12]}")
    resp = VoiceResponse()
    resp.say("I'm sorry, I wasn't able to connect you. Let me continue helping you.")

    # Reconnect caller to the AI streaming server using existing conversation_id
    public_base_url = resolve_public_base_url(
        getattr(request.app.state, "base_url", None),
        settings.base_url,
    )
    connect = Connect()
    connect.stream(url=f"wss://{public_base_url}/connect_call/{conv_id}")
    resp.append(connect)
    return Response(content=str(resp), media_type="application/xml")


# ── Recording Status Callback ────────────────────────────────────────────

@router.post("/recording-status")
async def recording_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Twilio recording status callbacks.

    Twilio calls this when a recording is completed. We store the
    recording URL in the CallLog so the frontend can play it back.
    """
    try:
        form = await request.form()
        call_sid = str(form.get("CallSid", ""))
        recording_url = str(form.get("RecordingUrl", ""))
        recording_sid = str(form.get("RecordingSid", ""))
        recording_duration = form.get("RecordingDuration")

        if not call_sid:
            return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response/>", media_type="application/xml")

        result = await db.execute(
            select(CallLog).where(
                or_(CallLog.conversation_id == call_sid, CallLog.twilio_call_sid == call_sid)
            )
        )
        call_log = result.scalar_one_or_none()

        if call_log:
            # Append .mp3 extension if Twilio returns base URL
            if recording_url and not recording_url.endswith(".mp3"):
                recording_url = f"{recording_url}.mp3"
            call_log.recording_url = recording_url  # type: ignore[assignment]
            if recording_sid:
                # Store recording SID in call_log notes for traceability
                logger.info(f"Recording saved for call {call_sid[:12]}: sid={recording_sid}, duration={recording_duration}s")
            await db.commit()
            logger.info(f"Recording URL saved for call {call_sid[:12]}")
        else:
            logger.warning(f"Recording callback: no CallLog found for {call_sid[:12]}")

        return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response/>", media_type="application/xml")
    except Exception as e:
        logger.error(f"Recording status callback error: {e}")
        return Response(content="<?xml version='1.0' encoding='UTF-8'?><Response/>", media_type="application/xml")


# ── Phone Number → Agent Mappings ──────────────────────────────────────

class MappingRequest(BaseModel):
    phone_number: str = Field(..., pattern=r"^\+[1-9]\d{1,14}$")
    agent_id: int
    label: Optional[str] = None


@router.get("/mappings")
async def list_mappings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all phone number → agent mappings for the current user."""
    from voice_platform.database import PhoneNumberMapping
    result = await db.execute(
        select(PhoneNumberMapping)
        .options(selectinload(PhoneNumberMapping.agent))
        .where(PhoneNumberMapping.user_id == user.id)
        .order_by(PhoneNumberMapping.created_at.desc())
    )
    mappings = result.scalars().all()
    return {"mappings": [m.to_dict() for m in mappings]}


@router.post("/mappings")
async def create_or_update_mapping(
    request: MappingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign a phone number to an agent (or reassign it)."""
    from voice_platform.database import Agent, PhoneNumberMapping

    # Verify agent ownership
    agent_result = await db.execute(
        select(Agent).where(Agent.id == request.agent_id, Agent.user_id == user.id)
    )
    if not agent_result.scalar_one_or_none():
        raise HTTPException(404, "Agent not found")

    # Upsert mapping
    result = await db.execute(
        select(PhoneNumberMapping).where(
            PhoneNumberMapping.user_id == user.id,
            PhoneNumberMapping.phone_number == request.phone_number,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.agent_id = request.agent_id
        existing.label = request.label or existing.label
        existing.updated_at = datetime.now(timezone.utc)
        msg = "Mapping updated"
    else:
        mapping = PhoneNumberMapping(
            user_id=user.id,
            phone_number=request.phone_number,
            agent_id=request.agent_id,
            label=request.label,
        )
        db.add(mapping)
        msg = "Mapping created"

    await db.commit()
    logger.info(f"📞 {msg}: {request.phone_number} → agent #{request.agent_id}")
    return {"message": msg}


@router.delete("/mappings/{mapping_id}")
async def delete_mapping(
    mapping_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a phone number → agent mapping."""
    from voice_platform.database import PhoneNumberMapping

    result = await db.execute(
        select(PhoneNumberMapping)
        .where(PhoneNumberMapping.id == mapping_id, PhoneNumberMapping.user_id == user.id)
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(404, "Mapping not found")

    await db.delete(mapping)
    await db.commit()
    logger.info(f"📞 Mapping deleted: {mapping.phone_number}")
    return {"message": "Mapping deleted"}
