"""PaymentsPlugin — Stripe payment integration."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class PaymentsPlugin:
    """Stripe payment integration plugin."""

    kinds = ("stripe",)

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[dict]:
        integration = request.integration
        action = request.action
        params = dict(request.params)
        api_key = integration.api_key

        try:
            from urllib.parse import urlencode
            from voice_platform.integrations.webhook_client import WebhookClient

            base_url = "https://api.stripe.com/v1"
            client = WebhookClient({"base_url": base_url})
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            action_map = {
                "create_payment_link": ("POST", "/payment_links"),
                "create_invoice": ("POST", "/invoices"),
                "check_payment_status": ("GET", f"/payment_intents/{params.get('payment_id', '')}"),
                "list_invoices": ("GET", f"/invoices?customer={params.get('customer_id', '')}"),
                "create_customer": ("POST", "/customers"),
            }

            if action not in action_map:
                return PluginResult(success=False, error=f"Unknown stripe action: {action}")

            method, url = action_map[action]
            if method != "GET":
                body_params = {k: v for k, v in params.items() if k not in ("payment_id", "customer_id")}
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                result = await client.request(url=url, method=method, headers=headers, body=urlencode(body_params))
            else:
                result = await client.request(url=url, method=method, headers=headers, body=None)
            return PluginResult(success=True, output=result)
        except Exception as e:
            logger.error(f"Stripe action {action} failed: {e}")
            return PluginResult(success=False, error=str(e))
