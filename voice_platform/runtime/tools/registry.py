"""ToolRegistry — catalogs ToolDefinitions. Static metadata, no DB session stored.

discover(ToolDiscoveryRequest) performs connected-integration filtering + MCP
discovery, returning list[AvailableTool] with availability metadata.
"""

from __future__ import annotations

import json
from types import MappingProxyType
from typing import Any, Mapping

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.runtime.tools.types import (
    AvailableTool,
    ToolDefinition,
    ToolDiscoveryRequest,
)


class ToolRegistry:
    """Catalogs ToolDefinitions. Static metadata — no DB session stored as instance state."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get(self, tool_name: str) -> ToolDefinition:
        if tool_name not in self._tools:
            raise KeyError(f"Unknown tool: {tool_name}")
        return self._tools[tool_name]

    def supports(self, tool_name: str) -> bool:
        return tool_name in self._tools

    def list(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def schemas(self) -> dict[str, Mapping[str, Any]]:
        return {name: tool.schema for name, tool in self._tools.items()}

    async def discover(
        self,
        session: AsyncSession,
        request: ToolDiscoveryRequest,
    ) -> tuple[list[AvailableTool], list[tuple[str, str]]]:
        """Filter tools by connected integrations + discover MCP tools.

        Returns (available_tools, skipped_tools).
        Each AvailableTool carries definition + integration_id + enabled + reason.
        """
        from voice_platform.config import settings as _platform_settings
        from voice_platform.database import Integration, UserApiKey
        from voice_platform.encryption import decrypt

        # Query active integrations for this user
        active_types: set[str] = set()
        try:
            result = await session.execute(
                select(Integration.service_type).where(
                    Integration.user_id == request.user_id,
                    Integration.is_active == True,
                ).distinct()
            )
            active_types = {row[0] for row in result.all()}
        except Exception as e:
            logger.warning(f"Could not load integrations for tool filtering: {e}")

        _has_platform_smtp = bool(
            _platform_settings.smtp_host and _platform_settings.smtp_password
        )
        _has_platform_twilio = bool(
            getattr(_platform_settings, "twilio_account_sid", None)
            and getattr(_platform_settings, "twilio_auth_token", None)
        )

        available: list[AvailableTool] = []
        skipped: list[tuple[str, str]] = []

        # 1. Static tools from registry
        for tool_name in request.tools_config:
            if not self.supports(tool_name):
                logger.warning(f"Unknown tool '{tool_name}' in tools_config, skipping")
                continue

            definition = self.get(tool_name)
            service_type = definition.service_type

            # Skip tools whose integration is not connected
            # Exceptions: recall_document (memory-only), email (platform SMTP), sms (platform Twilio)
            if service_type not in active_types and service_type != "recall_document":
                if service_type == "email" and _has_platform_smtp:
                    pass  # platform SMTP fallback
                elif service_type == "sms" and _has_platform_twilio:
                    pass  # platform Twilio fallback
                else:
                    logger.warning(
                        f"Tool '{tool_name}' skipped: no active '{service_type}' integration "
                        f"for user {request.user_id}."
                    )
                    skipped.append((tool_name, service_type))
                    continue

            # Resolve integration override
            override_id: int | None = None
            if request.integration_overrides:
                raw = request.integration_overrides.get(service_type)
                if raw is not None:
                    try:
                        override_id = int(raw)
                    except (TypeError, ValueError):
                        override_id = None

            available.append(
                AvailableTool(
                    definition=definition,
                    integration_id=override_id,
                    enabled=True,
                )
            )

        # 2. Dynamic MCP tools
        if "mcp" in active_types:
            try:
                mcp_result = await session.execute(
                    select(Integration).where(
                        Integration.user_id == request.user_id,
                        Integration.service_type == "mcp",
                        Integration.is_active == True,
                    )
                )
                for integration in mcp_result.scalars().all():
                    cfg: dict = {}
                    config_json: str = integration.config_json or ""
                    if config_json:
                        try:
                            cfg = json.loads(config_json)
                        except json.JSONDecodeError:
                            cfg = {}
                    server_url = cfg.get("server_url", "").strip()
                    if not server_url:
                        logger.warning(
                            f"MCP integration {integration.id} has no server_url, skipping"
                        )
                        continue

                    auth_token = ""
                    if integration.api_key_id:
                        key_result = await session.execute(
                            select(UserApiKey).where(
                                UserApiKey.id == integration.api_key_id,
                                UserApiKey.is_active == True,
                            )
                        )
                        key_row = key_result.scalar_one_or_none()
                        if key_row and key_row.api_key:
                            auth_token = decrypt(key_row.api_key)

                    mcp_tools = await _discover_mcp_tools(
                        server_url,
                        auth_token or None,
                        request.user_id,
                        integration.id,
                    )
                    available.extend(mcp_tools)
            except Exception as e:
                logger.warning(f"MCP tool discovery failed: {e}")

        logger.info(
            f"Tool discovery: {len(available)} available, {len(skipped)} skipped "
            f"for user {request.user_id}"
        )
        return available, skipped


async def _discover_mcp_tools(
    server_url: str,
    auth_token: str | None,
    user_id: int,
    integration_id: int,
) -> list[AvailableTool]:
    """Discover tools from an MCP server and return AvailableTool objects."""
    from voice_platform.actions.platform_tools import build_mcp_tool_actions_for_server

    mcp_action_configs = await build_mcp_tool_actions_for_server(
        server_url, auth_token, user_id
    )

    tools: list[AvailableTool] = []
    for action_config in mcp_action_configs:
        tool_name = getattr(action_config, "tool_name", "")
        tool_description = getattr(action_config, "tool_description", "")
        params_schema_str = getattr(action_config, "tool_parameters_schema", "{}")
        try:
            schema = json.loads(params_schema_str) if isinstance(params_schema_str, str) else params_schema_str
        except (json.JSONDecodeError, TypeError):
            schema = {}

        definition = ToolDefinition(
            name=tool_name,
            description=tool_description,
            schema=MappingProxyType(schema) if isinstance(schema, dict) else MappingProxyType({}),
            service_type="mcp",
            action=tool_name,
        )
        tools.append(
            AvailableTool(
                definition=definition,
                integration_id=integration_id,
                enabled=True,
            )
        )
    return tools


def build_default_tool_registry() -> ToolRegistry:
    """Build a ToolRegistry populated from PLATFORM_TOOLS."""
    from voice_platform.actions.platform_tools import PLATFORM_TOOLS

    registry = ToolRegistry()
    for name, tool_def in PLATFORM_TOOLS.items():
        definition = ToolDefinition(
            name=tool_def["name"],
            description=tool_def["description"],
            schema=MappingProxyType(tool_def["parameters"]),
            service_type=tool_def["integration_type"],
            action=tool_def["action"],
            required_context=MappingProxyType(tool_def.get("required_context", {})),
        )
        registry.register(definition)
    return registry
