"""
Voice Platform — Batch Outbound Campaign Routes
==================================================

Create and manage outbound calling campaigns with contact lists.

Features:
    - Create campaigns with CSV or manual contact lists
    - Configure agent, schedule, and calling parameters
    - Background task execution with rate limiting
    - Real-time progress tracking
    - Campaign analytics (completion rate, avg duration, outcomes)

Routes:
    GET    /api/campaigns              — List all campaigns
    POST   /api/campaigns              — Create a new campaign
    GET    /api/campaigns/{id}         — Get campaign details + contacts
    PUT    /api/campaigns/{id}         — Update campaign
    DELETE /api/campaigns/{id}         — Delete campaign
    POST   /api/campaigns/{id}/start   — Start executing a campaign
    POST   /api/campaigns/{id}/pause   — Pause a running campaign
    POST   /api/campaigns/{id}/resume  — Resume a paused campaign
    POST   /api/campaigns/{id}/contacts — Add contacts to a campaign
    GET    /api/campaigns/{id}/stats   — Get campaign statistics

DB Models (lightweight — stored in same SQLite):
    - Campaign: Campaign metadata and config
    - CampaignContact: Individual contacts with call status
"""

import asyncio
import csv
import io
import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship

from voice_platform.api.telephony_utils import normalize_public_base_url, resolve_public_base_url
from voice_platform.config import settings
from voice_platform.database import (
    Agent,
    Base,
    CallLog,
    Campaign,
    CampaignContact,
    UserApiKey,
    async_session,
    get_db,
)
from voice_platform.encryption import decrypt
from voice_platform.middleware.auth_middleware import get_current_user

router = APIRouter(prefix="/api/campaigns", tags=["Campaigns"])


# ═══════════════════════════════════════════════════════════════════════
# Campaign Execution Engine
# ═══════════════════════════════════════════════════════════════════════

# Track running campaigns
_running_campaigns: dict = {}  # campaign_id -> asyncio.Task
_running_campaigns_lock = asyncio.Lock()


def _build_twilio_webhook_urls(base_url: str) -> tuple[str, str]:
    """Build voice/status webhook URLs from a base URL."""
    clean_url = normalize_public_base_url(base_url or "http://localhost:3000")
    voice_url = f"https://{clean_url}/inbound_call"
    status_url = f"https://{clean_url}/call_status"
    return voice_url, status_url


async def _get_user_twilio_credentials(session: AsyncSession, user_id: int) -> tuple[str, str] | None:
    """Return decrypted Twilio credentials for a user, if configured."""
    result = await session.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user_id,
            UserApiKey.service == "twilio",
            UserApiKey.is_active == True,
        )
    )
    user_key = result.scalar_one_or_none()
    if user_key is None:
        return None
    api_key_cipher = user_key.api_key
    api_secret_cipher = user_key.api_secret
    if api_key_cipher is None or api_secret_cipher is None:
        return None
    return decrypt(str(api_key_cipher)), decrypt(str(api_secret_cipher))


async def _execute_campaign(campaign_id: int, user_id: int, public_base_url: str):
    """
    Background task that executes a campaign by calling each contact.

    GAP-05: Uses asyncio.Semaphore for concurrent execution — multiple
    contacts can be in-flight at once, limited by max_concurrent_calls.
    Each worker gets its own DB session to avoid shared-state issues.
    """
    from voice_platform.config import settings as platform_settings

    logger.info(f"🚀 Starting campaign {campaign_id}")

    try:
        async with async_session() as session:
            # Load campaign and resolve Twilio credentials
            result = await session.execute(
                select(Campaign).where(Campaign.id == campaign_id)
            )
            campaign = result.scalar_one_or_none()
            if not campaign:
                return

            user_twilio_creds = await _get_user_twilio_credentials(session, user_id)
            twilio_sid, twilio_token = None, None
            if user_twilio_creds:
                twilio_sid, twilio_token = user_twilio_creds
            elif (
                platform_settings.allow_platform_twilio_fallback_for_campaigns
                and platform_settings.twilio_account_sid
                and platform_settings.twilio_auth_token
            ):
                twilio_sid = platform_settings.twilio_account_sid
                twilio_token = platform_settings.twilio_auth_token
            else:
                campaign.status = "failed"
                await session.commit()
                logger.warning(
                    f"Campaign {campaign_id} blocked: missing user Twilio credentials "
                    "(platform fallback disabled)"
                )
                return

            campaign.status = "running"
            campaign.started_at = datetime.now(timezone.utc)
            await session.commit()

            # BUG-17: Resolve from_phone once at campaign level to avoid
            # making a Twilio API call per contact.
            cached_from_phone = getattr(campaign, "from_phone", None)
            if not cached_from_phone and twilio_sid and twilio_token:
                try:
                    from twilio.rest import Client as _TwilioClient

                    _twilio_client = _TwilioClient(twilio_sid, twilio_token)
                    numbers = await asyncio.to_thread(
                        lambda: list(_twilio_client.incoming_phone_numbers.list(limit=1))
                    )
                    if numbers:
                        cached_from_phone = numbers[0].phone_number
                except Exception as e:
                    logger.warning(f"Campaign {campaign_id}: could not resolve from_phone: {e}")

            # Get pending contacts
            contacts_result = await session.execute(
                select(CampaignContact).where(
                    CampaignContact.campaign_id == campaign_id,
                    CampaignContact.status.in_(["pending", "failed", "calling"]),
                ).order_by(CampaignContact.id)
            )
            contacts = contacts_result.scalars().all()
            if not contacts:
                campaign.status = "completed"
                campaign.completed_at = datetime.now(timezone.utc)
                await session.commit()
                return

            # BUG-8: Reset any "calling" contacts back to "pending" — they were
            # mid-call when the campaign was paused and need to be re-queued.
            for c in contacts:
                if c.status == "calling":
                    c.status = "pending"  # type: ignore[assignment]
            await session.commit()

            # BUG-18: Extract contact IDs and close the outer session so it
            # doesn't hold a DB connection for the entire campaign duration.
            contact_ids = [c.id for c in contacts]
            max_concurrent = max(getattr(campaign, "max_concurrent_calls", None) or 1, 1)
            campaign_agent_id = campaign.agent_id
            campaign_max_cps = max(getattr(campaign, "max_cps", None) or 1, 1)
            campaign_max_duration = getattr(campaign, "max_call_duration_secs", 300) or 300
            campaign_total_contacts = campaign.total_contacts

        # GAP-05: Semaphore limits concurrent active calls (avoid Twilio rate limits)
        semaphore = asyncio.Semaphore(max_concurrent)
        logger.info(
            f"Campaign {campaign_id}: {len(contact_ids)} contacts, "
            f"max_concurrent={max_concurrent}"
        )

        async def _call_one(contact_id: int) -> str:
            """Worker: place one call, poll result, update DB. Own DB session."""
            async with semaphore:
                async with async_session() as worker_session:
                    # Check if campaign was paused
                    campaign_check = await worker_session.execute(
                        select(Campaign).where(Campaign.id == campaign_id)
                    )
                    campaign_row = campaign_check.scalar_one_or_none()
                    if campaign_row and campaign_row.status == "paused":
                        logger.info(
                            f"Campaign {campaign_id} paused — "
                            f"skipping contact {contact_id}"
                        )
                        return "paused"

                    # Re-fetch contact for fresh state
                    contact_result = await worker_session.execute(
                        select(CampaignContact).where(
                            CampaignContact.id == contact_id
                        )
                    )
                    worker_contact = contact_result.scalar_one_or_none()
                    if not worker_contact:
                        return "missing"

                    # Skip if max retries exceeded
                    max_retries = getattr(campaign_row, "max_retries", 3) or 3
                    if (
                        worker_contact.retries >= max_retries
                        and worker_contact.status == "failed"
                    ):
                        worker_contact.status = "skipped"
                        await worker_session.commit()
                        return "skipped"

                    # Phase 1: Compliance check before dialing
                    from voice_platform.compliance import validate_call_eligibility
                    contact_tz = getattr(worker_contact, "timezone", None)
                    try:
                        await validate_call_eligibility(
                            worker_contact.phone_number,  # type: ignore[arg-type]
                            user_id=user_id,
                            campaign_type="informational",
                            require_consent=False,  # Campaign contacts don't require explicit consent record
                            timezone_hint=contact_tz,
                        )
                    except HTTPException as exc:
                        worker_contact.status = "skipped"  # type: ignore[assignment]
                        # Distinguish calling-hours block from DNC block
                        if "calling hours" in str(exc.detail).lower():
                            worker_contact.call_outcome = "hours_blocked"  # type: ignore[assignment]
                        else:
                            worker_contact.call_outcome = "dnc_blocked"  # type: ignore[assignment]
                        worker_contact.last_error = str(exc.detail)  # type: ignore[assignment]
                        await worker_session.commit()
                        logger.warning(
                            f"Campaign {campaign_id}: skipped {worker_contact.phone_number} — {exc.detail}"
                        )
                        return "dnc_blocked"

                    # Make the call
                    try:
                        worker_contact.status = "calling"
                        worker_contact.called_at = datetime.now(timezone.utc)
                        worker_contact.retries += 1
                        await worker_session.commit()

                        if twilio_sid and twilio_token:
                            from twilio.rest import Client

                            twilio_client = Client(twilio_sid, twilio_token)

                            from_phone = cached_from_phone

                            if not from_phone:
                                worker_contact.status = "failed"
                                worker_contact.last_error = (
                                    "No from_phone configured"
                                )
                                await worker_session.commit()
                                return "no_from_phone"

                            # Phase 2: Enforce campaign CPS rate limit (before CallLog
                            # creation so throttled contacts don't create orphan rows)
                            from voice_platform.telephony.outbound_throttle import (
                                OutboundCallThrottler,
                            )
                            throttler = OutboundCallThrottler()
                            campaign_max_cps = max(getattr(campaign_row, "max_cps", None) or 1, 1)
                            if not await throttler.acquire(
                                user_id=user_id, max_cps=campaign_max_cps, wait=True, max_wait_seconds=5.0
                            ):
                                # Throttled — reset to pending so next worker can retry
                                worker_contact.status = "pending"  # type: ignore[assignment]
                                worker_contact.call_outcome = "throttled"  # type: ignore[assignment]
                                worker_contact.last_error = "CPS rate limit exceeded"  # type: ignore[assignment]
                                await worker_session.commit()
                                logger.warning(
                                    f"Campaign {campaign_id}: throttled {worker_contact.phone_number} "
                                    f"(max_cps={campaign_max_cps})"
                                )
                                return "throttled"

                            # Place Twilio call
                            voice_url, status_url = _build_twilio_webhook_urls(
                                public_base_url
                            )
                            # GAP-09: Enable recording with status callback
                            recording_status_url = f"https://{public_base_url}/api/twilio/recording-status"
                            call = await asyncio.to_thread(
                                lambda: twilio_client.calls.create(
                                    to=worker_contact.phone_number,
                                    from_=from_phone,
                                    url=voice_url,
                                    method="POST",
                                    status_callback=status_url,
                                    status_callback_method="POST",
                                    status_callback_event=["initiated", "ringing", "answered", "completed"],
                                    record=True,
                                    recording_status_callback=recording_status_url,
                                    recording_status_callback_event=["completed"],
                                    timeout=30,
                                    machine_detection="Enable",  # AMD: detect voicemail/machine on answer
                                )
                            )

                            # Create CallLog AFTER Twilio call succeeds so we
                            # use the real call.sid as conversation_id (BUG-2 fix).
                            call_log = CallLog(
                                conversation_id=call.sid,
                                twilio_call_sid=call.sid,
                                agent_id=campaign_row.agent_id,
                                user_id=user_id,
                                from_phone=from_phone,
                                to_phone=worker_contact.phone_number,
                                direction="outbound",
                                status="initiated",
                                started_at=datetime.now(timezone.utc),
                            )
                            worker_session.add(call_log)
                            await worker_session.flush()
                            worker_contact.call_log_id = call_log.id
                            worker_contact.call_outcome = "initiated"
                            await worker_session.commit()

                            logger.info(
                                f"📞 Campaign call: {worker_contact.phone_number} "
                                f"(contact {worker_contact.id}, SID: {call.sid[:12]})"
                            )

                            # O-6: Webhook-first status polling. The /call_status
                            # webhook updates the CallLog in the DB, so we check
                            # that first (cheap). Only fall back to Twilio API
                            # fetch every 30s if the webhook hasn't fired yet.
                            webhook_check_interval = 5
                            api_poll_interval = 30
                            max_duration = getattr(campaign_row, "max_call_duration_secs", 300) or 300
                            deadline = datetime.now(timezone.utc).timestamp() + max_duration
                            terminal = False
                            last_api_poll = 0.0
                            poll_errors = 0
                            last_poll_error_msg = ""
                            terminal_statuses = {"completed", "busy", "no-answer", "failed", "canceled"}

                            while not terminal and datetime.now(timezone.utc).timestamp() < deadline:
                                await asyncio.sleep(webhook_check_interval)

                                # Check if the webhook already updated the CallLog
                                cl_result = await worker_session.execute(
                                    select(CallLog).where(CallLog.conversation_id == call.sid)
                                )
                                cl_row = cl_result.scalar_one_or_none()
                                if cl_row and cl_row.status in terminal_statuses:
                                    terminal = True
                                    # AMD: If voicemail was detected, mark contact as no_answer
                                    if getattr(cl_row, "call_outcome", None) == "voicemail":
                                        worker_contact.status = "completed"
                                        worker_contact.call_outcome = "voicemail"
                                    else:
                                        worker_contact.status = (
                                            "completed"
                                            if cl_row.status == "completed"
                                            else "failed"
                                        )
                                        worker_contact.call_outcome = cl_row.status
                                    worker_contact.completed_at = datetime.now(timezone.utc)
                                    if cl_row.duration_secs:
                                        worker_contact.call_duration_secs = float(
                                            cl_row.duration_secs
                                        )
                                    break

                                # Fallback: poll Twilio API every api_poll_interval seconds
                                now_ts = datetime.now(timezone.utc).timestamp()
                                if now_ts - last_api_poll < api_poll_interval:
                                    continue
                                last_api_poll = now_ts
                                try:
                                    updated_call = await asyncio.to_thread(
                                        lambda: twilio_client.calls(
                                            call.sid
                                        ).fetch()
                                    )
                                    if updated_call.status in terminal_statuses:
                                        terminal = True
                                        worker_contact.status = (
                                            "completed"
                                            if updated_call.status == "completed"
                                            else "failed"
                                        )
                                        worker_contact.call_outcome = updated_call.status
                                        worker_contact.completed_at = datetime.now(timezone.utc)
                                        if updated_call.duration:
                                            worker_contact.call_duration_secs = float(
                                                updated_call.duration
                                            )
                                except Exception as poll_err:
                                    poll_errors += 1
                                    last_poll_error_msg = f"Could not poll call status: {poll_err}"
                                    logger.warning(last_poll_error_msg)

                            if not terminal:
                                # Timed out — mark as failed
                                worker_contact.status = "failed"
                                if poll_errors > 0:
                                    worker_contact.call_outcome = "poll_error"
                                    worker_contact.last_error = last_poll_error_msg
                                else:
                                    worker_contact.call_outcome = "timeout"
                                    worker_contact.last_error = (
                                        f"Call did not reach terminal status within {max_duration}s"
                                    )
                                worker_contact.completed_at = datetime.now(
                                    timezone.utc
                                )

                            await worker_session.commit()
                        else:
                            # No Twilio — simulate for testing
                            worker_contact.status = "completed"
                            worker_contact.call_outcome = "simulated"
                            worker_contact.completed_at = datetime.now(
                                timezone.utc
                            )
                            await worker_session.commit()
                            logger.info(
                                f"📞 Simulated campaign call to {worker_contact.phone_number}"
                            )
                            await asyncio.sleep(1)

                    except Exception as call_err:
                        worker_contact.status = "failed"
                        worker_contact.last_error = str(call_err)[:500]
                        await worker_session.commit()
                        logger.error(
                            f"Campaign call failed for {worker_contact.phone_number}: {call_err}"
                        )

                    return worker_contact.status

        # Spawn contact tasks in batches to avoid creating 1000+ task
        # objects at once for large campaigns. Semaphore still limits
        # actual concurrency; batching just caps memory for task objects.
        BATCH_SIZE = 50
        for i in range(0, len(contact_ids), BATCH_SIZE):
            batch = contact_ids[i : i + BATCH_SIZE]
            tasks = [asyncio.create_task(_call_one(cid)) for cid in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

        # BUG-18: Open a new session for final aggregation instead of
        # holding the outer session for the entire campaign duration.
        async with async_session() as final_session:
            final_counts = await final_session.execute(
                select(CampaignContact.status, func.count(CampaignContact.id))
                .where(CampaignContact.campaign_id == campaign_id)
                .group_by(CampaignContact.status)
            )
            counts = {row[0]: row[1] for row in final_counts.all()}
            campaign_result = await final_session.execute(
                select(Campaign).where(Campaign.id == campaign_id)
            )
            campaign = campaign_result.scalar_one_or_none()
            if campaign:
                campaign.completed_contacts = counts.get("completed", 0)
                campaign.failed_contacts = counts.get("failed", 0) + counts.get(
                    "skipped", 0
                )
                campaign.status = "completed"
                campaign.completed_at = datetime.now(timezone.utc)
                await final_session.commit()
                logger.info(
                    f"✅ Campaign {campaign_id} completed: "
                    f"{campaign.completed_contacts}/{campaign.total_contacts}"
                )

    except Exception as e:
        logger.error(f"Campaign {campaign_id} failed: {e}")
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(Campaign).where(Campaign.id == campaign_id)
                )
                campaign = result.scalar_one_or_none()
                if campaign:
                    campaign.status = "failed"
                    await session.commit()
        except Exception:
            pass
    finally:
        async with _running_campaigns_lock:
            _running_campaigns.pop(campaign_id, None)


# ═══════════════════════════════════════════════════════════════════════
# API Request/Response Models
# ═══════════════════════════════════════════════════════════════════════

class CreateCampaignRequest(BaseModel):
    name: str
    description: Optional[str] = None
    agent_id: int
    team_id: Optional[int] = None
    from_phone: Optional[str] = None
    max_concurrent_calls: int = 1
    call_interval_secs: int = 30
    max_cps: int = 1
    max_retries: int = 2
    max_call_duration_secs: int = 300
    contacts: Optional[List[dict]] = None  # [{phone_number, name?, email?}]


class UpdateCampaignRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_id: Optional[int] = None
    team_id: Optional[int] = None
    from_phone: Optional[str] = None
    max_concurrent_calls: Optional[int] = None
    call_interval_secs: Optional[int] = None
    max_cps: Optional[int] = None
    max_retries: Optional[int] = None
    max_call_duration_secs: Optional[int] = None


class AddContactsRequest(BaseModel):
    contacts: List[dict]  # [{phone_number, name?, email?, ...custom}]


# ═══════════════════════════════════════════════════════════════════════
# API Routes
# ═══════════════════════════════════════════════════════════════════════

@router.get("")
async def list_campaigns(
    status: Optional[str] = None,
    team_id: Optional[int] = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
):
    """List all campaigns for the current user or team."""
    from sqlalchemy import func

    from voice_platform.rbac import get_team_membership

    offset = (page - 1) * per_page

    if team_id:
        membership = await get_team_membership(user.id, team_id)
        if membership:
            base_filter = Campaign.team_id == team_id
        else:
            base_filter = Campaign.user_id == user.id
    else:
        base_filter = Campaign.user_id == user.id

    if status:
        base_filter = base_filter & (Campaign.status == status)

    # Count total
    count_result = await db.execute(
        select(func.count(Campaign.id)).where(base_filter)
    )
    total = count_result.scalar() or 0

    query = (
        select(Campaign)
        .where(base_filter)
        .order_by(Campaign.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(query)
    campaigns = result.scalars().all()

    return {
        "campaigns": [c.to_dict() for c in campaigns],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("")
async def create_campaign(
    request: CreateCampaignRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new outbound campaign."""
    # Verify agent exists
    agent_result = await db.execute(
        select(Agent).where(Agent.id == request.agent_id, Agent.user_id == user.id)
    )
    agent_obj = agent_result.scalar_one_or_none()
    if not agent_obj:
        raise HTTPException(404, "Agent not found")

    # B3: Verify the agent is configured for outbound calls
    if not agent_obj.outbound_ready:
        raise HTTPException(
            400,
            "Selected agent is not configured for outbound calls. "
            "Enable 'Outbound Ready' in agent settings.",
        )
    
    campaign = Campaign(
        user_id=user.id,
        team_id=getattr(request, "team_id", None),
        name=request.name,
        description=request.description,
        agent_id=request.agent_id,
        from_phone=request.from_phone,
        max_concurrent_calls=request.max_concurrent_calls,
        call_interval_secs=request.call_interval_secs,
        max_cps=request.max_cps,
        max_retries=request.max_retries,
        max_call_duration_secs=request.max_call_duration_secs,
    )
    db.add(campaign)
    await db.flush()
    
    # Add contacts if provided
    if request.contacts:
        for c in request.contacts:
            phone = c.get("phone_number", "").strip()
            if not phone:
                continue
            contact = CampaignContact(
                campaign_id=campaign.id,
                phone_number=phone,
                name=c.get("name"),
                email=c.get("email"),
                custom_data=json.dumps({k: v for k, v in c.items() if k not in ("phone_number", "name", "email")}) if len(c) > 3 else None,
            )
            db.add(contact)
        campaign.total_contacts = len([c for c in request.contacts if c.get("phone_number", "").strip()])
    
    await db.commit()
    await db.refresh(campaign)
    
    return {"campaign": campaign.to_dict(), "message": "Campaign created"}


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get campaign details with contacts."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    
    # Get contacts
    contacts_result = await db.execute(
        select(CampaignContact)
        .where(CampaignContact.campaign_id == campaign_id)
        .order_by(CampaignContact.id)
    )
    contacts = contacts_result.scalars().all()
    
    return {
        "campaign": campaign.to_dict(),
        "contacts": [c.to_dict() for c in contacts],
    }


@router.put("/{campaign_id}")
async def update_campaign(
    campaign_id: int,
    request: UpdateCampaignRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update campaign settings."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    
    if campaign.status == "running":
        raise HTTPException(400, "Cannot update a running campaign. Pause it first.")
    
    for field, value in request.dict(exclude_none=True).items():
        setattr(campaign, field, value)
    
    await db.commit()
    await db.refresh(campaign)
    
    return {"campaign": campaign.to_dict(), "message": "Campaign updated"}


@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a campaign and all its contacts."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    
    if campaign.status == "running":
        raise HTTPException(400, "Cannot delete a running campaign. Pause or wait for completion.")
    
    await db.delete(campaign)
    await db.commit()
    
    return {"message": "Campaign deleted"}


@router.post("/{campaign_id}/contacts")
async def add_contacts(
    campaign_id: int,
    request: AddContactsRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add contacts to a campaign."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    
    added = 0
    for c in request.contacts:
        phone = c.get("phone_number", "").strip()
        if not phone:
            continue
        contact = CampaignContact(
            campaign_id=campaign_id,
            phone_number=phone,
            name=c.get("name"),
            email=c.get("email"),
            custom_data=json.dumps({k: v for k, v in c.items() if k not in ("phone_number", "name", "email")}) if len(c) > 3 else None,
        )
        db.add(contact)
        added += 1
    
    campaign.total_contacts += added
    await db.commit()
    
    return {"added": added, "total_contacts": campaign.total_contacts}


@router.post("/{campaign_id}/contacts/csv")
async def upload_contacts_csv(
    campaign_id: int,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload contacts from a CSV file. Expected columns: phone_number, name (optional), email (optional)."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    
    content = await file.read()
    text = content.decode("utf-8-sig")
    
    reader = csv.DictReader(io.StringIO(text))
    added = 0
    
    for row in reader:
        # Flexible column name matching
        phone = (
            row.get("phone_number") or row.get("phone") or 
            row.get("Phone Number") or row.get("Phone") or 
            row.get("mobile") or row.get("Mobile") or ""
        ).strip()
        
        if not phone:
            continue
        
        name = row.get("name") or row.get("Name") or row.get("Full Name") or None
        email = row.get("email") or row.get("Email") or row.get("E-mail") or None
        
        # Store any extra columns as custom_data
        extra = {
            k: v for k, v in row.items()
            if k.lower() not in ("phone_number", "phone", "mobile", "name", "full name", "email", "e-mail")
            and v
        }
        
        contact = CampaignContact(
            campaign_id=campaign_id,
            phone_number=phone,
            name=name,
            email=email,
            custom_data=json.dumps(extra) if extra else None,
        )
        db.add(contact)
        added += 1
    
    campaign.total_contacts += added
    await db.commit()
    
    return {"added": added, "total_contacts": campaign.total_contacts, "message": f"Imported {added} contacts from CSV"}


# BIL-04: Plan-based monthly call limits
_PLAN_LIMITS = {
    "free": 100,
    "pro": 1000,
    "enterprise": None,  # unlimited
}


async def _check_call_quota(user, db: AsyncSession) -> None:
    """Raise HTTPException(429) if user has exceeded their monthly call quota."""
    plan = getattr(user, "plan", "free") or "free"
    limit = _PLAN_LIMITS.get(plan)
    if limit is None:
        return  # unlimited

    from voice_platform.database import CallLog

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
            status_code=429,
            detail=f"Monthly outbound call limit reached ({limit}/{limit}). "
            f"Upgrade your plan to make more calls.",
        )


@router.post("/{campaign_id}/start")
async def start_campaign(
    campaign_id: int,
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start executing a campaign."""
    # BIL-04: Enforce monthly outbound call quota before starting campaign
    await _check_call_quota(user, db)

    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    if campaign.status == "running":
        raise HTTPException(400, "Campaign is already running")

    if campaign.total_contacts == 0:
        raise HTTPException(400, "Campaign has no contacts. Add contacts first.")
    
    public_base_url = resolve_public_base_url(
        getattr(request.app.state, "base_url", None),
        settings.base_url,
    )

    # Start background task
    task = asyncio.create_task(_execute_campaign(campaign_id, user.id, public_base_url))
    async with _running_campaigns_lock:
        _running_campaigns[campaign_id] = task
    
    return {"message": "Campaign started", "campaign_id": campaign_id}


@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pause a running campaign."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    
    if campaign.status != "running":
        raise HTTPException(400, "Campaign is not running")
    
    campaign.status = "paused"
    await db.commit()
    
    return {"message": "Campaign paused"}


@router.post("/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: int,
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused campaign."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    
    if campaign.status != "paused":
        raise HTTPException(400, "Campaign is not paused")
    
    public_base_url = resolve_public_base_url(
        getattr(request.app.state, "base_url", None),
        settings.base_url,
    )

    task = asyncio.create_task(_execute_campaign(campaign_id, user.id, public_base_url))
    async with _running_campaigns_lock:
        _running_campaigns[campaign_id] = task
    
    return {"message": "Campaign resumed"}


@router.get("/{campaign_id}/stats")
async def get_campaign_stats(
    campaign_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed statistics for a campaign."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user.id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    
    # Get contact status breakdown
    status_result = await db.execute(
        select(CampaignContact.status, func.count(CampaignContact.id))
        .where(CampaignContact.campaign_id == campaign_id)
        .group_by(CampaignContact.status)
    )
    by_status = {row[0]: row[1] for row in status_result.all()}
    
    # Get outcome breakdown
    outcome_result = await db.execute(
        select(CampaignContact.call_outcome, func.count(CampaignContact.id))
        .where(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.call_outcome.isnot(None),
        )
        .group_by(CampaignContact.call_outcome)
    )
    by_outcome = {row[0]: row[1] for row in outcome_result.all()}
    
    # Average call duration
    avg_dur = await db.execute(
        select(func.avg(CampaignContact.call_duration_secs))
        .where(
            CampaignContact.campaign_id == campaign_id,
            CampaignContact.call_duration_secs.isnot(None),
        )
    )
    avg_duration = avg_dur.scalar() or 0
    
    return {
        "campaign": campaign.to_dict(),
        "by_status": by_status,
        "by_outcome": by_outcome,
        "avg_call_duration_secs": round(avg_duration, 1),
        "is_running": campaign_id in _running_campaigns,
    }
