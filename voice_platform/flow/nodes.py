"""
Node handlers for LangGraph-based flow execution.

Each handler is a function that takes FlowState and returns a partial state update.
The compiler maps graph node types to these handlers.

Conversation nodes use LangGraph's interrupt() to pause and wait for user input,
replacing the old hand-rolled WebSocket pause/resume pattern.
"""

import asyncio
import hashlib
import json
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Mapping, Optional

from langgraph.types import interrupt
from loguru import logger

from vocode.streaming.models.actions import EndOfTurn
from vocode.streaming.models.message import BaseMessage
from vocode.streaming.utils.pii_redaction import redact_pii
from voice_platform.flow.slots import SlotEngine, mirror_aliases, normalize_variable
from voice_platform.flow.state import _TRANSIENT_RESULT_KEYS, FlowState, merge_result
from voice_platform.flow.tracer import get_tracer

# StreamSanitizer and patterns moved to voice_platform/runtime/llm/sanitizer.py
# Re-exported here for backward compatibility
from voice_platform.runtime.llm.sanitizer import (
    _INTERNAL_PATTERNS,
    _MARKDOWN_PATTERNS,
    _SPOKEN_BLOCKLIST,
    StreamSanitizer,
    _is_coaching_sentence,
    _sanitize_token,
)


def merge_node_result(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge accumulated result with current node output, stripping stale transient keys.

    Transient execution metadata (branch, error, etc.) from previous nodes is
    removed so it does not pollute routing decisions for subsequent nodes.
    Transient keys intentionally produced by the *current* node are preserved.
    Neither input dictionary is mutated.
    """
    previous = previous or {}
    current = current or {}
    cleaned_previous = {
        key: value
        for key, value in previous.items()
        if key not in _TRANSIENT_RESULT_KEYS
    }
    return {**cleaned_previous, **current}


# ── Retry Scope Exception ────────────────────────────────────────────────────


class RetryScopeError(Exception):
    """Raised when retry scope is missing or invalid.

    Uses SHA-256 fingerprint to avoid leaking raw scope strings in logs,
    tracebacks, or diagnostics.
    """

    def __init__(self, code: str, scope: str = ""):
        self.code = code
        self._scope = scope
        self._fingerprint = (
            hashlib.sha256(f"{code}:{scope}".encode()).hexdigest()[:12]
            if scope
            else code
        )
        super().__init__(code)

    def __str__(self) -> str:
        return f"RetryScopeError(code={self.code}, fingerprint={self._fingerprint})"


# ── Operation Classification ─────────────────────────────────────────────────


class OperationType:
    CHECK_AVAILABILITY = "CHECK_AVAILABILITY"
    CREATE_BOOKING = "CREATE_BOOKING"
    APPEND_PATIENT_LOG = "APPEND_PATIENT_LOG"
    SEND_EMAIL = "SEND_EMAIL"
    UNKNOWN = "UNKNOWN"


_OPERATION_MAP = {
    "check_availability": OperationType.CHECK_AVAILABILITY,
    "book_appointment": OperationType.CREATE_BOOKING,
    "create_event": OperationType.CREATE_BOOKING,
    "append_row": OperationType.APPEND_PATIENT_LOG,
    "send_email": OperationType.SEND_EMAIL,
}


# ── Safe Error Messages ──────────────────────────────────────────────────────

_ERROR_MESSAGES = {
    "CALENDAR_UNAVAILABLE": "The calendar service is unavailable right now.",
    "BOOKING_FAILED": "I could not complete the booking.",
    "EMAIL_FAILED": "I could not send the confirmation email.",
    "SHEETS_FAILED": "I could not save the patient record.",
    "MALFORMED_BOOKING_RESULT": "The booking response was incomplete.",
    "MISSING_INPUTS": "Required information is still missing.",
    "UNKNOWN_ERROR": "An unexpected error occurred.",
}


def _safe_error_message(error_code: str, operation: str = "") -> str:
    """Map error codes to fixed safe strings — never includes raw exceptions."""
    return _ERROR_MESSAGES.get(error_code, _ERROR_MESSAGES["UNKNOWN_ERROR"])


# ── Normalized Integration Result ────────────────────────────────────────────


def _normalize_integration_result(
    node_id: str,
    node_type: str,
    node_config: dict,
    node_result: dict,
    status: str,
    missing_inputs: list = None,
) -> dict:
    """Build a normalized integration result with R1 semantics and fail-closed evidence.

    Returns a dict with:
    - R1 routing fields (success, status, branch) = execution only
    - Nested integration_result with business_succeeded, evidence, etc.
    """
    output = (
        node_result.get("result", {})
        if isinstance(node_result.get("result"), dict)
        else {}
    )
    raw_action = node_config.get("action") or node_type
    op = _OPERATION_MAP.get(raw_action, OperationType.UNKNOWN)
    node_execution_id = str(uuid.uuid4())

    # Structured status — NO error-text inference
    if missing_inputs:
        exec_status = "missing_input"
    elif status == "success":
        exec_status = "succeeded"
    else:
        exec_status = "failed"

    execution_succeeded = status == "success"
    business_succeeded = False  # fail-closed default

    evidence = {
        "availability_checked": False,
        "booking_created": False,
        "patient_logged": False,
        "email_sent": False,
    }

    safe_facts = {}
    error_code = None
    error_message_safe = None

    if exec_status == "missing_input":
        error_code = "MISSING_INPUTS"
        error_message_safe = _ERROR_MESSAGES["MISSING_INPUTS"]
    elif exec_status != "succeeded":
        error_code = "UNKNOWN_ERROR"
        error_message_safe = _ERROR_MESSAGES["UNKNOWN_ERROR"]
    else:
        # Execution succeeded — check business evidence from REAL provider fields
        if op == OperationType.CHECK_AVAILABILITY:
            evidence["availability_checked"] = True
            business_succeeded = True
            safe_facts["available"] = bool(output.get("available", False))
            safe_facts["requested_time_available"] = bool(
                output.get("requested_time_available", False)
            )

        elif op == OperationType.CREATE_BOOKING:
            # Real fields: "id" (Google event ID), "event_created"
            event_id = output.get("id")
            event_created = output.get("event_created") is True
            if event_id and event_created:
                evidence["booking_created"] = True
                business_succeeded = True
            else:
                error_code = "MALFORMED_BOOKING_RESULT"
                error_message_safe = _ERROR_MESSAGES["MALFORMED_BOOKING_RESULT"]

        elif op == OperationType.APPEND_PATIENT_LOG:
            # Real field: "row_appended" — no default True
            if output.get("row_appended") is True:
                evidence["patient_logged"] = True
                business_succeeded = True
            else:
                error_code = "SHEETS_FAILED"
                error_message_safe = _ERROR_MESSAGES["SHEETS_FAILED"]

        elif op == OperationType.SEND_EMAIL:
            # Real field: "email_sent" — no default True
            if output.get("email_sent") is True:
                evidence["email_sent"] = True
                business_succeeded = True
            else:
                error_code = "EMAIL_FAILED"
                error_message_safe = _ERROR_MESSAGES["EMAIL_FAILED"]

        # UNKNOWN operations: execution may succeed, no business evidence,
        # must NOT auto-route to failure

    # External ID validation — only after evidence passes
    external_id = None
    if business_succeeded and op == OperationType.CREATE_BOOKING:
        raw_id = output.get("id")
        if isinstance(raw_id, str) and 1 <= len(raw_id) <= 256:
            external_id = raw_id

    # Build result — R1 semantics: last_result.success = execution_succeeded
    return {
        "node_id": node_id,
        "node_execution_id": node_execution_id,
        "node_type": node_type,
        "success": execution_succeeded,
        "status": exec_status,
        "branch": "on_missing" if exec_status == "missing_input" else None,
        "integration_result": {
            "business_succeeded": business_succeeded,
            "business_status": (
                "succeeded"
                if business_succeeded
                else "failed" if exec_status == "succeeded" else exec_status
            ),
            "operation": op,
            "evidence": evidence,
            "external_id": external_id,
            "error_code": error_code,
            "error_message_safe": error_message_safe,
            "safe_facts": safe_facts,
        },
    }


# ── Business Outcome ─────────────────────────────────────────────────────────


def _update_business_outcome(current: dict, integration_result: dict) -> dict:
    """Update business_outcome based on integration_result evidence.

    Reads integration_result (not last_result.success) for business state.
    Availability alone never changes booking. Email is noncritical.
    """
    outcome = dict(current)
    ev = integration_result.get("evidence", {})
    op = integration_result.get("operation", "")
    biz_success = integration_result.get("business_succeeded", False)
    safe_facts = integration_result.get("safe_facts", {})

    # Derive execution_succeeded from the integration_result's business_status
    # vs operation — if operation ran and business_status is not the exec_status
    exec_succeeded = integration_result.get("business_status") not in (
        "failed",
        "missing_input",
    ) or biz_success

    if op == OperationType.CHECK_AVAILABILITY:
        if not exec_succeeded and not biz_success:
            outcome["availability"] = "failed"
        elif safe_facts.get("available") is True:
            outcome["availability"] = "available"
        elif safe_facts.get("available") is False:
            outcome["availability"] = "unavailable"
        else:
            outcome["availability"] = "unknown"

    elif op == OperationType.CREATE_BOOKING:
        if ev.get("booking_created"):
            outcome["booking"] = "booked"
        elif exec_succeeded and not biz_success:
            outcome["booking"] = "unknown"
        else:
            outcome["booking"] = "failed"

    elif op == OperationType.APPEND_PATIENT_LOG:
        outcome["patient_log"] = "written" if ev.get("patient_logged") else "failed"

    elif op == OperationType.SEND_EMAIL:
        outcome["email"] = "sent" if ev.get("email_sent") else "failed"

    # Overall — criticality policy
    booking = outcome.get("booking", "not_attempted")
    if booking == "failed":
        outcome["overall"] = "failed"
    elif booking == "booked":
        noncritical_failed = (
            outcome.get("email") == "failed"
            or outcome.get("patient_log") == "failed"
        )
        if noncritical_failed:
            outcome["overall"] = "partial_success"
        elif outcome.get("email") == "sent":
            outcome["overall"] = "completed"
        else:
            outcome["overall"] = "in_progress"
    elif booking == "unknown":
        outcome["overall"] = "unresolved"

    return outcome


# ── Boundary Response ────────────────────────────────────────────────────────


def boundary_response(
    operation: str,
    business_succeeded: bool,
    business_outcome: dict,
) -> str | None:
    """Deterministic response at integration boundaries."""
    availability = business_outcome.get("availability", "not_checked")

    if operation == OperationType.CHECK_AVAILABILITY:
        if not business_succeeded:
            return "I couldn't check availability right now. The front desk can help confirm times."
        if availability == "available":
            return "The requested time appears available. Would you like me to book it?"
        if availability == "unavailable":
            return "The requested time is not available. Would you like to try a different time?"
        return "I checked the calendar. Could you confirm your preferred time?"

    if operation == OperationType.CREATE_BOOKING:
        if business_succeeded:
            return "Your appointment has been booked."
        if business_outcome.get("booking") == "unknown":
            return "I submitted the booking, but couldn't confirm it was created. The front desk will verify."
        return "I collected the details, but I couldn't complete the booking."

    if operation == OperationType.SEND_EMAIL:
        if business_succeeded:
            return None
        if business_outcome.get("booking") == "booked":
            return "Your appointment is booked, but I couldn't send the confirmation email."
        return None

    return None


# ── Claim Check ──────────────────────────────────────────────────────────────


class ClaimContext:
    BOOKING_TERMINAL = "BOOKING_TERMINAL"
    BOOKING_RESULT = "BOOKING_RESULT"
    EMAIL_RESULT = "EMAIL_RESULT"
    IDENTITY_CONFIRMATION = "IDENTITY_CONFIRMATION"
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"


_BOOKING_CLAIMS = {
    "booked",
    "scheduled",
    "appointment created",
    "added to calendar",
    "appointment confirmed",
    "appointment is confirmed",
}
_EMAIL_CLAIMS = {
    "email sent",
    "confirmation email has been sent",
    "sent the confirmation",
    "sent a confirmation",
    "confirmation has been sent",
}


def _is_negated(text_lower: str, claim: str) -> bool:
    """Check if the claim is negated in the text."""
    idx = text_lower.find(claim)
    if idx < 0:
        return False
    before = text_lower[max(0, idx - 30) : idx]
    negation_patterns = [
        r"\bnot\b",
        r"\bhaven'?t\b",
        r"\bcouldn'?t\b",
        r"\bdidn'?t\b",
        r"\bwon'?t\b",
        r"\bisn'?t\b",
        r"\bwasn'?t\b",
    ]
    return any(re.search(p, before) for p in negation_patterns)


def _is_hypothetical(text_lower: str) -> bool:
    """Check if the text is hypothetical."""
    hypothetical_patterns = [
        r"\bwould you like\b",
        r"\bshall i\b",
        r"\bshould i\b",
        r"\bdo you want\b",
        r"\bmay i\b",
        r"\bcan i\b",
    ]
    return any(re.search(p, text_lower) for p in hypothetical_patterns)


def _deterministic_response(business_outcome: dict) -> str:
    """Return a truthful deterministic response based on business_outcome."""
    booking = business_outcome.get("booking", "not_attempted")
    email = business_outcome.get("email", "not_attempted")

    if booking == "booked" and email == "sent":
        return "Your appointment has been booked. A confirmation email has been sent."
    elif booking == "booked" and email == "failed":
        return "Your appointment is booked, but I couldn't send the confirmation email."
    elif booking == "booked":
        return "Your appointment has been booked."
    elif booking == "failed":
        return "I collected the details, but I couldn't complete the booking."
    elif booking == "unknown":
        return "I submitted the booking, but couldn't confirm it was created. The front desk will verify."
    elif booking == "not_attempted":
        return "I'm working on your request. Could you provide more details?"
    return "I'm working on your request."


def _claim_check(text: str, business_outcome: dict, context: str) -> str:
    """Check typed claims against business_outcome within an explicit context.

    Only booking-confirmation language in booking contexts requires evidence.
    Identity confirmation and general conversation are never rewritten.
    Negated and hypothetical statements are always permitted.
    """
    if context in (ClaimContext.IDENTITY_CONFIRMATION, ClaimContext.GENERAL_CONVERSATION):
        return text

    text_lower = text.lower()
    booking = business_outcome.get("booking", "not_attempted")
    email = business_outcome.get("email", "not_attempted")

    if context in (ClaimContext.BOOKING_TERMINAL, ClaimContext.BOOKING_RESULT):
        for claim in _BOOKING_CLAIMS:
            if claim in text_lower and booking != "booked":
                if not _is_negated(text_lower, claim) and not _is_hypothetical(text_lower):
                    return _deterministic_response(business_outcome)

    if context in (ClaimContext.EMAIL_RESULT, ClaimContext.BOOKING_TERMINAL):
        for claim in _EMAIL_CLAIMS:
            if claim in text_lower and email != "sent":
                if not _is_negated(text_lower, claim):
                    return _deterministic_response(business_outcome)

    return text


def _message_to_dict(msg: Any) -> dict:
    """Normalize a LangChain/BaseMessage object or plain dict to a message dict.

    LangGraph's `add_messages` reducer stores message objects after the first
    resume, so any code reading `state["messages"]` must handle both forms.
    """
    if isinstance(msg, dict):
        return msg

    content = getattr(msg, "content", "") or ""
    role = getattr(msg, "role", None) or getattr(msg, "type", "user")
    # L-2: Complete role mapping including function, Human, AI variants
    role = {
        "human": "user", "Human": "user",
        "ai": "assistant", "AI": "assistant",
        "system": "system", "function": "tool", "tool": "tool",
    }.get(role, role)

    out: dict[str, Any] = {"role": role, "content": content}
    name = getattr(msg, "name", None)
    if name:
        out["name"] = name
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
        out["tool_calls"] = tool_calls
    return out


def _missing_messages(
    state_messages: list[Any],
    assistant_text: str,
    user_text: str,
) -> list[dict]:
    """Return only the assistant/user messages not already present at the end of state.

    Because LangGraph re-executes an interrupted node from the beginning, the
    handler must avoid appending duplicate assistant/user messages on resume.
    """
    out: list[dict] = []
    normalized = [_message_to_dict(m) for m in state_messages]

    # User message: only add if the state does not already end with the same user text.
    if user_text:
        if not (
            normalized
            and normalized[-1].get("role") == "user"
            and str(normalized[-1].get("content", "")).strip() == user_text.strip()
        ):
            out.append({"role": "user", "content": user_text})

    # Assistant message: only add if this exact response is not already the most
    # recent assistant message in state. This prevents re-adding a cached response
    # or a response that was persisted on a previous return from this node.
    if assistant_text:
        combined = normalized + out
        last_assistant = None
        for msg in reversed(combined):
            if msg.get("role") == "assistant":
                last_assistant = msg
                break
        if not (
            last_assistant
            and str(last_assistant.get("content", "")).strip() == assistant_text.strip()
        ):
            # Insert assistant before the new user message so order is preserved.
            if out and out[-1].get("role") == "user":
                out.insert(-1, {"role": "assistant", "content": assistant_text})
            else:
                out.append({"role": "assistant", "content": assistant_text})

    return out


def _node_type(node: dict) -> str:
    """Extract node type from a graph node dict."""
    data = node.get("data") or {}
    return str(data.get("nodeType") or node.get("type") or "action")


def _node_label(node: dict) -> str:
    """Extract node label from a graph node dict."""
    return (node.get("data") or {}).get("label", node.get("id", ""))


_TEMPLATE_PATTERN = re.compile(r"\{\{([^}]+)\}\}")


def _context_lookup(var_name: str, context: dict):
    """Look up a variable in context, supporting dot notation traversal."""
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


def _resolve_templates(text: str, context: dict) -> str:
    """Replace {{variable}} patterns in text with values from context.

    Supports dot notation (e.g. {{result.is_emergency}}), multi-pass
    resolution for nested templates, and preserves unresolved variables
    as-is instead of replacing with empty string.
    """
    if not isinstance(text, str):
        return text
    current = text
    for _ in range(5):
        # Check if the entire value is a single template — preserve non-string types
        whole = re.fullmatch(r"\{\{\s*([^}]+?)\s*\}\}", current)
        if whole:
            resolved = _context_lookup(whole.group(1), context)
            if resolved is None:
                return current
            if isinstance(resolved, str) and "{{" in resolved:
                current = resolved
                continue
            return str(resolved) if not isinstance(resolved, str) else resolved

        changed = False

        def _replace(match):
            nonlocal changed
            var_name = match.group(1).strip()
            resolved = _context_lookup(var_name, context)
            if resolved is None:
                return match.group(0)
            changed = True
            return str(resolved)

        updated = _TEMPLATE_PATTERN.sub(_replace, current)
        current = updated
        if not changed or "{{" not in current:
            break
    return current


def _resolve_params(params: dict, context: dict) -> dict:
    """Resolve {{variable}} templates in all string values of a params dict."""
    resolved = {}
    for key, value in params.items():
        if isinstance(value, str):
            resolved[key] = _resolve_templates(value, context)
        elif isinstance(value, list):
            resolved[key] = [
                _resolve_templates(v, context) if isinstance(v, str) else v
                for v in value
            ]
        elif isinstance(value, dict):
            resolved[key] = _resolve_params(value, context)
        else:
            resolved[key] = value
    return resolved


def _strip_unresolved_templates(value: Any) -> Any:
    """H-6: Remove unresolved {{variable}} patterns from resolved values.

    After template resolution, any remaining {{...}} patterns indicate
    variables that couldn't be resolved from context. Strip them to prevent
    leaking raw template syntax to integration APIs or caller-facing output.
    """
    if isinstance(value, str):
        return _TEMPLATE_PATTERN.sub("", value).strip()
    elif isinstance(value, list):
        return [_strip_unresolved_templates(v) for v in value]
    elif isinstance(value, dict):
        return {k: _strip_unresolved_templates(v) for k, v in value.items()}
    return value


def _build_template_context(state: dict) -> dict:
    """Build an enriched context dict for template resolution.

    Merges extracted_vars, top-level state fields, result/last_result,
    and default time values so that {{caller_name}}, {{result.foo}},
    {{now}}, etc. all resolve correctly.
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    timezone_name = str(state.get("agent_timezone") or "").strip()
    try:
        current_timezone = ZoneInfo(timezone_name) if timezone_name else timezone.utc
    except Exception:
        current_timezone = timezone.utc
    now = datetime.now(current_timezone)
    defaults = {
        "now": now.isoformat(),
        "call_date": now.strftime("%Y-%m-%d"),
        "call_time": now.strftime("%H:%M"),
        "current_date": now.strftime("%Y-%m-%d"),
        "current_time": now.strftime("%H:%M"),
    }
    extracted_vars = mirror_aliases(state.get("extracted_vars", {}))
    # Prefer alias-mirrored extracted values over top-level state fields
    # (top-level state may not be updated on every extraction).
    return {
        **defaults,
        **extracted_vars,
        "caller_name": extracted_vars.get("caller_name") or state.get("caller_name", ""),
        "caller_phone": extracted_vars.get("caller_phone") or state.get("caller_phone", ""),
        "transcript": state.get("transcript", ""),
        "user_id": state.get("user_id", 0),
        "agent_id": state.get("agent_id", 0),
        "result": state.get("result", {}),
        "last_result": state.get("last_result", {}),
    }


def _to_speech_date(value: str) -> str:
    """Turn YYYY-MM-DD into a speakable date (e.g. July 22nd). Keep original if unparseable."""
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        from datetime import datetime

        dt = datetime.strptime(raw[:10], "%Y-%m-%d")
    except ValueError:
        return raw
    day = dt.day
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{dt.strftime('%B')} {day}{suffix}"


def _to_speech_time(value: str) -> str:
    """Turn HH:MM / HH:MM:SS into speakable 12-hour time (e.g. 3 PM)."""
    raw = (value or "").strip()
    if not raw:
        return ""
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I %p"):
        try:
            from datetime import datetime

            dt = datetime.strptime(raw, fmt)
            hour_12 = dt.strftime("%I").lstrip("0") or "12"
            minute = dt.minute
            ampm = dt.strftime("%p")
            if minute == 0:
                return f"{hour_12} {ampm}"
            return f"{hour_12}:{dt.strftime('%M')} {ampm}"
        except ValueError:
            continue
    return raw


def _speech_template_context(state: dict) -> dict:
    """Template context with speakable date/time for TTS farewells."""
    ctx = _build_template_context(state)
    spoken = dict(ctx)
    for key in ("preferred_date", "appointment_date", "call_date", "current_date"):
        if spoken.get(key):
            spoken[key] = _to_speech_date(str(spoken[key])) or spoken[key]
    for key in ("preferred_time", "appointment_time", "call_time", "current_time"):
        if spoken.get(key):
            spoken[key] = _to_speech_time(str(spoken[key])) or spoken[key]
    return spoken


def _resolve_node_pending_vars(
    node_config: dict,
    state_pending: list[str] | None,
) -> list[str]:
    """Bind collection targets to the current node's declared variables.

    Stale ``pending_variables_to_extract`` from a prior node (e.g. contact email)
    must never become Visit/Schedule ownership — that caused Visit Details to
    re-ask caller_email until max retries and replay email readbacks.
    """
    from voice_platform.flow.slots import _canonical_name

    owned = list(node_config.get("variables_to_extract") or [])
    pending = list(state_pending or [])
    if not owned:
        return pending
    owned_canons = {_canonical_name(v) for v in owned}
    if pending and all(_canonical_name(v) in owned_canons for v in pending):
        return pending
    return owned


def _exact_spoken_readback(step_instruction: str) -> str | None:
    """Extract a deterministic confirmation script from a step instruction."""
    match = re.search(
        r"Say exactly:\s*(.+?)\s*Say nothing else\.",
        step_instruction or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    spoken = re.sub(r"\s+", " ", match.group(1)).strip()
    return spoken or None


def _build_slot_aware_instruction(
    node_prompt: str,
    node_label: str,
    engine: SlotEngine,
    node_variables: list[str] | None = None,
) -> str:
    """Build a step instruction that asks only the next unconfirmed slot.

    Falls back to _build_step_instruction if the slot engine has no next slot.
    Already-confirmed slots are summarized briefly so the LLM does not re-ask.

    When a confirmation-required slot has a pending candidate, generates a
    readback instruction using the speech-safe form of the candidate value —
    but ONLY if this node owns that variable (call 109: email readback must
    not hijack Visit/Schedule/Dentist and re-ask forever).
    """
    from voice_platform.flow.slots import _canonical_name

    owned = {_canonical_name(v) for v in (node_variables or [])}

    # ── Confirmation readback (node-scoped) ────────────────────────────
    awaiting = engine.get_awaiting_confirmation()
    if awaiting:
        awaiting_canon = _canonical_name(awaiting)
        # Only this node's variables may trigger a readback. Otherwise fall
        # through to ask what THIS step needs (date, dentist, etc.).
        if not owned or awaiting_canon in owned:
            slot = engine._slots.get(awaiting)
            if slot and slot.candidate_status == "filled":
                # Freeze the readback snapshot HERE — not during extraction
                engine._confirmation_readback_value = slot.candidate_normalized
                engine._confirmation_state = "awaiting_user_confirmation"
                from voice_platform.validation.email import email_to_speech
                spoken = email_to_speech(slot.candidate_normalized)
                instruction = (
                    f'[INSTRUCTION — You are now at the "{node_label}" step.]\n\n'
                    f"QUESTION:\n- Say exactly: I heard {spoken}. Is that correct? "
                    f"Say nothing else."
                )
                return instruction
            elif slot and slot.candidate_status == "invalid":
                # Invalid candidate — clear confirmation state and re-ask
                engine._confirmation_state = "none"
                engine._awaiting_confirmation_for = ""
                # Fall through to normal next_slot() to re-ask

    # Prefer the next unconfirmed slot that THIS node owns
    next_slot = None
    if owned:
        for name in (node_variables or []):
            canon = _canonical_name(name)
            slot = engine._slots.get(canon) or engine._slots.get(name)
            if not slot:
                continue
            if slot.status == "confirmed":
                continue
            if not slot.value:
                if slot.ask_count < engine._max_asks_per_slot:
                    next_slot = slot
                    break
            elif slot.ask_count < engine._max_asks_per_slot:
                next_slot = slot
                break
    if next_slot is None:
        next_slot = engine.next_slot()
        # If global next_slot is outside this node's ownership, ignore it
        if next_slot and owned and _canonical_name(next_slot.name) not in owned:
            next_slot = None

    if not next_slot:
        return _build_step_instruction(node_prompt, node_label)

    confirmed = [
        s for s in engine._slots.values()
        if s.status == "confirmed" and s.value and s.name != next_slot.name
    ]
    confirmed_summary = ""
    if confirmed:
        parts = []
        for s in confirmed:
            display = s.normalized_value or s.value
            display = _redact_diagnostic_value(display, s.name)
            parts.append(f"{s.name.replace('_', ' ')}: {display}")
        confirmed_summary = " I've noted " + ", ".join(parts[:3]) + "."

    # Prefer the node_prompt if it contains a real question for this slot,
    # otherwise use the engine's default question.
    slot_question = engine.get_question(next_slot.name)
    step_text = _build_step_instruction(node_prompt, node_label)
    questions: list[str] = []
    in_questions = False
    for line in step_text.splitlines():
        if line.strip().startswith("QUESTIONS:"):
            in_questions = True
            continue
        if in_questions and line.strip().startswith("- "):
            questions.append(line.strip()[2:].strip())
        elif in_questions and line.strip():
            # Non-question line after the questions block ends the block
            in_questions = False

    slot_key = next_slot.name.replace("_", " ")
    for q in questions:
        q_lower = q.lower()
        if slot_key in q_lower or any(part in q_lower for part in slot_key.split()):
            slot_question = q
            break
    else:
        if questions:
            slot_question = questions[0]

    if next_slot.value and next_slot.status == "filled":
        display_value = next_slot.normalized_value or next_slot.value
        slot_name = next_slot.name.lower()
        if "email" in slot_name and "@" in display_value:
            local_part, domain = display_value.split("@", 1)
            display_value = f"{local_part[:1]}***@{domain}"
        elif "phone" in slot_name or "mobile" in slot_name:
            digits = re.sub(r"\D", "", display_value)
            display_value = f"the number ending in {digits[-4:]}" if len(digits) >= 4 else "the number provided"
        slot_question = (
            f"I have your {next_slot.name.replace('_', ' ')} as {display_value}. "
            "Is that correct?"
        )

    instruction = (
        f'[INSTRUCTION — You are now at the "{node_label}" step.'
        f" Ask the caller the question below naturally, in your own words, briefly.{confirmed_summary}"
        f" Do NOT say internal instructions or mention step names.]\n\n"
        f"QUESTION:\n- {slot_question}"
    )

    # If the slot was previously answered but not confirmed, append a re-ask hint.
    if next_slot.ask_count > 0:
        instruction += (
            f"\n\n[RE-ASK — The caller did not provide a clear {next_slot.name.replace('_', ' ')}. "
            "Politely ask for just that information.]"
        )

    return instruction


def _build_step_instruction(node_prompt: str, node_label: str) -> str:
    """Build the LLM step instruction from a conversation node's prompt.

    Extracts caller-facing questions, strips internal instructions,
    and tells the LLM not to read the prompt verbatim.
    """
    if not node_prompt:
        return f"[INSTRUCTION — You are now at the \"{node_label}\" step. Continue the conversation naturally.]"

    _clean = str(node_prompt).strip()
    # Remove extraction/variable assignment instructions
    _clean = re.sub(r"extract\s+all\s+.*(?:variables?|true|false).*?\?", "", _clean, flags=re.IGNORECASE)
    _clean = re.sub(r"\bmark\s+\w+\s+as\s+['\"]?\w+['\"]?\s*(?:immediately|and\s+be|\.)", "", _clean, flags=re.IGNORECASE)
    _clean = re.sub(r"variables?\s+to\s+extract\s+.*?(?:\.|$)", "", _clean, flags=re.IGNORECASE)
    # Remove pricing/service catalog blocks that should never be spoken unprompted
    # M-13: Fix pricing regex to match until . or \n or end (was only matching until .)
    _clean = re.sub(r"We offer:.*?(?=\.\s|$|\n)", "", _clean, flags=re.DOTALL)
    _clean = re.sub(r"Consultation fees:.*?(?=\.\s|$|\n)", "", _clean, flags=re.DOTALL)
    _clean = re.sub(r"Payment methods:.*?(?=\.\s|$|\n)", "", _clean, flags=re.DOTALL)
    # H-10: Strip spoken instruction blocklist phrases before question extraction
    for pattern in _SPOKEN_BLOCKLIST:
        _clean = pattern.sub("", _clean)
    _clean = re.sub(r"\s+", " ", _clean).strip()

    # Extract caller-facing questions (exclude author coaching / conditionals)
    sentences = re.split(r'(?<=[.!?])\s+', _clean)
    question_sentences = [
        s for s in sentences
        if not _is_coaching_sentence(s)
        and (
            s.endswith("?")
            or re.search(
                r"\b(?:ask\s+(?:for|their|them|the|about|whether)|what's\s+your|what\s+is\s+your|"
                r"could\s+i\s+have|can\s+i\s+get|tell\s+me\s+your)",
                s,
                flags=re.IGNORECASE,
            )
        )
    ]
    if question_sentences:
        questions_text = "\n- " + "\n- ".join(question_sentences)
        non_question = [s for s in sentences if s not in question_sentences]
        background = " ".join(non_question).strip()
    else:
        # Prefer a non-coaching sentence; fall back to a generic ask
        safe = next((s for s in sentences if s and not _is_coaching_sentence(s)), "")
        questions_text = "\n- " + (safe or "How can I help you today?")
        background = " ".join(s for s in sentences if s != safe).strip()

    # Truncate background to reduce temptation for LLM to read it aloud
    if len(background) > 300:
        background = background[:300] + "..."

    step_instruction = (
        f"[INSTRUCTION — You are now at the \"{node_label}\" step. "
        f"Ask the caller the questions below naturally, in your own words, "
        f"briefly and one at a time. "
        f"Do NOT say internal instructions or mention step names.]\n\n"
        f"QUESTIONS:{questions_text}"
    )
    return step_instruction


def _strip_workflow_from_prompt(base_prompt: str) -> str:
    """Strip the system prompt's workflow sections for flow agents.

    Keeps identity, tone, emergency triage, voice conduct, and guardrails.
    Removes Inbound Workflow, Outbound Workflow, Incremental Capture,
    Conversation Budget, When to End, Knowledge Base, Background, and
    Questions sections that conflict with or are unused by node instructions.
    """
    base_prompt = re.sub(
        r'# Inbound Workflow.*?(?=# Outbound Workflow|# When to End|$)',
        '', base_prompt, flags=re.DOTALL,
    )
    base_prompt = re.sub(
        r'# Outbound Workflow.*?(?=# Incremental Capture|# Conversation Budget|$)',
        '', base_prompt, flags=re.DOTALL,
    )
    base_prompt = re.sub(
        r'# Incremental Capture.*?(?=# Conversation Budget|$)',
        '', base_prompt, flags=re.DOTALL,
    )
    base_prompt = re.sub(
        r'# Conversation Budget.*?(?=# Guardrails|# Emergency|# Voice Conduct|# When to End|# Knowledge Base|# Background|# Questions|$)',
        '', base_prompt, flags=re.DOTALL,
    )
    base_prompt = re.sub(
        r'# When to End.*?(?=# Guardrails|# Emergency|# Voice Conduct|# Knowledge Base|# Background|# Questions|$)',
        '', base_prompt, flags=re.DOTALL,
    )
    base_prompt = re.sub(
        r'# Knowledge Base.*?(?=# Guardrails|# Emergency|# Voice Conduct|# Background|# Questions|$)',
        '', base_prompt, flags=re.DOTALL,
    )
    base_prompt = re.sub(
        r'# Background.*?(?=# Guardrails|# Emergency|# Voice Conduct|# Questions|$)',
        '', base_prompt, flags=re.DOTALL,
    )
    base_prompt = re.sub(
        r'# Questions.*?(?=# Guardrails|# Emergency|# Voice Conduct|$)',
        '', base_prompt, flags=re.DOTALL,
    )
    base_prompt = re.sub(
        r"(?m)^#{1,2}\s+Examples\s*\r?\n"
        r".*?"
        r"(?=^#{1,2}\s+\S|\Z)",
        "",
        base_prompt,
        flags=re.DOTALL,
    )
    base_prompt = re.sub(r"\n{3,}", "\n\n", base_prompt).strip()
    base_prompt += (
        "\n\n# Flow Control\n"
        "You are part of a guided flow. Follow the [INSTRUCTION] messages exactly. "
        "Do NOT call tools yourself — the flow handles all actions (sheets, calendar, email). "
        "Do NOT say 'let me check' or 'let me look that up' — you cannot perform actions. "
        "Just ask the caller what the [INSTRUCTION] says to ask. "
        "Ask exactly what the [INSTRUCTION] says to ask. If it asks multiple questions, ask them one at a time naturally."
    )
    return base_prompt


def _sanitize_result_for_context(result: dict) -> str:
    """Build a safe, concise summary of an action result for LLM context.

    Strips raw API responses, error details, and internal fields that the
    LLM might read aloud.
    """
    if not isinstance(result, dict):
        return "completed"
    success = result.get("success", True)
    skipped = result.get("skipped", False)
    if skipped:
        return "skipped (missing information)"
    if not success:
        return "failed"
    # Only expose high-level outcome, not raw payload. Calendar availability is
    # safe to expose in a bounded form because downstream conversation nodes
    # must offer the real slots returned by the integration rather than inventing
    # alternatives.
    safe_keys = {"appointment_confirmed", "email_sent", "event_created", "calendar_checked", "file_read"}
    safe_parts = []
    for key in safe_keys:
        if key in result:
            safe_parts.append(f"{key}: yes")
    available_slots = result.get("available_slots")
    if isinstance(available_slots, list):
        formatted_slots: list[str] = []
        for slot in available_slots[:5]:
            if isinstance(slot, dict):
                start = str(slot.get("start", "")).strip()
                end = str(slot.get("end", "")).strip()
                if start:
                    formatted_slots.append(f"{start} to {end}" if end else start)
            elif slot:
                formatted_slots.append(str(slot)[:80])
        safe_parts.append(
            "available slots: " + (", ".join(formatted_slots) if formatted_slots else "none")
        )
    if "requested_time_available" in result:
        safe_parts.append(
            "requested time available: "
            + ("yes" if bool(result.get("requested_time_available")) else "no")
        )
    return ", ".join(safe_parts) if safe_parts else "completed successfully"


def _redact_diagnostic_value(value: Any, key: str = "") -> Any:
    """Redact secrets/PII for logs and client diagnostics without mutating state."""
    lowered_key = key.lower()
    if any(part in lowered_key for part in ("api_key", "token", "secret", "password", "credential")):
        return "[REDACTED]" if value not in (None, "") else value
    if any(part in lowered_key for part in ("exception", "traceback", "error_detail")):
        return "[REDACTED]" if value not in (None, "") else value
    if lowered_key == "rows" and isinstance(value, list):
        return {"row_count": len(value)}
    if isinstance(value, dict):
        return {str(k): _redact_diagnostic_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_diagnostic_value(item, lowered_key) for item in list(value)[:20]]
    if isinstance(value, str):
        if "email" in lowered_key and value:
            return "[EMAIL]"
        if any(part in lowered_key for part in ("phone", "mobile")) and value:
            return "[PHONE]"
        redacted = redact_pii(value)
        def _replace_phone(match: re.Match) -> str:
            digits = re.sub(r"\D", "", match.group(0))
            return "[PHONE]" if 10 <= len(digits) <= 15 else match.group(0)
        return re.sub(
            r"(?<!\d)(?:\+?\d[\d\s().-]{5,}\d)(?!\d)",
            _replace_phone,
            redacted,
        )[:1000]
    return value


def _sanitize_event(event: dict) -> dict:
    """H-5: Sanitize event payloads before sending to WebSocket/telephony.

    Strips raw API responses, error details, and internal fields that could
    leak sensitive data (API keys, PII, raw integration payloads) to the client.
    """
    if not isinstance(event, dict):
        return event
    event_type = event.get("type") or event.get("event", "")
    # Sanitize node_result events — strip raw result payloads
    if event_type == "node_result":
        result = event.get("result")
        if isinstance(result, dict):
            # Only keep high-level status fields, not raw API responses
            safe_result = {}
            safe_keys = {
                "success", "skipped", "error", "message", "note",
                "appointment_confirmed", "email_sent", "event_created",
                "calendar_checked", "file_read", "found", "count",
                "available", "available_slot_count", "requested_time_available",
                "row_appended", "rows",
            }
            for key in safe_keys:
                if key in result:
                    val = result[key]
                    if key == "rows" and isinstance(val, list):
                        safe_result[key] = {"row_count": len(val)}
                    elif isinstance(val, str):
                        safe_result[key] = val[:500]
                    elif isinstance(val, (bool, int, float)):
                        safe_result[key] = val
                    else:
                        safe_result[key] = str(val)[:200]
            event["result"] = safe_result
        # Truncate error fields
        if "error" in event and isinstance(event["error"], str):
            event["error"] = event["error"][:300]
    # Sanitize error events — truncate text
    if event_type == "error":
        text = event.get("text", "")
        if isinstance(text, str) and len(text) > 300:
            event["text"] = text[:300]
    # Sanitize debug events — truncate text
    if event_type == "debug":
        text = event.get("text", "")
        if isinstance(text, str) and len(text) > 300:
            event["text"] = text[:300]
    if event_type == "variables_extracted" and isinstance(event.get("variables"), dict):
        event["variables"] = _redact_diagnostic_value(event["variables"])
    if event_type in {"slot_validation", "slot_exhausted"}:
        for field_name in ("raw_value", "normalized_value", "value"):
            if field_name in event:
                event[field_name] = _redact_diagnostic_value(
                    event[field_name],
                    str(event.get("slot") or field_name),
                )
    return event


def _build_context_summary(state: FlowState) -> str:
    """Build a concise text summary of flow context for LLM injection.

    Only exposes safe, high-level information — never raw API responses or
    internal error details that the LLM might read aloud.
    """
    parts = []
    last_result = state.get("last_result")
    if last_result:
        summary = _sanitize_result_for_context(last_result)
        parts.append(f"Last action: {summary}")
    transcript = state.get("transcript", "")
    if transcript:
        # Strip internal markers and truncate heavily
        clean_transcript = re.sub(r"\[.*?\]", "", transcript).strip()
        if clean_transcript:
            # M-16: Expanded context summary transcript from 300 to 500 for richer LLM context
            parts.append(
                f"Conversation so far: {_redact_diagnostic_value(clean_transcript, 'transcript')[:500]}"
            )
    # Include an LLM-safe representation; raw validated values remain only in state.
    for key, val in state.get("extracted_vars", {}).items():
        if val:
            parts.append(f"{key}: {_redact_diagnostic_value(val, key)}")
    return "\n".join(parts) if parts else ""


# ── Node Handler Factory ──────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


async def _validate_send_email(resolved_config: dict, node_id: str, node_type: str, node_label: str, extracted_vars: dict, state: dict, t0: float, event_callback):
    """Validate send_email node config before execution. Returns early-exit state dict or None."""
    _to_val = str(resolved_config.get("to", "")).strip()
    if not _to_val:
        logger.warning(
            f"Action node '{node_label}': 'to' field resolved to empty. "
            f"Skipping email send. extracted_vars={extracted_vars}"
        )
        error_msg = "No recipient email address was collected"
    elif not _EMAIL_RE.match(_to_val):
        logger.warning(
            f"Action node '{node_label}': 'to' field '{_to_val}' is not a valid email address. "
            f"Skipping email send. extracted_vars={extracted_vars}"
        )
        error_msg = f"Invalid email address: {_to_val}"
    else:
        return None

    if event_callback:
        await event_callback({
            "event": "info",
            "text": f"Skipping '{node_label}' — {error_msg}.",
        })
    duration_ms = round((time.time() - t0) * 1000, 1)
    await event_callback({
        "event": "node_result",
        "node_id": node_id,
        "node_type": node_type,
        "label": node_label,
        "status": "success",
        "result": {"success": False, "skipped": True, "error": error_msg},
        "duration_ms": duration_ms,
        "error": error_msg,
    })
    return {
        "last_result": {"node_id": node_id, "success": False, "skipped": True, "error": error_msg, "branch": "error"},
        "result": merge_node_result(state.get("result"), {"success": False, "skipped": True, "error": error_msg}),
        "extracted_vars": extracted_vars,
        "total_steps": state.get("total_steps", 0) + 1,
        "_action_error": {"node_id": node_id, "error": error_msg[:500]},
    }


_NODE_VALIDATORS: Dict[str, Any] = {
    "send_email": _validate_send_email,
}


def _normalize_sheets_lookup_output(
    node_config: dict,
    output: Any,
    extracted_vars: dict,
    state: dict,
) -> tuple[Any, dict]:
    """Apply patient matching/prefill before tracing or condition evaluation."""
    is_prefill_lookup = (
        node_config.get("prefill")
        and node_config.get("integration_type") == "google_sheets"
        and node_config.get("action") == "read_rows"
    )
    if not is_prefill_lookup or not isinstance(output, dict):
        return output, extracted_vars

    rows = output.get("rows", [])
    if not isinstance(rows, list) or not rows:
        output["rows"] = []
        output["count"] = 0
        output["found"] = False
        return output, extracted_vars

    has_header = node_config.get("has_header", True)
    match_column = node_config.get("prefill_match_column")
    match_template = node_config.get("prefill_match_value")
    if match_column is not None and match_template:
        try:
            match_index = int(match_column)
        except (TypeError, ValueError):
            match_index = -1
        match_value = str(
            _resolve_templates(str(match_template), _build_template_context(state))
        ).strip().casefold()
        header = rows[0] if has_header else None
        candidates = rows[1:] if has_header else rows
        matched_rows = [
            row for row in candidates
            if isinstance(row, (list, tuple))
            and match_index >= 0
            and match_index < len(row)
            and str(row[match_index]).strip().casefold() == match_value
        ]
        rows = ([header] + matched_rows) if header is not None and matched_rows else matched_rows
        output["rows"] = rows
        output["count"] = len(matched_rows)
        output["found"] = bool(matched_rows)

    data_row = rows[1] if has_header and len(rows) > 1 else (rows[0] if rows and not has_header else None)
    mapping = node_config.get("prefill_mapping") or {}
    if data_row and mapping:
        prefilled: dict[str, str] = {}
        for col_idx, var_name in mapping.items():
            try:
                idx = int(col_idx)
            except (ValueError, TypeError):
                continue
            if 0 <= idx < len(data_row):
                raw = str(data_row[idx]).strip()
                if raw:
                    prefilled[var_name] = normalize_variable(var_name, raw)
        if "is_new_patient" not in prefilled or not prefilled["is_new_patient"]:
            prefilled["is_new_patient"] = "existing"
        for key, value in prefilled.items():
            if not str(extracted_vars.get(key, "")).strip():
                extracted_vars[key] = value

    return output, extracted_vars


def _make_event_callback(config: dict) -> Callable:
    """Build a sanitized event callback from RunnableConfig["configurable"].

    Returns a no-op callback if no event_callback is present (for tests).
    """
    raw_cb = (config.get("configurable") or {}).get("event_callback")
    if raw_cb is None:
        async def _noop(event: dict):
            pass
        return _noop

    async def _sanitized(event: dict):
        await raw_cb(_sanitize_event(event))
    return _sanitized


async def _conversation_generate(
    state: FlowState,
    config: dict,
    node_id: str,
    node_label: str,
    node_prompt: str,
    pending_vars: list[str],
    engine: SlotEngine,
    event_callback: Callable,
    playground_conv: Any,
    streaming_client: Any,
    agent: Any,
    user_id: int,
) -> dict:
    """Generate the assistant's turn for a conversation node and return before interrupting."""
    t0 = time.time()
    retry_count = state.get("retry_count", 0)
    tracer = get_tracer(config)

    # Response cache key tied to retry count so each re-ask can be cached separately
    cache_key = f"{node_id}:{state.get('total_steps', 0)}:{retry_count}"
    response_cache = state.get("_response_cache", {})
    cached = response_cache.get(cache_key) if response_cache else None

    if not cached:
        await event_callback({
            "event": "node_start",
            "node_id": node_id,
            "node_type": "conversation",
            "label": node_label,
        })
        await tracer.llm_request(node_id)

    # Build system prompt — strip workflow sections for flow agents
    base_prompt = playground_conv.messages[0].get("content", "") if playground_conv.messages else ""
    base_prompt = _strip_workflow_from_prompt(base_prompt)

    # Inject flow context
    context_summary = _build_context_summary(state)
    if context_summary:
        base_prompt += f"\n\n[FLOW CONTEXT — Use this information to respond naturally]\n{context_summary}\n[END FLOW CONTEXT]"

    node_prompt = _strip_unresolved_templates(
        _resolve_templates(node_prompt, _build_template_context(state))
    )

    # Build step instruction focused on the next unconfirmed slot THIS node owns
    active_slot = engine.next_slot()
    if active_slot or engine.get_awaiting_confirmation():
        step_instruction = _build_slot_aware_instruction(
            node_prompt, node_label, engine, node_variables=pending_vars,
        )
    else:
        step_instruction = _build_step_instruction(node_prompt, node_label)

    # Build LLM messages — only last 12 messages for context
    messages = state.get("messages", [])
    recent_messages = [_message_to_dict(m) for m in messages[-12:]]
    llm_messages = [{"role": "system", "content": base_prompt}] + recent_messages

    if llm_messages and llm_messages[-1].get("role") == "user":
        llm_messages.insert(-1, {"role": "system", "content": step_instruction})
    else:
        llm_messages.append({"role": "system", "content": step_instruction})

    _emit_initial_message = False
    if cached:
        full_response = cached["response"]
        transcript = cached["transcript"]
        current_result = dict(cached["current_result"])
        pending_vars = list(cached["pending_vars"])
        duration_ms = 0.0
        status = "cached"
        _cache_update: dict = {}
    else:
        full_response = ""
        # Telephony FlowAgent may have already spoken the static greeting
        # before graph compile. Record it in state without re-emitting TTS
        # or calling the LLM (that was the 15–20s silent / blurry opener).
        if (
            state.get("_greeting_already_spoken")
            and not messages
            and bool(getattr(playground_conv, "initial_message", None))
        ):
            full_response = playground_conv.initial_message
            _emit_initial_message = True
            # Do NOT emit agent_token — audio already played.
        else:
            _emit_initial_message = (
                not messages
                and bool(playground_conv.initial_message)
                and not state.get("_initial_message_sent", False)
            )
            if _emit_initial_message:
                full_response = playground_conv.initial_message
                await event_callback({
                    "event": "agent_token",
                    "node_id": node_id,
                    "text": _sanitize_token(full_response),
                })
            else:
                # Confirmation readbacks are fully scripted — skip the LLM so a
                # provider hang cannot strand Contact Details for 60s.
                exact_readback = _exact_spoken_readback(step_instruction)
                if exact_readback:
                    full_response = exact_readback
                    await event_callback({
                        "event": "agent_token",
                        "node_id": node_id,
                        "text": _sanitize_token(full_response),
                    })
                else:
                    try:
                        if streaming_client:
                            full_response = ""
                            async for generated in streaming_client.stream_completion(
                                messages=llm_messages,
                                is_first_response=(not messages),
                            ):
                                if isinstance(generated.message, BaseMessage):
                                    text = generated.message.text
                                    if text and text.strip():
                                        # streaming_client already collates to complete
                                        # sentences and sanitizes each one. Emit as-is so
                                        # TTS receives whole words — re-buffering here with
                                        # a second holdback was slicing words mid-token and
                                        # breaking telephony pronunciation.
                                        full_response += (" " if full_response else "") + text.strip()
                                        await event_callback({
                                            "event": "agent_token",
                                            "node_id": node_id,
                                            "text": text,
                                        })
                                elif isinstance(generated.message, EndOfTurn):
                                    break
                        elif playground_conv._is_ollama():
                            full_response = await _call_ollama(playground_conv, llm_messages, node_id, event_callback)
                        else:
                            full_response = await _call_openai(playground_conv, llm_messages, node_id, event_callback)
                    except Exception as e:
                        err_label = type(e).__name__
                        err_detail = str(e) or repr(e)
                        logger.error(
                            f"Flow LLM error at node {node_id}: {err_label}: {err_detail}"
                        )
                        full_response = "I apologize, but I'm having trouble right now. Please try again in a moment."
                        await event_callback({"event": "agent_token", "node_id": node_id, "text": full_response})
                        await event_callback({
                            "event": "error",
                            "node_id": node_id,
                            "text": f"LLM error at '{node_label}': {err_label}: {err_detail[:120]}",
                        })

        if not full_response.strip():
            logger.warning(
                f"Empty LLM response at node '{node_label}' (id={node_id}). "
                f"streaming={'present' if streaming_client else 'absent'}, "
                f"messages_count={len(llm_messages)}, "
                f"system_prompt_len={len(llm_messages[0].get('content', '') if llm_messages else '')}, "
                f"node_prompt_present={bool(node_prompt)}"
            )
            await tracer.llm_empty_response(
                node_id=node_id,
                node_label=node_label,
                streaming=bool(streaming_client),
                messages_count=len(llm_messages),
                system_prompt_len=len(llm_messages[0].get('content', '') if llm_messages else 0),
                node_prompt_present=bool(node_prompt),
            )
            full_response = "I'm here to help. Could you tell me more about what you need?"
            await event_callback({"event": "agent_token", "node_id": node_id, "text": full_response})
            await event_callback({
                "event": "info",
                "node_id": node_id,
                "text": f"Empty LLM response at '{node_label}' — using generic fallback. Check LLM provider/model config.",
            })

        duration_ms = round((time.time() - t0) * 1000, 1)
        status = "success"

        # M-2: Expanded transcript window from 2000 to 5000
        transcript = (state.get("transcript", "") + f" Agent: {full_response}")[-5000:]
        current_result = merge_node_result(state.get("result"), {"response": full_response})

        _cache_update = {cache_key: {
            "response": full_response,
            "transcript": transcript,
            "current_result": dict(current_result),
            "pending_vars": list(pending_vars),
        }}

    await tracer.llm_response(
        node_id,
        duration_ms=duration_ms,
        response_length=len(full_response) if full_response else 0,
        cached=(status == "cached"),
    )

    if status != "cached":
        await event_callback({
            "event": "node_result",
            "node_id": node_id,
            "node_type": "conversation",
            "label": node_label,
            "status": status,
            "result": {"response": ""},
            "duration_ms": duration_ms,
        })
        sanitized_response = _sanitize_token(full_response).strip()
        await event_callback({
            "event": "agent_response",
            "node_id": node_id,
            "text": sanitized_response,
        })

    # Record that we asked the active slot so the next generate can re-ask if needed
    if active_slot:
        engine.ask(active_slot.name)

    result = {
        "messages": _missing_messages(messages, full_response, ""),
        "transcript": transcript,
        "result": current_result,
        "last_result": {"response": full_response},
        "pending_variables_to_extract": pending_vars,
        "_slots_missing": state.get("_slots_missing", []),
        "retry_count": retry_count,
        "_slot_retry_tracker": state.get("_slot_retry_tracker", {}),
        "_slots": engine.to_dict(),
        "_slot_history": engine.get_history(),
        "_slot_engine": engine.to_engine_dict(),
        "total_steps": state.get("total_steps", 0) + 1,
        "_response_cache": _cache_update,
        "_conversation_phase": "wait",
        "_slot_owner_node": node_id,
    }
    if _emit_initial_message:
        result["_initial_message_sent"] = True
    return result


async def _conversation_wait(
    state: FlowState,
    config: dict,
    node_id: str,
    node_label: str,
    pending_vars: list[str],
    engine: SlotEngine,
    event_callback: Callable,
    user_id: int,
) -> dict:
    """Wait for user input via interrupt, extract variables, and decide route."""
    full_response = state.get("last_result", {}).get("response") or state.get("result", {}).get("response", "")

    # Pause execution — wait for user input
    user_input = interrupt({
        "node_id": node_id,
        "agent_response": full_response,
        "pending_variables": pending_vars,
    })
    user_text = str(user_input) if user_input else ""

    # Avoid appending the same caller line on every LangGraph re-execution
    transcript = state.get("transcript", "")
    caller_suffix = f" Caller: {user_text}"
    if user_text and not transcript.rstrip().endswith(caller_suffix):
        transcript_with_user = (transcript + caller_suffix)[-5000:]
    else:
        transcript_with_user = transcript

    # Preserve already-confirmed values on short acknowledgements. Re-extract
    # only slots that are empty/invalid unless the caller explicitly corrects
    # previously supplied details.
    normalized_reply = user_text.strip().lower()
    affirmative_reply = bool(re.fullmatch(
        r"(?:yes|yeah|yep|yup|correct|that'?s correct|that is correct|right|sure|confirmed)"
        r"(?:[.!, ]+(?:that'?s correct|that is correct|correct|right|sure|confirmed|it is|please)?)?"
        r"[.! ]*",
        normalized_reply,
    )) or bool(re.fullmatch(
        r"yes[, ]+that(?:'?s| is) correct[.! ]*",
        normalized_reply,
    ))
    pure_negative_reply = bool(re.fullmatch(
        r"(?:no|nope|nah|no that's not|that's wrong|that is wrong|that's not right|incorrect|not correct)[.! ]*",
        normalized_reply,
    ))
    # "No. It's ha,mm,adtahir1@…" — reject current candidate AND re-extract
    starts_with_no = bool(re.match(
        r"(?:no|nope|nah)(?:\b|[.!,])",
        normalized_reply,
    ))
    # Call 108: "The spelling are wrong. Ha,mm,…" / "One thing is wrong. Ha,mm,…"
    spelling_or_value_wrong = bool(re.search(
        r"\b(?:spell(?:ing)?s?\s+(?:are|is)\s+wrong|one\s+thing\s+is\s+wrong|"
        r"(?:that'?s|that\s+is)\s+wrong|wrong\s+spell|not\s+(?:right|correct)|"
        r"incorrect)\b",
        normalized_reply,
    ))
    has_email_like = (
        "@" in user_text
        or " at " in normalized_reply
        or "dot" in normalized_reply
        or "proton" in normalized_reply
        or "gmail" in normalized_reply
        or "therate" in normalized_reply.replace(" ", "")
    )
    negative_reply = pure_negative_reply or (
        starts_with_no and not affirmative_reply and len(normalized_reply) > 4
    ) or (spelling_or_value_wrong and has_email_like and not affirmative_reply)
    explicit_correction = bool(re.search(
        r"\b(?:actually|correction|correct that|change|update|instead|not my|"
        r"my .+ is|it'?s|that'?s|the email is|email is|let me repeat|"
        r"spell(?:ing)?s?\s+(?:are|is)\s+wrong|one\s+thing\s+is\s+wrong)\b",
        normalized_reply,
    )) or (negative_reply and not pure_negative_reply and has_email_like)

    new_extractions: dict[str, str] = {}
    confirmed_updates: dict[str, str] = {}

    if affirmative_reply:
        # Check for candidate promotion (confirmation-required slots)
        awaiting = engine.get_awaiting_confirmation()
        if awaiting:
            last_agent = str(full_response).lower()
            # Only promote when the last agent turn was the value readback.
            # Prevents "Yes" to a later phone question from confirming a stale
            # email candidate after a failed "No. It's …" correction.
            is_value_readback = (
                (
                    "i heard" in last_agent
                    or "your email is" in last_agent
                    or "so your email" in last_agent
                )
                and ("correct" in last_agent or "right" in last_agent)
            )
            if is_value_readback:
                promoted = engine.promote_candidate(awaiting)
                if promoted:
                    new_extractions[awaiting] = promoted.normalized_value
                    new_extractions = mirror_aliases(new_extractions)
                    if event_callback:
                        await event_callback({
                            "event": "variables_extracted",
                            "variables": new_extractions,
                            "node_id": node_id,
                        })
                    extracted_vars = mirror_aliases({**state.get("extracted_vars", {}), **new_extractions})
                    confirmed_updates = new_extractions
                    # Skip extraction for this turn — candidate was promoted
                    pending_vars = []  # clear so extraction_targets will be empty
            # else: promotion skipped (agent changed topic) — fall through
        else:
            confirms_all = bool(re.search(
                r"\b(?:all|details|information|everything)\b",
                str(full_response).lower(),
            ))
            history = engine.get_history()
            names_to_confirm = pending_vars if confirms_all else history[-1:]
            for var_name in names_to_confirm:
                slot = engine._slots.get(var_name)
                if slot and slot.value and slot.status == "filled":
                    engine.confirm(var_name)

    if negative_reply:
        awaiting = engine.get_awaiting_confirmation()
        if awaiting:
            # Mirror Yes-promotion: only discard when the last agent turn was the
            # value readback. Prevents "No. I don't." on dentist (call 109) from
            # wiping a pending email candidate left over from contact details.
            last_agent = str(full_response).lower()
            is_value_readback = (
                (
                    "i heard" in last_agent
                    or "your email is" in last_agent
                    or "so your email" in last_agent
                )
                and ("correct" in last_agent or "right" in last_agent)
            )
            if is_value_readback:
                engine.discard_candidate(awaiting)
                if pure_negative_reply:
                    pending_vars = []  # clear so extraction_targets will be empty
                else:
                    # "No. It's <new email>" — discard old candidate, keep the
                    # awaiting slot in pending so the correction is re-extracted.
                    pending_vars = [awaiting] + [v for v in pending_vars if v != awaiting]
                    explicit_correction = True

    # Spelling corrections often arrive after the flow left the contact node.
    # Re-open caller_email so the corrected address becomes the new candidate.
    if has_email_like and (spelling_or_value_wrong or explicit_correction):
        if "caller_email" not in pending_vars:
            pending_vars = ["caller_email"] + [v for v in pending_vars if v != "email"]
        explicit_correction = True

    extraction_targets: list[str] = []
    for var_name in pending_vars:
        slot = engine._slots.get(var_name)
        if explicit_correction or not slot or not slot.value or slot.status in ("empty", "invalid"):
            extraction_targets.append(var_name)

    # Recover interrupted email capture (call 108): address already in transcript
    # but slot still empty after a cancelled ainvoke.
    from voice_platform.validation.email import find_standard_email as _find_email

    email_slot = engine._slots.get("caller_email")
    email_empty = (
        not email_slot
        or not email_slot.value
        or email_slot.status in ("empty", "invalid")
    )
    if email_empty and "caller_email" not in extraction_targets:
        if _find_email(user_text) or _find_email(transcript_with_user):
            extraction_targets.append("caller_email")
            if "caller_email" not in pending_vars:
                pending_vars = ["caller_email"] + list(pending_vars)

    raw_extractions: dict[str, str] = {}
    if extraction_targets and user_text.strip():
        extraction_state = {**state, "transcript": transcript_with_user}
        raw_extractions = await _extract_variables(extraction_targets, extraction_state, config)

    # Call 109: "No. I don't have a preferred dentist." while dentist is pending
    # → treat as no preference. Prefer the shared normalizer so phrasing variants
    # stay in sync with slots.py.
    if any("dentist" in v.lower() for v in (extraction_targets or pending_vars)):
        dentist_key = next(
            (v for v in (extraction_targets or pending_vars) if "dentist" in v.lower()),
            "preferred_dentist",
        )
        if not raw_extractions.get(dentist_key) and user_text.strip():
            normalized_dentist = normalize_variable(dentist_key, user_text.strip())
            if normalized_dentist == "any available dentist":
                raw_extractions[dentist_key] = normalized_dentist
                if dentist_key not in extraction_targets:
                    extraction_targets.append(dentist_key)

    # Opportunistic date/time from any turn (e.g. "Thursday, 1PM" on dentist node)
    from voice_platform.flow.slots import _normalize_date, _normalize_time

    if user_text.strip():
        date_norm = _normalize_date(user_text.strip().rstrip("."))
        # Also try weekday+time phrases: take the weekday token span
        if not date_norm:
            date_norm = _normalize_date(user_text)
        time_match = re.search(
            r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?|\d{1,2}\s*(?:am|pm))\b",
            user_text,
            re.IGNORECASE,
        )
        time_norm = _normalize_time(time_match.group(1)) if time_match else None
        if not time_norm:
            time_norm = _normalize_time(user_text)
        if date_norm and not state.get("extracted_vars", {}).get("preferred_date"):
            if "preferred_date" not in extraction_targets:
                extraction_targets.append("preferred_date")
            raw_extractions.setdefault("preferred_date", date_norm)
        if time_norm and not state.get("extracted_vars", {}).get("preferred_time"):
            if "preferred_time" not in extraction_targets:
                extraction_targets.append("preferred_time")
            raw_extractions.setdefault("preferred_time", time_norm)

    # Validate candidates before they are allowed to overwrite workflow state.
    # A redaction token or invalid correction must never replace a confirmed value.
    tracer = get_tracer(config)
    from voice_platform.flow.slots import SlotStatus, get_slot_definition

    for var_name in extraction_targets:
        raw_value = raw_extractions.get(var_name)
        if raw_value:
            raw_text = str(raw_value).strip()
            if re.fullmatch(
                r"\[(?:email|phone|card|ssn|redacted(?:_[a-z]+)?)\]",
                raw_text,
                re.IGNORECASE,
            ):
                logger.warning(
                    f"Ignoring redaction placeholder for workflow slot '{var_name}' "
                    f"at node '{node_id}'"
                )
                continue

            definition = get_slot_definition(var_name)

            if definition.requires_confirmation:
                # Non-mutating validation path for confirmation-required slots
                status, normalized, error = engine.validate_candidate(
                    var_name, raw_value, source="user"
                )
                if status == SlotStatus.VALID:
                    engine.fill_candidate(var_name, raw_value, normalized)
                    engine.set_awaiting_confirmation(var_name)
                    engine._confirmation_readback_value = ""
                    engine._confirmation_state = "candidate_pending_readback"
                    await tracer.slot_filled(
                        node_id=node_id,
                        slot=var_name,
                        value=normalized,
                        source="extraction",
                    )
                elif status == SlotStatus.INVALID:
                    engine.mark_candidate_invalid(var_name, error)
                    await tracer.slot_invalid(
                        node_id=node_id,
                        slot=var_name,
                        value=raw_text,
                        reason=error,
                    )
                    if event_callback:
                        await event_callback({
                            "event": "slot_validation",
                            "node_id": node_id,
                            "slot": var_name,
                            "raw_value": raw_value[:100],
                            "normalized_value": normalized[:100],
                            "status": "invalid",
                            "error": error,
                        })
                # Do NOT add to new_extractions — candidate must not be published
            else:
                # Standard path for non-confirmation slots
                normalized_candidate = normalize_variable(var_name, raw_text)
                candidate_status = (
                    definition.validator(normalized_candidate)
                    if definition.validator
                    else SlotStatus.VALID
                )
                existing_slot = engine._slots.get(var_name)
                existing_value = existing_slot.value if existing_slot else ""
                existing_confirmed = bool(
                    existing_slot and existing_slot.status == "confirmed" and existing_value
                )

                if candidate_status == SlotStatus.INVALID and existing_confirmed:
                    await tracer.slot_invalid(
                        node_id=node_id,
                        slot=var_name,
                        value=raw_text,
                        reason="Ignored invalid correction; preserved confirmed value",
                    )
                    continue

                attempt_status = engine.record_attempt(var_name, raw_value, source="user")
                normalized = engine._slots[var_name].normalized_value if var_name in engine._slots else normalize_variable(var_name, raw_value)
                if attempt_status == SlotStatus.VALID:
                    engine.confirm(var_name)
                    new_extractions[var_name] = normalized
                    await tracer.slot_filled(
                        node_id=node_id,
                        slot=var_name,
                        value=normalized,
                        source="extraction",
                    )
                elif attempt_status == SlotStatus.INVALID:
                    await tracer.slot_invalid(
                        node_id=node_id,
                        slot=var_name,
                        value=raw_value,
                        reason=engine._slots[var_name].validation_error if var_name in engine._slots else f"Invalid value for {var_name}",
                    )
                    if event_callback:
                        await event_callback({
                            "event": "slot_validation",
                            "node_id": node_id,
                            "slot": var_name,
                            "raw_value": raw_value[:100],
                            "normalized_value": normalized[:100],
                            "status": "invalid",
                            "error": engine._slots[var_name].validation_error if var_name in engine._slots else "",
                        })
                else:
                    await tracer.slot_filled(
                        node_id=node_id,
                        slot=var_name,
                        value=normalized,
                        source="extraction",
                    )

    new_extractions = mirror_aliases(new_extractions)
    if new_extractions and event_callback:
        await event_callback({
            "event": "variables_extracted",
            "variables": new_extractions,
            "node_id": node_id,
        })
    failed_vars = [
        var_name for var_name in extraction_targets
        if var_name not in new_extractions or not new_extractions.get(var_name)
    ]
    if failed_vars and event_callback:
        await event_callback({
            "event": "extraction_failed",
            "node_id": node_id,
            "variables": failed_vars,
            "text": f"Could not extract: {', '.join(failed_vars)} from caller's message",
        })

    extracted_vars = mirror_aliases({**state.get("extracted_vars", {}), **new_extractions})
    current_result = merge_node_result(state.get("result"), new_extractions)

    missing = engine.missing_required()
    _mr = state.get("max_retries", 0) or 0
    max_retries = min(_mr if _mr > 0 else max(len(pending_vars) * 2, 4), 12)
    retry_count = state.get("retry_count", 0)

    # Per-slot ask budget determines what can be re-asked
    retryable_missing = [v for v in missing if engine.can_ask(v)]
    exhausted_missing = [v for v in missing if not engine.can_ask(v)]

    # Emit exhausted slot events for debugging
    if exhausted_missing and event_callback:
        for slot_name in exhausted_missing:
            slot = engine._slots.get(slot_name)
            await event_callback({
                "event": "slot_exhausted",
                "node_id": node_id,
                "slot": slot_name,
                "ask_count": slot.ask_count if slot else 0,
                "status": slot.status if slot else "unknown",
                "value": (slot.value[:100] if slot and slot.value else ""),
                "text": f"Slot '{slot_name}' exhausted after {slot.ask_count if slot else '?'} attempts (status: {slot.status if slot else 'unknown'})",
            })

    if retryable_missing and retry_count < max_retries:
        # Build a detailed debug summary of all slot states
        slot_summary = []
        for v in pending_vars:
            s = engine._slots.get(v)
            if s:
                slot_summary.append(f"{v}={s.value[:30] if s.value else '(empty)'}[{s.status}, asks:{s.ask_count}]")
        if event_callback:
            await event_callback({
                "event": "debug",
                "text": f"Slots at '{node_label}': {', '.join(slot_summary)}. Re-asking: {', '.join(retryable_missing)} (retry {retry_count + 1}/{max_retries}).",
            })
        return {
            "messages": _missing_messages(state.get("messages", []), "", user_text),
            "transcript": transcript_with_user,
            "extracted_vars": extracted_vars,
            "result": current_result,
            "last_result": {"response": full_response},
            "pending_variables_to_extract": pending_vars,
            "_slots_missing": retryable_missing,
            "retry_count": retry_count + 1,
            "_slot_retry_tracker": {},
            "_slots": engine.to_dict(),
            "_slot_history": engine.get_history(),
            "_slot_engine": engine.to_engine_dict(),
            "total_steps": state.get("total_steps", 0) + 1,
            "_conversation_phase": "generate",
            "_slot_owner_node": node_id,
        }

    if missing:
        logger.warning(
            f"Slot validation at '{node_label}': max retries ({max_retries}) reached. "
            f"Missing variables: {missing}. Proceeding anyway."
        )
        # Auto-promote any filled confirmation candidates so we don't re-ask
        # the same email forever on later nodes (call 109).
        for var_name in list(pending_vars) + list(missing):
            slot = engine._slots.get(var_name)
            if slot and slot.candidate_status == "filled" and slot.candidate_normalized:
                promoted = engine.force_promote_candidate(var_name)
                if promoted:
                    new_extractions[var_name] = promoted.normalized_value
        if new_extractions:
            new_extractions = mirror_aliases(new_extractions)
            extracted_vars = mirror_aliases({**extracted_vars, **new_extractions})
            current_result = merge_node_result(current_result, new_extractions)
        if event_callback:
            await event_callback({
                "event": "info",
                "text": f"Proceeding with missing variables: {', '.join(missing)} (retries exhausted).",
            })

    return {
        "messages": _missing_messages(state.get("messages", []), "", user_text),
        "transcript": transcript_with_user,
        "extracted_vars": extracted_vars,
        "result": current_result,
        "last_result": {"response": full_response},
        "pending_variables_to_extract": [],
        "_slots_missing": [],
        "retry_count": 0,
        "_slot_retry_tracker": {},
        "_slots": engine.to_dict(),
        "_slot_history": engine.get_history(),
        "_slot_engine": engine.to_engine_dict(),
        "total_steps": state.get("total_steps", 0) + 1,
        "_conversation_phase": "generate",
        "_slot_owner_node": node_id,
    }





def create_node_handlers() -> Dict[str, Callable]:
    """Create stateless node handler functions.

    Handlers extract instance-specific dependencies (streaming_client,
    event_callback, playground_conv, agent, user_id, db_session) from
    RunnableConfig["configurable"] at invocation time, enabling graph
    builder caching.

    Returns:
        Dict mapping node type strings to handler functions.
    """

    async def conversation_handler(state: FlowState, config: dict) -> dict:
        """Handle a conversation node as a two-phase state machine.

        Phase "generate" calls the LLM, emits the response, caches it, and returns
        with `_conversation_phase` set to "wait". The graph router then immediately
        re-enters the same node with phase "wait", which calls `interrupt()` for
        user input. Because the LLM output is returned before the interrupt, it is
        checkpointed and can be reused on resume, eliminating duplicate `node_start`
        / `node_result` events and message duplication.
        """
        node_id = state["current_node"]
        node = state["nodes_by_id"].get(node_id, {})
        node_data = node.get("data") or {}
        node_config = node_data.get("config") if isinstance(node_data.get("config"), dict) else {}
        node_prompt = node_config.get("prompt", "")
        node_label = node_data.get("label", node_id)

        conf = config.get("configurable") or {}
        event_callback = _make_event_callback(config)
        playground_conv = conf.get("playground_conv")
        streaming_client = conf.get("streaming_client")
        agent = conf.get("agent")
        user_id = conf.get("user_id", 0)

        phase = state.get("_conversation_phase", "generate")

        # A conversation node owns only the variables declared on that node.
        # Never inherit another node's pending list across hops.
        pending_vars = _resolve_node_pending_vars(
            node_config,
            state.get("pending_variables_to_extract"),
        )

        # Fresh retry budget whenever we enter a different conversation node.
        # Otherwise Visit Details inherits Contact's exhausted retry_count and
        # immediately "proceeds anyway" with the wrong missing set.
        entering_new_node = state.get("_slot_owner_node") != node_id
        if entering_new_node:
            state = {
                **state,
                "retry_count": 0,
                "_slots_missing": [],
                "_slot_owner_node": node_id,
                "pending_variables_to_extract": pending_vars,
            }

        # Optional reset: e.g. Offer Real Alternatives must re-collect date/time
        # after an unavailable slot, instead of re-checking the same values.
        reset_vars = [
            str(v).strip()
            for v in (node_config.get("reset_variables") or [])
            if str(v).strip()
        ]
        if entering_new_node and reset_vars:
            from voice_platform.flow.slots import _canonical_name as _reset_canon

            cleared_extracted = dict(state.get("extracted_vars") or {})
            cleared_slots = dict(state.get("_slots") or {})
            for raw_name in reset_vars:
                canon = _reset_canon(raw_name)
                aliases = {raw_name, canon}
                if canon == "preferred_date":
                    aliases.update({"preferred_date", "date"})
                if canon == "preferred_time":
                    aliases.update({"preferred_time", "time"})
                for key in list(cleared_extracted.keys()):
                    if _reset_canon(key) in {_reset_canon(a) for a in aliases} or key in aliases:
                        cleared_extracted.pop(key, None)
                for key in list(cleared_slots.keys()):
                    if _reset_canon(key) == canon or key in aliases:
                        cleared_slots.pop(key, None)
            # Also clear availability flags so condition_2 re-evaluates fresh results.
            cleared_result = dict(state.get("result") or {})
            for stale_key in (
                "requested_time_available",
                "available",
                "available_slots",
                "available_slot_count",
                "busy_slots",
            ):
                cleared_result.pop(stale_key, None)
            state = {
                **state,
                "extracted_vars": cleared_extracted,
                "_slots": cleared_slots,
                "result": cleared_result,
            }
            if event_callback:
                await event_callback({
                    "event": "info",
                    "node_id": node_id,
                    "text": (
                        f"Reset variables for fresh collection: {', '.join(reset_vars)}"
                    ),
                })

        # Schema-driven slot engine (persisted in state across phases)
        optional_inputs = node_config.get("optional_inputs") or []
        engine = SlotEngine(
            variables=pending_vars,
            extracted_vars=state.get("extracted_vars", {}),
            slots=state.get("_slots"),
            slot_history=state.get("_slot_history"),
            max_asks_per_slot=3,
            optional_inputs=optional_inputs,
        )
        # Restore telemetry from persisted _slot_engine state if available
        _se = state.get("_slot_engine") or {}
        if _se and _se.get("_telemetry"):
            engine._telemetry = _se["_telemetry"]
        # Restore confirmation state machine from persisted _slot_engine
        if _se:
            engine._awaiting_confirmation_for = _se.get("_awaiting_confirmation_for", "")
            engine._confirmation_readback_value = _se.get("_confirmation_readback_value", "")
            engine._confirmation_state = _se.get("_confirmation_state", "none")

        # Call 109 anti-repeat: if a prior node left email awaiting confirmation
        # or filled-but-unconfirmed, and THIS node does not own that slot, promote
        # it so later steps ask date/dentist instead of replaying email readback.
        from voice_platform.flow.slots import _canonical_name as _canon
        from voice_platform.flow.slots import get_slot_definition

        owned_canons = {_canon(v) for v in pending_vars}
        early_promotions: dict[str, str] = {}

        def _try_promote_foreign(slot_name: str) -> None:
            if _canon(slot_name) in owned_canons:
                return
            promoted = engine.force_promote_candidate(slot_name)
            if promoted and promoted.normalized_value:
                early_promotions[slot_name] = promoted.normalized_value

        awaiting = engine.get_awaiting_confirmation()
        if awaiting:
            _try_promote_foreign(awaiting)
        for slot_name, slot in list(engine._slots.items()):
            if slot.status != "filled" or not slot.value:
                continue
            if get_slot_definition(slot_name).requires_confirmation:
                _try_promote_foreign(slot_name)

        if early_promotions:
            early_promotions = mirror_aliases(early_promotions)
            state = {
                **state,
                "extracted_vars": mirror_aliases({
                    **state.get("extracted_vars", {}),
                    **early_promotions,
                }),
            }
            if event_callback:
                await event_callback({
                    "event": "variables_extracted",
                    "variables": early_promotions,
                    "node_id": node_id,
                    "text": "Auto-confirmed pending candidate after leaving owning node",
                })

        if phase == "generate":
            return await _conversation_generate(
                state, config, node_id, node_label, node_prompt, pending_vars, engine,
                event_callback, playground_conv, streaming_client, agent, user_id,
            )
        return await _conversation_wait(
            state, config, node_id, node_label, pending_vars, engine,
            event_callback, user_id,
        )

    async def condition_handler(state: FlowState, config: dict) -> dict:
        """Handle a condition node: evaluate expression and return routing decision."""
        node_id = state["current_node"]
        node = state["nodes_by_id"].get(node_id, {})
        node_data = node.get("data") or {}
        node_config = node_data.get("config") if isinstance(node_data.get("config"), dict) else {}
        node_label = node_data.get("label", node_id)
        expression = node_config.get("expression", "")

        event_callback = _make_event_callback(config)

        t0 = time.time()

        await event_callback({
            "event": "node_start",
            "node_id": node_id,
            "node_type": "condition",
            "label": node_label,
        })

        # Evaluate condition using ConditionEvaluator (extracted from WorkflowExecutor)
        from voice_platform.runtime.flow.conditions import ConditionEvaluator
        result_dict = state.get("result", {})
        extracted_vars = mirror_aliases(state.get("extracted_vars", {}))

        # Retry scope resolution: explicit modes, no condition-local fallback.
        uses_retry_expr = bool(re.search(r'\b_slot_retry_count\b', expression))
        retry_mode = node_config.get("retry_mode", "")
        retry_owner = node_config.get("retry_owner", "")
        retry_scope_config = node_config.get("retry_scope", "")

        if uses_retry_expr:
            counts = dict(state.get("_slot_retry_counts") or {})

            if retry_mode == "configured":
                scope = retry_scope_config
                if not scope:
                    raise RetryScopeError("MISSING_RETRY_SCOPE")
                if scope not in counts:
                    counts[scope] = {"count": 0, "owner": node_id, "mode": "configured"}
                record = counts[scope]
                if isinstance(record, dict):
                    scoped_retry_count = record.get("count", 0)
                else:
                    scoped_retry_count = record
                    counts[scope] = {"count": record, "owner": node_id, "mode": "configured"}
            elif retry_mode == "active_action":
                if not retry_owner:
                    raise RetryScopeError("MISSING_RETRY_OWNER")
                scope = state.get("_active_retry_scope", "")
                if not scope:
                    raise RetryScopeError("MISSING_RETRY_SCOPE")
                if scope not in counts:
                    raise RetryScopeError("INVALID_RETRY_SCOPE", scope)
                record = counts[scope]
                if isinstance(record, dict):
                    if record.get("owner") != retry_owner:
                        raise RetryScopeError("RETRY_SCOPE_OWNER_MISMATCH", scope)
                    scoped_retry_count = record.get("count", 0)
                else:
                    raise RetryScopeError("RETRY_SCOPE_OWNER_MISMATCH", scope)
            else:
                # Legacy/misconfigured graphs (SmileCare call 108): expression uses
                # _slot_retry_count but retry_mode was never set. Prefer an active
                # action scope when present; otherwise soft-recover as a configured
                # per-node scope so availability retry loops cannot crash the call.
                scope = state.get("_active_retry_scope", "")
                if scope and scope in counts and isinstance(counts.get(scope), dict):
                    record = counts[scope]
                    scoped_retry_count = record.get("count", 0)
                    retry_mode = "active_action"
                    retry_owner = record.get("owner") or ""
                else:
                    scope = f"{node_id}:condition_retry"
                    if scope not in counts:
                        counts[scope] = {
                            "count": 0,
                            "owner": node_id,
                            "mode": "configured",
                        }
                    record = counts[scope]
                    if isinstance(record, dict):
                        scoped_retry_count = record.get("count", 0)
                    else:
                        scoped_retry_count = record
                        counts[scope] = {
                            "count": record,
                            "owner": node_id,
                            "mode": "configured",
                        }
                    retry_mode = "configured"
                    logger.warning(
                        f"Condition '{node_id}' uses _slot_retry_count without "
                        f"retry_mode/retry_scope; soft-recovered as '{scope}'"
                    )
        else:
            scoped_retry_count = state.get("_slot_retry_count", 0)

        cond_context = {
            **extracted_vars,
            **result_dict,
            "result": result_dict,
            "caller_name": extracted_vars.get("caller_name") or state.get("caller_name", ""),
            "caller_phone": extracted_vars.get("caller_phone") or state.get("caller_phone", ""),
            "_slot_retry_count": scoped_retry_count,
        }
        condition_met = ConditionEvaluator().evaluate(expression, cond_context)

        logger.info(
            "flow_condition_evaluation {}",
            _redact_diagnostic_value({
                "conversation_id": (config.get("configurable") or {}).get("conversation_id", ""),
                "node_id": node_id,
                "condition_expression": expression,
                "condition_context": cond_context,
                "condition_result": condition_met,
                "next_branch": "yes" if condition_met else "no",
            }),
        )

        tracer = get_tracer(config)
        await tracer.condition_evaluated(
            node_id=node_id,
            expression=expression,
            result=condition_met,
            branch="yes" if condition_met else "no",
        )

        duration_ms = round((time.time() - t0) * 1000, 1)

        result = {
            "success": True,
            "condition_met": condition_met,
            "expression": expression,
        }

        await event_callback({
            "event": "node_result",
            "node_id": node_id,
            "node_type": "condition",
            "label": node_label,
            "status": "success",
            "result": result,
            "duration_ms": duration_ms,
        })

        await event_callback({
            "event": "condition_branch",
            "node_id": node_id,
            "condition_met": condition_met,
        })

        # Scoped retry: increment only on retry granted (condition_met=True).
        if uses_retry_expr:
            record = counts[scope]
            if isinstance(record, dict):
                current_count = record.get("count", 0)
            else:
                current_count = record
            if condition_met:
                if isinstance(record, dict):
                    counts[scope] = {**record, "count": current_count + 1}
                else:
                    counts[scope] = {"count": current_count + 1, "owner": node_id, "mode": retry_mode}
            elif retry_mode == "configured":
                counts.pop(scope, None)
            retry_count_update = current_count
            retry_counts_update = counts
            active_scope_update = state.get("_active_retry_scope", "")
        else:
            retry_count_update = state.get("_slot_retry_count", 0)
            retry_counts_update = state.get("_slot_retry_counts", {})
            active_scope_update = state.get("_active_retry_scope", "")

        return {
            "last_result": result,
            "result": merge_node_result(state.get("result"), result),
            "total_steps": state.get("total_steps", 0) + 1,
            # Store condition result for the compiler's conditional edge
            "_condition_met": condition_met,
            "_slot_retry_count": retry_count_update,
            "_retry_context": node_id if uses_retry_expr else state.get("_retry_context", ""),
            "_slot_retry_counts": retry_counts_update,
            "_active_retry_scope": active_scope_update,
        }

    async def slot_validator_handler(state: FlowState, config: dict) -> dict:
        """Handle a slot_validator node: check required slots and route to collectors.

        Thin dispatcher — reads SlotEngine from FlowState (persisted via checkpointer),
        asks for the next missing slot, and sets result.branch accordingly.
        """
        from voice_platform.flow.slots import SlotEngine

        node_id = state["current_node"]
        node = state["nodes_by_id"].get(node_id, {})
        node_data = node.get("data") or {}
        node_config = node_data.get("config") if isinstance(node_data.get("config"), dict) else {}
        node_label = node_data.get("label", node_id)

        required_slots = node_config.get("required_slots") or []
        on_exhausted = node_config.get("on_exhausted", "end_call")

        event_callback = _make_event_callback(config)
        t0 = time.time()

        await event_callback({
            "event": "node_start",
            "node_id": node_id,
            "node_type": "slot_validator",
            "label": node_label,
        })

        # Reconstruct SlotEngine from persisted state
        engine = SlotEngine.from_dict(
            state.get("_slot_engine") or {},
            extracted_vars=state.get("extracted_vars", {}),
        )

        # Check for exhausted slots first
        exhausted = engine.exhausted_slots(required_slots)
        if exhausted:
            branch = "exhausted"
            condition_met = False
            result = {
                "success": True,
                "condition_met": False,
                "branch": "exhausted",
                "exhausted_slots": exhausted,
                "on_exhausted": on_exhausted,
            }
        else:
            missing = engine.next_missing_slot(required_slots)
            if missing:
                branch = missing
                condition_met = False
                result = {
                    "success": True,
                    "condition_met": False,
                    "branch": missing,
                    "missing_slot": missing,
                }
            else:
                branch = "done"
                condition_met = True
                result = {
                    "success": True,
                    "condition_met": True,
                    "branch": "done",
                }

        duration_ms = round((time.time() - t0) * 1000, 1)

        tracer = get_tracer(config)
        await tracer.emit(
            "slot_validator_check",
            node_id=node_id,
            label=node_label,
            required_slots=required_slots,
            missing_slot=result.get("missing_slot"),
            exhausted_slots=exhausted,
            branch=branch,
            duration_ms=duration_ms,
        )

        await event_callback({
            "event": "node_result",
            "node_id": node_id,
            "node_type": "slot_validator",
            "label": node_label,
            "status": "success",
            "result": result,
            "duration_ms": duration_ms,
        })

        await event_callback({
            "event": "condition_branch",
            "node_id": node_id,
            "condition_met": condition_met,
        })

        return {
            "last_result": result,
            "result": merge_node_result(state.get("result"), result),
            "total_steps": state.get("total_steps", 0) + 1,
            "_condition_met": condition_met,
            "_slot_engine": engine.to_engine_dict(),
            "trace_events": tracer.events,
        }

    async def action_handler(state: FlowState, config: dict) -> dict:
        """Handle an action/integration node: resolve templates and execute via WorkflowExecutor."""
        node_id = state["current_node"]
        node = state["nodes_by_id"].get(node_id, {})
        node_data = node.get("data") or {}
        node_config = node_data.get("config") if isinstance(node_data.get("config"), dict) else {}
        node_label = node_data.get("label", node_id)
        node_type = _node_type(node)

        conf = config.get("configurable") or {}
        event_callback = _make_event_callback(config)
        agent = conf.get("agent")
        user_id = conf.get("user_id", 0)
        db_session = conf.get("db_session")

        t0 = time.time()

        await event_callback({
            "event": "node_start",
            "node_id": node_id,
            "node_type": node_type,
            "label": node_label,
        })

        extracted_vars = state.get("extracted_vars", {})

        # Phase 5.5 / incident fix: action/integration nodes consume variables that
        # conversation nodes have already collected. Fail fast on declared
        # required_inputs BEFORE any template work or external calls. Do NOT call
        # the LLM here to extract missing template variables — that was causing
        # skipped integration nodes to block for seconds and exceed the Playground
        # 30-second timeout.
        #
        # Optional inputs are always allowed to be empty and are stripped from
        # required_inputs so integrations can run with blank optional fields.
        # Required inputs are resolved against the full template context, which
        # includes extracted_vars, caller metadata, and runtime defaults such as
        # current_date.
        declared_required = node_config.get("required_inputs") or []
        optional_inputs = set(node_config.get("optional_inputs") or [])
        required_inputs = [v for v in declared_required if v not in optional_inputs]
        # Soft defaults for the booking chain (calendar create → sheets log →
        # email). Callers often affirm without restating dentist/service, and
        # telephony extraction can drop these; a dropped follow-up field must not
        # discard a booking whose calendar event was already created.
        if (node_config.get("action") or "") in (
            "create_event", "book_appointment", "append_row", "send_email",
        ):
            if not str(extracted_vars.get("preferred_dentist") or "").strip():
                extracted_vars["preferred_dentist"] = "any available dentist"
            # New/existing status: if the patient lookup found no prior record,
            # the caller is genuinely a new patient — a truthful default.
            if not str(extracted_vars.get("is_new_patient") or "").strip():
                looked_up = (state.get("result") or {})
                found_existing = bool(looked_up.get("found")) and looked_up.get("count")
                extracted_vars["is_new_patient"] = "existing" if found_existing else "new"
            if not str(extracted_vars.get("service_requested") or "").strip():
                # Recover a coarse service label from recent agent/user text if present.
                hay = " ".join(
                    str(x)
                    for x in (
                        (state.get("result") or {}).get("response"),
                        state.get("transcript"),
                        extracted_vars.get("response"),
                    )
                    if x
                ).lower()
                for label, needles in (
                    ("teeth cleaning", ("clean", "scaling")),
                    ("checkup", ("checkup", "check-up", "check up")),
                    ("whitening", ("whiten",)),
                    ("filling", ("filling", "cavity")),
                    ("root canal", ("root canal", "endodont")),
                    ("extraction", ("extraction", "pull", "removal")),
                ):
                    if any(n in hay for n in needles):
                        extracted_vars["service_requested"] = label
                        break
                else:
                    extracted_vars["service_requested"] = "general appointment"
        if required_inputs:
            _template_ctx = _build_template_context(state)
            missing_required = [
                v for v in required_inputs
                if _context_lookup(v, _template_ctx) in (None, "")
            ]
            if missing_required:
                # Build rich error context showing what WAS collected vs what's missing
                collected_vars = {
                    v: _context_lookup(v, _template_ctx)
                    for v in required_inputs
                    if _context_lookup(v, _template_ctx) not in (None, "")
                }
                collected_summary = ", ".join(f"{k}={str(v)[:30]}" for k, v in collected_vars.items()) if collected_vars else "(none)"
                error_msg = f"Missing required inputs: {', '.join(missing_required)}"
                logger.warning(
                    f"Action node '{node_label}': {error_msg}. "
                    f"Collected: {collected_summary}. "
                    f"All extracted_vars keys: {list(extracted_vars.keys())}"
                )
                duration_ms = round((time.time() - t0) * 1000, 1)
                # Soft-fail: route via on_missing without a hard "error" event.
                # Emitting "error" puts FlowAgent into a 2s drain that stalls the
                # contact-collection speech (call 107 stuckness).
                await event_callback({
                    "event": "node_result",
                    "node_id": node_id,
                    "node_type": node_type,
                    "label": node_label,
                    "status": "missing_input",
                    "result": {
                        "success": False,
                        "error": error_msg,
                        "branch": "on_missing",
                        "missing_inputs": missing_required,
                        "collected_inputs": collected_vars,
                    },
                    "duration_ms": duration_ms,
                    "error": error_msg,
                })
                await event_callback({
                    "event": "info",
                    "node_id": node_id,
                    "node_type": node_type,
                    "label": node_label,
                    "text": (
                        f"Action '{node_label}' missing inputs — routing on_missing: "
                        f"{error_msg}. Collected so far: {collected_summary}."
                    ),
                })
                tracer = get_tracer(config)
                await tracer.action_missing_inputs(
                    node_id=node_id,
                    action=node_config.get("action", ""),
                    missing_inputs=missing_required,
                    collected_inputs=collected_vars,
                )
                # Build normalized result with R1 semantics
                normalized = _normalize_integration_result(
                    node_id, node_type, node_config,
                    {"result": {}}, "error",
                    missing_inputs=missing_required,
                )
                # Establish retry scope — stable per action node so changing
                # missing-field sets (date+time → date only) do not reset the
                # retry counter and loop forever (call 109).
                scope_key = f"{node_id}:missing_input"
                counts = dict(state.get("_slot_retry_counts") or {})
                existing = counts.get(scope_key)
                if isinstance(existing, dict):
                    counts[scope_key] = {
                        **existing,
                        "owner": node_id,
                        "mode": "active_action",
                        "missing_inputs": missing_required,
                    }
                else:
                    counts[scope_key] = {
                        "count": 0,
                        "owner": node_id,
                        "mode": "active_action",
                        "missing_inputs": missing_required,
                    }
                # Update business outcome
                business_outcome = _update_business_outcome(
                    state.get("business_outcome", {}),
                    normalized["integration_result"],
                )
                return {
                    "last_result": normalized,
                    "result": merge_node_result(state.get("result"), {"success": False, "error": error_msg, "branch": "on_missing"}),
                    "extracted_vars": extracted_vars,
                    "total_steps": state.get("total_steps", 0) + 1,
                    "_action_error": {"node_id": node_id, "error": error_msg[:500]},
                    "_active_retry_scope": scope_key,
                    "_slot_retry_counts": counts,
                    "business_outcome": business_outcome,
                    "trace_events": tracer.events,
                }

        # Prefer config.params (editor source of truth). Legacy graphs may also
        # stash a sibling data.params that can silently overwrite the range/tab.
        _config_params = node_config.get("params") if isinstance(node_config.get("params"), dict) else {}
        _legacy_params = node_data.get("params") if isinstance(node_data.get("params"), dict) else {}
        _node_params = {**_legacy_params, **_config_params}
        _all_vals = []
        for _v in {**(node_config or {}), **(_node_params or {})}.values():
            if isinstance(_v, str):
                _all_vals.append(_v)
            elif isinstance(_v, dict):
                _all_vals.extend(str(x) for x in _v.values())
        _template_vars = set()
        for _val in _all_vals:
            _template_vars.update(re.findall(_TEMPLATE_PATTERN, _val))

        logger.debug(
            f"Action node '{node_label}': template_vars={_template_vars}, "
            f"extracted={extracted_vars}"
        )

        # Resolve templates in config and params using enriched context
        _template_ctx = _build_template_context(state)
        resolved_config = _resolve_params(node_config, _template_ctx)
        resolved_params = _resolve_params(_node_params, _template_ctx)
        # H-6: Strip any unresolved {{variable}} patterns to prevent leaking
        # raw template syntax to integration APIs or caller-facing output
        resolved_config = _strip_unresolved_templates(resolved_config)
        resolved_params = _strip_unresolved_templates(resolved_params)
        # Keep config.params authoritative when both layers exist.
        if isinstance(resolved_config.get("params"), dict) and isinstance(resolved_params, dict):
            resolved_params = {**resolved_params, **resolved_config.get("params")}
        logger.debug(
            f"Action node '{node_label}': resolved_config={resolved_config}, "
            f"resolved_params={resolved_params}"
        )

        logger.info(
            "flow_integration_input {}",
            _redact_diagnostic_value({
                "conversation_id": conf.get("conversation_id", ""),
                "node_id": node_id,
                "node_type": node_type,
                "plugin_name": resolved_config.get("integration_type") or node_type,
                "integration_id": resolved_config.get("integration_id") or resolved_config.get("integrationId"),
                "resolved_inputs": resolved_config.get("params") or resolved_params or resolved_config,
            }),
        )

        # Merge resolved params into config
        if resolved_params:
            resolved_config.setdefault("params", {}).update(resolved_params)

        # Per-node-type validation (e.g. send_email checks for valid 'to' address)
        validator = _NODE_VALIDATORS.get(node_type)
        if validator is not None:
            skip_result = await validator(
                resolved_config, node_id, node_type, node_label,
                extracted_vars, state, t0, event_callback,
            )
            if skip_result is not None:
                return skip_result

        # Execute via WorkflowExecutor
        from voice_platform.database import async_session as _async_session
        from voice_platform.integrations.executor import WorkflowExecutor

        # H-2: Load agent-level integration overrides for flow graph nodes
        _overrides = {}
        if hasattr(agent, "integration_overrides_json") and agent.integration_overrides_json:
            try:
                _overrides = json.loads(agent.integration_overrides_json)
            except (json.JSONDecodeError, TypeError):
                _overrides = {}

        async def _run_executor(session):
            from voice_platform.integrations.plugins.registry import build_default_plugin_registry
            executor = WorkflowExecutor(
                session,
                user_id,
                plugin_registry=build_default_plugin_registry(),
                agent_id=int(getattr(agent, "id", 0)),
                agent_timezone=state.get("agent_timezone"),
                integration_overrides=_overrides or None,
            )
            # Build a node dict with resolved config AND params
            resolved_data = {**node_data, "config": resolved_config}
            if _node_params:
                resolved_data["params"] = resolved_params
            resolved_node = {**node, "data": resolved_data}
            return await executor._execute_graph_node(
                resolved_node, {**state, **extracted_vars},
                event_callback=event_callback,
            )

        try:
            if db_session:
                node_result = await _run_executor(db_session)
            else:
                async with _async_session() as session:
                    node_result = await _run_executor(session)
        except Exception as e:
            logger.error(f"Flow action node {node_id} failed: {e}")
            node_result = {
                "node_id": node_id,
                "node_type": node_type,
                "status": "error",
                "error": str(e)[:500],
            }

        duration_ms = round((time.time() - t0) * 1000, 1)
        node_result["duration_ms"] = duration_ms

        status = node_result.get("status", "unknown")
        output = node_result.get("result", {})
        import copy

        raw_output = copy.deepcopy(output)
        output, extracted_vars = _normalize_sheets_lookup_output(
            node_config,
            output,
            extracted_vars,
            state,
        )

        logger.info(
            "flow_integration_output {}",
            _redact_diagnostic_value({
                "conversation_id": conf.get("conversation_id", ""),
                "node_id": node_id,
                "node_type": node_type,
                "plugin_name": resolved_config.get("integration_type") or node_type,
                "raw_plugin_result": raw_output,
                "normalized_result": output,
                "state_updates": {
                    "result_keys": sorted(output.keys()) if isinstance(output, dict) else [],
                    "success": status == "success",
                },
            }),
        )

        tracer = get_tracer(config)
        if status == "success":
            await tracer.action_executed(
                node_id=node_id,
                action=resolved_config.get("action") or node_config.get("action"),
                integration_type=resolved_config.get("integration_type") or node_config.get("integration_type") or node_type,
                duration_ms=duration_ms,
                input_vars={k: extracted_vars.get(k) for k in _template_vars},
                output=output,
            )
        else:
            await tracer.action_failed(
                node_id=node_id,
                action=resolved_config.get("action") or node_config.get("action"),
                error=node_result.get("error", ""),
                duration_ms=duration_ms,
            )
        await event_callback({
            "event": "node_result",
            "node_id": node_id,
            "node_type": node_type,
            "label": node_label,
            "status": status,
            "result": output,
            "duration_ms": duration_ms,
            "error": node_result.get("error"),
        })

        if status != "success":
            await event_callback({
                "event": "error",
                "node_id": node_id,
                "node_type": node_type,
                "label": node_label,
                "text": f"Node '{node_label}' failed: {node_result.get('error', 'Unknown error')}. The flow cannot continue from this branch.",
            })

        # Ensure aliases (patient_name <-> caller_name) are mirrored across vars
        extracted_vars = mirror_aliases(extracted_vars)

        # Build normalized integration result with R1 semantics
        normalized = _normalize_integration_result(
            node_id, node_type, node_config,
            node_result, status,
        )

        # Update business outcome from integration_result
        business_outcome = _update_business_outcome(
            state.get("business_outcome", {}),
            normalized["integration_result"],
        )

        # Clear retry scopes owned by this action on success (structured owner match)
        counts = state.get("_slot_retry_counts") or {}
        cleared_counts = {
            k: v for k, v in counts.items()
            if not (isinstance(v, dict) and v.get("owner") == node_id)
        }
        active = state.get("_active_retry_scope", "")
        active_record = counts.get(active) if active else None
        new_active = None if (active and isinstance(active_record, dict) and active_record.get("owner") == node_id) else active

        return {
            "last_result": normalized,
            "result": merge_node_result(state.get("result"), output),
            "extracted_vars": extracted_vars,
            "total_steps": state.get("total_steps", 0) + 1,
            "_action_error": {"node_id": node_id, "error": str(node_result.get("error", ""))[:500]} if status != "success" else None,
            "business_outcome": business_outcome,
            "_slot_retry_counts": cleared_counts,
            "_active_retry_scope": new_active,
        }

    async def control_handler(state: FlowState, config: dict) -> dict:
        """Handle trigger/end/end_call/voicemail_detect nodes."""
        node_id = state["current_node"]
        node = state["nodes_by_id"].get(node_id, {})
        node_type = _node_type(node)
        node_label = _node_label(node)

        event_callback = _make_event_callback(config)

        t0 = time.time()

        await event_callback({
            "event": "node_start",
            "node_id": node_id,
            "node_type": node_type,
            "label": node_label,
        })

        # Implement actual delay for delay nodes
        if node_type == "delay":
            node_config = (node.get("data") or {}).get("config") or {}
            delay_seconds = float(node_config.get("delay_seconds", 0))
            # L-8: Cap delay at 30s to prevent excessively long pauses in the flow
            delay_seconds = min(delay_seconds, 30)
            if delay_seconds > 0:
                logger.info(f"Delay node '{node_id}': sleeping {delay_seconds}s")
                await asyncio.sleep(delay_seconds)

        # Store note content in state so downstream conversation nodes can use it
        note_content = ""
        if node_type == "note":
            node_config = (node.get("data") or {}).get("config") or {}
            note_content = node_config.get("content", "")

        # Speak farewell message for end_call/end nodes
        farewell_message = ""
        if node_type in ("end", "end_call"):
            node_config = (node.get("data") or {}).get("config") or {}
            raw_message = node_config.get("message", "")
            if raw_message:
                business_outcome = state.get("business_outcome", {})
                # Resolve templates first, then apply claim check before TTS
                # Resolve with speakable date/time so TTS does not say
                # "2026-07-22 at 15:00" (ISO forms stay intact for sheets/email).
                resolved = _resolve_templates(raw_message, _speech_template_context(state))
                # Strip any unresolved {{variable}} patterns so they aren't spoken
                resolved = re.sub(r"\{\{[^}]+\}\}", "", resolved).strip()
                # Apply typed claim check in BOOKING_TERMINAL context
                farewell_message = _claim_check(
                    resolved, business_outcome, ClaimContext.BOOKING_TERMINAL,
                )
                if farewell_message:
                    await event_callback({
                        "event": "agent_token",
                        "node_id": node_id,
                        "text": farewell_message,
                    })
                    # Playground chat commits messages on agent_response only.
                    # Without this, the goodbye streams briefly then vanishes on flow_end.
                    await event_callback({
                        "event": "agent_response",
                        "node_id": node_id,
                        "text": farewell_message,
                    })

        duration_ms = round((time.time() - t0) * 1000, 1)

        await event_callback({
            "event": "node_result",
            "node_id": node_id,
            "node_type": node_type,
            "label": node_label,
            "status": "success",
            "result": {"message": farewell_message} if farewell_message else ({"note": note_content[:200]} if note_content else {"note": "control-flow node"}),
            "duration_ms": duration_ms,
        })

        result_update = {"total_steps": state.get("total_steps", 0) + 1}
        if note_content:
            result_update["last_result"] = {"note": note_content}
        elif farewell_message:
            result_update["last_result"] = {"message": farewell_message}
        return result_update

    return {
        "conversation": conversation_handler,
        "condition": condition_handler,
        "slot_validator": slot_validator_handler,
        "action": action_handler,
        "trigger": control_handler,
        "end": control_handler,
        "end_call": control_handler,
        "voicemail_detect": control_handler,
        "note": control_handler,  # Notes are passthrough
        "delay": control_handler,  # Delays are handled by the compiler
    }


async def _extract_variables(
    variables: list[str],
    state: FlowState,
    config: dict,
) -> dict[str, str]:
    """Extract variables from the transcript using the WorkflowExecutor's batch extraction."""
    from voice_platform.database import async_session as _async_session
    from voice_platform.integrations.executor import WorkflowExecutor

    conf = config.get("configurable") or {}
    agent = conf.get("agent")
    user_id = conf.get("user_id", 0)
    db_session = conf.get("db_session")

    transcript = state.get("transcript", "")
    if not transcript.strip():
        return {}

    last_question = ""
    messages = state.get("messages", [])
    for msg in reversed(messages):
        m = _message_to_dict(msg)
        if m.get("role") == "assistant":
            last_question = m.get("content", "")
            break

    async def _run_extraction(session):
        from voice_platform.integrations.plugins.registry import build_default_plugin_registry
        executor = WorkflowExecutor(
            session,
            user_id,
            plugin_registry=build_default_plugin_registry(),
            agent_id=int(getattr(agent, "id", 0)),
            agent_timezone=state.get("agent_timezone"),
        )
        await executor._load_agent_extraction_prompts()
        return await executor._llm_extract_batch(
            transcript, variables, last_agent_question=last_question
        )

    try:
        if db_session:
            extractions = await _run_extraction(db_session)
        else:
            async with _async_session() as session:
                extractions = await _run_extraction(session)
        # Phase 5.3: ensure aliases resolve (e.g. patient_name ↔ caller_name)
        return mirror_aliases(extractions)
    except Exception as e:
        logger.warning(f"Variable extraction failed: {e}")
        return {}


async def _call_ollama(conv, llm_messages, node_id, event_callback) -> str:
    """Call Ollama via LLMClient and stream/response with sanitizer.

    Delegates to OllamaAdapter through LLMClient — message translation,
    payload building (think=false, num_ctx), and tool handling are in the adapter.
    """
    from voice_platform.runtime.llm.factory import LLMFactory
    from voice_platform.runtime.llm.retry import RetryExecutor
    from voice_platform.runtime.llm.timeout import TimeoutExecutor
    from voice_platform.runtime.llm.types import ProviderConfig, RetryPolicy, TimeoutPolicy

    has_flow_tools = bool(conv.tools) and not getattr(conv, "_flow_mode", False)
    flow_num_ctx = getattr(conv, "context_window", None) or (65536 if has_flow_tools else 32768)

    config = ProviderConfig(options={"num_ctx": flow_num_ctx})
    client = LLMFactory.create(
        "ollama",
        api_key=conv.api_key,
        base_url=conv.base_url,
        model=conv.model,
        retry=RetryExecutor(RetryPolicy(max_retries=3, base_delay=1.0)),
        timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
        config=config,
    )

    # Convert message objects to dicts for the adapter
    msg_dicts = [_message_to_dict(m) for m in llm_messages]

    sanitizer = StreamSanitizer()
    full_response = ""

    if has_flow_tools:
        # Non-streaming path for tool calls
        response = await client.complete(
            msg_dicts,
            tools=conv.tools,
            temperature=conv.temperature,
            max_tokens=max(conv.max_tokens or 0, 500),
        )
        if response.content:
            full_response = response.content
            safe_chunk = sanitizer.feed(response.content)
            if safe_chunk and safe_chunk.strip():
                await event_callback({"event": "agent_token", "node_id": node_id, "text": safe_chunk})
        remaining = sanitizer.flush()
        if remaining and remaining.strip():
            await event_callback({"event": "agent_token", "node_id": node_id, "text": remaining})
    else:
        # Streaming path
        async for chunk in client.stream(
            msg_dicts,
            temperature=conv.temperature,
            max_tokens=max(conv.max_tokens or 0, 500),
        ):
            if chunk.content:
                full_response += chunk.content
                safe_chunk = sanitizer.feed(chunk.content)
                if safe_chunk and safe_chunk.strip():
                    await event_callback({"event": "agent_token", "node_id": node_id, "text": safe_chunk})
        remaining = sanitizer.flush()
        if remaining and remaining.strip():
            await event_callback({"event": "agent_token", "node_id": node_id, "text": remaining})

    return full_response


async def _call_openai(conv, llm_messages, node_id, event_callback) -> str:
    """Call OpenAI-compatible API via LLMClient and stream response."""
    from voice_platform.runtime.llm.factory import LLMFactory
    from voice_platform.runtime.llm.retry import RetryExecutor
    from voice_platform.runtime.llm.timeout import TimeoutExecutor
    from voice_platform.runtime.llm.types import RetryPolicy, TimeoutPolicy

    has_flow_tools = bool(conv.tools) and not getattr(conv, "_flow_mode", False)

    client = LLMFactory.create(
        "openai",
        api_key=conv.api_key,
        base_url=conv.base_url,
        model=conv.model,
        retry=RetryExecutor(RetryPolicy(max_retries=3, base_delay=1.0)),
        timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
    )

    # Convert message objects to dicts for the adapter
    msg_dicts = [_message_to_dict(m) for m in llm_messages]

    sanitizer = StreamSanitizer()
    full_response = ""

    async for chunk in client.stream(
        msg_dicts,
        tools=conv.tools if has_flow_tools else None,
        temperature=conv.temperature,
        max_tokens=max(conv.max_tokens or 0, 500),
    ):
        if chunk.content:
            full_response += chunk.content
            safe_chunk = sanitizer.feed(chunk.content)
            if safe_chunk and safe_chunk.strip():
                await event_callback({"event": "agent_token", "node_id": node_id, "text": safe_chunk})

    remaining = sanitizer.flush()
    if remaining and remaining.strip():
        await event_callback({"event": "agent_token", "node_id": node_id, "text": remaining})

    return full_response
