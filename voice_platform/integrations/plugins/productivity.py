"""ProductivityPlugin — Notion and Airtable integrations."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class ProductivityPlugin:
    """Productivity tool integration plugin (Notion, Airtable)."""

    kinds = ("notion", "airtable")

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
            from voice_platform.integrations.webhook_client import WebhookClient

            if service_type == "notion":
                base_url = "https://api.notion.com/v1"
                headers = {
                    "Content-Type": "application/json",
                    "Notion-Version": "2022-06-28",
                }
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                action_map = {
                    "create_page": ("POST", "/pages", params),
                    "query_database": ("POST", f"/databases/{params.get('database_id', '')}/query", params),
                    "search": ("POST", "/search", {"query": params.get("query", "")}),
                    "update_page": ("PATCH", f"/pages/{params.get('page_id', '')}", params),
                    "get_page": ("GET", f"/pages/{params.get('page_id', '')}", None),
                }
            else:  # airtable
                base_url = f"https://api.airtable.com/v0"
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                base_id = config.get("base_id", "")
                table_name = params.get("table_name", config.get("table_name", ""))
                action_map = {
                    "list_records": ("GET", f"/{base_id}/{table_name}?maxRecords={params.get('max_records', 100)}", None),
                    "create_record": ("POST", f"/{base_id}/{table_name}", {"records": [{"fields": params.get("fields", params)}]}),
                    "update_record": ("PATCH", f"/{base_id}/{table_name}", {"records": [{"id": params.get("record_id", ""), "fields": params.get("fields", params)}]}),
                    "search_records": ("GET", f"/{base_id}/{table_name}?filterByFormula={params.get('query', '')}", None),
                }

            if action not in action_map:
                return PluginResult(success=False, error=f"Unknown {service_type} action: {action}")

            client = WebhookClient({"base_url": base_url})
            method, url, body = action_map[action]
            result = await client.request(url=url, method=method, headers=headers, body=body)
            return PluginResult(success=True, output=result)
        except Exception as e:
            logger.error(f"Productivity action {service_type}/{action} failed: {e}")
            return PluginResult(success=False, error=str(e))
