"""SMSPlugin — Twilio SMS integration."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class SMSPlugin:
    """Twilio SMS integration plugin."""

    kinds = ("sms",)

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    def _build_client(self, integration: IntegrationConfiguration) -> Any:
        from voice_platform.integrations.sms_client import SMSClient
        config = dict(integration.config)
        account_sid = config.get("account_sid", "")
        auth_token = integration.api_key or config.get("auth_token", "")
        return SMSClient(account_sid, auth_token, config)

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[dict]:
        integration = request.integration
        action = request.action
        params = dict(request.params)

        client = (
            self._client_factory(integration)
            if self._client_factory
            else self._build_client(integration)
        )

        try:
            if action == "send_sms":
                result = await client.send_sms(
                    to=params.get("to", ""),
                    body=params.get("body", ""),
                    from_number=params.get("from_number"),
                    media_url=params.get("media_url"),
                )
                return PluginResult(success=True, output=result)
            else:
                return PluginResult(success=False, error=f"Unknown SMS action: {action}")
        except Exception as e:
            logger.error(f"SMS action {action} failed: {e}")
            return PluginResult(success=False, error=str(e))
