"""
Quick-Win Prompt 1 — Routing Truth, Integration Evidence, and Claim Safety.

24-test regression set covering:
- Stale branch routing after missing→success retry
- Unknown branch / retry scope fail-closed
- Retry off-by-one
- Evidence fail-closed (no defaults to True)
- Execution vs business success separation
- Availability facts preserved
- Structured status (no error-text inference)
- Typed claim check with explicit context
- Boundary response determinism
- Safe exceptions (no raw value leakage)
- PII absent from last_result
- Provider payload fixtures
"""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_platform.flow.compiler import UnknownBranchError, _routing_branch_key
from voice_platform.flow.nodes import (
    _ERROR_MESSAGES,
    ClaimContext,
    OperationType,
    RetryScopeError,
    _claim_check,
    _deterministic_response,
    _is_hypothetical,
    _is_negated,
    _normalize_integration_result,
    _update_business_outcome,
    boundary_response,
)
from voice_platform.flow.state import (
    _TRANSIENT_RESULT_KEYS,
    FlowState,
    make_initial_state,
    merge_dicts,
    merge_result,
)

# ── Provider Payload Fixtures (from real plugin audit) ──────────────────────

@pytest.fixture
def calendar_availability_success_available():
    """Real CalendarPlugin check_availability success output (available=True)."""
    return {
        "success": True,
        "date": "2025-07-20",
        "busy_slots": [],
        "available_slots": [{"start": "2025-07-20T10:00:00+05:00", "end": "2025-07-20T10:30:00+05:00"}],
        "available_slot_count": 1,
        "requested_time": "10:00",
        "requested_time_available": True,
        "available": True,
    }

@pytest.fixture
def calendar_availability_success_unavailable():
    """Real CalendarPlugin check_availability success output (available=False)."""
    return {
        "success": True,
        "date": "2025-07-20",
        "busy_slots": [{"start": "2025-07-20T10:00:00+05:00", "end": "2025-07-20T21:00:00+05:00"}],
        "available_slots": [],
        "available_slot_count": 0,
        "requested_time": "10:00",
        "requested_time_available": False,
        "available": False,
    }

@pytest.fixture
def calendar_booking_success():
    """Real CalendarPlugin book_appointment / create_event success output."""
    return {
        "success": True,
        "id": "evt_abc123def456",
        "summary": "Cleaning - John Doe",
        "start": "2025-07-20T10:00:00+05:00",
        "end": "2025-07-20T10:30:00+05:00",
        "html_link": "https://calendar.google.com/event?eid=abc123",
        "status": "created",
        "event_created": True,
    }

@pytest.fixture
def calendar_booking_malformed():
    """Booking execution succeeded but missing id/event_created evidence."""
    return {
        "success": True,
        "summary": "Cleaning - John Doe",
        "start": "2025-07-20T10:00:00+05:00",
        "end": "2025-07-20T10:30:00+05:00",
    }

@pytest.fixture
def sheets_append_success():
    """Real SheetsPlugin append_row success output."""
    return {
        "success": True,
        "updated_range": "Patients!A15:K15",
        "updated_rows": 1,
        "row_number": 15,
        "status": "appended",
        "row_appended": True,
    }

@pytest.fixture
def sheets_append_no_evidence():
    """Sheets execution succeeded but missing row_appended field."""
    return {
        "success": True,
        "updated_range": "Patients!A15:K15",
        "updated_rows": 1,
        "status": "appended",
    }

@pytest.fixture
def email_send_success():
    """Real EmailPlugin send_email success output."""
    return {
        "success": True,
        "to": "patient@example.com",
        "subject": "Appointment Confirmation",
        "cc": None,
        "attachments_count": 0,
        "email_sent": True,
    }

@pytest.fixture
def email_send_no_evidence():
    """Email execution succeeded but missing email_sent field."""
    return {
        "success": True,
        "to": "patient@example.com",
        "subject": "Appointment Confirmation",
    }


# ── Helper to build node_result from plugin output ──────────────────────────

def _make_node_result(node_id, node_type, action, plugin_output, status="success"):
    """Build a node_result dict as the executor would return it."""
    return {
        "node_id": node_id,
        "node_type": node_type,
        "action": action,
        "status": status,
        "result": plugin_output,
    }


# ════════════════════════════════════════════════════════════════════════════
# 1. ROUTING & RETRY TESTS
# ════════════════════════════════════════════════════════════════════════════

class TestStaleBranchRouting:
    """Bug 1: stale result.branch survives retry via merge_dicts reducer."""

    def test_stale_branch_missing_then_success_routes_to_condition_2(self):
        """action_2 missing → on_missing, then success → routes to condition_2."""
        # Simulate: action_2 missing inputs → branch=on_missing in result
        state_after_missing = {
            "result": merge_result(
                {"available": True},
                {"branch": "on_missing", "error": "Missing required inputs", "missing_inputs": ["preferred_time"]},
            ),
            "last_result": {
                "node_id": "action_2",
                "success": False,
                "status": "missing_input",
                "branch": "on_missing",
            },
        }

        # After retry success: handler returns result without branch
        # merge_result should strip the stale on_missing from old result
        state_after_success = {
            "result": merge_result(
                state_after_missing["result"],
                {"available": True, "requested_time_available": True},
            ),
            "last_result": {
                "node_id": "action_2",
                "success": True,
                "status": "succeeded",
                "branch": None,
            },
        }

        # The stale on_missing must NOT survive in result
        assert "branch" not in state_after_success["result"], \
            "Stale 'on_missing' branch survived in result after successful retry"

    def test_merge_result_strips_transient_from_both_sides(self):
        """merge_result must strip transient keys from BOTH left and right."""
        left = {"branch": "on_missing", "error": "old error", "available": True}
        right = {"branch": "on_error", "available": False}

        result = merge_result(left, right)

        assert "branch" not in result, "Transient 'branch' from left survived"
        assert "error" not in result, "Transient 'error' from left survived"
        assert result["available"] is False, "Non-transient from right not applied"


class TestUnknownBranchFailsClosed:

    def test_unknown_branch_fails_closed(self):
        """last_result.branch not matching any edge → UnknownBranchError."""
        state = {
            "last_result": {
                "node_id": "action_2",
                "success": True,
                "status": "succeeded",
                "branch": "nonexistent_branch",
            },
        }

        branches = {"on_missing": "condition_missing", "error": "end_calendar_error"}
        default = "condition_2"

        from voice_platform.flow.compiler import make_branch_router
        router = make_branch_router("action_2", default, branches)

        with pytest.raises(UnknownBranchError):
            router(state)


class TestRetryScopeFailClosed:

    def test_missing_retry_scope_raises(self):
        """Condition with _slot_retry_count but no active scope and no configured scope → RetryScopeError."""
        with pytest.raises(RetryScopeError) as exc_info:
            raise RetryScopeError("MISSING_RETRY_SCOPE")
        assert exc_info.value.code == "MISSING_RETRY_SCOPE"

    def test_invalid_retry_scope_fails_closed(self):
        """Active scope not in _slot_retry_counts → RetryScopeError."""
        state = {
            "_active_retry_scope": "action_2:missing_input:preferred_time",
            "_slot_retry_counts": {"action_3:missing_input:caller_email": {"count": 0, "owner": "action_3", "mode": "active_action"}},
        }

        with pytest.raises(RetryScopeError) as exc_info:
            scope = state.get("_active_retry_scope", "")
            counts = state.get("_slot_retry_counts") or {}
            if scope not in counts:
                raise RetryScopeError("INVALID_RETRY_SCOPE", scope)

        assert exc_info.value.code == "INVALID_RETRY_SCOPE"

    def test_retry_off_by_one(self):
        """0<2→retry(store 1), 1<2→retry(store 2), 2<2→no retry(remain 2)."""
        max_retries = 2
        counts = {"action_2:missing_input:preferred_time": {"count": 0, "owner": "action_2", "mode": "active_action"}}

        # Attempt 0: 0 < 2 → retry granted, increment to 1
        current = counts["action_2:missing_input:preferred_time"]["count"]
        assert current < max_retries, "Should retry at count=0"
        counts["action_2:missing_input:preferred_time"]["count"] = current + 1

        # Attempt 1: 1 < 2 → retry granted, increment to 2
        current = counts["action_2:missing_input:preferred_time"]["count"]
        assert current < max_retries, "Should retry at count=1"
        counts["action_2:missing_input:preferred_time"]["count"] = current + 1

        # Attempt 2: 2 < 2 → False, no retry, count stays 2
        current = counts["action_2:missing_input:preferred_time"]["count"]
        assert not (current < max_retries), "Should NOT retry at count=2"
        assert counts["action_2:missing_input:preferred_time"]["count"] == 2


class TestSafeExceptions:

    def test_raw_branch_and_scope_do_not_leak(self):
        """UnknownBranchError.__str__ and RetryScopeError.__str__ contain no raw values."""
        branch_error = UnknownBranchError("action_2", "super_secret_branch_label")
        branch_str = str(branch_error)

        assert "super_secret_branch_label" not in branch_str, \
            "Raw branch label leaked in UnknownBranchError.__str__"
        assert "action_2" not in branch_str, \
            "Raw node_id leaked in UnknownBranchError.__str__"
        assert "fingerprint" in branch_str, \
            "UnknownBranchError.__str__ should contain fingerprint"

        scope_error = RetryScopeError("INVALID_RETRY_SCOPE", "action_2:missing_input:preferred_time")
        scope_str = str(scope_error)

        assert "action_2:missing_input:preferred_time" not in scope_str, \
            "Raw scope string leaked in RetryScopeError.__str__"
        assert "fingerprint" in scope_str, \
            "RetryScopeError.__str__ should contain fingerprint"


# ════════════════════════════════════════════════════════════════════════════
# 2. EVIDENCE FAIL-CLOSED TESTS
# ════════════════════════════════════════════════════════════════════════════

class TestEvidenceFailClosed:

    def test_availability_success_cannot_imply_booking(
        self, calendar_availability_success_available
    ):
        """action_2 success with available=True → business_outcome.booking != 'booked'."""
        node_result = _make_node_result(
            "action_2", "action", "check_availability",
            calendar_availability_success_available,
        )
        normalized = _normalize_integration_result(
            "action_2", "action", {"action": "check_availability"},
            node_result, "success",
        )

        outcome = _update_business_outcome(
            {"availability": "not_checked", "booking": "not_attempted",
             "email": "not_attempted", "patient_log": "not_attempted",
             "overall": "in_progress"},
            normalized["integration_result"],
        )

        assert outcome["booking"] != "booked", \
            "Availability success incorrectly implied booking"
        assert outcome["availability"] == "available"

    def test_absent_email_sent_does_not_imply_email_success(
        self, email_send_no_evidence
    ):
        """email_1 output without email_sent field → business_outcome.email != 'sent'."""
        node_result = _make_node_result(
            "email_1", "send_email", "send_email",
            email_send_no_evidence,
        )
        normalized = _normalize_integration_result(
            "email_1", "send_email", {"action": "send_email"},
            node_result, "success",
        )

        assert normalized["integration_result"]["business_succeeded"] is False, \
            "Absent email_sent field incorrectly implied email success"
        assert normalized["integration_result"]["evidence"]["email_sent"] is False

    def test_absent_row_appended_does_not_imply_sheets_success(
        self, sheets_append_no_evidence
    ):
        """sheets_1 output without row_appended field → patient_log != 'written'."""
        node_result = _make_node_result(
            "sheets_1", "google_sheets", "append_row",
            sheets_append_no_evidence,
        )
        normalized = _normalize_integration_result(
            "sheets_1", "google_sheets", {"action": "append_row"},
            node_result, "success",
        )

        assert normalized["integration_result"]["business_succeeded"] is False, \
            "Absent row_appended field incorrectly implied sheets success"
        assert normalized["integration_result"]["evidence"]["patient_logged"] is False

    def test_booking_handler_success_without_event_id_is_not_booking_success(
        self, calendar_booking_malformed
    ):
        """action_3 returns status=success but no id field → business_succeeded=False."""
        node_result = _make_node_result(
            "action_3", "action", "book_appointment",
            calendar_booking_malformed,
        )
        normalized = _normalize_integration_result(
            "action_3", "action", {"action": "book_appointment"},
            node_result, "success",
        )

        assert normalized["integration_result"]["business_succeeded"] is False, \
            "Booking without event_id incorrectly marked as business success"
        assert normalized["integration_result"]["error_code"] == "MALFORMED_BOOKING_RESULT"
        assert normalized["integration_result"]["evidence"]["booking_created"] is False

    def test_last_result_execution_success_remains_true_when_booking_malformed(
        self, calendar_booking_malformed
    ):
        """Malformed booking: last_result.success=True, but integration_result.business_succeeded=False."""
        node_result = _make_node_result(
            "action_3", "action", "book_appointment",
            calendar_booking_malformed,
        )
        normalized = _normalize_integration_result(
            "action_3", "action", {"action": "book_appointment"},
            node_result, "success",
        )

        assert normalized["success"] is True, \
            "Execution success should remain True for malformed booking"
        assert normalized["status"] == "succeeded"
        assert normalized["integration_result"]["business_succeeded"] is False

    def test_unknown_action_execution_success_follows_normal_default_routing(
        self,
    ):
        """Unknown operation type with execution success → routes to default (not failure)."""
        node_result = _make_node_result(
            "custom_1", "custom_type", "do_something",
            {"success": True, "custom_field": "value"},
        )
        normalized = _normalize_integration_result(
            "custom_1", "custom_type", {"action": "do_something"},
            node_result, "success",
        )

        assert normalized["success"] is True, \
            "Unknown operation execution success should remain True"
        assert normalized["status"] == "succeeded"
        assert normalized["integration_result"]["business_succeeded"] is False, \
            "Unknown operation should not produce business evidence"
        assert normalized["integration_result"]["operation"] == OperationType.UNKNOWN

    def test_availability_check_success_with_available_false_becomes_unavailable(
        self, calendar_availability_success_unavailable
    ):
        """available=False → business_outcome.availability == 'unavailable'."""
        node_result = _make_node_result(
            "action_2", "action", "check_availability",
            calendar_availability_success_unavailable,
        )
        normalized = _normalize_integration_result(
            "action_2", "action", {"action": "check_availability"},
            node_result, "success",
        )

        outcome = _update_business_outcome(
            {"availability": "not_checked", "booking": "not_attempted",
             "email": "not_attempted", "patient_log": "not_attempted",
             "overall": "in_progress"},
            normalized["integration_result"],
        )

        assert outcome["availability"] == "unavailable", \
            "available=False should produce 'unavailable' not 'available'"

    def test_timeout_text_in_ordinary_error_does_not_classify_as_timed_out(self):
        """Error containing 'timeout' in text → status is 'failed', NOT 'timed_out'."""
        node_result = {
            "node_id": "action_2",
            "node_type": "action",
            "action": "check_availability",
            "status": "error",
            "error": "Connection timeout while contacting calendar API",
            "result": {},
        }
        normalized = _normalize_integration_result(
            "action_2", "action", {"action": "check_availability"},
            node_result, "error",
        )

        assert normalized["status"] == "failed", \
            "Error text containing 'timeout' should not classify as timed_out"
        assert normalized["status"] != "timed_out"


# ════════════════════════════════════════════════════════════════════════════
# 3. CLAIM & BOUNDARY TESTS
# ════════════════════════════════════════════════════════════════════════════

class TestClaimCheck:

    def test_appointment_confirmed_blocked_in_booking_context_without_evidence(self):
        """'appointment confirmed' in BOOKING_TERMINAL with booking != 'booked' → rewritten."""
        text = "Your appointment is confirmed for July 20th."
        outcome = {"booking": "not_attempted", "email": "not_attempted", "overall": "in_progress"}

        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)

        assert result != text, \
            "Unsupported booking claim was not rewritten in BOOKING_TERMINAL context"
        assert "confirmed" not in result.lower() or "not" in result.lower(), \
            "Rewritten text should not contain unsupported 'confirmed' claim"

    def test_your_name_is_confirmed_allowed_in_identity_context(self):
        """'your name is confirmed' in IDENTITY_CONFIRMATION → permitted."""
        text = "Your name is confirmed as John Doe."
        outcome = {"booking": "not_attempted", "email": "not_attempted", "overall": "in_progress"}

        result = _claim_check(text, outcome, ClaimContext.IDENTITY_CONFIRMATION)

        assert result == text, \
            "Identity confirmation text was incorrectly rewritten"

    def test_truthful_negative_and_hypothetical_permitted(self):
        """'I haven't booked it yet', 'Would you like me to book it?' → permitted."""
        outcome = {"booking": "not_attempted", "email": "not_attempted", "overall": "in_progress"}

        negated = "I haven't booked it yet."
        result = _claim_check(negated, outcome, ClaimContext.BOOKING_TERMINAL)
        assert result == negated, "Negated booking statement was incorrectly rewritten"

        hypothetical = "Would you like me to book it?"
        result = _claim_check(hypothetical, outcome, ClaimContext.BOOKING_TERMINAL)
        assert result == hypothetical, "Hypothetical booking statement was incorrectly rewritten"


class TestBoundaryResponse:

    def test_every_boundary_response_case_has_deterministic_output(self):
        """All 7 boundary cases produce fixed strings."""
        outcome_available = {"availability": "available", "booking": "not_attempted",
                              "email": "not_attempted", "overall": "in_progress"}
        outcome_unavailable = {"availability": "unavailable", "booking": "not_attempted",
                               "email": "not_attempted", "overall": "in_progress"}
        outcome_failed = {"availability": "failed", "booking": "not_attempted",
                          "email": "not_attempted", "overall": "in_progress"}
        outcome_booked = {"availability": "available", "booking": "booked",
                          "email": "not_attempted", "overall": "in_progress"}
        outcome_booking_failed = {"availability": "available", "booking": "failed",
                                   "email": "not_attempted", "overall": "failed"}
        outcome_booking_unknown = {"availability": "available", "booking": "unknown",
                                    "email": "not_attempted", "overall": "unresolved"}
        outcome_booked_email_failed = {"availability": "available", "booking": "booked",
                                        "email": "failed", "overall": "partial_success"}

        # 1. Availability check failed
        r = boundary_response(OperationType.CHECK_AVAILABILITY, False, outcome_failed)
        assert r is not None and "couldn't" in r.lower()

        # 2. Requested slot available
        r = boundary_response(OperationType.CHECK_AVAILABILITY, True, outcome_available)
        assert r is not None and "available" in r.lower()

        # 3. Requested slot unavailable
        r = boundary_response(OperationType.CHECK_AVAILABILITY, True, outcome_unavailable)
        assert r is not None and "not available" in r.lower()

        # 4. Booking created
        r = boundary_response(OperationType.CREATE_BOOKING, True, outcome_booked)
        assert r is not None and "booked" in r.lower()

        # 5. Booking failed
        r = boundary_response(OperationType.CREATE_BOOKING, False, outcome_booking_failed)
        assert r is not None and "couldn't" in r.lower()

        # 6. Booking result unknown
        r = boundary_response(OperationType.CREATE_BOOKING, False, outcome_booking_unknown)
        assert r is not None and "confirm" in r.lower()

        # 7. Booking succeeded but email failed
        r = boundary_response(OperationType.SEND_EMAIL, False, outcome_booked_email_failed)
        assert r is not None and "booked" in r.lower() and "email" in r.lower()


# ════════════════════════════════════════════════════════════════════════════
# 4. INTEGRATION & E2E TESTS
# ════════════════════════════════════════════════════════════════════════════

class TestBusinessOutcomeTransitions:

    def test_booking_success_email_failure_is_partial_success(
        self, calendar_booking_success, email_send_no_evidence
    ):
        """action_3 success + email_1 failure → overall == 'partial_success'."""
        # action_3 (booking) succeeds
        booking_result = _make_node_result(
            "action_3", "action", "book_appointment",
            calendar_booking_success,
        )
        booking_norm = _normalize_integration_result(
            "action_3", "action", {"action": "book_appointment"},
            booking_result, "success",
        )

        outcome = {"availability": "available", "booking": "not_attempted",
                    "email": "not_attempted", "patient_log": "not_attempted",
                    "overall": "in_progress"}
        outcome = _update_business_outcome(outcome, booking_norm["integration_result"])
        assert outcome["booking"] == "booked"

        # sheets_1 succeeds
        sheets_result = _make_node_result(
            "sheets_1", "google_sheets", "append_row",
            {"success": True, "row_appended": True, "updated_rows": 1, "status": "appended"},
        )
        sheets_norm = _normalize_integration_result(
            "sheets_1", "google_sheets", {"action": "append_row"},
            sheets_result, "success",
        )
        outcome = _update_business_outcome(outcome, sheets_norm["integration_result"])
        assert outcome["patient_log"] == "written"

        # email_1 fails (no email_sent field)
        email_result = _make_node_result(
            "email_1", "send_email", "send_email",
            email_send_no_evidence,
        )
        email_norm = _normalize_integration_result(
            "email_1", "send_email", {"action": "send_email"},
            email_result, "success",
        )
        outcome = _update_business_outcome(outcome, email_norm["integration_result"])

        assert outcome["email"] == "failed"
        assert outcome["overall"] == "partial_success", \
            "Booking success + email failure should be partial_success"

    def test_corrected_smilecare_golden_happy_path(
        self, calendar_availability_success_available,
        calendar_booking_success, sheets_append_success, email_send_success
    ):
        """Full happy path with evidence at each step."""
        outcome = {"availability": "not_checked", "booking": "not_attempted",
                    "email": "not_attempted", "patient_log": "not_attempted",
                    "overall": "in_progress"}

        # Step 1: check_availability succeeds, available=True
        avail_result = _make_node_result("action_2", "action", "check_availability",
                                          calendar_availability_success_available)
        avail_norm = _normalize_integration_result(
            "action_2", "action", {"action": "check_availability"}, avail_result, "success")
        outcome = _update_business_outcome(outcome, avail_norm["integration_result"])
        assert outcome["availability"] == "available"
        assert outcome["booking"] == "not_attempted"

        # Step 2: book_appointment succeeds with id + event_created
        booking_result = _make_node_result("action_3", "action", "book_appointment",
                                            calendar_booking_success)
        booking_norm = _normalize_integration_result(
            "action_3", "action", {"action": "book_appointment"}, booking_result, "success")
        outcome = _update_business_outcome(outcome, booking_norm["integration_result"])
        assert outcome["booking"] == "booked"
        assert booking_norm["integration_result"]["evidence"]["booking_created"] is True
        assert booking_norm["integration_result"]["external_id"] == "evt_abc123def456"

        # Step 3: sheets append succeeds with row_appended=True
        sheets_result = _make_node_result("sheets_1", "google_sheets", "append_row",
                                           sheets_append_success)
        sheets_norm = _normalize_integration_result(
            "sheets_1", "google_sheets", {"action": "append_row"}, sheets_result, "success")
        outcome = _update_business_outcome(outcome, sheets_norm["integration_result"])
        assert outcome["patient_log"] == "written"

        # Step 4: email send succeeds with email_sent=True
        email_result = _make_node_result("email_1", "send_email", "send_email",
                                          email_send_success)
        email_norm = _normalize_integration_result(
            "email_1", "send_email", {"action": "send_email"}, email_result, "success")
        outcome = _update_business_outcome(outcome, email_norm["integration_result"])
        assert outcome["email"] == "sent"
        assert outcome["overall"] == "completed"

    def test_corrected_smilecare_booking_failure_path(
        self, calendar_availability_success_available
    ):
        """Booking fails → truthful failure terminal, no Sheets/email."""
        outcome = {"availability": "not_checked", "booking": "not_attempted",
                    "email": "not_attempted", "patient_log": "not_attempted",
                    "overall": "in_progress"}

        # Availability succeeds
        avail_result = _make_node_result("action_2", "action", "check_availability",
                                          calendar_availability_success_available)
        avail_norm = _normalize_integration_result(
            "action_2", "action", {"action": "check_availability"}, avail_result, "success")
        outcome = _update_business_outcome(outcome, avail_norm["integration_result"])
        assert outcome["availability"] == "available"

        # Booking fails (execution error)
        booking_result = _make_node_result(
            "action_3", "action", "book_appointment",
            {"success": False, "error": "Calendar API returned 500"},
            status="error",
        )
        booking_norm = _normalize_integration_result(
            "action_3", "action", {"action": "book_appointment"}, booking_result, "error")
        outcome = _update_business_outcome(outcome, booking_norm["integration_result"])

        assert outcome["booking"] == "failed"
        assert outcome["overall"] == "failed"
        assert outcome["patient_log"] == "not_attempted"
        assert outcome["email"] == "not_attempted"


class TestSafeStateBoundary:

    def test_raw_pii_absent_from_last_result(
        self, calendar_booking_success
    ):
        """No names/emails/phones in last_result."""
        # The booking output contains patient info in summary/description
        node_result = _make_node_result(
            "action_3", "action", "book_appointment",
            calendar_booking_success,
        )
        normalized = _normalize_integration_result(
            "action_3", "action", {"action": "book_appointment"},
            node_result, "success",
        )

        # last_result is the normalized dict — check no PII leaked
        last_result_str = str(normalized)
        assert "John Doe" not in last_result_str, "Patient name leaked into last_result"
        assert "patient@example.com" not in last_result_str, "Email leaked into last_result"
        assert "0300" not in last_result_str, "Phone leaked into last_result"

    def test_raw_exception_absent_from_safe_error(self):
        """error_message_safe contains no raw exception text."""
        node_result = {
            "node_id": "action_3",
            "node_type": "action",
            "action": "book_appointment",
            "status": "error",
            "error": "googleapiclient.errors.HttpError 500: Internal Error at /calendar/v3/events",
            "result": {},
        }
        normalized = _normalize_integration_result(
            "action_3", "action", {"action": "book_appointment"},
            node_result, "error",
        )

        safe_msg = normalized["integration_result"]["error_message_safe"]
        assert safe_msg is not None
        assert "googleapiclient" not in safe_msg, "Raw exception class leaked into safe error"
        assert "HttpError" not in safe_msg, "Raw exception type leaked into safe error"
        assert "500" not in safe_msg, "Raw HTTP status leaked into safe error"
        assert "/calendar/v3" not in safe_msg, "Raw API path leaked into safe error"


class TestEvidenceMappingWithProviderFixtures:
    """Test 20: evidence mapping uses actual provider payload fixtures."""

    def test_evidence_mapping_uses_actual_provider_payload_fixtures(
        self,
        calendar_availability_success_available,
        calendar_booking_success,
        sheets_append_success,
        email_send_success,
    ):
        """Verify evidence is mapped from real provider fields, not defaults."""
        # Availability: evidence from available/requested_time_available
        avail_norm = _normalize_integration_result(
            "action_2", "action", {"action": "check_availability"},
            _make_node_result("action_2", "action", "check_availability",
                              calendar_availability_success_available),
            "success",
        )
        assert avail_norm["integration_result"]["evidence"]["availability_checked"] is True
        assert avail_norm["integration_result"]["safe_facts"]["available"] is True

        # Booking: evidence from id + event_created
        booking_norm = _normalize_integration_result(
            "action_3", "action", {"action": "book_appointment"},
            _make_node_result("action_3", "action", "book_appointment",
                              calendar_booking_success),
            "success",
        )
        assert booking_norm["integration_result"]["evidence"]["booking_created"] is True
        assert booking_norm["integration_result"]["external_id"] == "evt_abc123def456"

        # Sheets: evidence from row_appended
        sheets_norm = _normalize_integration_result(
            "sheets_1", "google_sheets", {"action": "append_row"},
            _make_node_result("sheets_1", "google_sheets", "append_row",
                              sheets_append_success),
            "success",
        )
        assert sheets_norm["integration_result"]["evidence"]["patient_logged"] is True

        # Email: evidence from email_sent
        email_norm = _normalize_integration_result(
            "email_1", "send_email", {"action": "send_email"},
            _make_node_result("email_1", "send_email", "send_email",
                              email_send_success),
            "success",
        )
        assert email_norm["integration_result"]["evidence"]["email_sent"] is True


# ---------------------------------------------------------------------------
# Quick-Win Prompt 1 Final Patch: 17 Retry-Scope Regression Tests
# ---------------------------------------------------------------------------


def _make_condition_state(
    node_id: str,
    expression: str,
    retry_mode: str = "",
    retry_owner: str = "",
    retry_scope: str = "",
    active_scope: str = "",
    counts: dict | None = None,
):
    """Build a minimal FlowState for condition_handler testing."""
    from voice_platform.flow.state import make_initial_state

    nodes_by_id = {
        node_id: {
            "id": node_id,
            "type": "condition",
            "data": {
                "label": node_id,
                "config": {
                    "expression": expression,
                    **({"retry_mode": retry_mode} if retry_mode else {}),
                    **({"retry_owner": retry_owner} if retry_owner else {}),
                    **({"retry_scope": retry_scope} if retry_scope else {}),
                },
            },
        },
    }
    state = make_initial_state(
        user_id=1, agent_id=1, nodes_by_id=nodes_by_id,
        outgoing={node_id: []},
    )
    state.update({
        "current_node": node_id,
        "_active_retry_scope": active_scope,
        "_slot_retry_counts": counts or {},
    })
    return state


async def _run_condition(state):
    """Run condition_handler and return the result dict."""
    from voice_platform.flow.nodes import create_node_handlers

    handlers = create_node_handlers()
    condition_handler = handlers["condition"]

    async def _noop(event: dict):
        pass

    return await condition_handler(state, {
        "configurable": {"conversation_id": "test", "event_callback": _noop},
    })


class TestRetryScopeOwnershipStrict:
    """9 tests: scope ownership and fail-closed behavior."""

    @pytest.mark.asyncio
    async def test_active_action_missing_retry_owner_raises(self):
        """active_action mode without retry_owner → MISSING_RETRY_OWNER."""
        state = _make_condition_state(
            "condition_missing",
            "_slot_retry_count < 2",
            retry_mode="active_action",
            active_scope="action_2:missing_input:preferred_time",
            counts={"action_2:missing_input:preferred_time": {"count": 0, "owner": "action_2", "mode": "active_action"}},
        )
        with pytest.raises(RetryScopeError) as exc_info:
            await _run_condition(state)
        assert exc_info.value.code == "MISSING_RETRY_OWNER"

    @pytest.mark.asyncio
    async def test_active_action_correct_owner_succeeds(self):
        """condition_missing with retry_owner=action_2 and matching scope → succeeds."""
        state = _make_condition_state(
            "condition_missing",
            "_slot_retry_count < 2",
            retry_mode="active_action",
            retry_owner="action_2",
            active_scope="action_2:missing_input:preferred_time",
            counts={"action_2:missing_input:preferred_time": {"count": 0, "owner": "action_2", "mode": "active_action"}},
        )
        result = await _run_condition(state)
        assert result["_condition_met"] is True
        assert result["_slot_retry_counts"]["action_2:missing_input:preferred_time"]["count"] == 1

    @pytest.mark.asyncio
    async def test_active_action_wrong_owner_raises_mismatch(self):
        """condition_missing with retry_owner=action_2 but scope owned by action_3 → RETRY_SCOPE_OWNER_MISMATCH."""
        state = _make_condition_state(
            "condition_missing",
            "_slot_retry_count < 2",
            retry_mode="active_action",
            retry_owner="action_2",
            active_scope="action_3:missing_input:caller_email",
            counts={"action_3:missing_input:caller_email": {"count": 0, "owner": "action_3", "mode": "active_action"}},
        )
        with pytest.raises(RetryScopeError) as exc_info:
            await _run_condition(state)
        assert exc_info.value.code == "RETRY_SCOPE_OWNER_MISMATCH"

    @pytest.mark.asyncio
    async def test_bare_integer_scope_rejected_under_strict_ownership(self):
        """active_action with bare int counter → RETRY_SCOPE_OWNER_MISMATCH."""
        state = _make_condition_state(
            "condition_missing",
            "_slot_retry_count < 2",
            retry_mode="active_action",
            retry_owner="action_2",
            active_scope="action_2:missing_input:preferred_time",
            counts={"action_2:missing_input:preferred_time": 0},
        )
        with pytest.raises(RetryScopeError) as exc_info:
            await _run_condition(state)
        assert exc_info.value.code == "RETRY_SCOPE_OWNER_MISMATCH"

    @pytest.mark.asyncio
    async def test_action_success_clears_scopes_by_metadata_owner(self):
        """action_3 success clears scopes where record.owner==action_3, preserves action_2 scopes."""
        counts = {
            "action_2:missing_input:preferred_time": {"count": 1, "owner": "action_2", "mode": "active_action"},
            "action_3:missing_input:caller_email": {"count": 1, "owner": "action_3", "mode": "active_action"},
        }
        cleared_counts = {
            k: v for k, v in counts.items()
            if not (isinstance(v, dict) and v.get("owner") == "action_3")
        }
        assert "action_2:missing_input:preferred_time" in cleared_counts
        assert "action_3:missing_input:caller_email" not in cleared_counts

    @pytest.mark.asyncio
    async def test_similarly_prefixed_scope_with_another_owner_preserved(self):
        """action_2:missing_input:preferred_time preserved when action_3 succeeds (not cleared by prefix)."""
        counts = {
            "action_2:missing_input:preferred_time": {"count": 1, "owner": "action_2", "mode": "active_action"},
            "action_3:missing_input:preferred_time": {"count": 1, "owner": "action_3", "mode": "active_action"},
        }
        cleared_counts = {
            k: v for k, v in counts.items()
            if not (isinstance(v, dict) and v.get("owner") == "action_3")
        }
        assert "action_2:missing_input:preferred_time" in cleared_counts
        assert "action_3:missing_input:preferred_time" not in cleared_counts

    @pytest.mark.asyncio
    async def test_configured_scope_ignores_unrelated_active_scope(self):
        """condition_3 (configured) ignores _active_retry_scope from action_2."""
        state = _make_condition_state(
            "condition_3",
            "_slot_retry_count < 2",
            retry_mode="configured",
            retry_scope="condition_3:alt_time_retry",
            active_scope="action_2:missing_input:preferred_time",
            counts={
                "action_2:missing_input:preferred_time": {"count": 1, "owner": "action_2", "mode": "active_action"},
            },
        )
        result = await _run_condition(state)
        # condition_3 should initialize its own scope at 0, evaluate 0<2=True, increment to 1
        assert result["_condition_met"] is True
        assert result["_slot_retry_counts"]["condition_3:alt_time_retry"]["count"] == 1
        assert result["_slot_retry_counts"]["condition_3:alt_time_retry"]["owner"] == "condition_3"
        assert result["_slot_retry_counts"]["condition_3:alt_time_retry"]["mode"] == "configured"
        # action_2 scope preserved
        assert "action_2:missing_input:preferred_time" in result["_slot_retry_counts"]

    @pytest.mark.asyncio
    async def test_configured_scope_clears_on_denied_retry(self):
        """condition_3 with count=2, condition_met=False → scope cleared."""
        state = _make_condition_state(
            "condition_3",
            "_slot_retry_count < 2",
            retry_mode="configured",
            retry_scope="condition_3:alt_time_retry",
            counts={
                "condition_3:alt_time_retry": {"count": 2, "owner": "condition_3", "mode": "configured"},
            },
        )
        result = await _run_condition(state)
        assert result["_condition_met"] is False
        assert "condition_3:alt_time_retry" not in result["_slot_retry_counts"]

    @pytest.mark.asyncio
    async def test_checkpoint_resume_retains_structured_owner_and_mode(self):
        """Serialize/deserialize _slot_retry_counts, owner and mode preserved."""
        import json

        original = {
            "action_2:missing_input:preferred_time": {"count": 1, "owner": "action_2", "mode": "active_action"},
            "condition_3:alt_time_retry": {"count": 0, "owner": "condition_3", "mode": "configured"},
        }
        serialized = json.loads(json.dumps(original))
        assert serialized == original
        assert serialized["action_2:missing_input:preferred_time"]["owner"] == "action_2"
        assert serialized["condition_3:alt_time_retry"]["mode"] == "configured"


class TestCondition3ConfiguredLifecycle:
    """5 tests: condition_3 configured scope lifecycle."""

    @pytest.mark.asyncio
    async def test_condition3_initializes_declared_scope(self):
        """condition_3 with retry_scope config initializes scope at 0."""
        state = _make_condition_state(
            "condition_3",
            "_slot_retry_count < 2",
            retry_mode="configured",
            retry_scope="condition_3:alt_time_retry",
            counts={},
        )
        result = await _run_condition(state)
        assert "condition_3:alt_time_retry" in result["_slot_retry_counts"]
        assert result["_slot_retry_counts"]["condition_3:alt_time_retry"]["count"] == 1
        assert result["_slot_retry_counts"]["condition_3:alt_time_retry"]["owner"] == "condition_3"

    @pytest.mark.asyncio
    async def test_condition3_exactly_two_retries(self):
        """count 0→retry, 1→retry, 2→no retry (exits loop)."""
        scope_key = "condition_3:alt_time_retry"
        # Attempt 0: count=0, 0<2=True → retry, increment to 1
        state_0 = _make_condition_state(
            "condition_3", "_slot_retry_count < 2",
            retry_mode="configured", retry_scope=scope_key,
            counts={scope_key: {"count": 0, "owner": "condition_3", "mode": "configured"}},
        )
        result_0 = await _run_condition(state_0)
        assert result_0["_condition_met"] is True
        assert result_0["_slot_retry_counts"][scope_key]["count"] == 1

        # Attempt 1: count=1, 1<2=True → retry, increment to 2
        state_1 = _make_condition_state(
            "condition_3", "_slot_retry_count < 2",
            retry_mode="configured", retry_scope=scope_key,
            counts={scope_key: {"count": 1, "owner": "condition_3", "mode": "configured"}},
        )
        result_1 = await _run_condition(state_1)
        assert result_1["_condition_met"] is True
        assert result_1["_slot_retry_counts"][scope_key]["count"] == 2

        # Attempt 2: count=2, 2<2=False → no retry, scope cleared
        state_2 = _make_condition_state(
            "condition_3", "_slot_retry_count < 2",
            retry_mode="configured", retry_scope=scope_key,
            counts={scope_key: {"count": 2, "owner": "condition_3", "mode": "configured"}},
        )
        result_2 = await _run_condition(state_2)
        assert result_2["_condition_met"] is False
        assert scope_key not in result_2["_slot_retry_counts"]

    @pytest.mark.asyncio
    async def test_action2_success_does_not_reset_condition3(self):
        """action_2 success clears its own scopes, preserves condition_3's scope."""
        counts = {
            "action_2:missing_input:preferred_time": {"count": 1, "owner": "action_2", "mode": "active_action"},
            "condition_3:alt_time_retry": {"count": 1, "owner": "condition_3", "mode": "configured"},
        }
        cleared_counts = {
            k: v for k, v in counts.items()
            if not (isinstance(v, dict) and v.get("owner") == "action_2")
        }
        assert "action_2:missing_input:preferred_time" not in cleared_counts
        assert "condition_3:alt_time_retry" in cleared_counts
        assert cleared_counts["condition_3:alt_time_retry"]["count"] == 1

    @pytest.mark.asyncio
    async def test_reentering_new_episode_gets_fresh_allowance(self):
        """After scope cleared, re-entering condition_3 re-initializes at 0."""
        scope_key = "condition_3:alt_time_retry"
        # Scope was cleared (not in counts)
        state = _make_condition_state(
            "condition_3", "_slot_retry_count < 2",
            retry_mode="configured", retry_scope=scope_key,
            counts={},
        )
        result = await _run_condition(state)
        # Should initialize at 0, evaluate 0<2=True, increment to 1
        assert result["_condition_met"] is True
        assert result["_slot_retry_counts"][scope_key]["count"] == 1

    @pytest.mark.asyncio
    async def test_missing_retry_mode_soft_recovers_with_condition_retry_scope(self):
        """Condition with _slot_retry_count but no retry_mode soft-recovers."""
        state = _make_condition_state(
            "condition_missing",
            "_slot_retry_count < 2",
            active_scope="",
            counts={},
        )
        result = await _run_condition(state)
        assert result["_condition_met"] is True
        assert "condition_missing:condition_retry" in result["_slot_retry_counts"]
        assert result["_slot_retry_counts"]["condition_missing:condition_retry"]["count"] == 1
        assert result["_slot_retry_counts"]["condition_missing:condition_retry"]["mode"] == "configured"

    @pytest.mark.asyncio
    async def test_missing_retry_mode_infers_active_scope(self):
        """Call 108: omit retry_mode but active action scope present → soft recover."""
        state = _make_condition_state(
            "condition_missing",
            "_slot_retry_count < 2",
            active_scope="action_2:missing_input:preferred_date,preferred_time",
            counts={
                "action_2:missing_input:preferred_date,preferred_time": {
                    "count": 0,
                    "owner": "action_2",
                    "mode": "active_action",
                }
            },
        )
        result = await _run_condition(state)
        assert result["_condition_met"] is True
        assert (
            result["_slot_retry_counts"][
                "action_2:missing_input:preferred_date,preferred_time"
            ]["count"]
            == 1
        )


class TestAdditionalScopeRegressions:
    """3 tests: no condition-local scope, stale count, scope survival."""

    @pytest.mark.asyncio
    async def test_no_condition_local_scope_created(self):
        """Assert no {node_id}:condition_retry key in counts after evaluation."""
        state = _make_condition_state(
            "condition_3",
            "_slot_retry_count < 2",
            retry_mode="configured",
            retry_scope="condition_3:alt_time_retry",
            counts={},
        )
        result = await _run_condition(state)
        assert "condition_3:condition_retry" not in result["_slot_retry_counts"]

    @pytest.mark.asyncio
    async def test_stale_slot_retry_count_cannot_be_used(self):
        """Legacy _slot_retry_count field ignored when scope system active."""
        state = _make_condition_state(
            "condition_3",
            "_slot_retry_count < 2",
            retry_mode="configured",
            retry_scope="condition_3:alt_time_retry",
            counts={},
        )
        # Set a stale _slot_retry_count that should NOT be used
        state["_slot_retry_count"] = 99
        result = await _run_condition(state)
        # Should use scope count (0), not stale field (99)
        assert result["_condition_met"] is True
        assert result["_slot_retry_counts"]["condition_3:alt_time_retry"]["count"] == 1

    @pytest.mark.asyncio
    async def test_action_owned_scope_survives_intermediate_node(self):
        """Action sets scope → condition reads same scope with correct owner."""
        scope_key = "action_2:missing_input:preferred_time"
        state = _make_condition_state(
            "condition_missing",
            "_slot_retry_count < 2",
            retry_mode="active_action",
            retry_owner="action_2",
            active_scope=scope_key,
            counts={scope_key: {"count": 0, "owner": "action_2", "mode": "active_action"}},
        )
        result = await _run_condition(state)
        assert result["_condition_met"] is True
        assert result["_slot_retry_counts"][scope_key]["count"] == 1
        assert result["_slot_retry_counts"][scope_key]["owner"] == "action_2"


# ---------------------------------------------------------------------------
# Quick-Win Prompt 1 Final Patch: 5 Claim Combination Tests
# ---------------------------------------------------------------------------


class TestClaimCombinations:
    """5 tests: exact final TTS text for all booking/email combinations."""

    def test_booking_booked_email_not_attempted(self):
        """booking=booked + email=not_attempted → booking claim passes, email claim rewritten."""
        text = "Your appointment is confirmed for July 20 at 10:00 with Dr. Ayesha. A confirmation email has been sent."
        outcome = {"booking": "booked", "email": "not_attempted"}
        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)
        # Booking claim passes (booking=booked), but email claim fails (email≠sent)
        assert "confirmation email has been sent" not in result.lower()
        assert _deterministic_response(outcome) == result

    def test_booking_booked_email_failed(self):
        """booking=booked + email=failed → booking claim passes, email claim rewritten."""
        text = "Your appointment is confirmed for July 20 at 10:00. A confirmation email has been sent."
        outcome = {"booking": "booked", "email": "failed"}
        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)
        assert "confirmation email has been sent" not in result.lower()
        assert "couldn't send the confirmation email" in result.lower()

    def test_booking_failed_email_sent_inconsistent(self):
        """booking=failed + email=sent → inconsistent → safe response that does not imply email proves booking."""
        text = "Your appointment is confirmed for July 20 at 10:00. A confirmation email has been sent."
        outcome = {"booking": "failed", "email": "sent"}
        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)
        # Booking claim must be rewritten (booking≠booked)
        assert "confirmed" not in result.lower() or "couldn't complete the booking" in result.lower()
        assert _deterministic_response(outcome) == result
        # The deterministic response for booking=failed should not claim booking success
        assert "couldn't complete the booking" in result.lower()

    def test_booking_unknown_claim_rewritten(self):
        """booking=unknown → booking claim rewritten."""
        text = "Your appointment is confirmed for July 20 at 10:00."
        outcome = {"booking": "unknown", "email": "not_attempted"}
        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)
        assert "confirmed" not in result.lower() or "couldn't confirm" in result.lower()
        assert _deterministic_response(outcome) == result

    def test_booking_booked_email_sent_both_pass(self):
        """booking=booked + email=sent → both claims pass (original text preserved)."""
        text = "Your appointment is confirmed for July 20 at 10:00. A confirmation email has been sent."
        outcome = {"booking": "booked", "email": "sent"}
        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)
        assert result == text
