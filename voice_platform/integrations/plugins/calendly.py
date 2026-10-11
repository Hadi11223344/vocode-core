"""CalendlyPlugin — Calendly scheduling integration via their API."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class CalendlyPlugin:
    """Calendly scheduling integration plugin."""

    kinds = ("calendly",)

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    def _build_client(self, integration: IntegrationConfiguration) -> Any:
        from voice_platform.integrations.webhook_client import WebhookClient
        base_url = integration.config.get("base_url", "https://api.calendly.com")
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

        headers = {"Content-Type": "application/json"}
        if integration.api_key:
            headers["Authorization"] = f"Bearer {integration.api_key}"

        try:
            if action == "get_availability":
                result = await client.request(
                    url=f"/event_type_available_times?event_type={params.get('event_type_uri', '')}",
                    method="GET", headers=headers,
                )
                return PluginResult(success=True, output=result)
            elif action == "create_invite":
                result = await client.request(
                    url="/scheduling_links", method="POST", headers=headers,
                    body={
                        "max_event_count": 1,
                        "owner": params.get("event_type_uri", config.get("event_type_uri", "")),
                        "owner_type": "EventType",
                    },
                )
                return PluginResult(success=True, output=result)
            elif action == "cancel_event":
                event_uuid = params.get("event_uuid", "")
                result = await client.request(
                    url=f"/scheduled_events/{event_uuid}/cancellation",
                    method="POST", headers=headers,
                    body={"reason": params.get("reason", "Cancelled via VOIA")},
                )
                return PluginResult(success=True, output=result)
            elif action == "list_events":
                org_uri = config.get("organization_uri", "")
                result = await client.request(
                    url=f"/scheduled_events?organization={org_uri}&count=10",
                    method="GET", headers=headers,
                )
                return PluginResult(success=True, output=result)
            else:
                return PluginResult(success=False, error=f"Unknown calendly action: {action}")
        except Exception as e:
            logger.error(f"Calendly action {action} failed: {e}")
            return PluginResult(success=False, error=str(e))
