"""
Voice Platform — Salesforce CRM Client
=========================================

Dedicated Salesforce REST API client.
Reference: https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/

Authentication: Uses OAuth2 Bearer token (access_token).
Users must provide their Salesforce instance URL and access token.

Supported actions:
    - create_lead        — Create a Lead sObject
    - update_lead        — Update a Lead
    - create_contact     — Create a Contact sObject
    - update_contact     — Update a Contact
    - create_opportunity — Create an Opportunity
    - update_opportunity — Update an Opportunity
    - get_record         — Get any sObject by type and ID
    - search             — SOSL search across objects
    - query              — SOQL query
"""

import asyncio
from typing import Any, Optional
from urllib.parse import quote

import httpx
from loguru import logger

TIMEOUT = 30.0
DEFAULT_API_VERSION = "v59.0"
MAX_RETRIES = 3


class SalesforceClient:
    """
    Salesforce REST API client.

    Args:
        api_key: OAuth2 access_token (Bearer token).
        config: Must contain 'instance_url' (e.g. https://myorg.my.salesforce.com).
                Optional 'api_version' (default: v59.0).
    """

    _ALLOWED_INSTANCE_HOSTS = (
        ".salesforce.com",
        ".my.salesforce.com",
        ".lightning.force.com",
    )

    def __init__(self, api_key: str, config: dict | None = None):
        self._api_key = api_key
        self._config = config or {}
        instance_url = self._config.get("instance_url", "").rstrip("/")
        if instance_url and not any(
            instance_url.lower().endswith(host) for host in self._ALLOWED_INSTANCE_HOSTS
        ):
            raise ValueError(
                f"Salesforce instance_url must end with one of {self._ALLOWED_INSTANCE_HOSTS}; got {instance_url}"
            )
        self._instance_url = instance_url
        self._api_version = self._config.get("api_version", DEFAULT_API_VERSION)

    @property
    def _base(self) -> str:
        return f"{self._instance_url}/services/data/{self._api_version}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated Salesforce API request with retry."""
        if not self._instance_url:
            return {"success": False, "error": "Salesforce instance_url not configured"}
        url = f"{self._base}{path}"
        last_error = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT, verify=True) as client:
                    resp = await client.request(method, url, headers=self._headers(), json=body, params=params)
                    # Salesforce returns 204 on some deletes
                    if resp.status_code == 204:
                        return {"success": True, "status_code": 204}
                    data = resp.json() if resp.content else {}

                    # Retry on 5xx and 429 (rate limit) with exponential backoff
                    if resp.status_code >= 500 or resp.status_code == 429:
                        last_error = data[0].get("message", str(data)) if isinstance(data, list) and data else str(data)
                        if attempt < MAX_RETRIES:
                            backoff = 2 ** attempt
                            logger.warning(
                                f"Salesforce {method} {path} returned {resp.status_code}, "
                                f"retrying in {backoff}s (attempt {attempt + 1}/{MAX_RETRIES})"
                            )
                            await asyncio.sleep(backoff)
                            continue

                    if resp.status_code >= 400:
                        # Salesforce error responses are an array
                        if isinstance(data, list) and data:
                            error_msg = data[0].get("message", str(data))
                        else:
                            error_msg = data.get("message", resp.text[:300]) if isinstance(data, dict) else str(data)
                        logger.error(f"Salesforce API error {resp.status_code}: {error_msg}")
                        return {"success": False, "status_code": resp.status_code, "error": error_msg}
                    return {"success": True, "status_code": resp.status_code, "data": data}

            except httpx.TimeoutException:
                last_error = "Request timed out"
                if attempt < MAX_RETRIES:
                    backoff = 2 ** attempt
                    logger.warning(f"Salesforce timeout, retrying in {backoff}s (attempt {attempt + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(backoff)
                    continue
                return {"success": False, "error": "Request timed out", "status_code": 0}
            except Exception as e:
                last_error = str(e)
                if attempt < MAX_RETRIES:
                    backoff = 2 ** attempt
                    logger.warning(f"Salesforce error: {e}, retrying in {backoff}s (attempt {attempt + 1}/{MAX_RETRIES})")
                    await asyncio.sleep(backoff)
                    continue
                return {"success": False, "error": last_error, "status_code": 0}

        return {"success": False, "error": last_error or "Request failed after all retries", "status_code": 0}

    # ── sObject CRUD helpers ────────────────────────────────

    async def _create_sobject(self, sobject_type: str, fields: dict) -> dict:
        """Create a Salesforce sObject record."""
        return await self._request("POST", f"/sobjects/{sobject_type}", body=fields)

    async def _update_sobject(self, sobject_type: str, record_id: str, fields: dict) -> dict:
        """Update a Salesforce sObject record by ID."""
        return await self._request("PATCH", f"/sobjects/{sobject_type}/{record_id}", body=fields)

    async def get_record(self, sobject_type: str, record_id: str, fields: list[str] | None = None) -> dict:
        """
        Get a single sObject record.

        Args:
            sobject_type: e.g. 'Lead', 'Contact', 'Account', 'Opportunity'
            record_id: 18-char Salesforce ID
            fields: Optional list of fields to return
        """
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        return await self._request("GET", f"/sobjects/{sobject_type}/{record_id}", params=params)

    # ── Leads ───────────────────────────────────────────────

    async def create_lead(self, **kwargs) -> dict:
        """
        Create a Salesforce Lead.

        Required: LastName, Company.
        Common: FirstName, Email, Phone, Title, LeadSource, Description, Status.
        """
        fields = {k: v for k, v in kwargs.items() if v is not None}
        # Map common lowercase params to Salesforce field names
        field_map = {
            "first_name": "FirstName", "firstname": "FirstName",
            "last_name": "LastName", "lastname": "LastName",
            "email": "Email", "phone": "Phone",
            "company": "Company", "title": "Title",
            "description": "Description", "status": "Status",
            "lead_source": "LeadSource", "source": "LeadSource",
            "name": "LastName",  # Fallback: use name as LastName
        }
        mapped = {}
        for k, v in fields.items():
            sf_field = field_map.get(k.lower(), k)
            mapped[sf_field] = v
        # Ensure required fields
        if "LastName" not in mapped:
            mapped["LastName"] = mapped.get("Name", "Unknown")
        if "Company" not in mapped:
            mapped["Company"] = mapped.pop("company_name", "Unknown")
        return await self._create_sobject("Lead", mapped)

    async def update_lead(self, lead_id: str, **kwargs) -> dict:
        """Update a Lead by ID."""
        fields = {k: v for k, v in kwargs.items() if k != "id" and v is not None}
        return await self._update_sobject("Lead", lead_id, fields)

    # ── Contacts ────────────────────────────────────────────

    async def create_contact(self, **kwargs) -> dict:
        """
        Create a Salesforce Contact.

        Required: LastName.
        Common: FirstName, Email, Phone, AccountId.
        """
        fields = {k: v for k, v in kwargs.items() if v is not None}
        field_map = {
            "first_name": "FirstName", "firstname": "FirstName",
            "last_name": "LastName", "lastname": "LastName",
            "email": "Email", "phone": "Phone",
            "account_id": "AccountId", "title": "Title",
            "name": "LastName",
        }
        mapped = {}
        for k, v in fields.items():
            sf_field = field_map.get(k.lower(), k)
            mapped[sf_field] = v
        if "LastName" not in mapped:
            mapped["LastName"] = "Unknown"
        return await self._create_sobject("Contact", mapped)

    async def update_contact(self, contact_id: str, **kwargs) -> dict:
        """Update a Contact by ID."""
        fields = {k: v for k, v in kwargs.items() if k != "id" and v is not None}
        return await self._update_sobject("Contact", contact_id, fields)

    # ── Opportunities ───────────────────────────────────────

    async def create_opportunity(self, **kwargs) -> dict:
        """
        Create a Salesforce Opportunity.

        Required: Name, StageName, CloseDate.
        Common: Amount, AccountId, Description.
        """
        fields = {k: v for k, v in kwargs.items() if v is not None}
        field_map = {
            "name": "Name", "stage": "StageName", "stage_name": "StageName",
            "close_date": "CloseDate", "amount": "Amount",
            "account_id": "AccountId", "description": "Description",
        }
        mapped = {}
        for k, v in fields.items():
            sf_field = field_map.get(k.lower(), k)
            mapped[sf_field] = v
        if "Name" not in mapped:
            mapped["Name"] = "Opportunity"
        if "StageName" not in mapped:
            mapped["StageName"] = "Prospecting"
        if "CloseDate" not in mapped:
            from datetime import datetime, timedelta, timezone
            mapped["CloseDate"] = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        return await self._create_sobject("Opportunity", mapped)

    async def update_opportunity(self, opportunity_id: str, **kwargs) -> dict:
        """Update an Opportunity by ID."""
        fields = {k: v for k, v in kwargs.items() if k != "id" and v is not None}
        return await self._update_sobject("Opportunity", opportunity_id, fields)

    # ── Search & Query ──────────────────────────────────────

    async def search(self, search_term: str) -> dict:
        """
        SOSL search across all searchable objects.

        Args:
            search_term: Text to search for (will be SOSL-escaped).
        """
        # Escape SOSL special chars
        escaped = search_term.replace("\\", "\\\\").replace("'", "\\'")
        sosl = f"FIND {{{escaped}}} IN ALL FIELDS RETURNING Lead(Id,Name,Email,Phone,Company), Contact(Id,Name,Email,Phone), Opportunity(Id,Name,Amount,StageName)"
        return await self._request("GET", "/search", params={"q": sosl})

    async def query(self, soql: str) -> dict:
        """
        Execute a SOQL query.

        Args:
            soql: Salesforce Object Query Language string.
                  e.g. "SELECT Id, Name, Email FROM Contact WHERE Email = 'test@example.com'"
        """
        return await self._request("GET", "/query", params={"q": soql})

    async def test_connection(self) -> dict:
        """Test the Salesforce connection by querying org limits."""
        return await self._request("GET", "/limits")
