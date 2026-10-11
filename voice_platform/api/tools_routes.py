"""
Voice Platform — Tools API Routes
====================================

Endpoints for managing in-call tools (live function calling).

Routes:
    GET  /api/tools/available   — List all available tools
    GET  /api/tools/agent/{id}  — Get tools enabled for an agent
    PUT  /api/tools/agent/{id}  — Update tools for an agent
"""

import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.actions.platform_tools import PLATFORM_TOOLS, get_available_tools
from voice_platform.database import Agent, Integration, get_db
from voice_platform.errors import AgentNotFoundError, ValidationError
from voice_platform.middleware.auth_middleware import get_current_user
from voice_platform.rbac import get_team_membership

router = APIRouter(prefix="/api/tools", tags=["Tools"])


class UpdateToolsRequest(BaseModel):
    tools: List[str]


@router.get("/available")
async def list_available_tools(user=Depends(get_current_user)):
    """List all available in-call tools."""
    return {"tools": get_available_tools()}


@router.get("/agent/{agent_id}")
async def get_agent_tools(
    agent_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the tools enabled for a specific agent, annotated with integration status."""
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise AgentNotFoundError(agent_id)

    # RBAC: allow access if user owns the agent OR is a member of the agent's team
    if agent.user_id != user.id:
        if not agent.team_id or not await get_team_membership(user.id, agent.team_id):
            raise AgentNotFoundError(agent_id)

    enabled = []
    if agent.tools_config:
        try:
            enabled = json.loads(agent.tools_config)
        except Exception:
            pass

    # Query active integrations for this user
    integration_result = await db.execute(
        select(Integration.service_type).where(
            Integration.user_id == user.id,
            Integration.is_active == True,
        ).distinct()
    )
    active_types = {row[0] for row in integration_result.all()}

    # Human-readable integration type labels
    _INTEGRATION_LABELS = {
        "google_sheets": "Google Sheets",
        "google_calendar": "Google Calendar",
        "google_drive_mcp": "Google Drive (MCP)",
        "email": "Email (SMTP)",
        "sms": "SMS (Twilio)",
        "whatsapp_cloud": "WhatsApp",
        "telegram_bot": "Telegram",
        "webhook": "Webhook",
        "mcp": "MCP Server",
    }

    # Return tools annotated with integration dependency + status
    all_tools = get_available_tools()
    for tool in all_tools:
        tool_id = tool["id"]
        tool_def = PLATFORM_TOOLS.get(tool_id, {})
        int_type = tool_def.get("integration_type", "")
        tool["enabled"] = tool_id in enabled
        tool["integration_required"] = int_type != "recall_document"
        tool["integration_type"] = int_type
        tool["integration_label"] = _INTEGRATION_LABELS.get(int_type, int_type)
        tool["integration_connected"] = int_type in active_types if tool["integration_required"] else True

        # Platform SMTP fallback: mark email as connected if platform SMTP is configured
        if int_type == "email" and not tool["integration_connected"]:
            from voice_platform.config import settings as _settings
            if _settings.smtp_host and _settings.smtp_password:
                tool["integration_connected"] = True
                tool["integration_label"] = "Email (Platform SMTP)"

        # Platform Twilio fallback: mark SMS as connected if platform Twilio is configured
        if int_type == "sms" and not tool["integration_connected"]:
            from voice_platform.config import settings as _settings
            if getattr(_settings, 'twilio_account_sid', None) and getattr(_settings, 'twilio_auth_token', None):
                tool["integration_connected"] = True
                tool["integration_label"] = "SMS (Platform Twilio)"

    return {
        "agent_id": agent_id,
        "enabled_tools": enabled,
        "tools": all_tools,
        "active_integration_types": sorted(active_types),
    }


@router.put("/agent/{agent_id}")
async def update_agent_tools(
    agent_id: int,
    request: UpdateToolsRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the tools enabled for a specific agent."""
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise AgentNotFoundError(agent_id)

    # RBAC: allow update if user owns the agent OR is a member of the agent's team
    if agent.user_id != user.id:
        if not agent.team_id or not await get_team_membership(user.id, agent.team_id):
            raise AgentNotFoundError(agent_id)

    # Validate tool names
    valid_tools = set(PLATFORM_TOOLS.keys())
    invalid_tools = [t for t in request.tools if t not in valid_tools]
    if invalid_tools:
        raise ValidationError(
            field="tools",
            message=f"Invalid tool names: {', '.join(invalid_tools)}",
            suggestion=f"Choose from available tools: {', '.join(sorted(PLATFORM_TOOLS.keys()))}",
        )

    # Warn about tools whose integrations are not connected
    integration_result = await db.execute(
        select(Integration.service_type).where(
            Integration.user_id == user.id,
            Integration.is_active == True,
        ).distinct()
    )
    active_types = {row[0] for row in integration_result.all()}

    # Check if platform SMTP is available for email fallback
    from voice_platform.config import settings as _settings
    _has_platform_smtp = bool(_settings.smtp_host and _settings.smtp_password)
    _has_platform_twilio = bool(
        getattr(_settings, 'twilio_account_sid', None)
        and getattr(_settings, 'twilio_auth_token', None)
    )

    missing_integration_tools = [
        t for t in request.tools
        if t in PLATFORM_TOOLS
        and PLATFORM_TOOLS[t].get("integration_type", "") not in active_types
        and PLATFORM_TOOLS[t].get("integration_type", "") != "recall_document"
        and not (PLATFORM_TOOLS[t].get("integration_type", "") == "email" and _has_platform_smtp)
        and not (PLATFORM_TOOLS[t].get("integration_type", "") == "sms" and _has_platform_twilio)
    ]

    agent.tools_config = json.dumps(request.tools)
    await db.commit()

    logger.info(f"Updated tools for agent {agent.name}: {request.tools}")

    response = {
        "agent_id": agent_id,
        "enabled_tools": request.tools,
        "message": f"Updated {len(request.tools)} tools for agent '{agent.name}'",
    }
    if missing_integration_tools:
        response["warning"] = (
            f"{len(missing_integration_tools)} tool(s) enabled but their integration(s) are not connected: "
            f"{', '.join(missing_integration_tools)}"
        )
    return response


class UpdateMcpBindingsRequest(BaseModel):
    bindings: dict = Field(
        default_factory=dict,
        description="MCP resource bindings: {drive: {file_ids:[], folder_ids:[]}, calendar: {calendar_ids:[]}}",
    )


@router.get("/agent/{agent_id}/mcp-bindings")
async def get_agent_mcp_bindings(
    agent_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get MCP resource bindings for a specific agent."""
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise AgentNotFoundError(agent_id)

    # RBAC: allow access if user owns the agent OR is a member of the agent's team
    if agent.user_id != user.id:
        if not agent.team_id or not await get_team_membership(user.id, agent.team_id):
            raise AgentNotFoundError(agent_id)

    bindings = {}
    if agent.mcp_bindings_json:
        try:
            bindings = json.loads(agent.mcp_bindings_json)
        except Exception:
            pass

    return {"agent_id": agent_id, "bindings": bindings}


@router.put("/agent/{agent_id}/mcp-bindings")
async def update_agent_mcp_bindings(
    agent_id: int,
    request: UpdateMcpBindingsRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update MCP resource bindings for a specific agent."""
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise AgentNotFoundError(agent_id)

    # RBAC: allow update if user owns the agent OR is a member of the agent's team
    if agent.user_id != user.id:
        if not agent.team_id or not await get_team_membership(user.id, agent.team_id):
            raise AgentNotFoundError(agent_id)

    agent.mcp_bindings_json = json.dumps(request.bindings) if request.bindings else None
    await db.commit()

    logger.info(f"Updated MCP bindings for agent {agent.name}: {request.bindings}")

    return {
        "agent_id": agent_id,
        "bindings": request.bindings,
        "message": f"Updated MCP resource bindings for '{agent.name}'",
    }
