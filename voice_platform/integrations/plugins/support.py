"""SupportPlugin — customer support integrations (Zendesk, Freshdesk, Intercom)."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class SupportPlugin:
    """Customer support platform integration plugin."""

    kinds = ("zendesk", "freshdesk", "intercom")

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

            if service_type == "zendesk":
                subdomain = config.get("subdomain", "")
                base_url = f"https://{subdomain}"
                auth_header = f"Bearer {api_key}" if api_key else ""
            elif service_type == "freshdesk":
                domain = config.get("domain", "")
                base_url = f"https://{domain}"
                auth_header = f"Basic {api_key}" if api_key else ""
            else:  # intercom
                base_url = config.get("base_url", "https://api.intercom.io")
                auth_header = f"Bearer {api_key}" if api_key else ""

            client = WebhookClient({"base_url": base_url})
            headers = {"Content-Type": "application/json", "Authorization": auth_header}

            endpoint_map = {
                "zendesk": {
                    "create_ticket": ("POST", "/api/v2/tickets.json", {"ticket": params}),
                    "update_ticket": ("PUT", f"/api/v2/tickets/{params.get('ticket_id', '')}.json", {"ticket": params}),
                    "search_tickets": ("GET", f"/api/v2/search.json?query={params.get('query', '')}", None),
                    "add_comment": ("PUT", f"/api/v2/tickets/{params.get('ticket_id', '')}.json",
                                   {"ticket": {"comment": {"body": params.get("comment", "")}}}),
                    "get_ticket": ("GET", f"/api/v2/tickets/{params.get('ticket_id', '')}.json", None),
                },
                "freshdesk": {
                    "create_ticket": ("POST", "/api/v2/tickets", params),
                    "update_ticket": ("PUT", f"/api/v2/tickets/{params.get('ticket_id', '')}", params),
                    "search_tickets": ("GET", f"/api/v2/search/tickets?query=\"{params.get('query', '')}\"", None),
                    "add_note": ("POST", f"/api/v2/tickets/{params.get('ticket_id', '')}/notes",
                                {"body": params.get("note", "")}),
                    "get_ticket": ("GET", f"/api/v2/tickets/{params.get('ticket_id', '')}", None),
                },
                "intercom": {
                    "create_contact": ("POST", "/contacts", params),
                    "create_conversation": ("POST", "/conversations", params),
                    "send_message": ("POST", "/messages", params),
                    "search_contacts": ("POST", "/contacts/search", {"query": {"field": "email", "operator": "=", "value": params.get("email", "")}}),
                    "add_tag": ("POST", f"/contacts/{params.get('contact_id', '')}/tags", {"id": params.get("tag_id", "")}),
                },
            }

            endpoints = endpoint_map.get(service_type, {})
            if action not in endpoints:
                return PluginResult(success=False, error=f"Unknown {service_type} action: {action}")

            method, url, body = endpoints[action]
            result = await client.request(url=url, method=method, headers=headers, body=body)
            return PluginResult(success=True, output=result)
        except Exception as e:
            logger.error(f"Support action {service_type}/{action} failed: {e}")
            return PluginResult(success=False, error=str(e))
