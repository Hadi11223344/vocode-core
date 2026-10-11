"""
Voice Platform — Pipedrive CRM Client
========================================

Dedicated Pipedrive API client.
Reference: https://developers.pipedrive.com/docs/api/v1

Authentication: API token passed as query parameter (per Pipedrive convention).

Supported actions:
    - create_person    — Create a person (contact)
    - update_person    — Update a person
    - search_persons   — Search persons by name/email/phone
    - create_deal      — Create a deal
    - update_deal      — Update a deal
    - search_deals     — Search deals
    - add_note         — Add a note to a deal or person
    - create_activity  — Create an activity (task/call/meeting)
"""

from typing import Any, Optional

import httpx
from loguru import logger

BASE_URL = "https://api.pipedrive.com/v1"
TIMEOUT = 30.0


class PipedriveClient:
    """
    Pipedrive CRM API v1 client.

    Args:
        api_key: Pipedrive API token.
        config: Optional config. May contain 'base_url' override.
    """

    def __init__(self, api_key: str, config: dict | None = None):
        self._api_key = api_key
        self._config = config or {}
        self._base_url = self._config.get("base_url", BASE_URL).rstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated Pipedrive API request."""
        url = f"{self._base_url}{path}"
        # Pipedrive uses api_token as a query parameter
        query = {"api_token": self._api_key}
        if params:
            query.update(params)
        headers = {"Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=True) as client:
            resp = await client.request(method, url, headers=headers, json=body, params=query)
            data = resp.json() if resp.content else {}
            if resp.status_code >= 400 or (isinstance(data, dict) and not data.get("success", True)):
                error_msg = data.get("error", resp.text[:300]) if isinstance(data, dict) else str(data)
                logger.error(f"Pipedrive API error {resp.status_code}: {error_msg}")
                return {"success": False, "status_code": resp.status_code, "error": error_msg}
            return {"success": True, "status_code": resp.status_code, "data": data.get("data", data)}

    # ── Persons (Contacts) ──────────────────────────────────

    async def create_person(self, **kwargs) -> dict:
        """
        Create a Pipedrive person.

        Expected: name (required), email, phone, org_id, visible_to.
        See: https://developers.pipedrive.com/docs/api/v1/Persons#addPerson
        """
        body = {}
        body["name"] = kwargs.get("name", kwargs.get("firstname", "Unknown"))
        if "email" in kwargs:
            body["email"] = [{"value": kwargs["email"], "primary": True}]
        if "phone" in kwargs:
            body["phone"] = [{"value": kwargs["phone"], "primary": True}]
        if "org_id" in kwargs:
            body["org_id"] = int(kwargs["org_id"])
        if "visible_to" in kwargs:
            body["visible_to"] = kwargs["visible_to"]
        # Pass through any custom fields
        for k, v in kwargs.items():
            if k not in ("name", "email", "phone", "org_id", "visible_to", "firstname", "lastname"):
                body[k] = v
        return await self._request("POST", "/persons", body=body)

    async def update_person(self, person_id: str, **kwargs) -> dict:
        """Update a person by ID."""
        body = {k: v for k, v in kwargs.items() if k != "id" and v is not None}
        if "email" in body and isinstance(body["email"], str):
            body["email"] = [{"value": body["email"], "primary": True}]
        if "phone" in body and isinstance(body["phone"], str):
            body["phone"] = [{"value": body["phone"], "primary": True}]
        return await self._request("PUT", f"/persons/{person_id}", body=body)

    async def search_persons(self, query: str, limit: int = 10) -> dict:
        """
        Search persons by name, email, phone, or notes.

        See: https://developers.pipedrive.com/docs/api/v1/Persons#searchPersons
        """
        return await self._request("GET", "/persons/search", params={
            "term": query,
            "limit": str(min(limit, 50)),
            "fields": "name,email,phone",
        })

    # ── Deals ───────────────────────────────────────────────

    async def create_deal(self, **kwargs) -> dict:
        """
        Create a Pipedrive deal.

        Expected: title (required), value, currency, person_id, org_id, pipeline_id, stage_id.
        See: https://developers.pipedrive.com/docs/api/v1/Deals#addDeal
        """
        body = {"title": kwargs.pop("title", kwargs.pop("dealname", "New Deal"))}
        for k in ("value", "currency", "person_id", "org_id", "pipeline_id", "stage_id", "status", "probability"):
            if k in kwargs:
                body[k] = kwargs[k]
        # Pass through custom fields
        for k, v in kwargs.items():
            if k not in body:
                body[k] = v
        return await self._request("POST", "/deals", body=body)

    async def update_deal(self, deal_id: str, **kwargs) -> dict:
        """Update a deal by ID."""
        body = {k: v for k, v in kwargs.items() if k != "id" and v is not None}
        return await self._request("PUT", f"/deals/{deal_id}", body=body)

    async def search_deals(self, query: str, limit: int = 10) -> dict:
        """Search deals by title."""
        return await self._request("GET", "/deals/search", params={
            "term": query,
            "limit": str(min(limit, 50)),
        })

    # ── Notes ───────────────────────────────────────────────

    async def add_note(self, content: str, deal_id: str | None = None, person_id: str | None = None) -> dict:
        """
        Add a note (attached to a deal or person).

        See: https://developers.pipedrive.com/docs/api/v1/Notes#addNote
        """
        body: dict[str, Any] = {"content": content}
        if deal_id:
            body["deal_id"] = int(deal_id)
        if person_id:
            body["person_id"] = int(person_id)
        return await self._request("POST", "/notes", body=body)

    # ── Activities ──────────────────────────────────────────

    async def create_activity(self, **kwargs) -> dict:
        """
        Create an activity (task, call log, meeting, etc).

        Expected: subject (required), type (call/meeting/task), due_date, due_time,
                  duration, deal_id, person_id, note.
        See: https://developers.pipedrive.com/docs/api/v1/Activities#addActivity
        """
        body = {"subject": kwargs.pop("subject", "Activity")}
        for k in ("type", "due_date", "due_time", "duration", "deal_id", "person_id", "org_id", "note"):
            if k in kwargs:
                body[k] = kwargs[k]
        return await self._request("POST", "/activities", body=body)

    async def test_connection(self) -> dict:
        """Test connection by fetching current user info."""
        return await self._request("GET", "/users/me")
