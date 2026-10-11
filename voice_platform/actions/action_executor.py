"""
Voice Platform — Action Executor
==================================

Handles execution of workflow actions via webhooks, Twilio transfer,
and SMS notifications.

Supported action types:
    - webhook: POST to an external URL with JSON payload
    - transfer: Redirect an active Twilio call to another number
    - notify: Send an SMS notification via Twilio
"""

import json
from typing import Optional

import httpx
from loguru import logger

from voice_platform.utils.ssrf import is_safe_url as _is_safe_url


async def execute_action(
    action_url: str,
    action_type: str,
    params: Optional[str] = None,
    call_context: Optional[dict] = None,
    twilio_account_sid: Optional[str] = None,
    twilio_auth_token: Optional[str] = None,
    twilio_from_number: Optional[str] = None,
) -> dict:
    """
    Execute a workflow action.

    Args:
        action_url: The webhook URL (for webhook type)
        action_type: 'webhook', 'transfer', or 'notify'
        params: JSON-encoded action parameters
        call_context: Call context (must include 'call_sid' for transfer)
        twilio_account_sid: Twilio credentials (for transfer/notify)
        twilio_auth_token: Twilio credentials (for transfer/notify)
        twilio_from_number: Twilio sender number (for notify)

    Returns:
        Dictionary with execution result
    """
    # Parse params from JSON string if provided
    parsed_params = {}
    if params:
        try:
            parsed_params = json.loads(params)
        except json.JSONDecodeError:
            parsed_params = {"raw": params}

    # Dispatch by action type
    if action_type == "transfer":
        return await _execute_transfer(
            parsed_params, call_context or {}, twilio_account_sid, twilio_auth_token
        )
    elif action_type == "notify":
        return await _execute_notify(
            parsed_params, twilio_account_sid, twilio_auth_token, twilio_from_number
        )
    else:
        return await _execute_webhook(action_url, action_type, parsed_params, call_context)


async def _execute_transfer(
    params: dict, call_context: dict, account_sid: Optional[str], auth_token: Optional[str]
) -> dict:
    """Redirect an active Twilio call to a destination number."""
    call_sid = call_context.get("call_sid") or call_context.get("conversation_id")
    destination = params.get("destination") or params.get("to")

    if not call_sid:
        return {"success": False, "error": "Missing call_sid in call_context"}
    if not destination:
        return {"success": False, "error": "Missing destination in params"}
    if not account_sid or not auth_token:
        return {"success": False, "error": "Twilio credentials not configured"}

    try:
        import asyncio

        from twilio.rest import Client

        client = Client(account_sid, auth_token)

        # Build transfer URL that returns <Dial> TwiML
        from urllib.parse import urlencode

        from voice_platform.config import settings

        base = settings.base_url or ""
        clean = base.rstrip("/")
        # Ensure protocol is present (C-3 fix)
        if clean and not clean.startswith(("http://", "https://")):
            clean = f"https://{clean}"
        # Pass destination and conversation_id so the TwiML handler can build the whisper (GAP-02)
        transfer_url = f"{clean}/api/twilio/transfer/dial?{urlencode({'To': destination, 'conversation_id': call_sid})}"

        await asyncio.to_thread(
            client.calls(call_sid).update,
            url=transfer_url,
            method="POST",
            fallback_url=transfer_url,
        )

        logger.info(f"✅ Call {call_sid[:12]} transferred to {destination}")
        return {
            "success": True,
            "call_sid": call_sid,
            "destination": destination,
            "message": f"Call transferred to {destination}",
        }
    except Exception as e:
        logger.error(f"❌ Transfer failed: {e}")
        return {"success": False, "error": str(e)}


async def _execute_notify(
    params: dict, account_sid: Optional[str], auth_token: Optional[str], from_number: Optional[str]
) -> dict:
    """Send an SMS notification via Twilio."""
    to = params.get("to") or params.get("phone_number")
    message = params.get("message") or params.get("body")

    if not to:
        return {"success": False, "error": "Missing recipient phone number (to)"}
    if not message:
        return {"success": False, "error": "Missing message text"}
    if not account_sid or not auth_token:
        return {"success": False, "error": "Twilio credentials not configured"}

    try:
        from voice_platform.integrations.sms_client import SMSClient
        client = SMSClient(account_sid, auth_token, {"from_number": from_number})
        result = await client.send_sms(to=to, body=message)
        return result
    except Exception as e:
        logger.error(f"❌ Notify failed: {e}")
        return {"success": False, "error": str(e)}


async def _execute_webhook(
    action_url: str, action_type: str, params: dict, call_context: Optional[dict]
) -> dict:
    """Execute a webhook action."""
    payload = {
        "action_type": action_type,
        "params": params,
        "context": call_context or {},
    }

    if not _is_safe_url(action_url):
        logger.warning(f"🚫 Blocked unsafe webhook URL: {action_url}")
        return {
            "status_code": 0,
            "success": False,
            "error": "URL blocked: must target an external HTTPS endpoint",
        }

    logger.info(f"🔗 Executing webhook: {action_url}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                action_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

            result = {
                "status_code": response.status_code,
                "success": response.is_success,
                "body": response.text[:500],
            }

            if response.is_success:
                logger.info(f"✅ Webhook executed: {response.status_code}")
            else:
                logger.warning(f"⚠️ Webhook failed: {response.status_code} - {response.text[:200]}")

            return result

    except httpx.TimeoutException:
        logger.error(f"⏰ Webhook timed out: {action_url}")
        return {"status_code": 408, "success": False, "error": "Request timed out"}
    except httpx.RequestError as e:
        logger.error(f"❌ Webhook request failed: {e}")
        return {"status_code": 0, "success": False, "error": str(e)}
