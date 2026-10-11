"""CRMPlugin — CRM integrations (HubSpot, Salesforce, Pipedrive, GoHighLevel)."""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class CRMPlugin:
    """CRM integration plugin — dispatches to sub-clients by service_type."""

    kinds = ("hubspot", "salesforce", "pipedrive", "gohighlevel")

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    async def _execute_hubspot(self, action: str, params: dict, api_key: str | None, config: dict) -> dict:
        from voice_platform.integrations.hubspot_client import HubSpotClient
        client = HubSpotClient(api_key or "", config)
        record_id = str(params.pop("id", "")) if "id" in params else ""
        action_params = {k: v for k, v in params.items() if k not in ("object_type", "query")}

        if action == "create_contact":
            return await client.create_contact(**action_params)
        elif action == "update_contact":
            return await client.update_contact(record_id, **action_params)
        elif action == "get_contact":
            return await client.get_contact(record_id)
        elif action == "search_contacts":
            return await client.search_contacts(query=params.get("query", ""), limit=int(params.get("limit", 10)))
        elif action == "create_deal":
            return await client.create_deal(**action_params)
        elif action == "update_deal":
            return await client.update_deal(record_id, **action_params)
        elif action == "search_deals":
            return await client.search_deals(query=params.get("query", ""), limit=int(params.get("limit", 10)))
        elif action == "create_note":
            return await client.create_note(
                body_text=params.get("body", params.get("note", "")),
                contact_id=params.get("contact_id"),
                deal_id=params.get("deal_id"),
            )
        elif action == "add_note":
            return await client.create_note(
                body_text=params.get("body", params.get("content", params.get("note", ""))),
                contact_id=params.get("contact_id"),
                deal_id=params.get("deal_id"),
            )
        elif action == "associate":
            return await client.associate(
                from_type=params.get("from_type", "contact"),
                from_id=params.get("from_id", ""),
                to_type=params.get("to_type", "deal"),
                to_id=params.get("to_id", ""),
                association_type_id=int(params.get("association_type_id", 1)),
            )
        else:
            raise ValueError(f"Unknown hubspot action: {action}")

    async def _execute_salesforce(self, action: str, params: dict, api_key: str | None, config: dict) -> dict:
        from voice_platform.integrations.salesforce_client import SalesforceClient
        client = SalesforceClient(api_key or "", config)
        record_id = str(params.pop("id", "")) if "id" in params else ""
        action_params = {k: v for k, v in params.items() if k not in ("object_type", "query")}

        if action == "create_lead":
            return await client.create_lead(**action_params)
        elif action == "update_lead":
            return await client.update_lead(record_id, **action_params)
        elif action == "create_contact":
            return await client.create_contact(**action_params)
        elif action == "update_contact":
            return await client.update_contact(record_id, **action_params)
        elif action == "create_opportunity":
            return await client.create_opportunity(**action_params)
        elif action == "update_opportunity":
            return await client.update_opportunity(record_id, **action_params)
        elif action == "get_record":
            return await client.get_record(sobject_type=params.get("object_type", "Lead"), record_id=record_id)
        elif action in ("search_records", "search"):
            return await client.search(params.get("query", ""))
        elif action == "query":
            return await client.query(params.get("query", params.get("soql", "")))
        else:
            raise ValueError(f"Unknown salesforce action: {action}")

    async def _execute_pipedrive(self, action: str, params: dict, api_key: str | None, config: dict) -> dict:
        from voice_platform.integrations.pipedrive_client import PipedriveClient
        client = PipedriveClient(api_key or "", config)
        record_id = str(params.pop("id", "")) if "id" in params else ""
        action_params = {k: v for k, v in params.items() if k not in ("query",)}

        if action == "create_person":
            return await client.create_person(**action_params)
        elif action == "update_person":
            return await client.update_person(record_id, **action_params)
        elif action == "search_persons":
            return await client.search_persons(query=params.get("query", ""), limit=int(params.get("limit", 10)))
        elif action == "create_deal":
            return await client.create_deal(**action_params)
        elif action == "update_deal":
            return await client.update_deal(record_id, **action_params)
        elif action == "search_deals":
            return await client.search_deals(query=params.get("query", ""), limit=int(params.get("limit", 10)))
        elif action == "add_note":
            return await client.add_note(
                content=params.get("content", params.get("body", params.get("note", ""))),
                deal_id=params.get("deal_id"),
                person_id=params.get("person_id"),
            )
        elif action == "create_activity":
            return await client.create_activity(**action_params)
        else:
            raise ValueError(f"Unknown pipedrive action: {action}")

    async def _execute_gohighlevel(self, action: str, params: dict, api_key: str | None, config: dict) -> dict:
        from voice_platform.integrations.webhook_client import WebhookClient
        base_url = config.get("base_url", "https://rest.gohighlevel.com/v1")
        client = WebhookClient({"base_url": base_url})
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        endpoint_map = {
            "create_contact": ("POST", "/contacts"),
            "update_contact": ("PUT", f"/contacts/{params.get('id', '')}"),
            "create_opportunity": ("POST", "/opportunities"),
            "add_tag": ("POST", f"/contacts/{params.get('id', '')}/tags"),
            "send_sms": ("POST", "/conversations/messages"),
            "create_task": ("POST", f"/contacts/{params.get('id', '')}/tasks"),
        }
        if action not in endpoint_map:
            raise ValueError(f"Unknown gohighlevel action: {action}")
        method, url = endpoint_map[action]
        body = {k: v for k, v in params.items() if k not in ("id",)}
        return await client.request(url=url, method=method, headers=headers, body=body if method != "GET" else None)

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[dict]:
        integration = request.integration
        service_type = integration.service_type
        action = request.action
        params = dict(request.params)
        config = dict(integration.config)
        api_key = integration.api_key

        try:
            if service_type == "hubspot":
                result = await self._execute_hubspot(action, params, api_key, config)
            elif service_type == "salesforce":
                result = await self._execute_salesforce(action, params, api_key, config)
            elif service_type == "pipedrive":
                result = await self._execute_pipedrive(action, params, api_key, config)
            elif service_type == "gohighlevel":
                result = await self._execute_gohighlevel(action, params, api_key, config)
            else:
                return PluginResult(success=False, error=f"Unknown CRM service: {service_type}")
            return PluginResult(success=True, output=result)
        except Exception as e:
            logger.error(f"CRM action {service_type}/{action} failed: {e}")
            return PluginResult(success=False, error=str(e))
