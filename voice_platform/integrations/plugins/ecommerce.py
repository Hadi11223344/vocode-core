"""EcommercePlugin — Shopify store integration."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class EcommercePlugin:
    """Shopify ecommerce integration plugin."""

    kinds = ("shopify",)

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[dict]:
        integration = request.integration
        action = request.action
        params = dict(request.params)
        config = dict(integration.config)
        api_key = integration.api_key

        try:
            from voice_platform.integrations.webhook_client import WebhookClient

            shop_domain = config.get("shop_domain", "")
            api_version = config.get("api_version", "2024-01")
            base_url = f"https://{shop_domain}/admin/api/{api_version}"
            client = WebhookClient({"base_url": base_url})
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["X-Shopify-Access-Token"] = api_key

            action_map = {
                "get_order": ("GET", f"/orders/{params.get('order_id', '')}.json"),
                "search_orders": ("GET", f"/orders.json?status=any&name={params.get('query', '')}"),
                "get_product": ("GET", f"/products/{params.get('product_id', '')}.json"),
                "search_products": ("GET", f"/products.json?title={params.get('query', '')}"),
                "get_customer": ("GET", f"/customers/{params.get('customer_id', '')}.json"),
                "update_order": ("PUT", f"/orders/{params.get('order_id', '')}.json"),
            }

            if action not in action_map:
                return PluginResult(success=False, error=f"Unknown shopify action: {action}")

            method, url = action_map[action]
            body = params.get("body") if method != "GET" else None
            result = await client.request(url=url, method=method, headers=headers, body=body)
            return PluginResult(success=True, output=result)
        except Exception as e:
            logger.error(f"Shopify action {action} failed: {e}")
            return PluginResult(success=False, error=str(e))
