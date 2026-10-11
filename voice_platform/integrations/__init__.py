"""
Voice Platform — Integrations Package
=======================================

Provides clients for third-party service integrations:
- Google Calendar: Create, list, update, delete events
- Google Sheets: Read, append, update, search rows
- Executor: Run workflow steps using the appropriate integration client
- McpClient: Dynamic MCP server tool discovery and execution
"""

from voice_platform.integrations.mcp_client import McpClient  # noqa: F401

__all__ = ["McpClient"]
