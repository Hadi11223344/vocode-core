"""
Voice Platform — Webhook / API Request Client
================================================

Enhanced webhook client for making HTTP requests to external APIs
during workflow execution (inspired by Bland AI's custom tools
and Vapi's API Request nodes).

Supports:
    - GET, POST, PUT, PATCH, DELETE methods
    - Custom headers with template variables
    - JSON and form-encoded payloads
    - Response data extraction via JSONPath-like notation
    - SSRF protection
    - Timeout and retry configuration

Use cases:
    - CRM updates (HubSpot, Salesforce)
    - Zapier webhook triggers
    - Slack notifications
    - Custom API calls to any service
    - Cal.com booking
"""

import asyncio
import json
from typing import Any, Optional

import httpx
from loguru import logger

from voice_platform.utils.ssrf import is_safe_url as _is_safe_url


class WebhookClient:
    """
    Enhanced HTTP client for webhook and API request workflow nodes.
    
    Config:
        base_url: Optional base URL prefix
        default_headers: Default headers for all requests
        timeout: Request timeout in seconds (default: 30)
        retry_count: Number of retries on failure (default: 0)
    """
    
    def __init__(self, config: dict = None):
        self._config = config or {}
        self._base_url = self._config.get("base_url", "")
        self._default_headers = self._config.get("default_headers", {})
        self._timeout = float(self._config.get("timeout", 30))
        self._retry_count = int(self._config.get("retry_count", 0))
    
    async def request(
        self,
        url: str,
        method: str = "POST",
        headers: Optional[dict] = None,
        body: Optional[dict] = None,
        body_raw: Optional[str] = None,
        auth_header: Optional[str] = None,
    ) -> dict:
        """
        Make an HTTP request to an external API.
        
        Args:
            url: Target URL
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            headers: Custom headers
            body: JSON body dict
            body_raw: Raw body string (parsed as JSON if valid)
            auth_header: Authorization header value
        
        Returns:
            dict with status_code, success, body, headers
        """
        full_url = f"{self._base_url}{url}" if self._base_url and not url.startswith("http") else url
        
        if not _is_safe_url(full_url):
            return {
                "success": False,
                "error": "URL blocked by security policy (internal network)",
                "status_code": 0,
            }
        
        # Build headers
        req_headers = {**self._default_headers}
        if headers:
            req_headers.update(headers)
        if auth_header:
            req_headers["Authorization"] = auth_header
        
        # Parse body
        req_body = body
        if body_raw and not req_body:
            try:
                req_body = json.loads(body_raw)
            except json.JSONDecodeError:
                req_body = {"data": body_raw}
        
        method = method.upper()
        
        last_error = None
        retry_count = max(self._retry_count, 3)  # Default to 3 retries minimum
        
        for attempt in range(retry_count + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout, verify=True) as client:
                    if method == "GET":
                        response = await client.get(full_url, headers=req_headers, params=req_body)
                    elif method == "POST":
                        response = await client.post(full_url, headers=req_headers, json=req_body)
                    elif method == "PUT":
                        response = await client.put(full_url, headers=req_headers, json=req_body)
                    elif method == "PATCH":
                        response = await client.patch(full_url, headers=req_headers, json=req_body)
                    elif method == "DELETE":
                        response = await client.delete(full_url, headers=req_headers)
                    else:
                        return {"success": False, "error": f"Unsupported method: {method}"}
                    
                    # Parse response
                    response_body = response.text[:2000]  # Cap response size
                    try:
                        response_json = response.json()
                    except Exception:
                        response_json = None
                    
                    # Retry on 5xx and 429 (rate limit) with exponential backoff
                    if response.status_code >= 500 or response.status_code == 429:
                        last_error = f"HTTP {response.status_code}: {response_body[:200]}"
                        if attempt < retry_count:
                            backoff = 2 ** attempt  # 1s, 2s, 4s, 8s
                            logger.warning(
                                f"Webhook {method} {full_url} returned {response.status_code}, "
                                f"retrying in {backoff}s (attempt {attempt + 1}/{retry_count})"
                            )
                            await asyncio.sleep(backoff)
                            continue
                    
                    result = {
                        "success": response.is_success,
                        "status_code": response.status_code,
                        "body": response_json or response_body,
                    }
                    
                    logger.info(f"🌐 {method} {full_url} → {response.status_code}")
                    return result
                    
            except httpx.TimeoutException:
                last_error = "Request timed out"
                if attempt < retry_count:
                    backoff = 2 ** attempt
                    logger.warning(f"Webhook timeout, retrying in {backoff}s (attempt {attempt + 1}/{retry_count})")
                    await asyncio.sleep(backoff)
                    continue
                return {"success": False, "error": "Request timed out", "status_code": 0}
            except Exception as e:
                last_error = str(e)
                if attempt < retry_count:
                    backoff = 2 ** attempt
                    logger.warning(f"Webhook error: {e}, retrying in {backoff}s (attempt {attempt + 1}/{retry_count})")
                    await asyncio.sleep(backoff)
                    continue
                return {"success": False, "error": last_error, "status_code": 0}
        
        return {"success": False, "error": last_error or "Request failed after all retries", "status_code": 0}
    
    @staticmethod
    def extract_response_data(response: dict, mappings: dict) -> dict:
        """
        Extract data from API response using JSONPath-like notation.
        
        E.g. mappings = {"booking_id": "$.data.id", "status": "$.status"}
        
        Args:
            response: The API response dict
            mappings: Dict of variable_name -> JSONPath expression
        
        Returns:
            Dict of extracted values
        """
        extracted = {}
        body = response.get("body", {})
        
        if not isinstance(body, dict):
            return extracted
        
        for var_name, path in mappings.items():
            if not path.startswith("$."):
                extracted[var_name] = path
                continue
            
            keys = path[2:].split(".")
            current = body
            
            try:
                for key in keys:
                    if isinstance(current, dict):
                        current = current[key]
                    elif isinstance(current, list) and key.isdigit():
                        current = current[int(key)]
                    else:
                        current = None
                        break
                extracted[var_name] = current
            except (KeyError, IndexError, TypeError):
                extracted[var_name] = None
        
        return extracted
