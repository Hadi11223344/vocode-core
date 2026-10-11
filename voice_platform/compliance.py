"""
Voice Platform — Twilio Compliance Utilities
============================================

Guardrails to keep outbound calling compliant with Twilio's
Voice Services Policy, TCPA, and TSR requirements.

Features:
    - Do Not Call (DNC) list checking
    - Consent validation for outbound calls
    - Opt-out recording (auto-adds to DNC)
    - Call-time window enforcement (8AM–9PM local)

Usage:
    from voice_platform.compliance import validate_call_eligibility, record_opt_out

    # Before placing an outbound call
    validate_call_eligibility("+14155551234", user_id=1, campaign_type="informational")

    # When a user opts out (IVR keypress, verbal, etc.)
    record_opt_out("+14155551234", user_id=1, reason="Caller requested stop")
"""

from datetime import datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.config import settings
from voice_platform.database import DNCList, async_session

# ── Constants ──────────────────────────────────────────────────────────
_CONSENT_REQUIRED_FOR = {"telemarketing", "advertising"}
_CONSENT_ACCEPTABLE = {"express", "written"}


# ── DNC Checking ─────────────────────────────────────────────────────

async def is_dnc(phone_number: str, user_id: Optional[int] = None) -> bool:
    """
    Return True if the number is on a DNC list (global or user-specific).

    Checks:
      1. Global block (user_id IS NULL)
      2. User-specific block (matching user_id)
    """
    normalized = _normalize_phone(phone_number)
    async with async_session() as session:
        # Global DNC check
        result = await session.execute(
            select(DNCList).where(
                DNCList.phone_number == normalized,
                DNCList.user_id.is_(None),
            )
        )
        if result.scalar_one_or_none():
            return True

        # User-specific DNC check
        if user_id is not None:
            result = await session.execute(
                select(DNCList).where(
                    DNCList.phone_number == normalized,
                    DNCList.user_id == user_id,
                )
            )
            if result.scalar_one_or_none():
                return True

    return False


# ── Consent Validation ───────────────────────────────────────────────

async def has_valid_consent(
    phone_number: str,
    user_id: Optional[int] = None,
    campaign_type: str = "informational",
) -> bool:
    """
    Return True if the contact has consent sufficient for the campaign type.

    - informational: any consent (express or written) is acceptable
    - telemarketing / advertising: requires written consent
    """
    from voice_platform.database import CampaignContact

    normalized = _normalize_phone(phone_number)
    async with async_session() as session:
        # Look up most recent contact record for this number + user
        from voice_platform.database import Campaign
        query = (
            select(CampaignContact)
            .join(Campaign, CampaignContact.campaign_id == Campaign.id)
            .where(CampaignContact.phone_number == normalized)
            .order_by(CampaignContact.created_at.desc())
            .limit(1)
        )
        if user_id is not None:
            query = query.where(Campaign.user_id == user_id)
        result = await session.execute(query)
        contact = result.scalar_one_or_none()

    if not contact:
        # No contact record → cannot verify consent
        return False

    if contact.opted_out_at:
        return False

    if contact.consent_status == "revoked":
        return False

    if campaign_type in _CONSENT_REQUIRED_FOR:
        return contact.consent_status == "written"  # type: ignore[return-value]

    return contact.consent_status in _CONSENT_ACCEPTABLE  # type: ignore[return-value]


# ── Call Eligibility ─────────────────────────────────────────────────

async def validate_call_eligibility(
    phone_number: str,
    user_id: Optional[int] = None,
    campaign_type: str = "informational",
    require_consent: bool = True,
    timezone_hint: Optional[str] = None,
) -> None:
    """
    Raise HTTPException(403) if the number is not eligible for an outbound call.

    Checks in order:
      1. DNC list
      2. Consent status (if require_consent=True)
      3. Calling hours (if enforce_calling_hours=True)
    """
    normalized = _normalize_phone(phone_number)

    # 1. DNC check
    if await is_dnc(normalized, user_id):
        logger.warning(
            f"Compliance blocked call to {normalized}: number on DNC list "
            f"(user_id={user_id})"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This phone number is on the Do Not Call list.",
        )

    # 2. Consent check
    if require_consent and not await has_valid_consent(normalized, user_id, campaign_type):
        logger.warning(
            f"Compliance blocked call to {normalized}: insufficient consent "
            f"(type={campaign_type}, user_id={user_id})"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This phone number does not have valid consent for this call type.",
        )

    # 3. Calling hours check (TSR / TCPA)
    if getattr(settings, "enforce_calling_hours", True):
        if not is_within_calling_hours(normalized, timezone_hint=timezone_hint):
            logger.warning(
                f"Compliance blocked call to {normalized}: outside allowed calling hours "
                f"(user_id={user_id})"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Calls can only be placed between 8:00 AM and 9:00 PM in the recipient's local time zone.",
            )


# ── Calling Hours ──────────────────────────────────────────────────────

CALLING_HOURS_START = time(8, 0)
CALLING_HOURS_END = time(21, 0)


def is_within_calling_hours(phone_number: str, timezone_hint: Optional[str] = None) -> bool:
    """
    Return True if the current UTC time is between 08:00-21:00 in the
    recipient's inferred local time zone.

    * For US/CA numbers the area code is mapped to a zone.
    * If a hint is passed (e.g. the contact's `timezone` field) it is preferred.
    * Un-mapped numbers are treated as UTC (safe default: 8:00-21:00 UTC).
    """
    normalized = _normalize_phone(phone_number)
    tz_name: str | None = None

    # 1. Use explicit hint if provided
    if timezone_hint:
        tz_name = timezone_hint

    # 2. Infer from US/CA area code
    if tz_name is None:
        from voice_platform._area_code_timezones import AREA_CODE_TIMEZONES
        digits = normalized.lstrip("+")
        if digits.startswith("1") and len(digits) >= 4:
            area_code = digits[1:4]
            tz_name = AREA_CODE_TIMEZONES.get(area_code)

    # 3. Default to UTC if we can't infer
    if tz_name is None:
        tz_name = "UTC"

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")

    now_local = datetime.now(timezone.utc).astimezone(tz)
    return CALLING_HOURS_START <= now_local.time() < CALLING_HOURS_END


# ── Opt-Out Recording ────────────────────────────────────────────────

async def record_opt_out(
    phone_number: str,
    user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> None:
    """
    Record an opt-out request:
      1. Add number to DNC list
      2. Mark any matching CampaignContact as opted out
    """
    normalized = _normalize_phone(phone_number)
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        # 1. Insert into DNC list (ignore if already present)
        existing = await session.execute(
            select(DNCList).where(
                DNCList.phone_number == normalized,
                DNCList.user_id == user_id if user_id is not None else DNCList.user_id.is_(None),
            )
        )
        if not existing.scalar_one_or_none():
            dnc = DNCList(
                phone_number=normalized,
                user_id=user_id,
                source="opt_out",
                reason=reason,
                created_at=now,
            )
            session.add(dnc)

        # 2. Update CampaignContact records
        from voice_platform.database import CampaignContact
        result = await session.execute(
            select(CampaignContact).where(
                CampaignContact.phone_number == normalized,
            )
        )
        for contact in result.scalars().all():
            contact.opted_out_at = now  # type: ignore[assignment]
            contact.consent_status = "revoked"  # type: ignore[assignment]

        await session.commit()

    logger.info(
        f"Opt-out recorded for {normalized} (user_id={user_id}, reason={reason})"
    )


# ── Helpers ──────────────────────────────────────────────────────────

def _normalize_phone(phone: str) -> str:
    """Strip non-digit characters and ensure E.164-ish consistency."""
    if not phone:
        return ""
    digits = "".join(c for c in phone if c.isdigit() or c == "+")
    return digits
