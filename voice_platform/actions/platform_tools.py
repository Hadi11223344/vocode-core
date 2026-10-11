"""
Voice Platform — In-Call Tool Use (Live Function Calling)
===========================================================

Bridges platform integrations (Google Calendar, CRM, etc.) with vocode's
function calling system so the AI agent can execute tools DURING a call.

Architecture:
    1. Agent has `tools_config` JSON field listing enabled tools
    2. During call setup, agent_factory reads tools_config and creates
       ActionConfig objects with FunctionCallActionTrigger
    3. When the LLM decides to call a function, vocode invokes our action
    4. Our action executes via the platform's WorkflowExecutor
    5. The result is fed back to the LLM for a natural response

Supported Tools:
    - check_calendar: Check availability on Google Calendar
    - create_event: Create a calendar event
    - send_email: Send an email via configured email service
    - send_sms: Send an SMS message
    - lookup_contact: Look up a contact in CRM
    - create_ticket: Create a support ticket
    - search_knowledge: Search the knowledge base
    - webhook: Call an arbitrary webhook URL
    - end_call: End the current call
    - transfer_call: Transfer to another number
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Type

from loguru import logger
from pydantic.v1 import BaseModel, Field

from vocode.streaming.action.abstract_factory import AbstractActionFactory
from vocode.streaming.action.default_factory import (
    CONVERSATION_ACTIONS,
    TWILIO_ACTIONS,
    DefaultActionFactory,
)
from vocode.streaming.models.actions import ActionType

# ── Tool Loop Safety ───────────────────────────────────────────────────
# Track in-call tool executions per conversation to prevent infinite loops.
# Key: conversation_id, Value: (count, last_update_timestamp).
# Cleared on call end via clear_tool_counts(), or by _sweep_stale_entries().
_MAX_TOOLS_PER_CALL = 20
_call_tool_counts: Dict[str, Tuple[int, float]] = {}


def clear_tool_counts(conversation_id: str) -> None:
    """Clear tool call count for a conversation (call ended)."""
    _call_tool_counts.pop(conversation_id, None)

# ── Per-Conversation Document Cache ────────────────────────────────────
# When Drive files are read during a call, their content is cached here
# so the agent can reference them in subsequent turns.
# Key: conversation_id, Value: list of {filename, content, timestamp}
_DOCUMENT_CACHE: Dict[str, List[Dict[str, Any]]] = {}
_MAX_DOC_CACHE_AGE_SECONDS = 600  # 10 minutes
_MAX_DOCS_PER_CONVERSATION = 10  # Issue 19: prevent unbounded doc cache growth


async def _track_tool_run(tool_name: str, success: bool) -> None:
    """Fire-and-forget success/failure counter for tool analytics."""
    try:
        from datetime import date

        from voice_platform.cache import RedisCache

        day = date.today().isoformat()
        key = f"tool_stats:{day}:{tool_name}"
        field = "ok" if success else "fail"
        # Use simple string counters (ok:N, fail:N) since RedisCache is JSON-based
        data = await RedisCache.get(key) or {"ok": 0, "fail": 0}
        data[field] = (data.get(field, 0) or 0) + 1
        await RedisCache.set(key, data, ttl_seconds=86400 * 7)  # 7 days
    except Exception:
        pass  # Never block call for analytics


def _cache_document(conversation_id: str, filename: str, content: str) -> None:
    """Cache a document read from Drive for this conversation."""
    if not conversation_id:
        return
    entry = {
        "filename": filename,
        "content": content,
        "timestamp": time.time(),
    }
    if conversation_id not in _DOCUMENT_CACHE:
        _DOCUMENT_CACHE[conversation_id] = []
    _DOCUMENT_CACHE[conversation_id].append(entry)
    # Issue 19: Enforce max docs per conversation — drop oldest if exceeded
    if len(_DOCUMENT_CACHE[conversation_id]) > _MAX_DOCS_PER_CONVERSATION:
        _DOCUMENT_CACHE[conversation_id] = _DOCUMENT_CACHE[conversation_id][-_MAX_DOCS_PER_CONVERSATION:]
        logger.debug(f"Trimmed doc cache for {conversation_id[:12]} to last {_MAX_DOCS_PER_CONVERSATION} entries")
    logger.info(f"Cached document '{filename}' for conversation {conversation_id[:12]}")


def get_cached_documents(conversation_id: str) -> List[Dict[str, Any]]:
    """Get cached documents for a conversation, filtering expired entries."""
    if not conversation_id or conversation_id not in _DOCUMENT_CACHE:
        return []
    now = time.time()
    entries = [
        e for e in _DOCUMENT_CACHE[conversation_id]
        if now - e["timestamp"] < _MAX_DOC_CACHE_AGE_SECONDS
    ]
    _DOCUMENT_CACHE[conversation_id] = entries
    return entries


def clear_document_cache(conversation_id: str) -> None:
    """Clear document cache for a conversation (call ended)."""
    _DOCUMENT_CACHE.pop(conversation_id, None)


# ── MCP Tool Discovery Cache ──────────────────────────────────────────
# Cache key: (server_url, auth_token_hash), Value: (tools_list, timestamp)
# TTL: 300 seconds (5 minutes) to balance freshness with latency.
_MCP_TOOL_CACHE: Dict[str, Tuple[List[dict], float]] = {}
_MCP_CACHE_TTL_SECONDS = 300


def _get_cached_mcp_tools(server_url: str, auth_token: str) -> Optional[List[dict]]:
    """Return cached MCP tools if still within TTL, else None."""
    cache_key = f"{server_url}::{hash(auth_token) & 0xFFFFFFFF}"
    entry = _MCP_TOOL_CACHE.get(cache_key)
    if not entry:
        return None
    tools, ts = entry
    if time.time() - ts > _MCP_CACHE_TTL_SECONDS:
        _MCP_TOOL_CACHE.pop(cache_key, None)
        return None
    return tools


def _set_cached_mcp_tools(server_url: str, auth_token: str, tools: List[dict]) -> None:
    """Store MCP tools in cache with current timestamp."""
    cache_key = f"{server_url}::{hash(auth_token) & 0xFFFFFFFF}"
    _MCP_TOOL_CACHE[cache_key] = (tools, time.time())


# ── Stale Entry Sweeper ────────────────────────────────────────────────
# Periodically evicts orphaned entries from global dicts when calls drop
# without proper cleanup (crash, timeout, WebSocket disconnect).
_SWEEP_INTERVAL_SECONDS = 300  # 5 minutes between sweeps
_last_sweep: float = 0.0


def _sweep_stale_entries() -> None:
    """Evict stale entries from _call_tool_counts, _DOCUMENT_CACHE, and _MCP_TOOL_CACHE."""
    global _last_sweep
    now = time.time()
    if now - _last_sweep < _SWEEP_INTERVAL_SECONDS:
        return
    _last_sweep = now

    # _call_tool_counts: evict entries older than 1 hour
    _TOOL_COUNT_TTL = 3600
    for conv_id in list(_call_tool_counts.keys()):
        _, ts = _call_tool_counts[conv_id]
        if now - ts > _TOOL_COUNT_TTL:
            _call_tool_counts.pop(conv_id, None)
    if len(_call_tool_counts) > 1000:
        _call_tool_counts.clear()
        logger.warning("Cleared _call_tool_counts (exceeded 1000 entries)")

    # _DOCUMENT_CACHE: remove conversations with only expired entries
    for conv_id in list(_DOCUMENT_CACHE.keys()):
        entries = _DOCUMENT_CACHE[conv_id]
        fresh = [e for e in entries if now - e["timestamp"] < _MAX_DOC_CACHE_AGE_SECONDS]
        if not fresh:
            _DOCUMENT_CACHE.pop(conv_id, None)
        else:
            _DOCUMENT_CACHE[conv_id] = fresh

    # _MCP_TOOL_CACHE: evict expired entries
    for key in list(_MCP_TOOL_CACHE.keys()):
        _, ts = _MCP_TOOL_CACHE[key]
        if now - ts > _MCP_CACHE_TTL_SECONDS:
            _MCP_TOOL_CACHE.pop(key, None)


_GOOGLE_MCP_HOSTS = {
    "drivemcp.googleapis.com",
    "calendarmcp.googleapis.com",
    "gmailmcp.googleapis.com",
    "peoplemcp.googleapis.com",
}


async def build_mcp_tool_actions_for_server(
    server_url: str,
    auth_token: Optional[str],
    user_id: Optional[int],
) -> List[ActionConfig]:
    """Discover MCP tools for one server and build ActionConfig entries."""
    from urllib.parse import urlparse as _urlparse

    from voice_platform.integrations.mcp_client import McpClient

    resolved_server_url = (server_url or "").strip()
    if not resolved_server_url:
        return []

    resolved_auth_token = auth_token or ""
    try:
        parsed_host = (_urlparse(resolved_server_url).hostname or "").lower()
    except Exception:
        parsed_host = ""

    if parsed_host in _GOOGLE_MCP_HOSTS and not resolved_auth_token and user_id:
        try:
            from voice_platform.integrations.google_oauth import GoogleOAuthManager

            creds = await GoogleOAuthManager.get_credentials(user_id)
            if creds and creds.token:
                resolved_auth_token = creds.token
                logger.info(
                    f"Resolved Google OAuth token for MCP server {resolved_server_url}"
                )
        except Exception as oauth_err:
            logger.warning(
                f"Google OAuth resolution failed for MCP server {resolved_server_url}: {oauth_err}"
            )

    cached = _get_cached_mcp_tools(resolved_server_url, resolved_auth_token)
    if cached is not None:
        mcp_tools = cached
        logger.debug(
            f"MCP server {resolved_server_url}: using cached tools ({len(mcp_tools)})"
        )
    else:
        try:
            client = McpClient(
                server_url=resolved_server_url,
                auth_token=resolved_auth_token or None,
                timeout=10.0,
            )
            mcp_tools = await client.list_tools()
            await client.aclose()
            _set_cached_mcp_tools(resolved_server_url, resolved_auth_token, mcp_tools)
            logger.info(
                f"MCP server {resolved_server_url}: discovered {len(mcp_tools)} tool(s)"
            )
        except Exception as mcp_err:
            logger.warning(
                f"MCP tool discovery failed for {resolved_server_url}: {mcp_err}"
            )
            return []

    action_configs: List[ActionConfig] = []
    for tool in mcp_tools:
        tool_name_mcp = tool.get("name", "")
        if not tool_name_mcp:
            continue
        action_configs.append(
            PlatformToolActionConfig(
                tool_name=tool_name_mcp,
                tool_description=tool.get("description", f"MCP tool from {resolved_server_url}"),
                tool_parameters_schema=json.dumps(
                    tool.get("inputSchema", {"type": "object", "properties": {}})
                ),
                integration_type="mcp",
                integration_action="call_tool",
                user_id=user_id or 0,
                mcp_server_url=resolved_server_url,
                mcp_auth_token=resolved_auth_token,
            )
        )

    return action_configs

from vocode.streaming.action.base_action import BaseAction
from vocode.streaming.models.actions import (
    ActionConfig,
    ActionInput,
    ActionOutput,
    ActionType,
    FunctionCallActionTrigger,
)
from vocode.streaming.models.message import BaseMessage

# ═══════════════════════════════════════════════════════════════════════
# Tool Definitions — Each tool the agent can call during a conversation
# ═══════════════════════════════════════════════════════════════════════

PLATFORM_TOOLS = {
    # ── Google Workspace ────────────────────────────────────────────
    "read_sheet": {
        "name": "read_sheet",
        "description": (
            "Check if we already have someone's information in our records. "
            "Use this to look up existing contacts, check if a lead is already logged, "
            "or find details about a previous inquiry. After checking, summarize what "
            "you found naturally — don't mention spreadsheets or rows."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "range": {"type": "string", "description": "A1 notation range, e.g. 'A1:D10'. Leave empty to read all."},
                "max_rows": {"type": "integer", "description": "Max rows to return (default 100)"},
            },
            "required": [],
        },
        "integration_type": "google_sheets",
        "action": "read_rows",
    },
    "append_sheet": {
        "name": "append_sheet",
        "description": (
            "Save someone's contact details and information to our records (Google Sheet). "
            "Use this to log a new lead, save a contact, or record call notes. "
            "Call this as soon as you have a name and phone number. "
            "IMPORTANT: Always pass values in this exact column order: "
            "[Name, Phone, Patient Type, Service, Dentist, Date, Time, Notes]. "
            "Use empty string for fields you don't have yet. "
            "Do NOT call this multiple times for the same person — call it once with all the information you have. "
            "If you need to update an existing row, use update_sheet_row instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Cell values in column order: [Name, Phone, Patient Type, Service, Dentist, Date, Time, Notes]",
                },
            },
            "required": ["values"],
        },
        "integration_type": "google_sheets",
        "action": "append_row",
        "required_context": {
            "min_values": 2,
            "gate_message": "I need to collect more information before saving. Could you tell me your name and phone number?",
        },
    },
    "update_sheet_row": {
        "name": "update_sheet_row",
        "description": (
            "Update an existing row in our records (Google Sheet) with new or corrected information. "
            "Use this when you already saved someone's details and want to add more info "
            "(like service, dentist, date, time) or fix a mistake. "
            "You must provide the row_number returned from a previous append_sheet call. "
            "Pass ALL columns in the same order: [Name, Phone, Patient Type, Service, Dentist, Date, Time, Notes]."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "row_number": {"type": "integer", "description": "Row number to update (returned from append_sheet)"},
                "values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "All cell values in column order: [Name, Phone, Patient Type, Service, Dentist, Date, Time, Notes]",
                },
            },
            "required": ["row_number", "values"],
        },
        "integration_type": "google_sheets",
        "action": "update_row",
    },
    "check_calendar": {
        "name": "check_calendar",
        "description": (
            "Check what times and dates are available for a visit, meeting, or appointment. "
            "Use this when someone wants to schedule something and you need to find open slots. "
            "If this tool fails or returns no results, tell the caller you cannot check the calendar right now "
            "and DO NOT make up or fabricate any time slots. Ask the caller to try again later or suggest they visit in person."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date to check (YYYY-MM-DD). Defaults to today."},
                "duration_minutes": {"type": "string", "description": "Meeting duration in minutes (default 60). Pass as a string like '30' or '60'."},
            },
            "required": [],
        },
        "integration_type": "google_calendar",
        "action": "check_availability",
    },
    "create_event": {
        "name": "create_event",
        "description": (
            "Schedule a meeting or appointment on the calendar. "
            "Always confirm the date, time, and purpose with the person before scheduling."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start datetime (ISO 8601)"},
                "end": {"type": "string", "description": "End datetime (ISO 8601)"},
                "description": {"type": "string", "description": "Event description"},
                "location": {"type": "string", "description": "Event location"},
            },
            "required": ["summary", "start"],
        },
        "integration_type": "google_calendar",
        "action": "create_event",
    },
    "book_appointment": {
        "name": "book_appointment",
        "description": (
            "FINALIZE a confirmed appointment by creating it on the calendar. "
            "Use this AFTER you and the caller have AGREED on date, time, and purpose/service. "
            "You MUST call this tool before telling the caller the appointment is booked. "
            "If the tool fails or returns an error, tell the caller honestly that the booking could not be completed and offer to try again. "
            "Never say the appointment is 'all set' or 'confirmed' until this tool returns success."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Appointment date (YYYY-MM-DD)"},
                "time": {"type": "string", "description": "Appointment start time (HH:MM, 24h format, e.g. '14:30')"},
                "duration_minutes": {"type": "string", "description": "Duration in minutes (default 30). Pass as a string like '30'."},
                "purpose": {"type": "string", "description": "Purpose or title of the appointment"},
                "attendee_email": {"type": "string", "description": "Optional attendee email to invite"},
                "location": {"type": "string", "description": "Optional location or meeting link"},
            },
            "required": ["date", "time", "purpose"],
        },
        "integration_type": "google_calendar",
        "action": "book_appointment",
        "required_context": {
            "required_params": ["date", "time", "purpose"],
            "gate_message": "I need to know what date, time, and purpose before I can book the appointment. Could you please confirm those details?",
        },
    },
    "read_drive_file": {
        "name": "read_drive_file",
        "description": (
            "Read content from a specific file that this agent has been given access to. "
            "Use this when the caller asks about data stored in a specific document. "
            "After reading, summarize the key information and remember it for the rest of the call."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "File ID"},
                "file_name": {"type": "string", "description": "Human-readable file name for reference"},
            },
            "required": ["file_id"],
        },
        "integration_type": "google_drive_mcp",
        "action": "read_file_content",
    },
    # ── Communication ───────────────────────────────────────────────
    "send_email": {
        "name": "send_email",
        "description": (
            "Send an email with details or information to someone. "
            "Use this to send a summary, confirm an appointment, or share follow-up details. "
            "Always confirm the recipient's email address and what you'll send before sending."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Plain text email body"},
            },
            "required": ["to", "subject", "body"],
        },
        "integration_type": "email",
        "action": "send_email",
    },
    "send_sms": {
        "name": "send_sms",
        "description": (
            "Send a quick text message to someone. "
            "Use this for confirmations, reminders, or sharing brief details. "
            "Always confirm the phone number before sending."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient phone number (E.164 format)"},
                "body": {"type": "string", "description": "Message text (max 1600 chars)"},
            },
            "required": ["to", "body"],
        },
        "integration_type": "sms",
        "action": "send_sms",
    },
    "send_whatsapp": {
        "name": "send_whatsapp",
        "description": (
            "Send a message via the connected messaging service. "
            "Use for order confirmations, appointment reminders, and follow-ups. "
            "The recipient must have opted in to receive messages."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient phone number (E.164 format, e.g. +1234567890)"},
                "text": {"type": "string", "description": "Message text (max 4096 chars)"},
            },
            "required": ["to", "text"],
        },
        "integration_type": "whatsapp_cloud",
        "action": "send_message",
    },
    "send_telegram": {
        "name": "send_telegram",
        "description": (
            "Send a message via the connected messaging service. "
            "Use for notifications, confirmations, and alerts. "
            "The recipient must have started the bot first."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string", "description": "Telegram chat ID or @username"},
                "text": {"type": "string", "description": "Message text (max 4096 chars, Markdown supported)"},
            },
            "required": ["chat_id", "text"],
        },
        "integration_type": "telegram_bot",
        "action": "send_message",
    },
    # ── Memory / Context ────────────────────────────────────────────
    "recall_document": {
        "name": "recall_document",
        "description": (
            "Recall content from a document or sheet that was previously read during this call. "
            "Use this when the caller refers to something mentioned earlier, e.g. "
            "'order 50 more of that' or 'what was the price again?'. "
            "Pass the filename or sheet name as the query."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name or partial name of the previously read document/sheet"},
            },
            "required": ["query"],
        },
        "integration_type": "recall_document",  # special — no external integration
        "action": "recall",
    },
    # ── Generic ─────────────────────────────────────────────────────
    "webhook": {
        "name": "call_webhook",
        "description": "Call an external webhook API to perform a custom action. Use this for custom integrations.",
        "parameters": {
            "type": "object",
            "properties": {
                "data": {"type": "object", "description": "JSON data to send to the webhook"},
            },
            "required": ["data"],
        },
        "integration_type": "webhook",
        "action": "post",
    },
}


# ═══════════════════════════════════════════════════════════════════════
# Platform Tool Action — vocode-compatible action for in-call tool use
# ═══════════════════════════════════════════════════════════════════════

class PlatformToolActionConfig(ActionConfig, type="action_platform_tool"):  # type: ignore
    """Config for a platform integration tool."""
    tool_name: str = ""
    tool_description: str = ""
    tool_parameters_schema: str = "{}"
    integration_type: str = ""
    integration_action: str = ""
    user_id: int = 0
    # Per-agent integration override — specific integration ID to use
    # instead of the first active one of this type.
    integration_id_override: Optional[int] = None
    # ── MCP-specific fields (BUG-B1 fix) ──────────────────────────────
    # Populated at agent-setup time by build_tool_actions() so run()
    # doesn't need to query the DB to resolve which MCP server to call.
    mcp_server_url: str = ""
    mcp_auth_token: str = ""   # encrypted — decrypted at build time
    # Issue 14: Agent timezone for calendar bookings (IANA tz string, e.g. "Asia/Karachi")
    agent_timezone: str = "Asia/Karachi"


class PlatformToolParameters(BaseModel):
    """Generic parameters — actual fields vary by tool."""
    payload: Dict[str, Any] = Field(default_factory=dict)


class PlatformToolResponse(BaseModel):
    """Response from executing a platform tool."""
    success: bool  # No default — must be explicit (LOGIC-3 fix)
    result: Optional[str] = None
    error: Optional[str] = None


class PlatformToolAction(
    BaseAction[
        PlatformToolActionConfig,
        PlatformToolParameters,
        PlatformToolResponse,
    ]
):
    """
    vocode Action that executes platform integrations during a call.
    
    When the LLM calls a function (e.g., "check_calendar"),
    this action:
    1. Receives the parameters from the LLM
    2. Looks up the user's integration for the service type
    3. Executes the action via WorkflowExecutor
    4. Returns the result to the LLM for natural language response
    """
    
    parameters_type: Type[PlatformToolParameters] = PlatformToolParameters
    response_type: Type[PlatformToolResponse] = PlatformToolResponse
    
    def __init__(self, action_config: PlatformToolActionConfig):
        self.description = action_config.tool_description
        super().__init__(
            action_config,
            should_respond="always",  # Always tell user before executing
            quiet=False,
            is_interruptible=True,  # Fix E: Allow interruption so callers can cancel long tool calls
        )
    
    def get_function_name(self) -> str:
        return self.action_config.tool_name
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        return json.loads(self.action_config.tool_parameters_schema)
    
    def create_action_params(self, params: Dict[str, Any]) -> PlatformToolParameters:
        return PlatformToolParameters(payload=params)

    def _check_required_context(self, tool_name: str, params: Dict[str, Any]) -> Optional[str]:
        """S2: Check required_context gate for a tool. Returns gate_message if blocked, None if passed."""
        tool_def = PLATFORM_TOOLS.get(tool_name, {})
        gate = tool_def.get("required_context")
        if not gate:
            return None

        # min_values gate (e.g. append_sheet needs >= 2 non-empty values)
        min_values = gate.get("min_values")
        if min_values is not None:
            values = params.get("values", [])
            if isinstance(values, list):
                non_empty = [v for v in values if v and str(v).strip()]
                if len(non_empty) < min_values:
                    logger.warning(
                        f"Gate blocked {tool_name}: only {len(non_empty)} non-empty values "
                        f"(need >= {min_values})."
                    )
                    return gate.get("gate_message", "I need more information first.")

        # required_params gate (e.g. book_appointment needs date, time, purpose)
        required_params = gate.get("required_params")
        if required_params:
            missing = [f for f in required_params if not params.get(f)]
            if missing:
                logger.warning(f"Gate blocked {tool_name}: missing required params {missing}")
                return gate.get("gate_message", "I need more information first.")

        return None
    
    async def run(
        self, action_input: ActionInput[PlatformToolParameters]
    ) -> ActionOutput[PlatformToolResponse]:
        """Execute the platform integration action."""
        # ── Wait for user_message to be spoken before executing ───────────
        # Prevents dead air: the LLM generates a user_message (e.g., "Let me
        # check that for you") which is sent to TTS. We wait for it to finish
        # before running the tool, so the caller hears something during execution.
        if action_input.user_message_tracker is not None:
            try:
                await asyncio.wait_for(
                    action_input.user_message_tracker.wait(),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                logger.warning("user_message_tracker timed out after 5s — proceeding with tool execution")
            except Exception as _e:
                logger.debug(f"user_message_tracker wait skipped: {_e}")

        tool_name = self.action_config.tool_name
        params = action_input.params.payload
        conv_id = getattr(action_input, "conversation_id", "")

        # ── S2: Required-context gate ───────────────────────────────────
        # Generalized programmatic gate that replaces the hardcoded Issue 01
        # guard. Checks required_context from PLATFORM_TOOLS definitions.
        gate_message = self._check_required_context(tool_name, params)
        if gate_message is not None:
            return ActionOutput(
                action_type=action_input.action_config.type,
                response=PlatformToolResponse(
                    success=False,
                    result=gate_message,
                    error=f"Gate: {tool_name} called with insufficient data",
                ),
            )

        # ── Phone number validation (Issue 05) ────────────────────────────
        # Runs after the gate passes — checks for incomplete phone numbers
        # in append_sheet values.
        if tool_name == "append_sheet":
            values = params.get("values", [])
            if isinstance(values, list):
                non_empty = [v for v in values if v and str(v).strip()]
                for v in non_empty:
                    digits = re.sub(r'\D', '', str(v))
                    if 7 <= len(digits) <= 15 and digits.startswith('0'):
                        if len(digits) < 10:
                            logger.warning(
                                f"append_sheet blocked: phone number has only {len(digits)} digits. "
                                f"conversation={conv_id[:12] if conv_id else '?'}"
                            )
                            return ActionOutput(
                                action_type=action_input.action_config.type,
                                response=PlatformToolResponse(
                                    success=False,
                                    result=f"The phone number you gave me seems incomplete — it has only {len(digits)} digits. Could you repeat your full phone number?",
                                    error=f"Phone number too short: {len(digits)} digits (expected 10+)",
                                ),
                            )

        # ── Coerce string params to int where needed ──────────────────────────
        # LLMs often pass integers as strings (e.g. "30" instead of 30).
        # The executor expects actual ints for duration_minutes.
        if "duration_minutes" in params and isinstance(params["duration_minutes"], str):
            try:
                params["duration_minutes"] = int(params["duration_minutes"])
            except (ValueError, TypeError):
                pass  # Let the executor handle invalid values

        # ── Tool loop safety: hard limit per call ──────────────────────────────
        if conv_id:
            prev = _call_tool_counts.get(conv_id, (0, 0.0))
            count = prev[0] + 1
            if count > _MAX_TOOLS_PER_CALL:
                logger.warning(f"🚫 Tool loop limit reached for call {conv_id[:12]}. Blocking {tool_name}.")
                return ActionOutput(
                    action_type=action_input.action_config.type,
                    response=PlatformToolResponse(
                        success=False,
                        result="I'm unable to perform additional actions at this time.",
                        error=f"Tool loop limit ({_MAX_TOOLS_PER_CALL}) exceeded",
                    ),
                )
            _call_tool_counts[conv_id] = (count, time.time())

        logger.info(f"🔧 In-call tool use #{_call_tool_counts.get(conv_id, (1, 0.0))[0]}: {tool_name} with params: {params}")

        # ── MCP dispatch (BUG-B1/B2 fix) ───────────────────────────────────────
        # MCP tools carry server_url + auth_token in the action config (set at
        # agent-setup time by build_tool_actions).  No DB query needed at call
        # time — this fixes BUG-B1 (multi-MCP wrong server) because each tool
        # action knows exactly which server it belongs to.
        if self.action_config.integration_type == "mcp":
            try:
                from voice_platform.integrations.mcp_client import McpClient

                server_url = self.action_config.mcp_server_url
                auth_token = self.action_config.mcp_auth_token or None

                if not server_url:
                    return ActionOutput(
                        action_type=action_input.action_config.type,
                        response=PlatformToolResponse(
                            success=False,
                            result=(
                                "I'm unable to access that service right now — "
                                "the MCP server URL is not configured."
                            ),
                            error="MCP action config missing mcp_server_url",
                        ),
                    )

                logger.info(f"🌐 MCP in-call tool: {tool_name} @ {server_url}")
                client = McpClient(
                    server_url=server_url,
                    auth_token=auth_token,
                    timeout=30.0,
                )
                try:
                    result = await client.call_tool(tool_name, params)
                finally:
                    await client.aclose()

                # McpClient already truncates to 4000 chars (LOGIC-1 fix:
                # removed redundant 2000-char truncation here)
                result_text = (
                    json.dumps(result) if isinstance(result, (dict, list))
                    else str(result)
                )

                logger.info(f"✅ MCP tool {tool_name} result: {result_text[:100]}")
                await _track_tool_run(tool_name, True)

                # Cache document content for read_file_content tool calls
                if tool_name == "read_file_content" and conv_id:
                    filename = params.get("file_id") or params.get("name") or "unknown"
                    _cache_document(conv_id, filename, result_text)

                return ActionOutput(
                    action_type=action_input.action_config.type,
                    response=PlatformToolResponse(
                        success=True,
                        result=result_text,
                    ),
                )

            except Exception as mcp_err:
                logger.error(f"❌ MCP in-call tool {tool_name} failed: {mcp_err}")
                await _track_tool_run(tool_name, False)
                return ActionOutput(
                    action_type=action_input.action_config.type,
                    response=PlatformToolResponse(
                        success=False,
                        result=(
                            "I'm sorry, I'm having trouble accessing that service "
                            "right now. I've noted your request for follow-up."
                        ),
                        error=str(mcp_err)[:200],
                    ),
                )
        # ── END MCP dispatch ──────────────────────────────────────────────────

        # ── Special: recall_document (no external integration needed) ──────────
        if self.action_config.integration_type == "recall_document":
            query = str(params.get("query", "")).lower()
            if not query:
                return ActionOutput(
                    action_type=action_input.action_config.type,
                    response=PlatformToolResponse(
                        success=False,
                        result="I need a document or sheet name to recall. Which one?",
                        error="Missing query parameter",
                    ),
                )
            docs = get_cached_documents(conv_id)
            matches = [
                d for d in docs
                if query in d.get("filename", "").lower()
                or query in d.get("content", "").lower()
            ]
            if not matches:
                available = ", ".join(d.get("filename", "unknown") for d in docs[:5]) or "none"
                return ActionOutput(
                    action_type=action_input.action_config.type,
                    response=PlatformToolResponse(
                        success=True,
                        result=(
                            f"I don't have a document matching '{query}' in memory. "
                            f"Available documents: {available}."
                        ),
                    ),
                )
            combined = "\n\n".join(
                f"--- {d.get('filename', 'Document')} ---\n{d.get('content', '')[:1500]}"
                for d in matches[:3]
            )
            return ActionOutput(
                action_type=action_input.action_config.type,
                response=PlatformToolResponse(
                    success=True,
                    result=combined,
                ),
            )
        # ── END recall_document ───────────────────────────────────────────────

        # ── Special: book_appointment (composite: check availability + create) ─
        if self.action_config.integration_action == "book_appointment":
            from datetime import datetime, timedelta
            from zoneinfo import ZoneInfo

            date_str = str(params.get("date", ""))
            time_str = str(params.get("time", ""))
            duration = int(params.get("duration_minutes", 30))
            purpose = str(params.get("purpose", "Appointment"))
            attendee = str(params.get("attendee_email", ""))
            location = str(params.get("location", ""))

            if not date_str or not time_str:
                return ActionOutput(
                    action_type=action_input.action_config.type,
                    response=PlatformToolResponse(
                        success=False,
                        result="I need both a date and time to book the appointment. Could you please confirm?",
                        error="Missing date or time parameter",
                    ),
                )

            try:
                _tz_name = getattr(self.action_config, 'agent_timezone', None) or "Asia/Karachi"
                _agent_tz = ZoneInfo(_tz_name)
                start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                start_dt = start_dt.replace(tzinfo=_agent_tz)
                end_dt = start_dt + timedelta(minutes=duration)
            except ValueError:
                return ActionOutput(
                    action_type=action_input.action_config.type,
                    response=PlatformToolResponse(
                        success=False,
                        result="I didn't understand that date or time format. Could you say it differently?",
                        error="Invalid date/time format",
                    ),
                )

            # Check availability then create event via legacy executor
            from sqlalchemy import select

            from voice_platform.database import Integration, async_session
            from voice_platform.integrations.executor import WorkflowExecutor

            async with async_session() as session:
                integration = None
                override_id = getattr(self.action_config, 'integration_id_override', None)
                if override_id:
                    int_result = await session.execute(
                        select(Integration).where(
                            Integration.id == override_id,
                            Integration.user_id == self.action_config.user_id,
                            Integration.is_active == True,
                        )
                    )
                    integration = int_result.scalar_one_or_none()
                    if not integration:
                        logger.warning(
                            f"book_appointment: Override integration {override_id} not found. "
                            f"Falling back to first active google_calendar integration."
                        )
                if not integration:
                    int_result = await session.execute(
                        select(Integration).where(
                            Integration.user_id == self.action_config.user_id,
                            Integration.service_type == "google_calendar",
                            Integration.is_active == True,
                        )
                    )
                    integration = int_result.scalars().first()
                if not integration:
                    return ActionOutput(
                        action_type=action_input.action_config.type,
                        response=PlatformToolResponse(
                            success=False,
                            result="I don't have Google Calendar connected yet. Please set it up in Integrations.",
                            error="No google_calendar integration configured",
                        ),
                    )

                from voice_platform.integrations.plugins.registry import (
                    build_default_plugin_registry,
                )
                executor = WorkflowExecutor(
                    session, self.action_config.user_id,
                    plugin_registry=build_default_plugin_registry(),
                    agent_timezone=getattr(self.action_config, 'agent_timezone', None),
                )

                # Step 1: Check availability
                avail = await executor.execute_single_step(
                    {
                        "type": "google_calendar",
                        "action": "check_availability",
                        "integration_id": integration.id,
                        "params": {"date": date_str, "duration_minutes": duration},
                    },
                    context={},
                )
                available_slots = []
                if isinstance(avail, dict):
                    available_slots = avail.get("available_slots", [])
                elif isinstance(avail, list):
                    available_slots = avail

                start_iso = start_dt.isoformat()
                # Check if requested time is within an available slot
                slot_found = False
                for slot in available_slots:
                    s_start = slot.get("start", "")
                    s_end = slot.get("end", "")
                    if s_start <= start_iso < s_end:
                        slot_found = True
                        break

                # If no slots returned or slot not found, warn but still try to create
                if available_slots and not slot_found:
                    return ActionOutput(
                        action_type=action_input.action_config.type,
                        response=PlatformToolResponse(
                            success=False,
                            result=f"That time slot on {date_str} at {time_str} doesn't appear to be available. Would you like to pick a different time?",
                            error="Time slot not available",
                        ),
                    )

                # Step 2: Create the event
                event_params = {
                    "summary": purpose,
                    "start": start_iso,
                    "end": end_dt.isoformat(),
                    "description": f"Booked via voice agent. Purpose: {purpose}",
                }
                if location:
                    event_params["location"] = location
                if attendee:
                    event_params["attendees"] = [{"email": attendee}]

                try:
                    result = await executor.execute_single_step(
                        {
                            "type": "google_calendar",
                            "action": "create_event",
                            "integration_id": integration.id,
                            "params": event_params,
                        },
                        context={},
                    )
                except Exception as e:
                    logger.error(f"book_appointment create_event failed: {e}")
                    return ActionOutput(
                        action_type=action_input.action_config.type,
                        response=PlatformToolResponse(
                            success=False,
                            result="I'm sorry, I wasn't able to finalize the appointment in our calendar right now. Could we try booking again in a moment?",
                            error=str(e),
                        ),
                    )

                if isinstance(result, dict) and (result.get("error") or result.get("status") == "error"):
                    error_msg = result.get("error", "Calendar event creation failed")
                    logger.error(f"book_appointment create_event returned error: {error_msg}")
                    return ActionOutput(
                        action_type=action_input.action_config.type,
                        response=PlatformToolResponse(
                            success=False,
                            result="I'm sorry, I wasn't able to finalize the appointment in our calendar right now. Could we try booking again in a moment?",
                            error=error_msg,
                        ),
                    )

                result_text = json.dumps(result) if isinstance(result, dict) else str(result)
                return ActionOutput(
                    action_type=action_input.action_config.type,
                    response=PlatformToolResponse(
                        success=True,
                        result=f"Appointment booked! {purpose} on {date_str} at {time_str}. {result_text[:200]}",
                    ),
                )

        # ── END book_appointment ──────────────────────────────────────────────

        try:
            # Legacy path: execute via platform integration system
            from sqlalchemy import select

            from voice_platform.database import Integration, async_session
            from voice_platform.integrations.executor import WorkflowExecutor

            async with async_session() as session:
                # Find the user's integration for this service type
                # Prefer integration_id_override if set (per-agent selector)
                integration = None
                override_id = getattr(self.action_config, 'integration_id_override', None)
                if override_id:
                    int_result = await session.execute(
                        select(Integration).where(
                            Integration.id == override_id,
                            Integration.user_id == self.action_config.user_id,
                            Integration.is_active == True,
                        )
                    )
                    integration = int_result.scalar_one_or_none()
                    if not integration:
                        logger.warning(
                            f"Override integration {override_id} not found or inactive for user "
                            f"{self.action_config.user_id}. Falling back to first active "
                            f"{self.action_config.integration_type} integration."
                        )
                if not integration:
                    int_result = await session.execute(
                        select(Integration).where(
                            Integration.user_id == self.action_config.user_id,
                            Integration.service_type == self.action_config.integration_type,
                            Integration.is_active == True,
                        )
                    )
                    integration = int_result.scalars().first()

                if not integration:
                    # Platform SMTP fallback for email — use .env SMTP settings
                    if self.action_config.integration_type == "email":
                        from voice_platform.config import settings as _settings
                        if _settings.smtp_host and _settings.smtp_password:
                            from voice_platform.integrations.email_client import EmailClient
                            _client = EmailClient(
                                api_key=_settings.smtp_password,
                                config={
                                    "smtp_host": _settings.smtp_host,
                                    "smtp_port": _settings.smtp_port,
                                    "smtp_user": _settings.smtp_user,
                                    "from_email": _settings.smtp_from_email or _settings.smtp_user,
                                    "from_name": _settings.smtp_from_name,
                                    "use_tls": _settings.smtp_use_tls,
                                },
                            )
                            try:
                                _result = await _client.send_email(
                                    to=params.get("to", ""),
                                    subject=params.get("subject", ""),
                                    body=params.get("body", ""),
                                    html_body=params.get("html_body"),
                                    cc=params.get("cc"),
                                    attachments=params.get("attachments"),
                                )
                                result_text = json.dumps(_result) if isinstance(_result, dict) else str(_result)
                                logger.info(f"✅ Tool {tool_name} (platform SMTP) result: {result_text[:100]}")
                                await _track_tool_run(tool_name, True)
                                return ActionOutput(
                                    action_type=action_input.action_config.type,
                                    response=PlatformToolResponse(
                                        success=True,
                                        result=result_text,
                                    ),
                                    canned_response=None,
                                )
                            except Exception as smtp_err:
                                result_text = f"Email sending failed: {str(smtp_err)[:200]}"
                                logger.warning(f"Platform SMTP failed for {tool_name}: {smtp_err}")
                                return ActionOutput(
                                    action_type=action_input.action_config.type,
                                    response=PlatformToolResponse(
                                        success=False,
                                        result=result_text,
                                        error=str(smtp_err),
                                    ),
                                )

                    # No integration configured — return helpful message
                    _is_calendar = self.action_config.integration_type in ("google_calendar",)
                    if _is_calendar:
                        result_text = (
                            "I don't have the calendar connected right now, so I cannot check availability or book appointments. "
                            "Please DO NOT make up or fabricate any time slots or confirmations. "
                            "Tell the caller you cannot check the calendar at the moment and ask them to try again later or visit in person."
                        )
                    else:
                        result_text = (
                            f"I don't have {self.action_config.integration_type} configured yet. "
                            f"The caller's request has been noted for follow-up."
                        )
                    return ActionOutput(
                        action_type=action_input.action_config.type,
                        response=PlatformToolResponse(
                            success=False,
                            result=result_text,
                            error=f"No {self.action_config.integration_type} integration configured",
                        ),
                    )

                # Execute the action
                from voice_platform.integrations.plugins.registry import (
                    build_default_plugin_registry,
                )
                executor = WorkflowExecutor(
                    session, self.action_config.user_id,
                    plugin_registry=build_default_plugin_registry(),
                    agent_timezone=getattr(self.action_config, 'agent_timezone', None),
                )

                # Build step config matching workflow executor format
                step = {
                    "type": self.action_config.integration_type,
                    "action": self.action_config.integration_action,
                    "integration_id": integration.id,
                    "params": params,
                }

                _exec_success = False
                try:
                    result = await executor.execute_single_step(step, context={})
                    result_text = json.dumps(result) if isinstance(result, dict) else str(result)
                    _exec_success = True
                except Exception as exec_err:
                    _is_cal = self.action_config.integration_type == "google_calendar"
                    if _is_cal:
                        result_text = (
                            "The calendar check failed. DO NOT make up or fabricate any time slots or confirmations. "
                            "Tell the caller you cannot check the calendar right now and ask them to try again later."
                        )
                    else:
                        result_text = (
                            f"The {tool_name} tool failed with an error: {str(exec_err)[:200]}. "
                            "Do not retry the same action. Inform the caller and offer to try again later."
                        )
                    logger.warning(f"⚠️ Tool {tool_name} execution failed: {str(exec_err)[:200]}")
                    await _track_tool_run(tool_name, False)

                    return ActionOutput(
                        action_type=action_input.action_config.type,
                        response=PlatformToolResponse(
                            success=False,
                            result=result_text,
                            error=str(exec_err)[:200],
                        ),
                        canned_response=None,
                    )

                # ── Cache document content for later recall ─────────────────────
                if conv_id and self.action_config.integration_type in (
                    "google_sheets", "google_calendar", "email", "sms"
                ):
                    doc_name = f"{tool_name} ({integration.name})"
                    _cache_document(conv_id, doc_name, result_text)

                logger.info(f"✅ Tool {tool_name} result: {result_text[:100]}")
                await _track_tool_run(tool_name, True)

                return ActionOutput(
                    action_type=action_input.action_config.type,
                    response=PlatformToolResponse(
                        success=True,
                        result=result_text,
                    ),
                    canned_response=None,
                )

        except Exception as e:
            logger.error(f"❌ Tool {tool_name} failed: {e}")
            await _track_tool_run(tool_name, False)
            _is_cal_outer = self.action_config.integration_type == "google_calendar"
            _err_result = (
                "The calendar check failed. DO NOT make up or fabricate any time slots or confirmations. "
                "Tell the caller you cannot check the calendar right now and ask them to try again later."
                if _is_cal_outer
                else f"I'm sorry, I'm having trouble with that right now. Please try again later."
            )
            return ActionOutput(
                action_type=action_input.action_config.type,
                response=PlatformToolResponse(
                    success=False,
                    result=_err_result,
                    error=str(e)[:200],
                ),
            )



# ═══════════════════════════════════════════════════════════════════════
# Helper: Build action configs from agent's tools_config
# ═══════════════════════════════════════════════════════════════════════

async def build_tool_actions(
    tools_config: List[str],
    user_id: int,
    mcp_bindings: Optional[Dict[str, Any]] = None,
    tool_instructions: Optional[str] = None,
    integration_overrides: Optional[Dict[str, Any]] = None,
    agent_timezone: Optional[str] = None,
) -> Tuple[List[ActionConfig], List[Tuple[str, str]]]:
    """
    Build vocode ActionConfig list from agent's enabled tool names.

    Includes:
      1. Static tools from PLATFORM_TOOLS whose integration is connected
      2. Dynamic MCP tools discovered from the user's active MCP servers
         (BUG-B2 fix — previously MCP tools were never registered)

    Args:
        tools_config: List of tool names (e.g., ["check_calendar", "send_email"])
        user_id: The user who owns the agent (for integration lookup)
        mcp_bindings: Optional dict of bound resources to inject as defaults
                      e.g., {"drive": {"file_ids": ["abc123"]}, "calendar": {"calendar_ids": ["primary"]}}
        tool_instructions: Optional per-agent instructions appended to each tool description.
        integration_overrides: Optional dict mapping integration type to specific integration ID.
                               e.g., {"google_sheets": 123, "google_calendar": 456}

    Returns:
        Tuple of (actions, skipped_tools) where skipped_tools is a list of
        (tool_name, integration_type) pairs that were skipped because the
        integration is not connected.
    """
    # Periodically sweep stale entries from global caches (Issue 10)
    _sweep_stale_entries()

    from sqlalchemy import select

    from voice_platform.database import Integration, UserApiKey, async_session

    # Query active integrations for this user
    active_types = set()
    mcp_integrations = []
    try:
        async with async_session() as session:
            result = await session.execute(
                select(Integration.service_type).where(
                    Integration.user_id == user_id,
                    Integration.is_active == True,
                ).distinct()
            )
            active_types = {row[0] for row in result.all()}

            # ── BUG-B2 fix: Discover MCP tools dynamically ────────────────
            if "mcp" in active_types:
                from voice_platform.encryption import decrypt

                mcp_result = await session.execute(
                    select(Integration).where(
                        Integration.user_id == user_id,
                        Integration.service_type == "mcp",
                        Integration.is_active == True,
                    )
                )
                for integration in mcp_result.scalars().all():
                    cfg: dict = {}
                    config_json: str = integration.config_json or ""  # type: ignore[assignment]
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

                    # Resolve auth token (BUG-B1 fix: each integration
                    # gets its own resolved token, not shared)
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
                            api_key_val: str = key_row.api_key  # type: ignore[assignment]
                            auth_token = decrypt(api_key_val)

                    mcp_integrations.extend(
                        await build_mcp_tool_actions_for_server(
                            server_url,
                            auth_token or None,
                            user_id,
                        )
                    )
            # ── END BUG-B2 fix ─────────────────────────────────────────────

    except Exception as e:
        logger.warning(f"Could not load integrations for tool filtering: {e}")

    actions: List[ActionConfig] = []
    skipped_tools: List[Tuple[str, str]] = []

    # 1. Static tools from PLATFORM_TOOLS
    for tool_name in tools_config:
        tool_def = PLATFORM_TOOLS.get(tool_name)
        if not tool_def:
            logger.warning(f"Unknown tool '{tool_name}' in agent tools_config, skipping")
            continue
        
        integration_type: str = tool_def["integration_type"]
        
        # B-005: Skip tools whose integration is not connected
        # Exception: recall_document needs no external integration (memory-only)
        # Exception: email can fall back to platform SMTP settings from .env
        # Issue 08: SMS can fall back to platform Twilio settings from .env
        from voice_platform.config import settings as _platform_settings
        _has_platform_smtp = bool(_platform_settings.smtp_host and _platform_settings.smtp_password)
        _has_platform_twilio = bool(getattr(_platform_settings, 'twilio_account_sid', None) and getattr(_platform_settings, 'twilio_auth_token', None))
        if integration_type not in active_types and integration_type != "recall_document":
            if integration_type == "email" and _has_platform_smtp:
                logger.debug(f"Tool '{tool_name}': no user email integration, using platform SMTP fallback")
            elif integration_type == "sms" and _has_platform_twilio:
                logger.debug(f"Tool '{tool_name}': no user SMS integration, using platform Twilio fallback")
            else:
                logger.warning(
                    f"⚠️ Tool '{tool_name}' skipped: no active '{integration_type}' integration "
                    f"for user {user_id}. The agent prompt may reference this tool — "
                    f"anti-fabrication guard will be injected."
                )
                skipped_tools.append((tool_name, integration_type))
                continue
        
        tool_name_val: str = tool_def["name"]
        tool_description: str = tool_def["description"]
        tool_action: str = tool_def["action"]
        params_schema: Dict[str, Any] = dict(tool_def["parameters"])

        # ── Inject MCP resource bindings into tool schema ──────────
        # This makes the LLM aware of which files/calendars it can access
        if mcp_bindings and tool_name == "read_drive_file":
            drive_bindings = mcp_bindings.get("drive", {})
            file_ids = drive_bindings.get("file_ids", [])
            if file_ids:
                tool_description += (
                    f"\n\nBound files: {len(file_ids)} file(s) configured. "
                    f"Use the provided file IDs when reading."
                )
                # Inject file_ids as enum in schema for predictability
                props = params_schema.get("properties", {})
                if "file_id" in props:
                    props["file_id"]["enum"] = file_ids

        elif mcp_bindings and tool_name in ("book_appointment", "create_event", "check_calendar"):
            cal_bindings = mcp_bindings.get("calendar", {})
            cal_ids = cal_bindings.get("calendar_ids", [])
            if cal_ids:
                tool_description += (
                    f"\n\nBound calendars: {len(cal_ids)} calendar(s) configured. "
                    f"Use the provided calendar IDs when creating or checking events."
                )

        # NOTE: tool_instructions are now injected once into the system prompt
        # in agent_factory.py to avoid N× token waste when multiple tools
        # are enabled.  They are no longer appended to each individual
        # tool description.

        # Resolve integration override for this tool's integration type
        override_id: Optional[int] = None
        if integration_overrides:
            raw = integration_overrides.get(integration_type)
            if raw is not None:
                try:
                    override_id = int(raw)
                except (TypeError, ValueError):
                    override_id = None

        # ── Multi-integration warning ──────────────────────────────────────
        # If the user has multiple active integrations of this type but no
        # override is set, the resolver will use .first() which may pick the
        # wrong one. Warn so operators can set integration_overrides_json.
        if not override_id and integration_type not in ("recall_document",):
            try:
                from sqlalchemy import func as _func

                from voice_platform.database import Integration as _Int
                from voice_platform.database import async_session as _async_session
                async with _async_session() as _sess:
                    _count_result = await _sess.execute(
                        select(_func.count()).select_from(_Int).where(
                            _Int.user_id == user_id,
                            _Int.service_type == integration_type,
                            _Int.is_active == True,
                        )
                    )
                    _int_count = _count_result.scalar() or 0
                    if _int_count > 1:
                        logger.warning(
                            f"⚠️ Tool '{tool_name}': user {user_id} has {_int_count} active "
                            f"'{integration_type}' integrations but no integration_id_override. "
                            f"Will use first found — this may be the wrong one. "
                            f"Set integration_overrides_json to specify the correct integration."
                        )
            except Exception as _e:
                logger.debug(f"Could not check integration count for {integration_type}: {_e}")

        action_config = PlatformToolActionConfig(
            tool_name=tool_name_val,
            tool_description=tool_description,
            tool_parameters_schema=json.dumps(params_schema),
            integration_type=integration_type,
            integration_action=tool_action,
            user_id=user_id,
            integration_id_override=override_id,
            agent_timezone=agent_timezone or "Asia/Karachi",
        )
        actions.append(action_config)
        logger.debug(f"Registered in-call tool: {tool_name}")
    
    # 2. Dynamic MCP tools (BUG-B2 fix)
    actions.extend(mcp_integrations)

    static_count = len(actions) - len(mcp_integrations)
    logger.info(
        f"Tool setup: {static_count} static + {len(mcp_integrations)} MCP = "
        f"{len(actions)} total tools for user {user_id}"
        + (f" ({len(skipped_tools)} skipped — missing integrations)" if skipped_tools else "")
    )
    return actions, skipped_tools


# ═══════════════════════════════════════════════════════════════════════
# Tool Registry — for API endpoints
# ═══════════════════════════════════════════════════════════════════════

def get_available_tools() -> List[Dict[str, Any]]:
    """Get list of all available tools for the frontend.
    Delegates to ToolRegistry.list()."""
    from voice_platform.runtime.tools import build_default_tool_registry

    registry = build_default_tool_registry()
    tools = []
    for definition in registry.list():
        tools.append({
            "id": definition.name,
            "name": definition.name,
            "description": definition.description,
            "parameters": dict(definition.schema),
            "integration_type": definition.service_type,
            "action": definition.action,
        })
    return tools


# ═══════════════════════════════════════════════════════════════════════
# Action Factory — vocode action factory that knows about platform tools
# ═══════════════════════════════════════════════════════════════════════

class PlatformActionFactory(DefaultActionFactory):
    """Extends vocode's DefaultActionFactory to support platform tool actions.

    The base factory only knows about built-in action types (end_conversation,
    record_email, wait, execute_external_action). VOIA agents can also have
    custom platform tools (action_platform_tool) that need to be executed via
    PlatformToolAction during a call.
    """

    def __init__(self, actions):
        super().__init__(actions)
        # Issue 21: Include all action class mappings so that any action type
        # in the passed `actions` list can be created by create_action().
        # super().__init__ already builds action_configs_dict from the list;
        # this ensures self.actions has a matching BaseAction class for each.
        self.actions = {
            **CONVERSATION_ACTIONS,
            **TWILIO_ACTIONS,
            ActionType.PLATFORM_TOOL: PlatformToolAction,
        }


