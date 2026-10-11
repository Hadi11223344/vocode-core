"""DrivePlugin — Google Drive REST API v3 integration.

Owns google_drive service type (REST API only, not MCP).
MCPPlugin owns mcp_tool for MCP protocol tools.
"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class DrivePlugin:
    """Google Drive REST API integration plugin."""

    kinds = ("google_drive", "google_drive_mcp")

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

        auth_token = integration.api_key or config.get("auth_token") or config.get("api_key") or ""
        creds = None

        # Auto-resolve Google OAuth token if no static token is configured
        if not auth_token and integration.user_id:
            try:
                from voice_platform.integrations.google_oauth import GoogleOAuthManager
                creds = await GoogleOAuthManager.get_credentials(integration.user_id)
                if creds and creds.token:
                    auth_token = creds.token
            except Exception as oauth_err:
                logger.warning(f"Google OAuth resolution failed for Drive action: {oauth_err}")

        if not auth_token:
            return PluginResult(
                success=False,
                error="No Google OAuth token available. Connect your Google account in Integrations.",
                output={"status": "error", "message": "No Google OAuth token available. Connect your Google account in Integrations."},
            )

        from voice_platform.integrations.google_drive_client import GoogleDriveClient
        drive_client = GoogleDriveClient(
            access_token=auth_token, credentials=creds, timeout=15.0,
        )

        try:
            if action == "read_file_content":
                file_id = params.get("file_id") or params.get("id", "")
                if not file_id:
                    return PluginResult(success=False, error="Missing 'file_id' parameter",
                                       output={"status": "error", "message": "Missing 'file_id' parameter"})
                content = await drive_client.read_file_content(file_id)
                return PluginResult(success=True, output={"status": "ok", "content": content, "file_id": file_id})

            elif action == "list_files":
                files = await drive_client.list_files(
                    query=params.get("query"),
                    page_size=params.get("page_size", 20),
                )
                return PluginResult(success=True, output={"status": "ok", "files": files, "count": len(files)})

            elif action == "search_files":
                files = await drive_client.search_files(
                    query=params.get("query", ""),
                    page_size=params.get("page_size", 20),
                )
                return PluginResult(success=True, output={"status": "ok", "files": files, "count": len(files)})

            else:
                return PluginResult(success=False, error=f"Unknown Drive action: {action}",
                                   output={"status": "error", "message": f"Unknown Drive action: {action}"})
        except Exception as exc:
            logger.warning(f"Drive action {action} failed: {exc}")
            return PluginResult(success=False, error=f"Drive action failed: {str(exc)[:200]}",
                               output={"status": "error", "message": f"Drive action failed: {str(exc)[:200]}"})
        finally:
            await drive_client.aclose()
