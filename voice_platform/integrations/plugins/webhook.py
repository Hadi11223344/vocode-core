"""WebhookPlugin — generic webhook and HTTP-based integrations.

Handles: webhook, zapier, slack, make, discord, microsoft_teams.
All are HTTP POST wrappers — if any diverge significantly, split later.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class WebhookPlugin:
    """Generic webhook / HTTP request integration plugin."""

    kinds = ("webhook", "zapier", "slack", "make", "discord", "microsoft_teams")

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    def _build_client(self, integration: IntegrationConfiguration) -> Any:
        from voice_platform.integrations.webhook_client import WebhookClient
        return WebhookClient(dict(integration.config))

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

        try:
            url = params.get("url", config.get("url", "") or config.get("webhook_url", "") or config.get("base_url", ""))
            method = params.get("method", config.get("method", "POST"))
            headers = params.get("headers", {})

            api_key = integration.api_key
            if api_key:
                headers.setdefault("Authorization", f"Bearer {api_key}")

            body = params.get("body", params.get("payload", {}))
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except json.JSONDecodeError:
                    body = {"data": body}

            result = await client.request(
                url=url,
                method=method,
                headers=headers,
                body=body,
                auth_header=headers.get("Authorization"),
            )

            response_mappings = params.get("response_mappings", {})
            if response_mappings and isinstance(response_mappings, dict):
                from voice_platform.integrations.webhook_client import WebhookClient
                extracted = WebhookClient.extract_response_data(result, response_mappings)
                result["extracted"] = extracted

            if not result.get("success", False):
                error = result.get("error") or f"HTTP request failed with status {result.get('status_code', 0)}"
                return PluginResult(success=False, output=result, error=error)

            return PluginResult(success=True, output=result)
        except Exception as e:
            logger.error(f"Webhook action {action} failed: {e}")
            return PluginResult(success=False, error=str(e))
