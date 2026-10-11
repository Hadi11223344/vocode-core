"""Voice Platform — Inbound Call Handler

Handles Twilio inbound call webhooks with:
- Per-call agent config reloading
- Cross-call memory injection (FR-07)
- Workflow trigger phrase injection (FR-08)
- Knowledge base context injection
- Phone number → agent routing via PhoneNumberMapping
- Call status webhook updates

This module extracts the telephony-specific logic from main.py
to keep the application entry point clean and domain-focused.
"""

import copy
import json
from datetime import datetime, timezone
from typing import Optional, cast

from fastapi import APIRouter, Form, HTTPException, Request, status
from loguru import logger
from sqlalchemy import or_, select
from twilio.request_validator import RequestValidator

from voice_platform.config import settings
from voice_platform.database import (
    Agent,
    CallLog,
    PhoneNumberMapping,
    ScheduledCall,
    UserApiKey,
    Workflow,
    async_session,
)
from voice_platform.memory import get_caller_history_summary
from voice_platform.rate_limit import limiter

router = APIRouter(tags=["Telephony"])


# ── Twilio Webhook Signature Validation ────────────────────────────────

def _candidate_signature_urls(request: Request) -> list[str]:
    """Build candidate public URLs for Twilio signature verification."""
    urls: list[str] = []
    xf_proto = request.headers.get("x-forwarded-proto")
    xf_host = request.headers.get("x-forwarded-host")
    if xf_proto and xf_host:
        forwarded = f"{xf_proto}://{xf_host}{request.url.path}"
        if request.url.query:
            forwarded = f"{forwarded}?{request.url.query}"
        urls.append(forwarded)
    urls.append(str(request.url))
    seen = set()
    unique_urls: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    return unique_urls


async def _validate_twilio_webhook_signature(request: Request, form_fields: dict[str, str]) -> None:
    """Validate Twilio webhook signature with compatibility-safe defaults.

    BUG-4: For calls placed with user-specific Twilio credentials, the webhook
    is signed with the user's auth token, not the platform's. We first try the
    platform token, and if that fails, look up the CallLog by CallSid to find
    the user_id and try their Twilio auth token.
    """
    if not settings.twilio_auth_token:
        return
    signature = request.headers.get("X-Twilio-Signature")
    require_signature = settings.require_twilio_webhook_signature
    validate_if_present = settings.validate_twilio_webhook_if_present
    if not signature:
        if require_signature:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing Twilio signature")
        return
    if not (validate_if_present or require_signature):
        return
    try:
        from twilio.request_validator import RequestValidator
    except ImportError:
        if require_signature:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Twilio SDK required for webhook signature validation",
            )
        logger.warning("Twilio SDK unavailable; skipping webhook signature validation")
        return

    # Try platform token first
    validator = RequestValidator(settings.twilio_auth_token)
    candidate_urls = _candidate_signature_urls(request)
    for url in candidate_urls:
        if validator.validate(url, form_fields, signature):
            return

    # BUG-4: Platform token didn't match — try the user's Twilio auth token.
    # Look up the CallLog by CallSid to find which user placed this call.
    call_sid = form_fields.get("CallSid", "")
    if call_sid:
        try:
            from voice_platform.encryption import decrypt

            async with async_session() as session:
                result = await session.execute(
                    select(CallLog).where(
                        or_(CallLog.conversation_id == call_sid, CallLog.twilio_call_sid == call_sid)
                    )
                )
                call_log = result.scalars().first()
                if call_log and call_log.user_id:
                    key_result = await session.execute(
                        select(UserApiKey).where(
                            UserApiKey.user_id == call_log.user_id,
                            UserApiKey.service == "twilio",
                            UserApiKey.is_active == True,
                        )
                    )
                    user_key = key_result.scalar_one_or_none()
                    if user_key and user_key.api_secret:
                        user_auth_token = decrypt(str(user_key.api_secret))
                        user_validator = RequestValidator(user_auth_token)
                        for url in candidate_urls:
                            if user_validator.validate(url, form_fields, signature):
                                return
        except Exception as e:
            logger.warning(f"Failed to validate with user Twilio token: {e}")

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Twilio signature")


# ── Context Injection Helpers ──────────────────────────────────────────

async def _get_workflow_context(user_id: Optional[int] = None, agent_id: Optional[int] = None) -> str:
    """Load active workflow trigger phrases for LLM injection."""
    if user_id is None:
        return ""

    # Skip text workflow instructions for conversational_flow agents —
    # the FlowAgent executes the graph directly via LangGraph
    if agent_id is not None:
        try:
            async with async_session() as session:
                agent = await session.get(Agent, agent_id)
                if agent and getattr(agent, 'mode', None) == 'conversational_flow':
                    logger.info(f"Agent {agent_id} is conversational_flow — skipping text workflow instructions")
                    return ""
        except Exception as e:
            logger.warning(f"Failed to check agent mode for workflow context: {e}")

    _MAX_WORKFLOWS_IN_PROMPT = 10
    _MAX_DESC_LENGTH = 120

    def _compile_graph_to_instructions(graph_json: Optional[str]) -> list[str]:
        """S1: Compile a workflow graph into numbered step-by-step instructions.

        Replaces the old node/edge summary with a topological ordering that
        the LLM can follow sequentially. Conversation nodes become
        CONVERSATION steps, condition nodes become CONDITION steps, and
        action nodes become ACTION steps. Control-flow nodes (trigger, end,
        end_call, voicemail_detect) are skipped.
        """
        if not graph_json:
            return []
        try:
            graph = json.loads(graph_json)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(graph, dict):
            return []

        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        if not isinstance(nodes, list):
            nodes = []
        if not isinstance(edges, list):
            edges = []

        # Build node lookup
        node_map: dict[str, dict] = {}
        for node in nodes:
            if isinstance(node, dict) and node.get("id"):
                node_map[node["id"]] = node

        # Build adjacency list from edges for topological sort
        adj: dict[str, list[str]] = {nid: [] for nid in node_map}
        in_degree: dict[str, int] = {nid: 0 for nid in node_map}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            src = edge.get("source")
            tgt = edge.get("target")
            if src in node_map and tgt in node_map:
                adj[src].append(tgt)
                in_degree[tgt] = in_degree.get(tgt, 0) + 1

        # Kahn's algorithm for topological sort
        queue = [nid for nid in node_map if in_degree.get(nid, 0) == 0]
        ordered: list[str] = []
        while queue:
            nid = queue.pop(0)
            ordered.append(nid)
            for child in adj.get(nid, []):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        # Fallback: if cycle detected, use original node order
        if len(ordered) < len(node_map):
            ordered = list(node_map.keys())

        # Compile ordered steps
        _SKIP_TYPES = {"trigger", "end", "end_call", "voicemail_detect"}
        steps: list[str] = []
        step_num = 0
        for nid in ordered[:15]:  # cap at 15 steps to limit prompt size
            node = node_map.get(nid, {})
            node_data = node.get("data") or {}
            if not isinstance(node_data, dict):
                node_data = {}
            node_type = str(
                node_data.get("nodeType") or node.get("type") or "node"
            ).lower()
            # Config is stored under node_data.config in the workflow editor
            node_config = node_data.get("config") if isinstance(node_data.get("config"), dict) else {}
            label = node_data.get("label") or node_type

            if node_type in _SKIP_TYPES:
                continue

            step_num += 1
            if node_type == "conversation":
                prompt = (
                    node_config.get("prompt")
                    or node_config.get("message")
                    or label
                    or "Discuss with the caller"
                )
                steps.append(f"  {step_num}. CONVERSATION: {str(prompt)[:120]}")
            elif node_type == "condition":
                expr = (
                    node_config.get("expression")
                    or node_config.get("condition")
                    or label
                    or "condition"
                )
                steps.append(
                    f"  {step_num}. CONDITION: If {str(expr)[:100]}, "
                    f"continue to the next step; otherwise skip to the step after."
                )
            elif node_type == "knowledge_base":
                query = node_config.get("query") or label
                steps.append(f"  {step_num}. KNOWLEDGE_BASE: Search knowledge base for: {str(query)[:100]}")
            elif node_type == "llm_process":
                prompt = node_config.get("prompt") or label
                steps.append(f"  {step_num}. AI_PROCESS: {str(prompt)[:120]}")
            elif node_type == "send_sms":
                body = node_config.get("body") or node_config.get("message") or ""
                steps.append(f"  {step_num}. SEND_SMS: Send SMS to caller{': ' + str(body)[:80] if body else ''}")
            elif node_type == "send_email":
                subject = node_config.get("subject") or ""
                steps.append(f"  {step_num}. SEND_EMAIL: Send email{': ' + str(subject)[:80] if subject else ''}")
            elif node_type == "transfer_call":
                number = node_config.get("transfer_number") or node_config.get("transfer_to") or ""
                steps.append(f"  {step_num}. TRANSFER_CALL: Transfer to {str(number)[:40] or 'configured number'}")
            elif node_type == "notification":
                msg = node_config.get("message") or ""
                steps.append(f"  {step_num}. NOTIFICATION: Send notification{': ' + str(msg)[:80] if msg else ''}")
            elif node_type == "delay":
                secs = node_config.get("delay_seconds") or "3"
                steps.append(f"  {step_num}. DELAY: Wait {secs} seconds")
            elif node_type == "note":
                content = node_config.get("content") or ""
                steps.append(f"  {step_num}. NOTE: {str(content)[:100]}")
            elif node_type in ("webhook", "api_request", "custom_api"):
                url = node_config.get("url") or ""
                method = node_config.get("method") or "GET"
                steps.append(f"  {step_num}. API_CALL: {method} {str(url)[:80]}")
            elif node_type == "mcp_tool":
                tool = node_config.get("tool") or node_data.get("action") or label
                steps.append(f"  {step_num}. MCP_TOOL: Use {str(tool)[:80]}")
            elif node_type == "extract_variable":
                variables = node_config.get("variables_to_extract") or []
                steps.append(f"  {step_num}. EXTRACT: Extract variables: {', '.join(variables)[:80] if isinstance(variables, list) else str(variables)[:80]}")
            elif node_type == "subagent":
                prompt = node_config.get("prompt") or label
                steps.append(f"  {step_num}. SUBAGENT: Delegate to subagent: {str(prompt)[:80]}")
            elif node_type == "code":
                steps.append(f"  {step_num}. CODE: Execute custom code")
            elif node_type == "action":
                tool = (
                    node_config.get("tool")
                    or node_data.get("action")
                    or label
                    or "the appropriate tool"
                )
                steps.append(f"  {step_num}. ACTION: Use {str(tool)[:80]} to complete this step.")
            else:
                # Integration nodes (google_calendar, google_sheets, salesforce, etc.)
                action = node_data.get("action") or node_config.get("action") or ""
                steps.append(f"  {step_num}. {str(label)[:40]}: {str(action)[:80] if action else 'Perform action'}")

        if not steps:
            return []
        return ["  Steps:"] + steps

    try:
        async with async_session() as session:
            # BUG-10: Scope to the current agent (or global workflows with no agent)
            from sqlalchemy import or_
            filters = [
                Workflow.is_active == True,
                Workflow.user_id == user_id,
            ]
            if agent_id is not None:
                filters.append(
                    or_(Workflow.agent_id == agent_id, Workflow.agent_id.is_(None))
                )
            result = await session.execute(
                select(Workflow).where(*filters).order_by(Workflow.updated_at.desc())
            )
            workflows = result.scalars().all()
            if not workflows:
                return ""
            if len(workflows) > _MAX_WORKFLOWS_IN_PROMPT:
                logger.warning(
                    f"User {user_id} has {len(workflows)} active workflows; "
                    f"injecting only the {_MAX_WORKFLOWS_IN_PROMPT} most recently updated."
                )
                workflows = workflows[:_MAX_WORKFLOWS_IN_PROMPT]
            parts = ["\n=== WORKFLOW INSTRUCTIONS ==="]
            parts.append(
                "Follow these steps in order when the user's intent matches. "
                "Do NOT call any tool until you have completed the CONVERSATION "
                "steps that precede it."
            )
            for wf in workflows:
                triggers = json.loads(wf.trigger_phrases) if wf.trigger_phrases else []  # type: ignore[arg-type]
                trigger_str = ", ".join(f'"{t}"' for t in triggers)
                desc = wf.description or "No description"
                if len(desc) > _MAX_DESC_LENGTH:
                    desc = desc[:_MAX_DESC_LENGTH].rstrip() + "..."
                parts.append(f"\n- Workflow: {wf.name}")
                parts.append(f"  Description: {desc}")
                parts.append(f"  Trigger phrases: [{trigger_str}]")
                if wf.requires_approval:
                    parts.append("  ⚠️ Requires human approval before execution")
                parts.extend(_compile_graph_to_instructions(cast(Optional[str], wf.graph_json)))
            parts.append("===========================\n")
            return "\n".join(parts)
    except Exception as e:
        logger.error(f"Error loading workflows: {e}")
        return ""


async def _get_knowledge_base_context(agent_id: Optional[int] = None, caller_phone: Optional[str] = None, agent_config=None) -> str:
    """Load knowledge base entries linked to the active agent.

    Phase B: delegates to KnowledgeService.retrieve() and converts the
    structured KnowledgeContext to a formatted string for backward
    compatibility with the inbound handler's string-based prompt injection.
    """
    from voice_platform.runtime.services.knowledge import KnowledgeService
    if agent_id is None:
        return ""
    try:
        async with async_session() as session:
            service = KnowledgeService()
            ctx = await service.retrieve(session, agent_id, agent_config)
            if not ctx.documents:
                return ""
            parts = []
            for doc in ctx.documents:
                parts.append(f"\n## {doc.title}")
                parts.append(doc.content)
            return "\n".join(parts)
    except Exception as e:
        logger.error(f"KB context loading error: {e}")
        return ""


def _normalize_phone_number(value: Optional[str]) -> str:
    """Normalize a phone number for equality checks."""
    if not value:
        return ""
    return "".join(character for character in str(value) if character.isdigit())


def _phone_numbers_match(left: Optional[str], right: Optional[str]) -> bool:
    """Compare two phone numbers using digit-only normalization."""
    left_norm = _normalize_phone_number(left)
    right_norm = _normalize_phone_number(right)
    return bool(left_norm and right_norm and left_norm == right_norm)


class PhoneAgentRoutingError(Exception):
    """Fail-closed telephony routing error with a stable MVP error code."""

    def __init__(self, error_code: str, message: str = ""):
        self.error_code = error_code
        super().__init__(message or error_code)


async def _validate_assigned_agent(session, agent_id: Optional[int]) -> Agent:
    """Validate that a phone-assigned agent can be loaded for telephony.

    Raises PhoneAgentRoutingError with PHONE_AGENT_* codes.
    """
    from sqlalchemy.orm import selectinload

    from voice_platform.diagnostics import build_safe_error_event

    if not agent_id:
        raise PhoneAgentRoutingError("PHONE_AGENT_NOT_ASSIGNED")

    result = await session.execute(
        select(Agent)
        .options(selectinload(Agent.linked_workflow))
        .where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        ev = build_safe_error_event(
            "PHONE_AGENT_NOT_FOUND",
            agent_id=str(agent_id),
            execution_channel="telephony",
            execution_status="failed",
        )
        logger.error(f"Telephony routing error: {ev}")
        raise PhoneAgentRoutingError("PHONE_AGENT_NOT_FOUND")

    if not bool(agent.is_active):
        ev = build_safe_error_event(
            "PHONE_AGENT_DISABLED",
            agent_id=str(agent_id),
            execution_channel="telephony",
            execution_status="failed",
        )
        logger.error(f"Telephony routing error: {ev}")
        raise PhoneAgentRoutingError("PHONE_AGENT_DISABLED")

    mode = getattr(agent, "mode", "single_prompt") or "single_prompt"
    if mode not in ("single_prompt", "conversational_flow"):
        ev = build_safe_error_event(
            "PHONE_AGENT_MODE_UNSUPPORTED",
            agent_id=str(agent_id),
            execution_channel="telephony",
            execution_status="failed",
            safe_context={"agent_mode": mode},
        )
        logger.error(f"Telephony routing error: {ev}")
        raise PhoneAgentRoutingError("PHONE_AGENT_MODE_UNSUPPORTED")

    if mode == "conversational_flow" and not getattr(agent, "graph", None):
        ev = build_safe_error_event(
            "PHONE_AGENT_CONFIG_INVALID",
            agent_id=str(agent_id),
            execution_channel="telephony",
            execution_status="failed",
            safe_context={"reason": "missing_graph"},
        )
        logger.error(f"Telephony routing error: {ev}")
        raise PhoneAgentRoutingError("PHONE_AGENT_CONFIG_INVALID")

    if mode == "single_prompt" and not (agent.prompt_preamble or "").strip():
        ev = build_safe_error_event(
            "PHONE_AGENT_CONFIG_INVALID",
            agent_id=str(agent_id),
            execution_channel="telephony",
            execution_status="failed",
            safe_context={"reason": "missing_prompt"},
        )
        logger.error(f"Telephony routing error: {ev}")
        raise PhoneAgentRoutingError("PHONE_AGENT_CONFIG_INVALID")

    return agent


def _twiml_routing_error(error_code: str):
    """Return a safe TwiML response for phone-routing failures (no PII)."""
    from fastapi.responses import Response as _Resp
    from twilio.twiml.voice_response import VoiceResponse as _VR

    from voice_platform.diagnostics import get_error_info

    info = get_error_info(error_code)
    resp = _VR()
    resp.say(info["error_message_safe"], voice="Polly.Joanna-Neural")
    resp.hangup()
    return _Resp(content=str(resp), media_type="application/xml")


async def _resolve_inbound_routing_context(
    session,
    to_phone: str,
) -> tuple[Optional[int], Optional[int], Optional[str], str, Optional[int]]:
    """Resolve owner, agent, greeting, source, and phone_number_id for inbound."""
    mapping_result = await session.execute(
        select(PhoneNumberMapping).where(
            PhoneNumberMapping.phone_number == to_phone,
            PhoneNumberMapping.is_active == True,
        )
    )
    phone_mapping = mapping_result.scalars().first()
    if phone_mapping:
        return (
            phone_mapping.user_id,
            phone_mapping.agent_id,
            phone_mapping.greeting_override,
            "phone_mapping",
            phone_mapping.id,
        )

    twilio_keys_result = await session.execute(
        select(UserApiKey).where(
            UserApiKey.service == "twilio",
            UserApiKey.is_active == True,
        )
    )
    for key_row in twilio_keys_result.scalars().all():
        if not key_row.metadata_json:
            continue
        try:
            metadata = json.loads(key_row.metadata_json)
        except json.JSONDecodeError:
            continue
        if not isinstance(metadata, dict):
            continue

        configured_phone = metadata.get("phone_number")
        if not configured_phone or not _phone_numbers_match(configured_phone, to_phone):
            continue

        agent_result = await session.execute(
            select(Agent)
            .where(
                Agent.user_id == key_row.user_id,
                Agent.is_active == True,
            )
            .order_by(Agent.updated_at.desc())
            .limit(1)
        )
        agent_row = agent_result.scalars().first()
        return (
            key_row.user_id,
            agent_row.id if agent_row else None,
            metadata.get("greeting_override"),
            "twilio_key",
            None,
        )

    return None, None, None, "unassigned", None


# ── Inbound Call Handler ───────────────────────────────────────────────

@router.post("/inbound_call")
@limiter.limit("60/minute")
async def inbound_call(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    AnsweredBy: Optional[str] = Form(None),
):
    """Custom inbound call handler with per-call setup.

    1. Reload agent config from DB
    2. Pre-create CallLog
    3. Inject cross-call memory (FR-07)
    4. Inject workflow trigger phrases (FR-08)
    5. Inject Knowledge Base context
    6. Save config to Redis and return TwiML
    """
    from vocode.streaming.models.telephony import TwilioCallConfig
    from vocode.streaming.telephony.templater import get_connection_twiml
    from vocode.streaming.utils import create_conversation_id
    from voice_platform.agents.agent_factory import _get_configs_for_agent, _get_default_configs

    app_state = request.app.state
    form_fields = {k: str(v) for k, v in (await request.form()).items()}
    await _validate_twilio_webhook_signature(request, form_fields)

    # AMD: If Twilio detected a machine/voicemail, hang up instead of connecting the AI agent.
    # This saves ~300s of wasted call time per voicemail contact.
    _MACHINE_ANSWERS = {
        "machine_start", "machine_end_beep", "machine_end_silence",
        "machine_end_other", "fax",
    }
    if AnsweredBy and AnsweredBy.lower() in _MACHINE_ANSWERS:
        logger.info(f"📞 Voicemail/machine detected for {CallSid[:12]} (AnsweredBy={AnsweredBy})")
        from fastapi.responses import Response as _Resp
        from twilio.twiml.voice_response import VoiceResponse as _VR

        # Update existing CallLog if present (outbound calls have pre-created logs)
        # Also fetch agent's voicemail_message if configured
        voicemail_msg = None
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(CallLog).where(
                        or_(CallLog.conversation_id == CallSid, CallLog.twilio_call_sid == CallSid)
                    )
                )
                call_log = result.scalars().first()
                if call_log:
                    call_log.status = "completed"  # type: ignore[assignment]
                    call_log.call_outcome = "voicemail"  # type: ignore[assignment]
                    call_log.ended_at = datetime.now(timezone.utc)  # type: ignore[assignment]
                    await session.commit()

                    # Fetch agent's voicemail message
                    if call_log.agent_id:
                        agent = await session.get(Agent, call_log.agent_id)
                        if agent:
                            voicemail_msg = getattr(agent, 'voicemail_message', None)
        except Exception as e:
            logger.error(f"Failed to update CallLog for voicemail AMD: {e}")

        resp = _VR()
        if voicemail_msg:
            logger.info(f"📞 Leaving voicemail message for {CallSid[:12]}")
            resp.say(voicemail_msg, voice="Polly.Joanna-Neural")
            resp.hangup()
        else:
            resp.hangup()
        return _Resp(content=str(resp), media_type="application/xml")

    # Step 1–2: Resolve agent assignment (fail-closed) and create CallLog.
    # Do NOT fall back to an unrelated default agent — that causes cross-agent
    # demo contamination when phone mapping is missing or stale.
    from voice_platform.diagnostics import build_runtime_identity, build_safe_error_event

    conversation_id = None
    user_id = None
    agent_id = None
    phone_number_id = None
    existing_log = None
    agent_config = None
    transcriber_config = None
    synthesizer_config = None
    runtime_identity = None
    greeting_override = None

    try:
        async with async_session() as session:
            existing_result = await session.execute(
                select(CallLog).where(CallLog.conversation_id == CallSid)
            )
            existing_log = existing_result.scalars().first()

            if existing_log:
                # Outbound call — CallLog was pre-created with CallSid as conversation_id.
                conversation_id = existing_log.conversation_id
                existing_log.status = "ringing"  # type: ignore[assignment]
                agent_id = existing_log.agent_id
                user_id = existing_log.user_id
                logger.info(
                    f"📞 Outbound call connected (twilio_sid: {CallSid[:12]}, conv_id: {conversation_id[:12]})"
                )
                try:
                    await _validate_assigned_agent(session, agent_id)  # type: ignore[arg-type]
                    from vocode.streaming.models.message import BaseMessage as _BM
                    agent_config, transcriber_config, synthesizer_config = await _get_configs_for_agent(agent_id)  # type: ignore[arg-type]
                    agent_config = copy.deepcopy(agent_config)
                    # deepcopy can drop non-field attrs like _flow_owns_greeting
                    if getattr(agent_config, "flow_agent_id", None) or getattr(agent_config, "graph_json", None):
                        object.__setattr__(agent_config, "_flow_owns_greeting", True)
                    logger.info(f"Loaded outbound agent config for agent_id={agent_id}")
                except PhoneAgentRoutingError as e:
                    await session.commit()
                    return _twiml_routing_error(e.error_code)
                except Exception as e:
                    logger.error(
                        f"Failed to load outbound agent config for agent_id={agent_id}: {e}"
                    )
                    await session.commit()
                    return _twiml_routing_error("PHONE_AGENT_CONFIG_INVALID")
            else:
                conversation_id = create_conversation_id()
                (
                    user_id,
                    agent_id,
                    greeting_override,
                    routing_source,
                    phone_number_id,
                ) = await _resolve_inbound_routing_context(session, To)

                if routing_source == "unassigned" or not agent_id:
                    ev = build_safe_error_event(
                        "PHONE_AGENT_NOT_ASSIGNED",
                        execution_channel="telephony",
                        conversation_id=conversation_id,
                        execution_status="failed",
                    )
                    logger.error(f"Telephony routing error: {ev}")
                    return _twiml_routing_error("PHONE_AGENT_NOT_ASSIGNED")

                if routing_source == "phone_mapping":
                    logger.info(f"📍 Phone routing: {To} → Agent #{agent_id} (mapped)")
                elif routing_source == "twilio_key":
                    logger.info(f"📍 Twilio key routing: {To} → user #{user_id}, agent #{agent_id}")

                try:
                    db_agent = await _validate_assigned_agent(session, agent_id)
                    from vocode.streaming.models.message import BaseMessage as _BM
                    agent_config, transcriber_config, synthesizer_config = await _get_configs_for_agent(agent_id)  # type: ignore[arg-type]
                    agent_config = copy.deepcopy(agent_config)
                    # deepcopy can drop non-field attrs like _flow_owns_greeting
                    if getattr(agent_config, "flow_agent_id", None) or getattr(agent_config, "graph_json", None):
                        object.__setattr__(agent_config, "_flow_owns_greeting", True)
                    if greeting_override:
                        agent_config.initial_message = _BM(text=greeting_override)

                    prompt_version = getattr(agent_config, "_selected_prompt_version_id", None)
                    runtime_identity = build_runtime_identity(
                        agent_id=db_agent.id,
                        agent_name=db_agent.name,
                        agent_mode=getattr(db_agent, "mode", "single_prompt"),
                        execution_channel="telephony",
                        conversation_id=conversation_id,
                        call_id=CallSid,
                        prompt_version_or_hash=str(prompt_version) if prompt_version else None,
                        prompt_preamble=db_agent.prompt_preamble,
                        graph=getattr(db_agent, "graph", None),
                        model_provider=getattr(db_agent, "llm_provider", None),
                        stt_provider=getattr(db_agent, "stt_provider", None),
                        tts_provider=getattr(db_agent, "tts_provider", None),
                        phone_number_id=phone_number_id,
                    )
                    object.__setattr__(agent_config, "_runtime_identity", runtime_identity)
                    logger.info(f"Runtime identity: {runtime_identity}")
                except PhoneAgentRoutingError as e:
                    return _twiml_routing_error(e.error_code)
                except Exception as e:
                    logger.error(
                        f"Failed to load mapped agent config for agent_id={agent_id}: {e}"
                    )
                    return _twiml_routing_error("PHONE_AGENT_CONFIG_INVALID")

                call_log = CallLog(
                    conversation_id=conversation_id,
                    twilio_call_sid=CallSid,
                    from_phone=From,
                    to_phone=To,
                    agent_id=agent_id,
                    user_id=user_id,
                    direction="inbound",
                    status="ringing",
                    started_at=datetime.now(timezone.utc),
                    prompt_version_id=getattr(agent_config, "_selected_prompt_version_id", None),
                )
                session.add(call_log)

            # Outbound path: attach runtime identity after successful load
            if existing_log and agent_config is not None and agent_id:
                try:
                    db_agent = await _validate_assigned_agent(session, agent_id)
                    prompt_version = getattr(agent_config, "_selected_prompt_version_id", None)
                    runtime_identity = build_runtime_identity(
                        agent_id=db_agent.id,
                        agent_name=db_agent.name,
                        agent_mode=getattr(db_agent, "mode", "single_prompt"),
                        execution_channel="telephony",
                        conversation_id=conversation_id,
                        call_id=CallSid,
                        prompt_version_or_hash=str(prompt_version) if prompt_version else None,
                        prompt_preamble=db_agent.prompt_preamble,
                        graph=getattr(db_agent, "graph", None),
                        model_provider=getattr(db_agent, "llm_provider", None),
                        stt_provider=getattr(db_agent, "stt_provider", None),
                        tts_provider=getattr(db_agent, "tts_provider", None),
                        phone_number_id=phone_number_id,
                    )
                    object.__setattr__(agent_config, "_runtime_identity", runtime_identity)
                    logger.info(f"Runtime identity: {runtime_identity}")
                except PhoneAgentRoutingError:
                    pass

            await session.commit()
    except PhoneAgentRoutingError as e:
        return _twiml_routing_error(e.error_code)
    except Exception as e:
        logger.error(f"Failed to pre-create call log: {e}")
        return _twiml_routing_error("PHONE_AGENT_CONFIG_INVALID")

    if not conversation_id or agent_config is None:
        return _twiml_routing_error("PHONE_AGENT_CONFIG_INVALID")

    # Step 3: Inject cross-call memory (FR-07)
    # BUG-3: For outbound calls, From is our Twilio number — use To (the
    # callee) for memory lookup instead.
    memory_phone = To if existing_log else From
    if getattr(agent_config, "flow_agent_id", None):
        agent_config.flow_caller_phone = memory_phone
    try:
        memory_summary = await get_caller_history_summary(memory_phone)
        if memory_summary:
            agent_config.prompt_preamble = agent_config.prompt_preamble + memory_summary
            logger.info(f"📝 Injected cross-call memory for {memory_phone} ({len(memory_summary)} chars)")
    except Exception as e:
        logger.error(f"Failed to inject memory: {e}")

    # Step 4: Inject workflow trigger phrases (FR-08)
    try:
        workflow_context = await _get_workflow_context(user_id, agent_id)  # type: ignore[arg-type]
        if workflow_context:
            agent_config.prompt_preamble = agent_config.prompt_preamble + workflow_context
            logger.info(f"📋 Injected workflow context ({len(workflow_context)} chars)")
    except Exception as e:
        logger.error(f"Failed to inject workflows: {e}")

    # Step 5: Inject Knowledge Base context
    # BUG-20: Use the callee's phone for outbound calls, not our own number.
    try:
        kb_context = await _get_knowledge_base_context(agent_id, memory_phone, agent_config)  # type: ignore[arg-type]
        if kb_context:
            agent_config.prompt_preamble = agent_config.prompt_preamble + kb_context
            logger.info(f"📚 Injected KB context ({len(kb_context)} chars)")
    except Exception as e:
        logger.error(f"Failed to inject KB context: {e}")

    # Step 6: Build TwilioCallConfig and save to Redis
    # D-8: Use existing_log direction for outbound calls, default to inbound
    call_direction: str = getattr(existing_log, "direction", None) or "inbound"

    # O-10: For outbound calls placed with user-specific Twilio credentials,
    # resolve the user's Twilio config so transfer/end-call uses the right account.
    twilio_config = app_state.twilio_config
    if existing_log and existing_log.user_id:
        try:
            from vocode.streaming.models.telephony import TwilioConfig as _TwilioConfig
            from voice_platform.encryption import decrypt as _decrypt

            async with async_session() as cred_session:
                key_result = await cred_session.execute(
                    select(UserApiKey).where(
                        UserApiKey.user_id == existing_log.user_id,
                        UserApiKey.service == "twilio",
                        UserApiKey.is_active == True,
                    )
                )
                user_twilio_key = key_result.scalar_one_or_none()
                if user_twilio_key and user_twilio_key.api_key and user_twilio_key.api_secret:
                    user_sid = _decrypt(str(user_twilio_key.api_key))
                    user_token = _decrypt(str(user_twilio_key.api_secret))
                    twilio_config = _TwilioConfig(account_sid=user_sid, auth_token=user_token)
                    logger.debug(f"Using user Twilio config for outbound call (user_id={existing_log.user_id})")
        except Exception as e:
            logger.warning(f"Failed to resolve user Twilio config, using platform default: {e}")

    call_config = TwilioCallConfig(
        transcriber_config=transcriber_config,
        agent_config=agent_config,
        synthesizer_config=synthesizer_config,
        twilio_config=twilio_config,
        twilio_sid=CallSid,
        from_phone=From,
        to_phone=To,
        direction=call_direction,  # type: ignore[arg-type]
    )

    await app_state.config_manager.save_config(conversation_id, call_config)

    logger.info(f"📞 Inbound call from {From} → {To} (conv_id: {conversation_id})")

    return get_connection_twiml(base_url=app_state.base_url, call_id=conversation_id)


# ── Call Status Webhook ────────────────────────────────────────────────

@router.post("/call_status")
@limiter.limit("120/minute")
async def call_status_webhook(
    request: Request,
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    From: str = Form(...),
    To: str = Form(...),
    CallDuration: Optional[str] = Form(None),
    RecordingUrl: Optional[str] = Form(None),
    RecordingSid: Optional[str] = Form(None),
):
    """Twilio status callback — updates CallLog for terminal statuses."""
    form_fields = {k: str(v) for k, v in (await request.form()).items()}
    await _validate_twilio_webhook_signature(request, form_fields)

    logger.info(f"📡 Call status update: {CallSid[:12]} → {CallStatus}")

    terminal_statuses = {"completed", "busy", "no-answer", "failed", "canceled"}

    try:
        async with async_session() as session:
            result = await session.execute(
                select(CallLog).where(
                    or_(CallLog.conversation_id == CallSid, CallLog.twilio_call_sid == CallSid)
                )
            )
            call_log = result.scalars().first()

            if call_log:
                # Update CallLog for all non-terminal status changes too
                # (e.g. "answered", "in-progress") so we can track call progress.
                # BUG-12: Don't overwrite "active" — the events manager sets it
                # when the WebSocket connects, which is more accurate than Twilio's
                # "answered"/"in-progress" callback that may arrive later.
                protected_non_terminal = {"completed", "failed", "cancelled", "active"}
                if CallStatus not in terminal_statuses and call_log.status not in protected_non_terminal:
                    call_log.status = CallStatus  # type: ignore[assignment]
                    await session.commit()
                    logger.info(f"📡 Updated CallLog for {CallSid[:12]} → {CallStatus}")

                # Terminal status: finalize CallLog
                # BUG-13: Protect "failed" and "cancelled" from being overwritten
                # by "completed" — the events manager may have already marked the
                # call as failed (e.g. did-not-connect) before Twilio sends completed.
                protected_terminal = {"completed", "failed", "cancelled"}
                if CallStatus in terminal_statuses and call_log.status not in protected_terminal:
                    call_log.status = CallStatus  # type: ignore[assignment]
                    call_log.ended_at = datetime.now(timezone.utc)  # type: ignore[assignment]
                    if CallDuration:
                        try:
                            call_log.duration_secs = int(CallDuration)  # type: ignore[assignment]
                        except ValueError:
                            pass
                    # BUG-09: Persist recording URL from Twilio callback
                    if RecordingUrl and not call_log.recording_url:
                        call_log.recording_url = f"{RecordingUrl}.mp3"  # type: ignore[assignment]
                        logger.info(f"🎙️ Recording URL persisted from status callback: {RecordingSid}")
                    await session.commit()
                    logger.info(f"📡 Updated CallLog for {CallSid[:12]} → {CallStatus}")
    except Exception as e:
        logger.error(f"Error updating call status: {e}")

    # Always update linked ScheduledCall when terminal status arrives,
    # even if CallLog was already marked completed (e.g. user clicked End Call).
    if CallStatus in terminal_statuses:
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(CallLog).where(
                        or_(CallLog.conversation_id == CallSid, CallLog.twilio_call_sid == CallSid)
                    )
                )
                call_log = result.scalars().first()

                if call_log and call_log.id:
                    sc_result = await session.execute(
                        select(ScheduledCall).where(
                            ScheduledCall.call_log_id == call_log.id
                        )
                    )
                    scheduled_call = sc_result.scalar_one_or_none()
                    if scheduled_call:
                        scheduled_call.status = CallStatus  # type: ignore[assignment]
                        if CallStatus in ("failed", "busy", "no-answer"):
                            scheduled_call.last_error = f"Call {CallStatus}"
                        await session.commit()
                        logger.info(
                            f"📅 Updated ScheduledCall #{scheduled_call.id} → {CallStatus}"
                        )
        except Exception as e:
            logger.error(f"Error updating scheduled call status: {e}")

    return {"status": "ok"}
