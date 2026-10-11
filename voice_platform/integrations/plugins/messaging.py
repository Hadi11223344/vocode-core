"""MessagingPlugin — WhatsApp Cloud API and Telegram Bot integrations."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class MessagingPlugin:
    """Messaging integration plugin (WhatsApp Cloud, Telegram Bot)."""

    kinds = ("whatsapp_cloud", "telegram_bot")

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[dict]:
        integration = request.integration
        service_type = integration.service_type
        action = request.action
        params = dict(request.params)
        config = dict(integration.config)
        api_key = integration.api_key

        try:
            if service_type == "whatsapp_cloud":
                from voice_platform.integrations.whatsapp_client import WhatsAppClient
                phone_number_id = config.get("phone_number_id", "")
                access_token = api_key or config.get("access_token", "")
                client = WhatsAppClient(
                    access_token=access_token,
                    phone_number_id=phone_number_id,
                    business_account_id=config.get("business_account_id"),
                )
                try:
                    if action == "send_message":
                        result = await client.send_message(to=params.get("to", ""), text=params.get("text", ""))
                        return PluginResult(success=True, output=result)
                    elif action == "send_template":
                        result = await client.send_template(
                            to=params.get("to", ""),
                            template_name=params.get("template_name", ""),
                            language_code=params.get("language_code", "en"),
                            components=params.get("components"),
                        )
                        return PluginResult(success=True, output=result)
                    else:
                        return PluginResult(success=False, error=f"Unknown whatsapp_cloud action: {action}")
                finally:
                    pass

            elif service_type == "telegram_bot":
                from voice_platform.integrations.telegram_client import TelegramClient
                bot_token = api_key or config.get("bot_token", "")
                client = TelegramClient(bot_token=bot_token)
                try:
                    if action == "send_message":
                        result = await client.send_message(
                            chat_id=params.get("chat_id", ""),
                            text=params.get("text", ""),
                        )
                        return PluginResult(success=True, output=result)
                    else:
                        return PluginResult(success=False, error=f"Unknown telegram_bot action: {action}")
                finally:
                    await client.aclose()

            else:
                return PluginResult(success=False, error=f"Unknown messaging service: {service_type}")
        except Exception as e:
            logger.error(f"Messaging action {service_type}/{action} failed: {e}")
            return PluginResult(success=False, error=str(e))
