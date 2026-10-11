"""
Voice Platform — Diagnostics, Safe Error Events, and Manual Test Mode.

Provides:
- ERROR_REGISTRY: stable error codes with safe messages, component, retryable, etc.
- build_safe_error_event(): structured runtime_error event for developer visibility.
- build_runtime_identity(): sanitized per-session/call identity for logs and events.
- build_diagnostic_snapshot(): sanitized runtime state snapshot for manual testing.
- FailureInjection: controlled test-only failure injection at adapter boundaries.
- is_manual_test_mode(): checks VOICE_PLATFORM_MANUAL_TEST_MODE env var.

All diagnostic output is sanitized — no raw PII, credentials, provider payloads,
or exception strings are exposed.
"""

import hashlib
import json
import os
import uuid
from typing import Any, Dict, Optional

from voice_platform.flow.nodes import _redact_diagnostic_value
from voice_platform.graph_contracts import canonical_content_hash

# ── Error Code Registry ──────────────────────────────────────────────────────

ERROR_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ── Common ────────────────────────────────────────────────────────────────
    "AGENT_CONFIGURATION_INVALID": {
        "component": "agent_config",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The agent configuration is invalid.",
        "recommended_manual_action": "Check agent template, prompt, and tool bindings.",
    },
    "PROMPT_RENDER_FAILED": {
        "component": "prompt_renderer",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The agent could not prepare its response.",
        "recommended_manual_action": "Inspect prompt template for unresolved variables.",
    },
    "MODEL_TIMEOUT": {
        "component": "llm_provider",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The AI model took too long to respond.",
        "recommended_manual_action": "Check provider status and retry.",
    },
    "MODEL_PROVIDER_UNAVAILABLE": {
        "component": "llm_provider",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The AI service is temporarily unavailable.",
        "recommended_manual_action": "Check provider API status.",
    },
    "MODEL_OUTPUT_EMPTY": {
        "component": "llm_provider",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The AI model returned an empty response.",
        "recommended_manual_action": "Retry or check model configuration.",
    },
    "MODEL_OUTPUT_MALFORMED": {
        "component": "llm_provider",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The AI model returned an unexpected format.",
        "recommended_manual_action": "Inspect raw model output and parsing logic.",
    },
    "TOOL_NOT_CONFIGURED": {
        "component": "tool_registry",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The required tool is not configured.",
        "recommended_manual_action": "Check agent tool bindings and integration setup.",
    },
    "TOOL_EXECUTION_FAILED": {
        "component": "tool_executor",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The tool execution failed.",
        "recommended_manual_action": "Check integration credentials and retry.",
    },
    "TOOL_RESULT_MALFORMED": {
        "component": "tool_executor",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The tool returned an incomplete result.",
        "recommended_manual_action": "Inspect the sanitized integration trace.",
    },
    "STATE_CHECKPOINT_FAILED": {
        "component": "checkpointer",
        "retryable": True,
        "caller_informed": False,
        "manual_intervention_required": True,
        "error_message_safe": "The conversation state could not be saved.",
        "recommended_manual_action": "Check database connectivity.",
    },
    "STATE_RESUME_FAILED": {
        "component": "checkpointer",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The conversation could not be resumed.",
        "recommended_manual_action": "Check checkpoint integrity and thread ID.",
    },
    "UNKNOWN_WORKFLOW_BRANCH": {
        "component": "flow_router",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The workflow reached an unknown branch.",
        "recommended_manual_action": "Inspect graph edges and branch labels.",
    },
    "MISSING_RETRY_SCOPE": {
        "component": "retry_scope",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The retry scope was not found.",
        "recommended_manual_action": "Check condition retry_mode and retry_scope config.",
    },
    "INVALID_RETRY_SCOPE": {
        "component": "retry_scope",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The retry scope is invalid.",
        "recommended_manual_action": "Verify scope key exists in _slot_retry_counts.",
    },
    "RETRY_SCOPE_OWNER_MISMATCH": {
        "component": "retry_scope",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The retry scope ownership does not match.",
        "recommended_manual_action": "Verify retry_owner matches scope record owner.",
    },
    "RESPONSE_POLICY_BLOCKED_CLAIM": {
        "component": "claim_policy",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The response contained an unsupported claim.",
        "recommended_manual_action": "Review claim check and business outcome.",
    },
    "TTS_EMISSION_FAILED": {
        "component": "tts_provider",
        "retryable": True,
        "caller_informed": False,
        "manual_intervention_required": True,
        "error_message_safe": "The text-to-speech service failed.",
        "recommended_manual_action": "Check TTS provider status.",
    },
    "TTS_PROVIDER_UNAVAILABLE": {
        "component": "tts_provider",
        "retryable": True,
        "caller_informed": False,
        "manual_intervention_required": True,
        "error_message_safe": "The text-to-speech provider is unavailable.",
        "recommended_manual_action": "Check TTS credentials and provider status.",
    },
    "TTS_CANCEL_FAILED": {
        "component": "tts_provider",
        "retryable": False,
        "caller_informed": False,
        "manual_intervention_required": False,
        "error_message_safe": "Active speech playback could not be cancelled cleanly.",
        "recommended_manual_action": "Inspect interruption handling and TTS cancel path.",
    },
    "STALE_TTS_RESPONSE_DROPPED": {
        "component": "tts_provider",
        "retryable": False,
        "caller_informed": False,
        "manual_intervention_required": False,
        "error_message_safe": "A stale TTS response was dropped.",
        "recommended_manual_action": "Confirm turn IDs and interruption timing.",
    },
    "STT_TIMEOUT": {
        "component": "stt_provider",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "Speech recognition timed out.",
        "recommended_manual_action": "Check STT provider status and network.",
    },
    "STT_EMPTY_FINAL": {
        "component": "stt_provider",
        "retryable": False,
        "caller_informed": False,
        "manual_intervention_required": False,
        "error_message_safe": "Speech recognition returned an empty final transcript.",
        "recommended_manual_action": "Retry the utterance or check microphone/audio quality.",
    },
    "STT_PROVIDER_UNAVAILABLE": {
        "component": "stt_provider",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "Speech recognition is temporarily unavailable.",
        "recommended_manual_action": "Check STT credentials and provider status.",
    },
    "STT_STREAM_DISCONNECTED": {
        "component": "stt_provider",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The speech recognition stream disconnected.",
        "recommended_manual_action": "Inspect media stream and STT websocket logs.",
    },
    "DUPLICATE_FINAL_TRANSCRIPT": {
        "component": "stt_provider",
        "retryable": False,
        "caller_informed": False,
        "manual_intervention_required": False,
        "error_message_safe": "A duplicate final transcript was ignored.",
        "recommended_manual_action": "Confirm dedupe keys and provider finalization settings.",
    },
    "PHONE_AGENT_NOT_ASSIGNED": {
        "component": "telephony_routing",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "No agent is assigned to this inbound number.",
        "recommended_manual_action": "Assign an active agent in Number mappings.",
    },
    "PHONE_AGENT_NOT_FOUND": {
        "component": "telephony_routing",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The assigned agent could not be found.",
        "recommended_manual_action": "Update the number mapping to a valid agent ID.",
    },
    "PHONE_AGENT_DISABLED": {
        "component": "telephony_routing",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The assigned agent is disabled.",
        "recommended_manual_action": "Re-enable the agent or remap the inbound number.",
    },
    "PHONE_AGENT_MODE_UNSUPPORTED": {
        "component": "telephony_routing",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The assigned agent mode is not supported for telephony.",
        "recommended_manual_action": "Use single_prompt or conversational_flow mode.",
    },
    "PHONE_AGENT_CONFIG_INVALID": {
        "component": "telephony_routing",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The assigned agent configuration is invalid for telephony.",
        "recommended_manual_action": "Verify prompt/graph, providers, and tool bindings.",
    },
    "CALL_DISCONNECTED": {
        "component": "telephony",
        "retryable": False,
        "caller_informed": False,
        "manual_intervention_required": False,
        "error_message_safe": "The call was disconnected.",
        "recommended_manual_action": "No action needed unless recurring.",
    },
    "INTERNAL_RUNTIME_ERROR": {
        "component": "runtime",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "An internal error occurred.",
        "recommended_manual_action": "Check server logs for details.",
    },
    # ── UMT ───────────────────────────────────────────────────────────────────
    "KNOWLEDGE_LOOKUP_FAILED": {
        "component": "knowledge_base",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The knowledge lookup failed.",
        "recommended_manual_action": "Check knowledge base configuration.",
    },
    "KNOWLEDGE_RESULT_EMPTY": {
        "component": "knowledge_base",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "No knowledge base results were found.",
        "recommended_manual_action": "Verify KB content covers the query topic.",
    },
    "KNOWLEDGE_RESULT_CONFLICT": {
        "component": "knowledge_base",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The knowledge base returned conflicting information.",
        "recommended_manual_action": "Review conflicting KB chunks.",
    },
    "ADMISSION_FACT_UNVERIFIED": {
        "component": "knowledge_base",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The admission information is not verified.",
        "recommended_manual_action": "Update knowledge base with current data.",
    },
    "LEAD_SAVE_FAILED": {
        "component": "google_sheets",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The lead could not be saved.",
        "recommended_manual_action": "Check Sheets integration and retry.",
    },
    "FOLLOWUP_REQUEST_FAILED": {
        "component": "tool_executor",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The follow-up request could not be completed.",
        "recommended_manual_action": "Check integration status.",
    },
    "OPT_OUT_PROCESSING_FAILED": {
        "component": "tool_executor",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The opt-out request could not be processed.",
        "recommended_manual_action": "Manually verify opt-out was recorded.",
    },
    # ── SmileCare ─────────────────────────────────────────────────────────────
    "AVAILABILITY_CHECK_FAILED": {
        "component": "google_calendar",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The calendar availability check failed.",
        "recommended_manual_action": "Check Calendar integration credentials.",
    },
    "AVAILABILITY_RESULT_MALFORMED": {
        "component": "google_calendar",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The availability response was incomplete.",
        "recommended_manual_action": "Inspect calendar provider output format.",
    },
    "BOOKING_CREATE_FAILED": {
        "component": "google_calendar",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The booking could not be created.",
        "recommended_manual_action": "Check Calendar integration and retry.",
    },
    "BOOKING_RESULT_MALFORMED": {
        "component": "google_calendar",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The booking response was incomplete.",
        "recommended_manual_action": "Inspect the sanitized integration trace and verify the provider event ID.",
    },
    "BOOKING_OUTCOME_UNKNOWN": {
        "component": "google_calendar",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": True,
        "error_message_safe": "The booking outcome is unknown.",
        "recommended_manual_action": "Verify whether the event was created in the provider.",
    },
    "PATIENT_LOG_FAILED": {
        "component": "google_sheets",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The patient record could not be saved.",
        "recommended_manual_action": "Check Sheets integration and retry.",
    },
    "EMAIL_SEND_FAILED": {
        "component": "email_provider",
        "retryable": True,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The confirmation email could not be sent.",
        "recommended_manual_action": "Check email integration and retry.",
    },
    "REQUIRED_SLOT_UNCONFIRMED": {
        "component": "slot_validator",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "Required information is still missing.",
        "recommended_manual_action": "Check slot validation and retry scope.",
    },
    "BOOKING_CONFIRMATION_MISSING": {
        "component": "claim_policy",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The booking was not confirmed by the caller.",
        "recommended_manual_action": "No action needed — caller declined or was ambiguous.",
    },
    "UNSUPPORTED_BOOKING_CLAIM": {
        "component": "claim_policy",
        "retryable": False,
        "caller_informed": True,
        "manual_intervention_required": False,
        "error_message_safe": "The response contained an unsupported booking claim.",
        "recommended_manual_action": "Review claim check and business outcome.",
    },
}


def get_error_info(error_code: str) -> Dict[str, Any]:
    """Look up error metadata from the registry. Falls back to INTERNAL_RUNTIME_ERROR."""
    return ERROR_REGISTRY.get(error_code, ERROR_REGISTRY["INTERNAL_RUNTIME_ERROR"])


# ── Runtime Identity ─────────────────────────────────────────────────────────

def _content_hash(value: Any) -> Optional[str]:
    """Return a short SHA-256 fingerprint. Never returns the raw content."""
    return canonical_content_hash(value)


def build_runtime_identity(
    *,
    agent_id: Any,
    agent_name: Optional[str] = None,
    agent_mode: Optional[str] = None,
    execution_channel: str,
    conversation_id: Optional[str] = None,
    call_id: Optional[str] = None,
    websocket_connection_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    prompt_version_or_hash: Optional[str] = None,
    prompt_preamble: Optional[str] = None,
    graph: Any = None,
    graph_hash: Optional[str] = None,
    executor_instance_id: Optional[str] = None,
    model_provider: Optional[str] = None,
    stt_provider: Optional[str] = None,
    tts_provider: Optional[str] = None,
    phone_number_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a sanitized runtime identity for one playground session or phone call.

    Generated once per session/call. Contains no PII, credentials, full prompt,
    full graph JSON, or raw transcript.
    """
    mode = agent_mode or "single_prompt"
    if mode not in ("single_prompt", "conversational_flow"):
        mode = "single_prompt"

    channel = execution_channel if execution_channel in ("playground", "telephony") else "playground"
    prompt_fp = prompt_version_or_hash or _content_hash(prompt_preamble)
    graph_fp = graph_hash or _content_hash(graph)

    return {
        "agent_id": str(agent_id) if agent_id is not None else None,
        "agent_name": agent_name,
        "agent_mode": mode,
        "execution_channel": channel,
        "conversation_id": conversation_id,
        "call_id": call_id,
        "websocket_connection_id": websocket_connection_id,
        "thread_id": thread_id,
        "prompt_version_or_hash": prompt_fp,
        "graph_hash": graph_fp,
        "executor_instance_id": executor_instance_id or str(uuid.uuid4()),
        "model_provider": model_provider,
        "stt_provider": stt_provider,
        "tts_provider": tts_provider,
        "phone_number_id": str(phone_number_id) if phone_number_id is not None else None,
    }


# ── Safe Error Event Builder ─────────────────────────────────────────────────

def build_safe_error_event(
    error_code: str,
    agent_id: Optional[str] = None,
    agent_type: Optional[str] = None,
    conversation_id: Optional[str] = None,
    node_id: Optional[str] = None,
    operation: Optional[str] = None,
    execution_status: Optional[str] = None,
    business_status: Optional[str] = None,
    safe_context: Optional[Dict[str, Any]] = None,
    execution_channel: Optional[str] = None,
    call_id: Optional[str] = None,
    tool: Optional[str] = None,
    side_effect_attempted: bool = False,
    side_effect_may_have_succeeded: bool = False,
    caller_informed: Optional[bool] = None,
    manual_action_required: Optional[bool] = None,
) -> Dict[str, Any]:
    """Build a sanitized runtime_error event for developer/manual-testing visibility.

    The event contains no raw user data, provider responses, or exception strings.
    """
    info = get_error_info(error_code)
    intervention = info["manual_intervention_required"]
    event = {
        "event": "runtime_error",
        "error_code": error_code,
        "component": info["component"],
        "agent_id": agent_id,
        "agent_type": agent_type,
        "execution_channel": execution_channel,
        "conversation_id": conversation_id,
        "call_id": call_id,
        "node_id": node_id,
        "tool": tool,
        "operation": operation,
        "execution_status": execution_status,
        "business_status": business_status,
        "side_effect_attempted": side_effect_attempted,
        "side_effect_may_have_succeeded": side_effect_may_have_succeeded,
        "retryable": info["retryable"],
        "caller_informed": info["caller_informed"] if caller_informed is None else caller_informed,
        "manual_intervention_required": intervention,
        "manual_action_required": intervention if manual_action_required is None else manual_action_required,
        "recommended_manual_action": info["recommended_manual_action"],
        "error_message_safe": info["error_message_safe"],
        "safe_context": _redact_diagnostic_value(safe_context or {}),
    }
    return event


# ── Diagnostic Snapshot ──────────────────────────────────────────────────────

def build_diagnostic_snapshot(
    state: Dict[str, Any],
    agent_id: Optional[str] = None,
    agent_type: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a sanitized runtime diagnostic snapshot for developer visibility.

    Excludes: raw caller names, phone numbers, emails, transcripts, complete prompts,
    credentials, provider payloads, calendar descriptions, Sheets row data, raw exceptions.
    """
    last_result = state.get("last_result") or {}
    retry_counts = state.get("_slot_retry_counts") or {}
    active_scope = state.get("_active_retry_scope") or ""

    # Sanitize retry state — expose only fingerprints and counts, not raw scope keys
    sanitized_retry_counts = {}
    for scope_key, record in retry_counts.items():
        if isinstance(record, dict):
            sanitized_retry_counts[scope_key] = {
                "count": record.get("count", 0),
                "owner": record.get("owner", ""),
                "mode": record.get("mode", ""),
            }
        else:
            sanitized_retry_counts[scope_key] = {"count": record, "owner": "", "mode": ""}

    # Sanitize last_result — redact PII (phone, email, secrets, exceptions)
    sanitized_last_result = _redact_diagnostic_value(last_result)
    # Additionally redact name fields — _redact_diagnostic_value doesn't redact
    # names by design (existing tests rely on that), so we do it here for snapshots
    _NAME_FIELDS = ("patient_name", "caller_name", "prospect_name", "guest_name",
                    "student_name", "user_name", "name")
    if isinstance(sanitized_last_result, dict):
        for field in _NAME_FIELDS:
            if field in sanitized_last_result and sanitized_last_result[field]:
                sanitized_last_result[field] = "[NAME]"

    # Extract safe business outcome
    business_outcome = state.get("_business_outcome")
    sanitized_business_outcome = _redact_diagnostic_value(business_outcome) if business_outcome else None
    if isinstance(sanitized_business_outcome, dict):
        for field in _NAME_FIELDS:
            if field in sanitized_business_outcome and sanitized_business_outcome[field]:
                sanitized_business_outcome[field] = "[NAME]"

    # Error info from state
    error_code = last_result.get("integration_result", {}).get("error_code") if isinstance(last_result, dict) else None
    error_message_safe = last_result.get("integration_result", {}).get("error_message_safe") if isinstance(last_result, dict) else None

    snapshot = {
        "agent_id": agent_id,
        "agent_type": agent_type,
        "conversation_id": conversation_id,
        "current_phase": state.get("current_phase"),
        "current_node_id": state.get("current_node"),
        "last_completed_node_id": state.get("_last_completed_node"),
        "last_result": sanitized_last_result,
        "last_tool": state.get("_last_tool"),
        "last_tool_status": state.get("_last_tool_status"),
        "business_outcome": sanitized_business_outcome,
        "retry_state": {
            "active_scope": active_scope,
            "scope_count": len(sanitized_retry_counts),
            "scopes": sanitized_retry_counts,
        },
        "error_code": error_code,
        "error_message_safe": error_message_safe,
        "recommended_manual_action": get_error_info(error_code)["recommended_manual_action"] if error_code else None,
    }
    return snapshot


# ── Manual Test Mode ─────────────────────────────────────────────────────────

def is_manual_test_mode() -> bool:
    """Check if VOICE_PLATFORM_MANUAL_TEST_MODE is enabled.

    This mode exposes sanitized debug events through the developer console,
    WebSocket event stream, or test response payload.

    It must NOT:
    - alter routing;
    - alter prompts;
    - force tool success;
    - bypass validation;
    - expose credentials;
    - expose raw PII;
    - swallow exceptions;
    - be enabled by default.
    """
    return os.environ.get("VOICE_PLATFORM_MANUAL_TEST_MODE", "").lower() in ("true", "1", "yes")


# ── Failure Injection ────────────────────────────────────────────────────────

class FailureInjection:
    """Controlled test-only failure injection at adapter boundaries.

    Available only in tests or manual local mode.
    Impossible to enable accidentally in production.
    Visible in diagnostics when active.
    Does not alter unrelated integrations.
    Deterministic and reset between tests.
    """

    _instance: Optional["FailureInjection"] = None

    _DEFAULT_FLAGS: Dict[str, Any] = {
        "fail_model": False,
        "model_timeout": False,
        "model_malformed": False,
        "knowledge_empty": False,
        "knowledge_conflict": False,
        "knowledge_timeout": False,
        "tool_timeout": False,
        "tool_malformed_result": False,
        "lead_save_failure": False,
        "followup_failure": False,
        "calendar_unavailable": False,
        "calendar_create_failure": False,
        "calendar_create_missing_id": False,
        "patient_lookup_failure": False,
        "sheets_missing_tab": False,
        "sheets_failure": False,
        "email_failure": False,
        "checkpoint_failure": False,
        "checkpoint_resume_failure": False,
        "stt_timeout": False,
        "stt_empty_final": False,
        "stt_duplicate_final": False,
        "tts_failure": False,
        "provider_disconnect": False,
        "duplicate_completion_callback": False,
        "disconnect_after_node": None,
        "disconnect_after_booking": False,
    }

    def __init__(self):
        self._flags: Dict[str, Any] = dict(self._DEFAULT_FLAGS)

    @classmethod
    def instance(cls) -> "FailureInjection":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset all failure flags — call in test teardown."""
        if cls._instance is not None:
            cls._instance._flags = dict(cls._DEFAULT_FLAGS)

    def set(self, flag: str, value: Any = True) -> None:
        """Set a failure injection flag."""
        if flag in self._flags:
            self._flags[flag] = value
        else:
            raise KeyError(f"Unknown failure injection flag: {flag}")

    def get(self, flag: str) -> Any:
        """Get a failure injection flag value."""
        return self._flags.get(flag, False)

    def is_active(self, flag: str) -> bool:
        """Check if a failure injection flag is active."""
        return bool(self._flags.get(flag, False))

    def any_active(self) -> bool:
        """Check if any failure injection is active."""
        return any(v for k, v in self._flags.items() if k != "disconnect_after_node") or \
               self._flags.get("disconnect_after_node") is not None

    def to_dict(self) -> Dict[str, Any]:
        """Return all flags for diagnostics."""
        return dict(self._flags)

    def is_enabled(self) -> bool:
        """Check if failure injection is allowed in the current environment."""
        return is_manual_test_mode() or os.environ.get("PYTEST_CURRENT_TEST") is not None
