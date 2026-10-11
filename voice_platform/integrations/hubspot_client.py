"""
Voice Platform — HubSpot CRM Client
======================================

Dedicated HubSpot CRM client using the HubSpot API v3.
Reference: https://developers.hubspot.com/docs/api/crm

Supported actions:
    - create_contact     — Create a new contact
    - update_contact     — Update an existing contact
    - get_contact        — Get contact by ID
    - search_contacts    — Search contacts by property value
    - create_deal        — Create a new deal
    - update_deal        — Update a deal
    - search_deals       — Search deals
    - create_note        — Create an engagement note
    - associate          — Associate objects (e.g. contact→deal)
"""

import asyncio
from typing import Any, Optional

import httpx
from loguru import logger

BASE_URL = "https://api.hubapi.com"
TIMEOUT = 30.0
MAX_RETRIES = 3


class HubSpotClient:
    """
    HubSpot CRM v3 API client.

    Args:
        api_key: HubSpot private app access token (Bearer token).
        config: Optional extra config (unused currently).
    """

    def __init__(self, api_key: str, config: dict | None = None):
        self._api_key = api_key
        self._config = config or {}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        body: dict | list | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request to the HubSpot API with retry."""
        url = f"{BASE_URL}{path}"
        last_error = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT, verify=True) as client:
                    resp = await client.request(
                        method,
                        url,
                        headers=self._headers(),
                        json=body,
                        params=params,
                    )
                    data = resp.json() if resp.content else {}

                    # Retry on 5xx and 429 (HubSpot rate limit) with exponential backoff
                    if resp.status_code >= 500 or resp.status_code == 429:
                        last_error = data.get("message", resp.text[:300])
                        if attempt < MAX_RETRIES:
                            backoff = 2 ** attempt
                            logger.warning(
                                f"HubSpot {method} {path} returned {resp.status_code}, "
                                f"retrying in {backoff}s (attempt {attempt + 1}/{MAX_RETRIES})"
                            )
                            await asyncio.sleep(backoff)
                            continue

                    if resp.status_code >= 400:
                        error_msg = data.get("message", resp.text[:300])
                        logger.error(f"HubSpot API error {resp.status_code}: {error_msg}")
                        return {
                            "success": False,
                            "status_code": resp.status_code,
                            "error": error_msg,
                        }
                    return {"success": True, "status_code": resp.status_code, "data": data}

            except httpx.TimeoutException:
                last_error = "Request timed out"
                if attempt < MAX_RETRIES:
                    backoff = 2 ** attempt
                    logger.warning(f"HubSpot timeout, retrying in {backoff}s (attempt {attempt + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(backoff)
                    continue
                return {"success": False, "error": "Request timed out", "status_code": 0}
            except Exception as e:
                last_error = str(e)
                if attempt < MAX_RETRIES:
                    backoff = 2 ** attempt
                    logger.warning(f"HubSpot error: {e}, retrying in {backoff}s (attempt {attempt + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(backoff)
                    continue
                return {"success": False, "error": last_error, "status_code": 0}

        return {"success": False, "error": last_error or "Request failed after all retries", "status_code": 0}

    # ── Contacts ────────────────────────────────────────────

    async def create_contact(self, **kwargs) -> dict:
        """
        Create a HubSpot contact.

        Expected params: email, firstname, lastname, phone, company, etc.
        See: https://developers.hubspot.com/docs/api/crm/contacts
        """
        properties = {k: str(v) for k, v in kwargs.items() if v is not None}
        return await self._request("POST", "/crm/v3/objects/contacts", body={
            "properties": properties,
        })

    async def update_contact(self, contact_id: str, **kwargs) -> dict:
        """Update a HubSpot contact by ID."""
        properties = {k: str(v) for k, v in kwargs.items() if k != "id" and v is not None}
        return await self._request("PATCH", f"/crm/v3/objects/contacts/{contact_id}", body={
            "properties": properties,
        })

    async def get_contact(self, contact_id: str, properties: list[str] | None = None) -> dict:
        """Get a contact by ID with optional property selection."""
        params = {}
        if properties:
            params["properties"] = ",".join(properties)
        return await self._request("GET", f"/crm/v3/objects/contacts/{contact_id}", params=params)

    async def search_contacts(self, query: str = "", filters: list[dict] | None = None, limit: int = 10) -> dict:
        """
        Search contacts using HubSpot's search API.

        Simple usage: search_contacts(query="john@example.com")
        Advanced: search_contacts(filters=[{"propertyName": "email", "operator": "EQ", "value": "..."}])
        See: https://developers.hubspot.com/docs/api/crm/search
        """
        body: dict[str, Any] = {"limit": min(limit, 100)}
        if filters:
            body["filterGroups"] = [{"filters": filters}]
        elif query:
            # Default: search by email or name
            body["filterGroups"] = [
                {"filters": [{"propertyName": "email", "operator": "CONTAINS_TOKEN", "value": query}]},
            ]
            # HubSpot search also supports a query string
            body["query"] = query
        return await self._request("POST", "/crm/v3/objects/contacts/search", body=body)

    # ── Deals ───────────────────────────────────────────────

    async def create_deal(self, **kwargs) -> dict:
        """
        Create a HubSpot deal.

        Expected params: dealname, pipeline, dealstage, amount, etc.
        See: https://developers.hubspot.com/docs/api/crm/deals
        """
        properties = {k: str(v) for k, v in kwargs.items() if v is not None}
        return await self._request("POST", "/crm/v3/objects/deals", body={
            "properties": properties,
        })

    async def update_deal(self, deal_id: str, **kwargs) -> dict:
        """Update a deal by ID."""
        properties = {k: str(v) for k, v in kwargs.items() if k != "id" and v is not None}
        return await self._request("PATCH", f"/crm/v3/objects/deals/{deal_id}", body={
            "properties": properties,
        })

    async def search_deals(self, query: str = "", filters: list[dict] | None = None, limit: int = 10) -> dict:
        """Search deals."""
        body: dict[str, Any] = {"limit": min(limit, 100)}
        if filters:
            body["filterGroups"] = [{"filters": filters}]
        elif query:
            body["query"] = query
        return await self._request("POST", "/crm/v3/objects/deals/search", body=body)

    # ── Notes / Engagements ─────────────────────────────────

    async def create_note(self, body_text: str, contact_id: str | None = None, deal_id: str | None = None) -> dict:
        """
        Create an engagement note, optionally associated with a contact or deal.

        See: https://developers.hubspot.com/docs/api/crm/notes
        """
        payload: dict[str, Any] = {
            "properties": {
                "hs_note_body": body_text,
                "hs_timestamp": "",  # HubSpot auto-fills if empty
            },
        }
        associations = []
        if contact_id:
            associations.append({
                "to": {"id": contact_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}],
            })
        if deal_id:
            associations.append({
                "to": {"id": deal_id},
                "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 214}],
            })
        if associations:
            payload["associations"] = associations
        return await self._request("POST", "/crm/v3/objects/notes", body=payload)

    # ── Associations ────────────────────────────────────────

    async def associate(
        self, from_type: str, from_id: str, to_type: str, to_id: str, association_type_id: int = 1,
    ) -> dict:
        """
        Associate two HubSpot objects.

        Common association_type_ids:
            1 = contact_to_company
            3 = deal_to_contact
            5 = deal_to_company
        See: https://developers.hubspot.com/docs/api/crm/associations
        """
        return await self._request(
            "PUT",
            f"/crm/v4/objects/{from_type}/{from_id}/associations/{to_type}/{to_id}",
            body=[{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": association_type_id}],
        )

    async def test_connection(self) -> dict:
        """Test the HubSpot connection by fetching account info."""
        return await self._request("GET", "/account-info/v3/details")
