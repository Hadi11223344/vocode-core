"""
Voice Platform — Compliance API Routes
========================================

REST endpoints for Do Not Call (DNC) management and opt-out handling.

Routes:
    GET    /api/compliance/dnc           — List DNC entries
    POST   /api/compliance/dnc           — Add number to DNC
    DELETE /api/compliance/dnc/{phone}   — Remove number from DNC (admin)
    POST   /api/compliance/opt-out       — Public opt-out (no auth required)
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.compliance import record_opt_out
from voice_platform.database import DNCList, User, async_session, get_db
from voice_platform.middleware.auth_middleware import get_current_user
from voice_platform.rate_limit import limiter

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


# ── Pydantic Schemas ───────────────────────────────────────────────────

class DNCAddRequest(BaseModel):
    phone_number: str
    reason: Optional[str] = None


class DNCRemoveRequest(BaseModel):
    phone_number: str


class OptOutRequest(BaseModel):
    phone_number: str
    reason: Optional[str] = "Caller requested opt-out"


# ── DNC List Management ────────────────────────────────────────────────

@router.get("/dnc")
@limiter.limit("60/minute")
async def list_dnc(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    phone: Optional[str] = Query(None, description="Filter by phone number"),
):
    """List DNC entries for the current user (and global entries)."""
    query = select(DNCList).where(
        (DNCList.user_id == user.id) | (DNCList.user_id.is_(None))
    )
    if phone:
        query = query.where(DNCList.phone_number == phone)
    query = query.order_by(DNCList.created_at.desc())
    result = await db.execute(query)
    entries = result.scalars().all()
    return {"entries": [e.to_dict() for e in entries]}


@router.post("/dnc")
@limiter.limit("30/minute")
async def add_dnc(
    request: Request,
    body: DNCAddRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a phone number to the DNC list."""
    normalized = "".join(c for c in body.phone_number if c.isdigit() or c == "+")

    # Check if already exists for this user
    existing = await db.execute(
        select(DNCList).where(
            DNCList.phone_number == normalized,
            DNCList.user_id == user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Number already on DNC list")

    entry = DNCList(
        phone_number=normalized,
        user_id=user.id,
        source="manual",
        reason=body.reason,
    )
    db.add(entry)
    await db.commit()
    logger.info(f"DNC added by user {user.id}: {normalized}")
    return {"message": "Number added to DNC list", "entry": entry.to_dict()}


@router.delete("/dnc/{phone_number}")
@limiter.limit("30/minute")
async def remove_dnc(
    request: Request,
    phone_number: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a phone number from the user's DNC list."""
    normalized = "".join(c for c in phone_number if c.isdigit() or c == "+")

    result = await db.execute(
        select(DNCList).where(
            DNCList.phone_number == normalized,
            DNCList.user_id == user.id,
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Number not found on DNC list")

    await db.delete(entry)
    await db.commit()
    logger.info(f"DNC removed by user {user.id}: {normalized}")
    return {"message": "Number removed from DNC list"}


# ── Public Opt-Out ────────────────────────────────────────────────────

@router.post("/opt-out")
@limiter.limit("20/minute")
async def public_opt_out(
    request: Request,
    body: OptOutRequest,
):
    """
    Public opt-out endpoint — no authentication required.

    Callers can opt out by hitting this endpoint (e.g. via IVR menu,
    SMS reply, or web form). The number is added to DNC and any
    associated campaign contacts are marked as opted out.
    """
    normalized = "".join(c for c in body.phone_number if c.isdigit() or c == "+")
    if not normalized or len(normalized) < 7:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid phone number",
        )

    await record_opt_out(normalized, user_id=None, reason=body.reason)
    return {"message": "Opt-out recorded successfully"}
