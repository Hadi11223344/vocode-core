"""CalComPlugin — Cal.com booking integration via their API."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class CalComPlugin:
    """Cal.com booking integration plugin."""

    kinds = ("cal_com",)

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    def _build_client(self, integration: IntegrationConfiguration) -> Any:
        from voice_platform.integrations.webhook_client import WebhookClient
        base_url = integration.config.get("base_url", "https://api.cal.com/v1")
        return WebhookClient({"base_url": base_url})

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[dict]:
        integration = request.integration
        action = request.action
        params = dict(request.params)
        config = dict(integration.config)

        client = (
            self._client_factory(integration)
            if self._client_factory
            else self._build_client(integration)
        )

        headers = {}
        if integration.api_key:
            headers["Authorization"] = f"Bearer {integration.api_key}"

        try:
            if action == "get_availability":
                result = await client.request(
                    url=f"/availability?eventTypeId={params.get('event_type_id', '')}",
                    method="GET", headers=headers,
                )
                return PluginResult(success=True, output=result)
            elif action == "create_booking":
                result = await client.request(
                    url="/bookings", method="POST", headers=headers,
                    body={
                        "eventTypeId": int(params.get("event_type_id", 0)),
                        "start": params.get("start", ""),
                        "name": params.get("name", ""),
                        "email": params.get("email", ""),
                        "notes": params.get("notes", ""),
                    },
                )
                return PluginResult(success=True, output=result)
            elif action == "cancel_booking":
                booking_id = params.get("booking_id", "")
                result = await client.request(
                    url=f"/bookings/{booking_id}/cancel",
                    method="DELETE", headers=headers,
                )
                return PluginResult(success=True, output=result)
            else:
                return PluginResult(success=False, error=f"Unknown cal_com action: {action}")
        except Exception as e:
            logger.error(f"Cal.com action {action} failed: {e}")
            return PluginResult(success=False, error=str(e))
