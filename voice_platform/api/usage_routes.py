"""
Usage & Billing routes — Phase 7: Billing & Usage Tracking.

GET    /api/usage/overview      Aggregate usage for period
GET    /api/usage/daily          Daily breakdown
GET    /api/usage/by-provider    Usage grouped by provider
GET    /api/usage/calls          Per-call usage logs
POST   /api/usage/estimate      Estimate cost for a hypothetical call
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import Agent, CallLog, PricingRate, UsageLog, User, _is_sqlite, get_db
from voice_platform.middleware.auth_middleware import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/usage", tags=["usage"])


def _date_expr(column):
    """Cross-DB date extraction: SQLite uses date(col), PostgreSQL uses date(timezone('UTC', col))."""
    if _is_sqlite:
        return func.date(column)
    return func.date(func.timezone(literal_column("'UTC'"), column))

# ── Approximate pricing (USD) ──────────────────────────────────
# These are ballpark figures for self-hosted cost visibility.
LLM_PRICING = {
    "gpt-4o-mini": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    "gpt-4o": {"input": 2.50 / 1_000_000, "output": 10.00 / 1_000_000},
    "gpt-4-turbo": {"input": 10.00 / 1_000_000, "output": 30.00 / 1_000_000},
    "claude-3-haiku": {"input": 0.25 / 1_000_000, "output": 1.25 / 1_000_000},
    "claude-3-sonnet": {"input": 3.00 / 1_000_000, "output": 15.00 / 1_000_000},
    "gemini-1.5-flash": {"input": 0.075 / 1_000_000, "output": 0.30 / 1_000_000},
    "gemini-1.5-pro": {"input": 3.50 / 1_000_000, "output": 10.50 / 1_000_000},
    "llama-3.1-8b": {"input": 0.05 / 1_000_000, "output": 0.08 / 1_000_000},
    "openai/gpt-oss-120b": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    "openai/gpt-oss-20b": {"input": 0.075 / 1_000_000, "output": 0.30 / 1_000_000},
    "llama-3.3-70b": {"input": 0.59 / 1_000_000, "output": 0.79 / 1_000_000},
    "default": {"input": 0.50 / 1_000_000, "output": 1.50 / 1_000_000},
}

STT_PRICING = {
    "deepgram": 0.0077 / 60,  # per second (Nova-3 ≈ $0.0077/min)
    "assemblyai": 0.0037 / 60,
    "azure": 0.016 / 60,
    "google": 0.006 / 60,
    "default": 0.005 / 60,
}

DEEPGRAM_MODEL_PRICING = {
    "nova-3": 0.0077 / 60,
    "nova-3-phonecall": 0.0077 / 60,
    "nova-3-conversationalai": 0.0077 / 60,
    "nova-2-phonecall": 0.0043 / 60,
    "nova-2": 0.0043 / 60,
    "nova-2-meeting": 0.0043 / 60,
    "enhanced": 0.0043 / 60,
    "base": 0.0043 / 60,
}

TTS_PRICING = {
    "elevenlabs": 0.30 / 1_000,  # per character
    "azure": 16.00 / 1_000_000,   # per character
    "playht": 0.033 / 1_000,
    "gtts": 0.0,
    "default": 0.0,
}

TWILIO_PRICING = {
    "inbound": 0.0085 / 60,   # per second (≈ $0.0085/min for US inbound)
    "outbound": 0.013 / 60,   # per second (≈ $0.013/min for US outbound)
}


async def _get_pricing_rate(db: AsyncSession, service_type: str, provider: str, metric: str) -> float:
    """Query PricingRate from DB; fall back to hardcoded defaults."""
    result = await db.execute(
        select(PricingRate.rate_usd)
        .where(
            PricingRate.service_type == service_type,
            PricingRate.provider == provider,
            PricingRate.metric == metric,
        )
    )
    rate = result.scalar()
    if rate is not None:
        return rate
    # fallback
    if service_type == "llm":
        rates = LLM_PRICING.get(provider or "", LLM_PRICING["default"])
        return rates.get(metric, 0.0)
    if service_type == "stt":
        return STT_PRICING.get(provider or "", STT_PRICING["default"])
    if service_type == "tts":
        return TTS_PRICING.get(provider or "", TTS_PRICING["default"])
    if service_type == "telephony":
        return TWILIO_PRICING.get(provider or "inbound", TWILIO_PRICING["inbound"])
    return 0.0


def estimate_llm_cost(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """Estimate LLM cost in USD."""
    rates = LLM_PRICING.get(model or "", LLM_PRICING["default"])
    return (input_tokens * rates["input"]) + (output_tokens * rates["output"])


def estimate_stt_cost(provider: str | None, seconds: float, model: str | None = None) -> float:
    """Estimate STT cost in USD."""
    if provider == "deepgram" and model:
        rate = DEEPGRAM_MODEL_PRICING.get(model, STT_PRICING["deepgram"])
    else:
        rate = STT_PRICING.get(provider or "", STT_PRICING["default"])
    return seconds * rate


def estimate_tts_cost(provider: str | None, chars: int) -> float:
    """Estimate TTS cost in USD."""
    rate = TTS_PRICING.get(provider or "", TTS_PRICING["default"])
    return chars * rate


def estimate_telephony_cost(direction: str, seconds: float) -> float:
    """Estimate telephony cost in USD."""
    rate = TWILIO_PRICING.get(direction or "inbound", TWILIO_PRICING["inbound"])
    return seconds * rate


def estimate_total_cost(
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    stt_provider: str | None,
    stt_seconds: float,
    tts_provider: str | None,
    tts_chars: int,
    direction: str | None,
    duration_seconds: float,
    stt_model: str | None = None,
) -> float:
    """Sum all estimated costs."""
    return (
        estimate_llm_cost(model, input_tokens, output_tokens)
        + estimate_stt_cost(stt_provider, stt_seconds, stt_model)
        + estimate_tts_cost(tts_provider, tts_chars)
        + estimate_telephony_cost(direction or "inbound", duration_seconds)
    )


# ── Pydantic models ────────────────────────────────────────────

class EstimateRequest(BaseModel):
    duration_seconds: float = Field(default=120, ge=0)
    llm_model: str = Field(default="gpt-4o-mini")
    input_tokens: int = Field(default=500, ge=0)
    output_tokens: int = Field(default=200, ge=0)
    stt_provider: str = Field(default="deepgram")
    stt_model: str = Field(default="nova-3")
    tts_provider: str = Field(default="elevenlabs")
    direction: str = Field(default="inbound")


# ── API Routes ─────────────────────────────────────────────────

@router.get("/overview")
async def get_usage_overview(
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate usage stats for the user's calls over a period."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    base_filter = [UsageLog.user_id == user.id, UsageLog.recorded_at >= cutoff]

    total_calls = (await db.execute(
        select(func.count(UsageLog.id)).where(*base_filter)
    )).scalar() or 0

    total_duration = (await db.execute(
        select(func.coalesce(func.sum(UsageLog.duration_seconds), 0)).where(*base_filter)
    )).scalar() or 0

    total_input = (await db.execute(
        select(func.coalesce(func.sum(UsageLog.input_tokens), 0)).where(*base_filter)
    )).scalar() or 0

    total_output = (await db.execute(
        select(func.coalesce(func.sum(UsageLog.output_tokens), 0)).where(*base_filter)
    )).scalar() or 0

    total_cost = (await db.execute(
        select(func.coalesce(func.sum(UsageLog.estimated_cost_usd), 0)).where(*base_filter)
    )).scalar() or 0

    # Provider breakdown
    provider_rows = (await db.execute(
        select(UsageLog.llm_provider, func.count(UsageLog.id), func.sum(UsageLog.estimated_cost_usd))
        .where(*base_filter, UsageLog.llm_provider.isnot(None))
        .group_by(UsageLog.llm_provider)
    )).all()

    by_provider = {
        row[0] or "unknown": {
            "calls": row[1],
            "cost_usd": round(row[2] or 0, 4),
        }
        for row in provider_rows
    }

    return {
        "period_days": days,
        "total_calls": total_calls,
        "total_duration_minutes": round(total_duration / 60, 1),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "estimated_cost_usd": round(total_cost, 4),
        "by_provider": by_provider,
    }


@router.get("/daily")
async def get_daily_usage(
    days: int = Query(default=30, ge=1, le=90),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Daily usage breakdown with cost. Missing days are filled with zeros."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    base_filter = [UsageLog.user_id == user.id, UsageLog.recorded_at >= cutoff]

    # AN-03: Timezone-aware date extraction (SQLite/PostgreSQL compatible)
    _date_col = _date_expr(UsageLog.recorded_at)
    rows = (await db.execute(
        select(
            _date_col,
            func.count(UsageLog.id),
            func.sum(UsageLog.duration_seconds),
            func.sum(UsageLog.input_tokens),
            func.sum(UsageLog.output_tokens),
            func.sum(UsageLog.estimated_cost_usd),
        )
        .where(*base_filter)
        .group_by(_date_col)
        .order_by(_date_col)
    )).all()

    # BIL-03: Build a dict of existing data, then fill missing days with zeros
    data_by_date: dict[str, dict] = {}
    for row in rows:
        date_str = str(row[0])
        data_by_date[date_str] = {
            "date": date_str,
            "calls": row[1],
            "duration_minutes": round((row[2] or 0) / 60, 1),
            "input_tokens": row[3] or 0,
            "output_tokens": row[4] or 0,
            "cost_usd": round(row[5] or 0, 4),
        }

    daily = []
    for i in range(days):
        date_obj = (now - timedelta(days=i)).date()
        date_str = date_obj.isoformat()
        daily.append(data_by_date.get(date_str, {
            "date": date_str,
            "calls": 0,
            "duration_minutes": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
        }))
    daily.reverse()  # oldest first

    return {"daily": daily}


@router.get("/calls")
async def get_call_usage(
    days: int = Query(default=30, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Per-call usage log entries."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(UsageLog)
        .where(UsageLog.user_id == user.id, UsageLog.recorded_at >= cutoff)
        .order_by(desc(UsageLog.recorded_at))
        .limit(limit)
    )
    entries = result.scalars().all()
    return {"calls": [e.to_dict() for e in entries], "count": len(entries)}


@router.post("/estimate")
async def estimate_cost(request: EstimateRequest, user=Depends(get_current_user)):
    """Estimate the cost of a hypothetical call."""
    llm_cost = estimate_llm_cost(request.llm_model, request.input_tokens, request.output_tokens)
    stt_cost = estimate_stt_cost(request.stt_provider, request.duration_seconds, request.stt_model)
    tts_cost = estimate_tts_cost(request.tts_provider, request.output_tokens * 4)  # rough: 4 chars per token
    tel_cost = estimate_telephony_cost(request.direction, request.duration_seconds)

    return {
        "duration_seconds": request.duration_seconds,
        "llm_model": request.llm_model,
        "cost_breakdown": {
            "llm_usd": round(llm_cost, 6),
            "stt_usd": round(stt_cost, 6),
            "tts_usd": round(tts_cost, 6),
            "telephony_usd": round(tel_cost, 6),
        },
        "total_usd": round(llm_cost + stt_cost + tts_cost + tel_cost, 6),
    }
