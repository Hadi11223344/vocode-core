"""
Voice Platform — WhatsApp Cloud API Client
=============================================

Send messages via Meta's WhatsApp Cloud API.

Requires:
    WHATSAPP_BUSINESS_ACCOUNT_ID
    WHATSAPP_ACCESS_TOKEN
    WHATSAPP_PHONE_NUMBER_ID

Setup:
    1. Create a Meta Developer account
    2. Set up a WhatsApp Business App
    3. Add a phone number to the WhatsApp Business Account
    4. Generate a permanent access token

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

from typing import Optional

import httpx
from loguru import logger


class WhatsAppClient:
    """Client for Meta's WhatsApp Cloud API."""

    BASE_URL = "https://graph.facebook.com/v18.0"

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        business_account_id: Optional[str] = None,
    ) -> None:
        self._token = access_token
        self._phone_number_id = phone_number_id
        self._business_account_id = business_account_id

    async def send_message(self, to: str, text: str) -> dict:
        """Send a plain text message to a WhatsApp number.

        Args:
            to: Recipient phone number in E.164 format (e.g., +1234567890)
            text: Message text (max 4096 chars)

        Returns:
            dict with success status and message ID or error
        """
        url = f"{self.BASE_URL}/{self._phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": text[:4096]},
        }
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0, verify=True) as client:
                resp = await client.post(url, json=payload, headers=headers)
                data = resp.json()

            if resp.status_code >= 400:
                logger.warning(f"WhatsApp API error {resp.status_code}: {data}")
                return {
                    "success": False,
                    "error": data.get("error", {}).get("message", str(data)),
                }

            message_id = (
                data.get("messages", [{}])[0].get("id")
                if data.get("messages")
                else None
            )
            logger.info(f"WhatsApp message sent to {to}: {message_id}")
            return {
                "success": True,
                "message_id": message_id,
                "to": to,
            }
        except Exception as e:
            logger.error(f"WhatsApp send failed: {e}")
            return {"success": False, "error": str(e)}

    async def test_connection(self) -> dict:
        """
        Verify the WhatsApp access token by fetching phone number details.
        Returns success dict or raises RuntimeError on failure.
        """
        url = f"{self.BASE_URL}/{self._phone_number_id}"
        headers = {
            "Authorization": f"Bearer {self._token}",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=True) as client:
                resp = await client.get(url, headers=headers)
                data = resp.json()

            if resp.status_code >= 400:
                err = data.get("error", {}).get("message", str(data))
                raise RuntimeError(f"WhatsApp API error {resp.status_code}: {err}")

            return {
                "success": True,
                "phone_number_id": self._phone_number_id,
                "display_name": data.get("display_phone_number"),
                "verified": data.get("is_valid_whatsapp_number", False),
            }
        except Exception as e:
            logger.error(f"WhatsApp test connection failed: {e}")
            raise RuntimeError(f"WhatsApp connection failed: {e}")

    async def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str = "en",
        components: Optional[list] = None,
    ) -> dict:
        """Send a pre-approved template message.

        Templates must be approved by Meta before use.
        """
        url = f"{self.BASE_URL}/{self._phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components or [],
            },
        }
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0, verify=True) as client:
                resp = await client.post(url, json=payload, headers=headers)
                data = resp.json()

            if resp.status_code >= 400:
                return {
                    "success": False,
                    "error": data.get("error", {}).get("message", str(data)),
                }

            return {"success": True, "message_id": data.get("messages", [{}])[0].get("id")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def normalize_phone(phone: str) -> str:
        """Normalize a phone number to E.164 format."""
        cleaned = "".join(c for c in phone if c.isdigit() or c == "+")
        if not cleaned.startswith("+"):
            # Assume US if no country code — caller should provide full number
            cleaned = "+" + cleaned
        return cleaned
