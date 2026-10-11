"""
Voice Platform — SMS Integration Client
==========================================

Sends SMS messages via Twilio during or after calls.

Use cases:
    - Send appointment confirmation to caller
    - Send follow-up link after call
    - Notify team members about call outcomes
    - Send verification codes

Requires Twilio credentials (account_sid + auth_token + from_number).
"""

from typing import Optional

from loguru import logger


class SMSClient:
    """
    Twilio SMS client for sending text messages.
    
    Config:
        from_number: Twilio phone number to send from (E.164)
    """
    
    def __init__(self, account_sid: str, auth_token: str, config: dict = None):
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._config = config or {}
        self._from_number = self._config.get("from_number", "")
    
    async def send_sms(
        self,
        to: str,
        body: str,
        from_number: Optional[str] = None,
        media_url: Optional[str] = None,
    ) -> dict:
        """
        Send an SMS or MMS message via Twilio.

        Args:
            to: Recipient phone number (E.164 format)
            body: Message text (max 1600 chars for Twilio)
            from_number: Override sender number (default: config from_number)
            media_url: Optional public URL of media to send (MMS).
                       Must be a publicly accessible URL. Twilio will fetch
                       the media and attach it to the message.

        Returns:
            dict with message_sid, status, to, body, media_url
        """
        import asyncio

        from twilio.rest import Client

        sender = from_number or self._from_number
        if not sender:
            return {"success": False, "error": "No sender phone number configured for SMS. Please set the 'from_number' in your SMS integration config.", "to": to}

        if not to:
            return {"success": False, "error": "Recipient phone number is required", "to": to}

        # Truncate body to Twilio's limit
        body = body[:1600] if body else ""

        def _send():
            client = Client(self._account_sid, self._auth_token)
            create_kwargs = {
                "body": body,
                "from_": sender,
                "to": to,
            }
            if media_url:
                create_kwargs["media_url"] = media_url
            message = client.messages.create(**create_kwargs)
            return {
                "message_sid": message.sid,
                "status": message.status,
                "to": to,
                "body_preview": body[:100],
                "media_url": media_url,
                "success": True,
            }

        try:
            result = await asyncio.to_thread(_send)
            if media_url:
                logger.info(f"📱 MMS sent to {to}: {body[:50]}... (media: {media_url})")
            else:
                logger.info(f"📱 SMS sent to {to}: {body[:50]}...")
            return result
        except Exception as e:
            logger.error(f"Failed to send SMS to {to}: {e}")
            return {
                "success": False,
                "error": str(e),
                "to": to,
            }
