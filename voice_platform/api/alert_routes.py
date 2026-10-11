"""
Alert routes — Phase 6: Real-time Alerting System.

POST   /api/alerts/rules              Create alert rule
GET    /api/alerts/rules              List alert rules
PUT    /api/alerts/rules/{id}         Update alert rule
DELETE /api/alerts/rules/{id}         Delete alert rule
GET    /api/alerts/history            Alert history
POST   /api/alerts/evaluate           Manually evaluate all rules
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import AlertHistory, AlertRule, CallLog, User, async_session, get_db
from voice_platform.middleware.auth_middleware import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/alerts", tags=["alerts"])


# ── Pydantic models ────────────────────────────────────────────

class CreateAlertRule(BaseModel):
    name: str = Field(..., max_length=255)
    condition_type: str = Field(..., pattern="^(call_failed_count|avg_latency_spike|call_duration_short|quality_score_drop|no_calls)$")
    threshold: float | None = None
    window_minutes: int = Field(default=10, ge=1, le=1440)
    agent_id: int | None = None
    channels: list[str] = Field(default_factory=list)
    channel_config: dict = Field(default_factory=dict)
    cooldown_minutes: int = Field(default=15, ge=1, le=1440)


class UpdateAlertRule(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    condition_type: str | None = None
    threshold: float | None = None
    window_minutes: int | None = None
    agent_id: int | None = None
    channels: list[str] | None = None
    channel_config: dict | None = None
    cooldown_minutes: int | None = None


# ── Alert evaluation engine ────────────────────────────────────

async def _notify(rule: AlertRule, message: str) -> list[str]:
    """Send alert via configured channels. Returns list of succeeded channels."""
    succeeded: list[str] = []
    channels = []
    config = {}
    if rule.channels_json:
        try:
            channels = json.loads(rule.channels_json)
        except Exception:
            pass
    if rule.channel_config_json:
        try:
            config = json.loads(rule.channel_config_json)
        except Exception:
            pass

    # Webhook
    if "webhook" in channels:
        url = config.get("webhook_url")
        if url:
            try:
                import aiohttp
                payload = {
                    "rule": rule.name,
                    "message": message,
                    "condition": rule.condition_type,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                async with aiohttp.ClientSession() as session:
                    await session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10))
                succeeded.append("webhook")
            except Exception as e:
                logger.warning(f"Webhook alert failed for rule {rule.id}: {e}")

    # Slack
    if "slack" in channels:
        token = config.get("slack_token")
        channel = config.get("slack_channel", "#alerts")
        if token:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    await session.post(
                        "https://slack.com/api/chat.postMessage",
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={"channel": channel, "text": f":rotating_light: *{rule.name}*\n{message}"},
                        timeout=aiohttp.ClientTimeout(total=10),
                    )
                succeeded.append("slack")
            except Exception as e:
                logger.warning(f"Slack alert failed for rule {rule.id}: {e}")

    # Email (via shared EmailClient for consistency)
    if "email" in channels:
        to_email = config.get("email_address")
        if to_email:
            try:
                from voice_platform.integrations.email_client import EmailClient
                email_cfg = {
                    "smtp_host": config.get("smtp_server", "localhost"),
                    "smtp_port": config.get("smtp_port", 25),
                    "smtp_user": config.get("smtp_user", config.get("email_from", "")),
                    "from_email": config.get("email_from", "alerts@voice-platform.local"),
                    "from_name": config.get("from_name", "VOIA Alerts"),
                    "use_tls": config.get("use_tls", False),
                }
                client = EmailClient(api_key=config.get("smtp_password", ""), config=email_cfg)
                await client.send_email(
                    to=to_email,
                    subject=f"Alert: {rule.name}",
                    body=message,
                )
                succeeded.append("email")
            except Exception as e:
                logger.warning(f"Email alert failed for rule {rule.id}: {e}")

    # In-app always succeeds (recorded in history)
    succeeded.append("in_app")
    return succeeded


async def evaluate_alert_rule(rule: AlertRule, db: AsyncSession) -> str | None:
    """
    Evaluate a single alert rule. Returns message if triggered, else None.
    """
    if not rule.is_active:
        return None

    # Check cooldown
    now = datetime.now(timezone.utc)
    if rule.last_fired_at:
        # Normalize timezone for comparison
        last = rule.last_fired_at.replace(tzinfo=timezone.utc) if rule.last_fired_at.tzinfo is None else rule.last_fired_at
        cooldown = timedelta(minutes=rule.cooldown_minutes)
        if now - last < cooldown:
            return None

    window_start = now - timedelta(minutes=rule.window_minutes)
    base_filter = [
        CallLog.user_id == rule.user_id,
        CallLog.started_at >= window_start,
    ]
    if rule.agent_id:
        base_filter.append(CallLog.agent_id == rule.agent_id)

    triggered = False
    message = ""

    if rule.condition_type == "call_failed_count":
        result = await db.execute(
            select(func.count(CallLog.id)).where(*base_filter, CallLog.status == "failed")
        )
        count = result.scalar() or 0
        threshold = rule.threshold or 3
        if count >= threshold:
            triggered = True
            message = f"{int(count)} failed calls in the last {rule.window_minutes} minutes"

    elif rule.condition_type == "avg_latency_spike":
        result = await db.execute(
            select(func.avg(CallLog.avg_turn_latency_ms))
            .where(*base_filter, CallLog.avg_turn_latency_ms.isnot(None))
        )
        avg_lat = result.scalar() or 0
        threshold = rule.threshold or 2000
        if avg_lat > threshold:
            triggered = True
            message = f"Average turn latency spiked to {round(avg_lat)}ms (threshold: {threshold}ms)"

    elif rule.condition_type == "call_duration_short":
        result = await db.execute(
            select(func.count(CallLog.id)).where(
                *base_filter,
                CallLog.status == "completed",
                CallLog.duration_secs < (rule.threshold or 30),
            )
        )
        count = result.scalar() or 0
        if count >= (rule.threshold or 5):
            triggered = True
            message = f"{int(count)} calls ended shorter than {rule.threshold or 30}s"

    elif rule.condition_type == "quality_score_drop":
        result = await db.execute(
            select(func.avg(CallLog.quality_score))
            .where(*base_filter, CallLog.quality_score.isnot(None))
        )
        avg_q = result.scalar() or 0
        threshold = rule.threshold or 50
        if avg_q < threshold:
            triggered = True
            message = f"Average quality score dropped to {round(avg_q, 1)} (threshold: {threshold})"

    elif rule.condition_type == "no_calls":
        result = await db.execute(
            select(func.count(CallLog.id)).where(*base_filter)
        )
        count = result.scalar() or 0
        if count == 0:
            triggered = True
            message = f"No calls received in the last {rule.window_minutes} minutes"

    if not triggered:
        return None

    # Send notifications
    channels = await _notify(rule, message)

    # Record history — use savepoint so a failure here doesn't roll back
    # other rules' history inserts when called in a loop.
    try:
        async with db.begin_nested():
            history = AlertHistory(
                user_id=rule.user_id,
                alert_rule_id=rule.id,
                rule_name=rule.name,
                condition_type=rule.condition_type,
                message=message,
                channels=",".join(channels),
            )
            db.add(history)
            # Update last_fired_at
            rule.last_fired_at = now
    except Exception as e:
        logger.error(f"Failed to record alert history for rule {rule.id}: {e}")
        return message

    return message


# ── API Routes ─────────────────────────────────────────────────

@router.post("/rules")
async def create_alert_rule(
    request: CreateAlertRule,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rule = AlertRule(
        user_id=user.id,
        name=request.name,
        condition_type=request.condition_type,
        threshold=request.threshold,
        window_minutes=request.window_minutes,
        agent_id=request.agent_id,
        channels_json=json.dumps(request.channels),
        channel_config_json=json.dumps(request.channel_config),
        cooldown_minutes=request.cooldown_minutes,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return {"rule": rule.to_dict()}


@router.get("/rules")
async def list_alert_rules(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AlertRule).where(AlertRule.user_id == user.id).order_by(desc(AlertRule.created_at))
    )
    rules = result.scalars().all()
    return {"rules": [r.to_dict() for r in rules]}


@router.put("/rules/{rule_id}")
async def update_alert_rule(
    rule_id: int,
    request: UpdateAlertRule,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AlertRule).where(AlertRule.id == rule_id, AlertRule.user_id == user.id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "Alert rule not found")

    if request.name is not None:
        rule.name = request.name
    if request.is_active is not None:
        rule.is_active = request.is_active
    if request.condition_type is not None:
        rule.condition_type = request.condition_type
    if request.threshold is not None:
        rule.threshold = request.threshold
    if request.window_minutes is not None:
        rule.window_minutes = request.window_minutes
    if request.agent_id is not None:
        rule.agent_id = request.agent_id
    if request.channels is not None:
        rule.channels_json = json.dumps(request.channels)
    if request.channel_config is not None:
        rule.channel_config_json = json.dumps(request.channel_config)
    if request.cooldown_minutes is not None:
        rule.cooldown_minutes = request.cooldown_minutes

    await db.commit()
    await db.refresh(rule)
    return {"rule": rule.to_dict()}


@router.delete("/rules/{rule_id}")
async def delete_alert_rule(
    rule_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AlertRule).where(AlertRule.id == rule_id, AlertRule.user_id == user.id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "Alert rule not found")
    await db.delete(rule)
    await db.commit()
    return {"message": "Alert rule deleted"}


@router.get("/history")
async def get_alert_history(
    days: int = Query(default=30, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(AlertHistory)
        .where(AlertHistory.user_id == user.id, AlertHistory.sent_at >= cutoff)
        .order_by(desc(AlertHistory.sent_at))
        .limit(limit)
    )
    entries = result.scalars().all()
    return {"history": [e.to_dict() for e in entries], "count": len(entries)}


@router.post("/evaluate")
async def evaluate_all_rules(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger evaluation of all active rules."""
    result = await db.execute(
        select(AlertRule).where(AlertRule.user_id == user.id, AlertRule.is_active == True)
    )
    rules = result.scalars().all()
    triggered = []
    for rule in rules:
        msg = await evaluate_alert_rule(rule, db)
        if msg:
            triggered.append({"rule": rule.name, "message": msg})
    return {"evaluated": len(rules), "triggered": triggered}
