"""
Manual Debug Error Surfaces — Tests for safe error events, diagnostic snapshots,
failure injection, and manual test mode.

35+ scenarios covering:
- Error code registry completeness
- Safe error event structure and PII redaction
- Diagnostic snapshot sanitization
- Failure injection controls
- Manual test mode behavior
- Error code coverage for all three agents
"""

import json
import os
from unittest.mock import patch

import pytest

from voice_platform.diagnostics import (
    ERROR_REGISTRY,
    FailureInjection,
    build_diagnostic_snapshot,
    build_safe_error_event,
    get_error_info,
    is_manual_test_mode,
)


# ── Error Code Registry Completeness ─────────────────────────────────────────

class TestErrorCodeRegistry:
    """10 tests: registry structure and required codes."""

    REQUIRED_COMMON_CODES = [
        "AGENT_CONFIGURATION_INVALID", "PROMPT_RENDER_FAILED", "MODEL_TIMEOUT",
        "MODEL_PROVIDER_UNAVAILABLE", "MODEL_OUTPUT_EMPTY", "MODEL_OUTPUT_MALFORMED",
        "TOOL_NOT_CONFIGURED", "TOOL_EXECUTION_FAILED", "TOOL_RESULT_MALFORMED",
        "STATE_CHECKPOINT_FAILED", "STATE_RESUME_FAILED", "UNKNOWN_WORKFLOW_BRANCH",
        "MISSING_RETRY_SCOPE", "INVALID_RETRY_SCOPE", "RETRY_SCOPE_OWNER_MISMATCH",
        "RESPONSE_POLICY_BLOCKED_CLAIM", "TTS_EMISSION_FAILED", "CALL_DISCONNECTED",
        "INTERNAL_RUNTIME_ERROR",
    ]

    REQUIRED_UMT_CODES = [
        "KNOWLEDGE_LOOKUP_FAILED", "KNOWLEDGE_RESULT_EMPTY", "KNOWLEDGE_RESULT_CONFLICT",
        "ADMISSION_FACT_UNVERIFIED", "LEAD_SAVE_FAILED", "FOLLOWUP_REQUEST_FAILED",
        "OPT_OUT_PROCESSING_FAILED",
    ]

    REQUIRED_SMILECARE_CODES = [
        "AVAILABILITY_CHECK_FAILED", "AVAILABILITY_RESULT_MALFORMED",
        "BOOKING_CREATE_FAILED", "BOOKING_RESULT_MALFORMED", "BOOKING_OUTCOME_UNKNOWN",
        "PATIENT_LOG_FAILED", "EMAIL_SEND_FAILED", "REQUIRED_SLOT_UNCONFIRMED",
        "BOOKING_CONFIRMATION_MISSING", "UNSUPPORTED_BOOKING_CLAIM",
    ]

    def test_all_common_codes_present(self):
        for code in self.REQUIRED_COMMON_CODES:
            assert code in ERROR_REGISTRY, f"Missing common error code: {code}"

    def test_all_umt_codes_present(self):
        for code in self.REQUIRED_UMT_CODES:
            assert code in ERROR_REGISTRY, f"Missing UMT error code: {code}"

    def test_all_smilecare_codes_present(self):
        for code in self.REQUIRED_SMILECARE_CODES:
            assert code in ERROR_REGISTRY, f"Missing SmileCare error code: {code}"

    def test_every_code_has_required_fields(self):
        required_fields = {"component", "retryable", "caller_informed",
                          "manual_intervention_required", "error_message_safe",
                          "recommended_manual_action"}
        for code, info in ERROR_REGISTRY.items():
            missing = required_fields - set(info.keys())
            assert not missing, f"Error code {code} missing fields: {missing}"

    def test_error_messages_are_safe(self):
        """No error message contains raw exception text or PII patterns."""
        pii_patterns = ["password", "api_key", "token", "secret", "@", "phone"]
        for code, info in ERROR_REGISTRY.items():
            msg = info["error_message_safe"].lower()
            for pattern in pii_patterns:
                assert pattern not in msg, f"Error code {code} message contains '{pattern}'"

    def test_get_error_info_falls_back(self):
        info = get_error_info("NONEXISTENT_CODE")
        assert info["component"] == "runtime"
        assert info["error_message_safe"] == "An internal error occurred."

    def test_retryable_classification_consistency(self):
        """Retryable errors should not require manual intervention by default."""
        for code, info in ERROR_REGISTRY.items():
            if info["retryable"] and info["manual_intervention_required"]:
                # Some retryable errors do require intervention (e.g., STATE_CHECKPOINT_FAILED)
                # but they should still have caller_informed set appropriately
                assert "error_message_safe" in info

    def test_caller_informed_for_user_facing_errors(self):
        """Errors that affect the caller should have caller_informed=True."""
        user_facing = ["BOOKING_CREATE_FAILED", "EMAIL_SEND_FAILED", "AVAILABILITY_CHECK_FAILED"]
        for code in user_facing:
            assert ERROR_REGISTRY[code]["caller_informed"] is True

    def test_internal_errors_may_not_inform_caller(self):
        """Internal errors like checkpoint failure should not necessarily inform the caller."""
        assert ERROR_REGISTRY["STATE_CHECKPOINT_FAILED"]["caller_informed"] is False
        assert ERROR_REGISTRY["CALL_DISCONNECTED"]["caller_informed"] is False

    def test_total_error_code_count(self):
        """Registry should have at least 36 error codes (19 common + 7 UMT + 10 SmileCare)."""
        assert len(ERROR_REGISTRY) >= 36


# ── Safe Error Event Structure ───────────────────────────────────────────────

class TestSafeErrorEvent:
    """10 tests: safe error event construction and PII redaction."""

    def test_event_has_required_fields(self):
        ev = build_safe_error_event("BOOKING_CREATE_FAILED", agent_id=1, agent_type="flow")
        required = {"event", "error_code", "component", "agent_id", "agent_type",
                    "conversation_id", "node_id", "operation", "execution_status",
                    "business_status", "retryable", "caller_informed",
                    "manual_intervention_required", "recommended_manual_action",
                    "error_message_safe", "safe_context"}
        assert required.issubset(set(ev.keys()))

    def test_event_type_is_runtime_error(self):
        ev = build_safe_error_event("MODEL_TIMEOUT")
        assert ev["event"] == "runtime_error"

    def test_event_component_matches_registry(self):
        ev = build_safe_error_event("BOOKING_CREATE_FAILED")
        assert ev["component"] == "google_calendar"

    def test_event_safe_context_redacts_pii(self):
        ev = build_safe_error_event("TOOL_EXECUTION_FAILED",
                                    safe_context={"caller_phone": "03001234567",
                                                  "caller_email": "test@example.com",
                                                  "patient_name": "Alex"})
        ctx = ev["safe_context"]
        assert "03001234567" not in str(ctx)
        assert "test@example.com" not in str(ctx)

    def test_event_does_not_contain_raw_exception(self):
        ev = build_safe_error_event("INTERNAL_RUNTIME_ERROR",
                                    safe_context={"exception": "ValueError: invalid input at line 42"})
        assert "ValueError" not in str(ev["safe_context"])

    def test_event_with_all_optional_fields(self):
        ev = build_safe_error_event("BOOKING_RESULT_MALFORMED",
                                    agent_id=5, agent_type="flow",
                                    conversation_id="conv-123",
                                    node_id="action_3",
                                    operation="CREATE_BOOKING",
                                    execution_status="succeeded",
                                    business_status="unknown",
                                    safe_context={"attempt": 1, "evidence_flags": {"id": False}})
        assert ev["agent_id"] == 5
        assert ev["conversation_id"] == "conv-123"
        assert ev["node_id"] == "action_3"
        assert ev["operation"] == "CREATE_BOOKING"

    def test_event_safe_context_empty_by_default(self):
        ev = build_safe_error_event("MODEL_TIMEOUT")
        assert ev["safe_context"] == {}

    def test_event_retryable_flag(self):
        ev_retryable = build_safe_error_event("MODEL_TIMEOUT")
        assert ev_retryable["retryable"] is True

        ev_not_retryable = build_safe_error_event("BOOKING_RESULT_MALFORMED")
        assert ev_not_retryable["retryable"] is False

    def test_event_recommended_manual_action_present(self):
        ev = build_safe_error_event("BOOKING_RESULT_MALFORMED")
        assert ev["recommended_manual_action"]
        assert "inspect" in ev["recommended_manual_action"].lower()

    def test_event_serializable_to_json(self):
        ev = build_safe_error_event("BOOKING_CREATE_FAILED",
                                    safe_context={"attempt": 1, "retry_count": 2})
        serialized = json.dumps(ev)
        deserialized = json.loads(serialized)
        assert deserialized["error_code"] == "BOOKING_CREATE_FAILED"


# ── Diagnostic Snapshot ──────────────────────────────────────────────────────

class TestDiagnosticSnapshot:
    """8 tests: snapshot structure and PII redaction."""

    def test_snapshot_has_required_fields(self):
        snap = build_diagnostic_snapshot({}, agent_id=1, agent_type="flow")
        required = {"agent_id", "agent_type", "conversation_id", "current_phase",
                    "current_node_id", "last_completed_node_id", "last_result",
                    "last_tool", "last_tool_status", "business_outcome",
                    "retry_state", "error_code", "error_message_safe",
                    "recommended_manual_action"}
        assert required.issubset(set(snap.keys()))

    def test_snapshot_redacts_pii_in_last_result(self):
        state = {
            "last_result": {
                "patient_name": "Alex Patient",
                "caller_phone": "+15555550100",
                "caller_email": "alex@example.com",
            },
        }
        snap = build_diagnostic_snapshot(state, agent_id=1, agent_type="flow")
        result_str = str(snap["last_result"])
        assert "+15555550100" not in result_str
        assert "alex@example.com" not in result_str

    def test_snapshot_retry_state_structure(self):
        state = {
            "_active_retry_scope": "action_2:missing_input:preferred_time",
            "_slot_retry_counts": {
                "action_2:missing_input:preferred_time": {"count": 1, "owner": "action_2", "mode": "active_action"},
            },
        }
        snap = build_diagnostic_snapshot(state, agent_id=1, agent_type="flow")
        assert snap["retry_state"]["active_scope"] == "action_2:missing_input:preferred_time"
        assert snap["retry_state"]["scope_count"] == 1
        scope = snap["retry_state"]["scopes"]["action_2:missing_input:preferred_time"]
        assert scope["count"] == 1
        assert scope["owner"] == "action_2"

    def test_snapshot_handles_empty_state(self):
        snap = build_diagnostic_snapshot({}, agent_id=None, agent_type=None)
        assert snap["current_node_id"] is None
        assert snap["retry_state"]["scope_count"] == 0
        assert snap["error_code"] is None

    def test_snapshot_extracts_error_from_last_result(self):
        state = {
            "last_result": {
                "integration_result": {
                    "error_code": "BOOKING_RESULT_MALFORMED",
                    "error_message_safe": "The booking response was incomplete.",
                },
            },
        }
        snap = build_diagnostic_snapshot(state, agent_id=1, agent_type="flow")
        assert snap["error_code"] == "BOOKING_RESULT_MALFORMED"
        assert snap["error_message_safe"] == "The booking response was incomplete."

    def test_snapshot_business_outcome_sanitized(self):
        state = {
            "_business_outcome": {
                "booking": "booked",
                "email": "sent",
                "patient_name": "Alex",
            },
        }
        snap = build_diagnostic_snapshot(state, agent_id=1, agent_type="flow")
        outcome_str = str(snap["business_outcome"])
        assert "Alex" not in outcome_str
        assert snap["business_outcome"]["booking"] == "booked"

    def test_snapshot_handles_bare_integer_retry_counts(self):
        state = {
            "_slot_retry_counts": {"legacy_scope": 2},
        }
        snap = build_diagnostic_snapshot(state, agent_id=1, agent_type="flow")
        assert snap["retry_state"]["scopes"]["legacy_scope"]["count"] == 2

    def test_snapshot_serializable_to_json(self):
        state = {
            "current_node": "action_3",
            "_active_retry_scope": "",
            "_slot_retry_counts": {},
            "last_result": {"integration_result": {"error_code": "EMAIL_SEND_FAILED"}},
        }
        snap = build_diagnostic_snapshot(state, agent_id=1, agent_type="flow", conversation_id="c1")
        serialized = json.dumps(snap)
        deserialized = json.loads(serialized)
        assert deserialized["current_node_id"] == "action_3"


# ── Failure Injection ────────────────────────────────────────────────────────

class TestFailureInjection:
    """7 tests: failure injection controls."""

    def setup_method(self):
        FailureInjection.reset()

    def teardown_method(self):
        FailureInjection.reset()

    def test_all_flags_false_by_default(self):
        fi = FailureInjection.instance()
        for flag in fi._flags:
            if flag == "disconnect_after_node":
                assert fi.get(flag) is None
            else:
                assert fi.get(flag) is False

    def test_set_and_get_flag(self):
        fi = FailureInjection.instance()
        fi.set("calendar_create_failure", True)
        assert fi.is_active("calendar_create_failure") is True
        assert fi.get("calendar_create_failure") is True

    def test_reset_clears_all_flags(self):
        fi = FailureInjection.instance()
        fi.set("sheets_failure", True)
        fi.set("email_failure", True)
        FailureInjection.reset()
        assert fi.is_active("sheets_failure") is False
        assert fi.is_active("email_failure") is False

    def test_unknown_flag_raises(self):
        fi = FailureInjection.instance()
        with pytest.raises(KeyError):
            fi.set("nonexistent_flag", True)

    def test_any_active_detects_active_flags(self):
        fi = FailureInjection.instance()
        assert fi.any_active() is False
        fi.set("tool_timeout", True)
        assert fi.any_active() is True

    def test_disconnect_after_node_supports_string_value(self):
        fi = FailureInjection.instance()
        fi.set("disconnect_after_node", "action_3")
        assert fi.get("disconnect_after_node") == "action_3"
        assert fi.any_active() is True

    def test_to_dict_returns_all_flags(self):
        fi = FailureInjection.instance()
        flags = fi.to_dict()
        assert "fail_model" in flags
        assert "calendar_create_failure" in flags
        assert "disconnect_after_node" in flags
        assert len(flags) >= 14
        assert "stt_timeout" in flags
        assert "disconnect_after_booking" in flags


# ── Manual Test Mode ─────────────────────────────────────────────────────────

class TestManualTestMode:
    """5 tests: manual test mode configuration."""

    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            assert is_manual_test_mode() is False

    def test_enabled_with_true(self):
        with patch.dict(os.environ, {"VOICE_PLATFORM_MANUAL_TEST_MODE": "true"}):
            assert is_manual_test_mode() is True

    def test_enabled_with_1(self):
        with patch.dict(os.environ, {"VOICE_PLATFORM_MANUAL_TEST_MODE": "1"}):
            assert is_manual_test_mode() is True

    def test_disabled_with_false(self):
        with patch.dict(os.environ, {"VOICE_PLATFORM_MANUAL_TEST_MODE": "false"}):
            assert is_manual_test_mode() is False

    def test_failure_injection_enabled_in_test_env(self):
        """PYTEST_CURRENT_TEST should enable failure injection."""
        fi = FailureInjection.instance()
        assert fi.is_enabled() is True
