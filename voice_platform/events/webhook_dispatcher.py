"""
Voice Platform — Webhook Dispatcher
====================================

GAP-03: Post-Call Webhook Delivery

Dispatches call lifecycle events (call_started, call_ended) to agent-configured
webhook URLs. Supports HMAC-SHA256 signing and automatic retry with exponential backoff.

Usage:
    from voice_platform.events.webhook_dispatcher import WebhookDispatcher
    asyncio.create_task(WebhookDispatcher.dispatch_call_ended(call_log, event))
"""

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from voice_platform.config import settings
from voice_platform.database import ActionLog, Agent, CallLog, Transcript, async_session
from voice_platform.utils.ssrf import is_safe_url as _is_safe_url


class WebhookDispatcher:
    """Dispatch call events to agent-configured webhook URLs."""

    @staticmethod
    async def dispatch_call_started(call_log: CallLog):
        """Fire call_started webhook."""
        await WebhookDispatcher._dispatch(
            event_type="call_started",
            call_log=call_log,
        )

    @staticmethod
    async def dispatch_call_ended(call_log: CallLog):
        """Fire call_ended webhook with full context."""
        await WebhookDispatcher._dispatch(
            event_type="call_ended",
            call_log=call_log,
        )

    @staticmethod
    async def _dispatch(
        event_type: str,
        call_log: CallLog,
    ):
        """Send webhook payload to the agent's configured URL."""

        # Re-fetch the call_log inside a fresh session to avoid
        # DetachedInstanceError when accessing attributes from a
        # call_log that was loaded in a different (now-closed) session.
        call_log_id = call_log.id
        agent_id = call_log.agent_id  # Grab eagerly-loaded scalar before session

        if not agent_id:
            return

        async with async_session() as session:
            from sqlalchemy import select as _select

            # Re-load call_log with all attributes fresh
            fresh_log = await session.get(CallLog, call_log_id)
            if not fresh_log:
                logger.warning(f"Webhook dispatch: CallLog {call_log_id} not found")
                return

            agent = await session.get(Agent, agent_id)
            if not agent or not agent.webhook_url:
                return  # No webhook configured

            webhook_url = agent.webhook_url

            # SEC-05: SSRF blocklist — reject internal/private URLs
            if not _is_safe_url(webhook_url):
                logger.warning(f"🚫 Blocked unsafe webhook URL for agent {agent_id}: {webhook_url}")
                return

            # Build payload (inside session so we can query related tables)
            payload = await WebhookDispatcher._build_payload(
                event_type=event_type,
                call_log=fresh_log,
                session=session,
            )

        # Sign payload
        signature = WebhookDispatcher._sign_payload(payload)

        # Send async (don't block event processing)
        asyncio.create_task(
            WebhookDispatcher._send_webhook(webhook_url, payload, signature)
        )

    @staticmethod
    async def _build_payload(
        event_type: str,
        call_log: CallLog,
        session,
    ) -> Dict[str, Any]:
        """Build the webhook payload."""

        from sqlalchemy import select

        # Fetch transcript
        transcript_result = await session.execute(
            select(Transcript)
            .where(Transcript.call_log_id == call_log.id)
            .order_by(Transcript.timestamp.asc())
        )
        transcripts = transcript_result.scalars().all()

        # Fetch action logs
        action_result = await session.execute(
            select(ActionLog)
            .where(ActionLog.call_log_id == call_log.id)
            .order_by(ActionLog.timestamp.asc())
        )
        actions = action_result.scalars().all()

        # Parse analysis if available
        analysis = None
        if getattr(call_log, 'analysis_json', None):
            try:
                analysis = json.loads(call_log.analysis_json)
            except json.JSONDecodeError:
                pass

        return {
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "call": {
                "id": call_log.id,
                "conversation_id": call_log.conversation_id,
                "direction": call_log.direction,
                "from_phone": call_log.from_phone,
                "to_phone": call_log.to_phone,
                "status": call_log.status,
                "started_at": call_log.started_at.isoformat() if call_log.started_at else None,
                "ended_at": call_log.ended_at.isoformat() if call_log.ended_at else None,
                "duration_secs": call_log.duration_secs,
                "agent_id": call_log.agent_id,
            },
            "transcript": [
                {
                    "role": "agent" if t.sender == "bot" else "customer",
                    "message": t.message,
                    "timestamp": datetime.fromtimestamp(t.timestamp, tz=timezone.utc).isoformat() if t.timestamp else None,
                }
                for t in transcripts
            ],
            "analysis": analysis,
            "actions": [
                {
                    "tool": a.action_type,
                    "status": a.status if hasattr(a, 'status') else None,
                    "result": a.result_json,
                    "created_at": datetime.fromtimestamp(a.timestamp, tz=timezone.utc).isoformat() if a.timestamp else None,
                }
                for a in actions
            ],
        }

    @staticmethod
    def _sign_payload(payload: Dict[str, Any]) -> str:
        """Sign payload with HMAC-SHA256 using platform secret."""
        secret = settings.webhook_signing_secret or settings.jwt_secret

        payload_json = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
        signature = hmac.new(
            secret.encode(),
            payload_json.encode(),
            hashlib.sha256,
        ).hexdigest()

        return signature

    @staticmethod
    async def _send_webhook(
        url: str,
        payload: Dict[str, Any],
        signature: str,
    ):
        """Send the webhook with retries."""
        headers = {
            "Content-Type": "application/json",
            "X-VOIA-Signature": signature,
            "X-VOIA-Event": payload["event"],
        }

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(url, json=payload, headers=headers)

                    if response.status_code < 500:
                        logger.info(
                            f"Webhook delivered to {url}: {response.status_code} "
                            f"(event={payload['event']}, call={payload['call']['id']})"
                        )
                        return
                    else:
                        logger.warning(
                            f"Webhook failed (attempt {attempt+1}): "
                            f"{response.status_code} from {url}"
                        )
            except Exception as e:
                logger.error(f"Webhook delivery error (attempt {attempt+1}): {e}")

            await asyncio.sleep(2 ** attempt)  # Exponential backoff

        logger.error(f"Webhook delivery failed after 3 attempts: {url}")
