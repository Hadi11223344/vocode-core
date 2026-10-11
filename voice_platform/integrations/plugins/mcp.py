"""MCPPlugin — Model Context Protocol tool integration.

Handles mcp_tool node execution, including Google Workspace MCP auto-resolve
of OAuth tokens for Google-hosted MCP servers.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)

_GOOGLE_MCP_HOSTS = {
    "drivemcp.googleapis.com",
    "calendarmcp.googleapis.com",
    "gmailmcp.googleapis.com",
    "peoplemcp.googleapis.com",
}


def _resolve_templates(obj: Any, context: dict | None) -> Any:
    """Resolve {{variable}} templates in tool arguments using flow context."""
    if not context:
        return obj
    import re
    pattern = re.compile(r"\{\{([^}]+)\}\}")

    def _lookup(var_name: str):
        var_name = var_name.strip()
        if var_name in context:
            return context[var_name]
        if "." in var_name:
            current: Any = context
            for part in var_name.split("."):
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None
            return current
        return None

    def _resolve_value(value, depth=0):
        if isinstance(value, str):
            current = value
            for _ in range(5):
                whole = re.fullmatch(r"\{\{\s*([^}]+?)\s*\}\}", current)
                if whole:
                    resolved = _lookup(whole.group(1).strip())
                    if resolved is None:
                        return current
                    if isinstance(resolved, str) and depth < 5 and "{{" in resolved:
                        current = resolved
                        continue
                    return resolved
                changed = False
                def _replace(match):
                    nonlocal changed
                    var_name = match.group(1).strip()
                    resolved = _lookup(var_name)
                    if resolved is None:
                        return match.group(0)
                    changed = True
                    return str(resolved)
                updated = pattern.sub(_replace, current)
                current = updated
                if not changed or "{{" not in current:
                    break
            return current
        if isinstance(value, dict):
            return {k: _resolve_value(v, depth + 1) for k, v in value.items()}
        if isinstance(value, list):
            return [_resolve_value(v, depth + 1) for v in value]
        return value

    return _resolve_value(obj)


class MCPPlugin:
    """MCP (Model Context Protocol) tool integration plugin."""

    kinds = ("mcp_tool",)

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[dict]:
        integration = request.integration
        params = dict(request.params)
        config = dict(integration.config)

        server_url: str = (
            config.get("server_url") or params.get("server_url") or ""
        ).strip()
        auth_token: str | None = (
            config.get("auth_token") or params.get("auth_token") or None
        )
        tool_name: str = (
            config.get("tool_name") or params.get("tool_name") or ""
        ).strip()

        # ── Google Workspace MCP: Auto-resolve OAuth token ────────────
        try:
            from urllib.parse import urlparse as _urlparse
            _parsed_host = (_urlparse(server_url).hostname or "").lower()
        except Exception:
            _parsed_host = ""

        if _parsed_host in _GOOGLE_MCP_HOSTS and not auth_token:
            try:
                from voice_platform.integrations.google_oauth import GoogleOAuthManager
                _user_id = integration.user_id
                if not _user_id:
                    return PluginResult(
                        success=False,
                        error=(
                            "Google Drive MCP requires authentication. "
                            "Connect your Google account in Settings → Integrations."
                        ),
                    )
                _creds = await GoogleOAuthManager.get_credentials(_user_id)
                if _creds and _creds.token:
                    auth_token = _creds.token
                    logger.info(f"Resolved Google OAuth token for MCP (host={_parsed_host})")
                else:
                    return PluginResult(
                        success=False,
                        error=(
                            "No Google OAuth credentials found. "
                            "Connect your Google account in Settings → Integrations first."
                        ),
                    )
            except Exception as oauth_err:
                logger.warning(f"Google OAuth resolution failed for MCP: {oauth_err}")
                return PluginResult(
                    success=False,
                    error=f"Google authentication error: {str(oauth_err)[:200]}",
                )

        if not server_url:
            return PluginResult(success=False, error="mcp_tool node is missing 'server_url'")
        if not tool_name:
            return PluginResult(success=False, error="mcp_tool node is missing 'tool_name'")

        # parameters field may be a JSON string
        raw_tool_args = config.get("parameters") or params.get("parameters") or {}
        if isinstance(raw_tool_args, str):
            try:
                raw_tool_args = json.loads(raw_tool_args)
            except json.JSONDecodeError:
                logger.warning("mcp_tool: 'parameters' is not valid JSON, defaulting to empty dict")
                raw_tool_args = {}

        # Resolve {{variable}} templates inside tool arguments
        flow_ctx = dict(request.context.variables) if request.context else {}
        tool_args = _resolve_templates(raw_tool_args, flow_ctx)

        logger.info(f"Executing mcp_tool: {tool_name} @ {server_url}")

        from voice_platform.integrations.mcp_client import McpClient
        client = McpClient(
            server_url=server_url,
            auth_token=auth_token,
            timeout=30.0,
        )
        try:
            result = await client.call_tool(tool_name, tool_args)
        finally:
            await client.aclose()

        return PluginResult(
            success=True,
            output={
                "action": tool_name,
                "status": "success",
                "result": result,
            },
        )
