"""
Voice Platform — Google Drive API v3 Client
=============================================

Direct REST client for Google Drive API v3 using OAuth 2.0 tokens.
Replaces the non-existent MCP-based Drive integration with real API calls.

Endpoints used:
  - files.list       → List/search files
  - files.get        → Get file metadata
  - files.export     → Export Google Workspace docs to plain text
  - files.get?alt=media → Download binary files

OAuth scopes required:
  - https://www.googleapis.com/auth/drive.readonly
  - https://www.googleapis.com/auth/drive.file
"""

import asyncio
from typing import Any, Dict, List, Optional

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from loguru import logger

_GOOGLE_DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"


class GoogleDriveClient:
    """Lightweight async client for Google Drive API v3."""

    def __init__(
        self,
        access_token: str,
        timeout: float = 30.0,
        credentials: Optional[Credentials] = None,
    ) -> None:
        self._token = access_token
        self._timeout = timeout
        self._credentials = credentials
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                verify=True,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/json",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _refresh_token(self) -> None:
        """Refresh the access token if we have an expired Credentials object."""
        if self._credentials is None or not self._credentials.expired:
            return
        if not self._credentials.refresh_token:
            logger.warning("Google Drive token expired but no refresh token available")
            return
        logger.info("Refreshing expired Google Drive access token")
        await asyncio.to_thread(self._credentials.refresh, Request())
        self._token = self._credentials.token
        if self._client is not None:
            self._client.headers["Authorization"] = f"Bearer {self._token}"

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        await self._refresh_token()
        client = await self._get_client()
        url = f"{_GOOGLE_DRIVE_API_BASE}/{path}"
        resp = await client.request(method, url, **kwargs)
        if resp.status_code >= 400:
            text = resp.text[:500]
            raise RuntimeError(f"Drive API {resp.status_code}: {text}")
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.content

    async def list_files(
        self,
        query: Optional[str] = None,
        page_size: int = 20,
        fields: str = "files(id,name,mimeType,modifiedTime,size,webViewLink)",
    ) -> List[Dict[str, Any]]:
        """List files the user has access to."""
        params: Dict[str, Any] = {
            "pageSize": page_size,
            "fields": f"nextPageToken,{fields}",
            "orderBy": "modifiedTime desc",
        }
        if query:
            params["q"] = f"name contains '{query.replace(chr(39), chr(92)+chr(39))}'"

        data = await self._request("GET", "files", params=params)
        files = data.get("files", []) if isinstance(data, dict) else []
        logger.info(f"Drive files.list returned {len(files)} file(s)")
        return files

    async def get_file_metadata(self, file_id: str) -> Dict[str, Any]:
        """Get metadata for a single file."""
        return await self._request(
            "GET",
            f"files/{file_id}",
            params={"fields": "id,name,mimeType,modifiedTime,size,webViewLink"},
        )

    async def read_file_content(self, file_id: str) -> str:
        """
        Read the content of a file.

        - Google Workspace docs (Docs, Sheets, Slides) are exported to plain text.
        - Binary files (PDF, images) are returned as base64 with a note.
        """
        meta = await self.get_file_metadata(file_id)
        mime = meta.get("mimeType", "")

        # Google Docs → export as plain text
        if mime == "application/vnd.google-apps.document":
            data = await self._request(
                "GET",
                f"files/{file_id}/export",
                params={"mimeType": "text/plain"},
            )
            return data.decode("utf-8") if isinstance(data, bytes) else str(data)

        # Google Sheets → export as CSV
        if mime == "application/vnd.google-apps.spreadsheet":
            data = await self._request(
                "GET",
                f"files/{file_id}/export",
                params={"mimeType": "text/csv"},
            )
            return data.decode("utf-8") if isinstance(data, bytes) else str(data)

        # Google Slides → export as plain text ( speaker notes )
        if mime == "application/vnd.google-apps.presentation":
            data = await self._request(
                "GET",
                f"files/{file_id}/export",
                params={"mimeType": "text/plain"},
            )
            return data.decode("utf-8") if isinstance(data, bytes) else str(data)

        # Binary / other → try alt=media download, return base64 hint
        try:
            data = await self._request(
                "GET",
                f"files/{file_id}",
                params={"alt": "media"},
            )
            if isinstance(data, bytes):
                # Try decode as text first
                try:
                    return data.decode("utf-8")
                except UnicodeDecodeError:
                    import base64
                    b64 = base64.b64encode(data[:2000]).decode("ascii")
                    return f"[Binary file: {mime}] Base64 preview (first 2KB): {b64[:200]}..."
            return str(data)
        except Exception as exc:
            return f"[Unable to read file content: {exc}]"

    async def search_files(self, query: str, page_size: int = 20) -> List[Dict[str, Any]]:
        """Search files by name or content keywords."""
        return await self.list_files(query=query, page_size=page_size)

    async def test_connection(self) -> Dict[str, Any]:
        """Quick health check: list 1 file to verify token works."""
        files = await self.list_files(page_size=1)
        return {
            "success": True,
            "file_count": len(files),
            "message": f"Drive access confirmed. {len(files)} file(s) visible."
        }
