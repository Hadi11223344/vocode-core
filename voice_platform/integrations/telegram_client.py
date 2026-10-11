"""
Voice Platform — Telegram Bot API Client
========================================

Send messages via Telegram Bot API.

Requires:
    TELEGRAM_BOT_TOKEN

Setup:
    1. Message @BotFather on Telegram
    2. Create a new bot with /newbot
    3. Copy the token
    4. To send to a user, they must first start the bot and share their chat ID

Docs: https://core.telegram.org/bots/api
"""

import asyncio
from typing import Optional

import httpx
from loguru import logger


class TelegramClient:
    """Client for the Telegram Bot API."""

    BASE_URL = "https://api.telegram.org/bot{token}"
    MAX_RETRIES = 3

    def __init__(self, bot_token: str) -> None:
        self._token = bot_token
        self._base = self.BASE_URL.format(token=bot_token)
        self._client: Optional[httpx.AsyncClient] = None

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make a Telegram API request with retries on transient errors."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0, verify=True)
        url = f"{self._base}{path}"
        last_error = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                resp = await self._client.request(method, url, **kwargs)
                return resp.json()
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = str(e)
                if attempt < self.MAX_RETRIES:
                    backoff = 2 ** attempt
                    logger.warning(f"Telegram {path} failed ({e}), retrying in {backoff}s")
                    await asyncio.sleep(backoff)
                    continue
                raise
        raise RuntimeError(f"Telegram {path} failed after retries: {last_error}")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def send_message(self, chat_id: str, text: str) -> dict:
        """Send a text message to a Telegram chat.

        Args:
            chat_id: Telegram chat ID (numeric string) or @channel_username
            text: Message text (max 4096 chars, MarkdownV2 supported)

        Returns:
            dict with success status and message ID or error
        """
        payload = {
            "chat_id": chat_id,
            "text": text[:4096],
            "parse_mode": "MarkdownV2",
        }

        try:
            data = await self._request("POST", "/sendMessage", json=payload)

            if not data.get("ok"):
                logger.warning(f"Telegram API error: {data}")
                return {
                    "success": False,
                    "error": data.get("description", str(data)),
                }

            message_id = data.get("result", {}).get("message_id")
            logger.info(f"Telegram message sent to {chat_id}: {message_id}")
            return {
                "success": True,
                "message_id": message_id,
                "chat_id": chat_id,
            }
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return {"success": False, "error": str(e)}

    async def test_connection(self) -> dict:
        """
        Verify the Telegram bot token by calling getMe.
        Returns success dict or raises RuntimeError on failure.
        """
        try:
            data = await self._request("GET", "/getMe")

            if not data.get("ok"):
                err = data.get("description", str(data))
                raise RuntimeError(f"Telegram API error: {err}")

            bot = data.get("result", {})
            logger.info(f"Telegram bot connected: @{bot.get('username')}")
            return {
                "success": True,
                "bot_username": bot.get("username"),
                "bot_name": bot.get("first_name"),
            }
        except Exception as e:
            logger.error(f"Telegram test connection failed: {e}")
            raise RuntimeError(f"Telegram connection failed: {e}")

    async def get_updates(self, limit: int = 10) -> list:
        """Fetch recent updates to discover chat IDs.

        Useful for admin dashboards to show which users have started the bot.
        """
        try:
            data = await self._request("GET", "/getUpdates", params={"limit": limit})

            if not data.get("ok"):
                return []
            return data.get("result", [])
        except Exception:
            return []

    @staticmethod
    def escape_markdown(text: str) -> str:
        """Escape special characters for Telegram MarkdownV2."""
        chars = r"_[]()~`>#+-=|{}.!"
        for c in chars:
            text = text.replace(c, f"\\{c}")
        return text
