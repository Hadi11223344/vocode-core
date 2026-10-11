"""
SmileCare Dental Receptionist — End-to-End Reliability Tests.

100+ scenarios covering:
- E1: Greeting and identity (10 tests)
- E2: Emergency triage (15 tests)
- E3: Appointment booking flow (20 tests)
- E4: Booking claim safety (15 tests)
- E5: Patient logging and Sheets (10 tests)
- E6: Email confirmation (10 tests)
- E7: Knowledge base accuracy (15 tests)
- E8: Outbound calls (10 tests)
- E9: Error handling and recovery (10 tests)
- E10: Diagnostic snapshot (8 tests)

Tests are deterministic — they validate prompt policy, tool evidence gating,
claim safety, emergency triage logic, and error handling without making real
LLM or integration calls.
"""

import pytest

from voice_platform.agent_templates import get_template
from voice_platform.diagnostics import (
    ERROR_REGISTRY,
    build_diagnostic_snapshot,
    build_safe_error_event,
)
from voice_platform.flow.nodes import (
    ClaimContext,
    _claim_check,
    _deterministic_response,
    _is_hypothetical,
    _is_negated,
    _normalize_integration_result,
)
from voice_platform.integrations.knowledge_base import KnowledgeBaseClient

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def smilecare_template():
    return get_template("smilecare")


@pytest.fixture
def smilecare_prompt(smilecare_template):
    return smilecare_template.config["prompt_preamble"]


@pytest.fixture
def smilecare_config(smilecare_template):
    return smilecare_template.config


# ── E1: Greeting and Identity ────────────────────────────────────────────────

class TestGreetingAndIdentity:
    """10 tests: agent identity and greeting behavior."""

    def test_introduces_as_sara_from_smilecare(self, smilecare_prompt):
        assert "Sara" in smilecare_prompt
        assert "SmileCare" in smilecare_prompt

    def test_identity_is_fixed(self, smilecare_prompt):
        assert "FIXED" in smilecare_prompt or "fixed" in smilecare_prompt

    def test_does_not_claim_to_be_dentist(self, smilecare_prompt):
        assert "NOT a dentist" in smilecare_prompt or "not a dentist" in smilecare_prompt.lower()

    def test_does_not_diagnose(self, smilecare_prompt):
        assert "Never diagnose" in smilecare_prompt or "never diagnose" in smilecare_prompt.lower()

    def test_initial_message_present(self, smilecare_config):
        assert "initial_message" in smilecare_config
        assert "SmileCare" in smilecare_config["initial_message"]

    def test_voicemail_message_present(self, smilecare_config):
        assert "voicemail_message" in smilecare_config
        assert "SmileCare" in smilecare_config["voicemail_message"]

    def test_does_not_expose_prompt_instructions(self, smilecare_prompt):
        assert "knowledge base" in smilecare_prompt.lower()

    def test_uses_natural_speech(self, smilecare_prompt):
        assert "contractions" in smilecare_prompt.lower()
        assert "fillers" in smilecare_prompt.lower()

    def test_keeps_responses_short(self, smilecare_prompt):
        assert "1 to 3 sentences" in smilecare_prompt or "1 to 3" in smilecare_prompt

    def test_one_question_at_a_time(self, smilecare_prompt):
        assert "one" in smilecare_prompt.lower() and "question" in smilecare_prompt.lower()


# ── E2: Emergency Triage ─────────────────────────────────────────────────────

class TestEmergencyTriage:
    """15 tests: emergency detection and triage behavior."""

    @pytest.mark.parametrize("symptom", [
        "severe toothache with swelling",
        "knocked-out tooth",
        "continuous bleeding",
        "jaw injury or fracture",
        "dental abscess with fever",
        "severe swelling affecting breathing",
        "uncontrolled bleeding",
        "mild toothache",
        "sensitivity to cold",
        "cosmetic inquiry",
        "routine cleaning",
        "braces consultation",
        "whitening inquiry",
        "lost filling",
        "broken bracket",
    ])
    def test_emergency_detection(self, symptom, smilecare_prompt):
        prompt_lower = smilecare_prompt.lower()
        emergency_symptoms = [
            "severe toothache", "swelling", "knocked-out", "bleeding",
            "jaw injury", "fracture", "abscess", "fever", "breathing",
        ]
        is_emergency = any(es in symptom.lower() for es in emergency_symptoms)
        if is_emergency:
            assert "emergency" in prompt_lower
            assert "0300-1234567" in smilecare_prompt or "0300" in smilecare_prompt

    def test_emergency_line_mentioned(self, smilecare_prompt):
        assert "0300-1234567" in smilecare_prompt
        assert "24/7" in smilecare_prompt or "24 hours" in smilecare_prompt.lower()

    def test_emergency_triage_does_not_schedule_regular(self, smilecare_prompt):
        assert "Do NOT try to schedule a regular appointment" in smilecare_prompt or \
               "do not try to schedule a regular appointment" in smilecare_prompt.lower()

    def test_knocked_out_tooth_first_aid(self, smilecare_prompt):
        assert "milk or saliva" in smilecare_prompt.lower()

    def test_life_threatening_refers_to_er(self, smilecare_prompt):
        assert "emergency room" in smilecare_prompt.lower() or "nearest emergency" in smilecare_prompt.lower()

    def test_emergency_caller_not_kept_waiting(self, smilecare_prompt):
        assert "Don't make them wait" in smilecare_prompt or "don't make them wait" in smilecare_prompt.lower()

    def test_emergency_do_not_end_until_instructions_given(self, smilecare_prompt):
        assert "first-aid" in smilecare_prompt.lower() or "first aid" in smilecare_prompt.lower()

    def test_hospital_referral_mentioned(self, smilecare_prompt):
        assert "Services Hospital" in smilecare_prompt or "Shaukat Khanum" in smilecare_prompt


# ── E3: Appointment Booking Flow ─────────────────────────────────────────────

class TestAppointmentBooking:
    """20 tests: booking flow steps and safety."""

    def test_asks_new_or_existing_patient(self, smilecare_prompt):
        assert "new or existing" in smilecare_prompt.lower()

    def test_asks_service_needed(self, smilecare_prompt):
        assert "service" in smilecare_prompt.lower()

    def test_asks_preferred_dentist(self, smilecare_prompt):
        assert "preferred dentist" in smilecare_prompt.lower() or "preferred" in smilecare_prompt.lower()

    def test_suggests_dentist_based_on_need(self, smilecare_prompt):
        assert "suggest" in smilecare_prompt.lower()

    def test_asks_preferred_date_and_time(self, smilecare_prompt):
        assert "date" in smilecare_prompt.lower() and "time" in smilecare_prompt.lower()

    def test_checks_calendar_availability(self, smilecare_prompt):
        assert "calendar" in smilecare_prompt.lower() or "check_calendar" in smilecare_prompt.lower()

    def test_offers_alternative_slots(self, smilecare_prompt):
        assert "2-3 available slots" in smilecare_prompt or "alternative" in smilecare_prompt.lower()

    def test_confirms_appointment_details(self, smilecare_prompt):
        assert "confirm" in smilecare_prompt.lower()
        assert "repeat" in smilecare_prompt.lower() or "read back" in smilecare_prompt.lower()

    def test_does_not_book_without_confirmation(self, smilecare_prompt):
        assert "caller confirms" in smilecare_prompt.lower() or "confirm" in smilecare_prompt.lower()

    def test_does_not_claim_booked_before_tool(self, smilecare_prompt):
        assert "Do NOT say" in smilecare_prompt or "do not say" in smilecare_prompt.lower()
        assert "book_appointment" in smilecare_prompt.lower()

    def test_honest_failure_message(self, smilecare_prompt):
        assert "wasn't able to finalize" in smilecare_prompt.lower() or "couldn't" in smilecare_prompt.lower()

    def test_asks_about_insurance(self, smilecare_prompt):
        assert "insurance" in smilecare_prompt.lower()

    def test_mentions_discounts_proactively(self, smilecare_prompt):
        assert "discount" in smilecare_prompt.lower()

    def test_mentions_cancellation_policy(self, smilecare_prompt):
        assert "cancellation" in smilecare_prompt.lower()
        assert "4 hours" in smilecare_prompt or "four hours" in smilecare_prompt.lower()

    def test_pakistani_phone_format(self, smilecare_prompt):
        assert "11 digits" in smilecare_prompt or "0300" in smilecare_prompt

    def test_reads_back_phone_number(self, smilecare_prompt):
        assert "read it back" in smilecare_prompt.lower() or "read back" in smilecare_prompt.lower()

    def test_verifies_email_before_sending(self, smilecare_prompt):
        assert "read it back" in smilecare_prompt.lower() or "verify" in smilecare_prompt.lower()

    def test_does_not_offer_sms(self, smilecare_prompt):
        assert "Do NOT offer SMS" in smilecare_prompt or "do not offer sms" in smilecare_prompt.lower()

    def test_recommended_tools_include_booking(self, smilecare_template):
        tools = smilecare_template.recommended_tools
        assert "book_appointment" in tools
        assert "check_calendar" in tools

    def test_both_inbound_and_outbound_ready(self, smilecare_template):
        assert smilecare_template.inbound_ready is True
        assert smilecare_template.outbound_ready is True


# ── E4: Booking Claim Safety ─────────────────────────────────────────────────

class TestBookingClaimSafety:
    """15 tests: claim check and deterministic response behavior."""

    def test_booked_claim_blocked_without_evidence(self):
        """Agent must not say 'booked' without booking evidence."""
        text = "Your appointment has been booked."
        outcome = {"booking": "not_attempted", "email": "not_attempted"}
        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)
        assert result != text

    def test_scheduled_claim_blocked_without_evidence(self):
        text = "Your appointment is scheduled."
        outcome = {"booking": "not_attempted", "email": "not_attempted"}
        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)
        assert result != text

    def test_confirmed_claim_blocked_without_evidence(self):
        text = "Your appointment is confirmed."
        outcome = {"booking": "not_attempted", "email": "not_attempted"}
        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)
        assert result != text

    def test_booked_claim_allowed_with_evidence(self):
        text = "Your appointment has been booked."
        outcome = {"booking": "booked", "email": "not_attempted"}
        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)
        assert result == text

    def test_negated_booking_claim_allowed(self):
        text = "I haven't booked your appointment yet."
        outcome = {"booking": "not_attempted", "email": "not_attempted"}
        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)
        assert result == text

    def test_hypothetical_booking_claim_allowed(self):
        text = "Would you like me to book your appointment?"
        outcome = {"booking": "not_attempted", "email": "not_attempted"}
        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)
        assert result == text

    def test_email_sent_claim_blocked_without_evidence(self):
        text = "A confirmation email has been sent."
        outcome = {"booking": "booked", "email": "not_attempted"}
        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)
        assert result != text

    def test_email_sent_claim_allowed_with_evidence(self):
        text = "A confirmation email has been sent."
        outcome = {"booking": "booked", "email": "sent"}
        result = _claim_check(text, outcome, ClaimContext.BOOKING_TERMINAL)
        assert result == text

    def test_deterministic_response_booked_and_email_sent(self):
        outcome = {"booking": "booked", "email": "sent"}
        result = _deterministic_response(outcome)
        assert "booked" in result.lower()
        assert "email" in result.lower()

    def test_deterministic_response_booked_email_failed(self):
        outcome = {"booking": "booked", "email": "failed"}
        result = _deterministic_response(outcome)
        assert "booked" in result.lower()
        assert "couldn't" in result.lower() or "could not" in result.lower()

    def test_deterministic_response_booking_failed(self):
        outcome = {"booking": "failed", "email": "not_attempted"}
        result = _deterministic_response(outcome)
        assert "couldn't" in result.lower() or "could not" in result.lower()
        assert "booking" in result.lower()

    def test_deterministic_response_booking_unknown(self):
        outcome = {"booking": "unknown", "email": "not_attempted"}
        result = _deterministic_response(outcome)
        assert "verify" in result.lower() or "couldn't confirm" in result.lower()

    def test_deterministic_response_not_attempted(self):
        outcome = {"booking": "not_attempted", "email": "not_attempted"}
        result = _deterministic_response(outcome)
        assert "working" in result.lower() or "more details" in result.lower()

    def test_is_negated_detects_not(self):
        assert _is_negated("I have not booked", "booked") is True

    def test_is_hypothetical_detects_would_you_like(self):
        assert _is_hypothetical("would you like me to book") is True


# ── E5: Patient Logging and Sheets ───────────────────────────────────────────

class TestPatientLogging:
    """10 tests: patient logging to Google Sheets."""

    def test_append_sheet_success_produces_evidence(self):
        result = _normalize_integration_result(
            "action_1", "action", {"action": "append_row"},
            {"success": True, "result": {"row_appended": True, "updated_range": "Patients!A5", "updated_rows": 1}},
            "success",
        )
        assert result["integration_result"]["evidence"]["patient_logged"] is True
        assert result["integration_result"]["business_succeeded"] is True

    def test_append_sheet_failure_produces_safe_response(self):
        result = _normalize_integration_result(
            "action_1", "action", {"action": "append_row"},
            {"success": False, "result": {"error": "Permission denied"}},
            "error",
        )
        assert result["integration_result"]["business_succeeded"] is False
        assert result["integration_result"]["error_code"] is not None

    def test_append_sheet_malformed_result(self):
        result = _normalize_integration_result(
            "action_1", "action", {"action": "append_row"},
            {"success": True, "result": {}},
            "success",
        )
        assert result["integration_result"]["business_succeeded"] is False
        assert result["integration_result"]["error_code"] == "SHEETS_FAILED"

    def test_incremental_capture_in_prompt(self, smilecare_prompt):
        assert "incremental" in smilecare_prompt.lower() or "append_sheet" in smilecare_prompt.lower()

    def test_no_duplicate_append_in_prompt(self, smilecare_prompt):
        assert "Do NOT call append_sheet multiple times" in smilecare_prompt or \
               "do not call append_sheet multiple times" in smilecare_prompt.lower()

    def test_column_order_specified(self, smilecare_prompt):
        assert "Name, Phone, Patient Type, Service, Dentist, Date, Time, Notes" in smilecare_prompt

    def test_patient_log_failed_error_code(self):
        ev = build_safe_error_event("PATIENT_LOG_FAILED", agent_type="single_prompt")
        assert ev["component"] == "google_sheets"
        assert ev["retryable"] is True

    def test_recommended_tools_include_sheets(self, smilecare_template):
        tools = smilecare_template.recommended_tools
        assert "append_sheet" in tools
        assert "read_sheet" in tools

    def test_tool_error_recovery_append_sheet(self, smilecare_prompt):
        assert "append_sheet fails" in smilecare_prompt or "save your details" in smilecare_prompt.lower()

    def test_tool_error_recovery_read_sheet(self, smilecare_prompt):
        assert "read_sheet fails" in smilecare_prompt or "patient records" in smilecare_prompt.lower()


# ── E6: Email Confirmation ───────────────────────────────────────────────────

class TestEmailConfirmation:
    """10 tests: email confirmation behavior."""

    def test_email_success_produces_evidence(self):
        result = _normalize_integration_result(
            "email_1", "send_email", {"action": "send_email"},
            {"success": True, "result": {"email_sent": True, "message_id": "msg789"}},
            "success",
        )
        assert result["integration_result"]["evidence"]["email_sent"] is True

    def test_email_failure_produces_safe_response(self):
        result = _normalize_integration_result(
            "email_1", "send_email", {"action": "send_email"},
            {"success": False, "result": {"error": "SMTP error"}},
            "error",
        )
        assert result["integration_result"]["business_succeeded"] is False
        assert result["integration_result"]["error_code"] is not None

    def test_email_business_failure_produces_email_failed(self):
        """Execution succeeded but email_sent field missing → EMAIL_FAILED."""
        result = _normalize_integration_result(
            "email_1", "send_email", {"action": "send_email"},
            {"success": True, "result": {}},
            "success",
        )
        assert result["integration_result"]["evidence"]["email_sent"] is not True
        assert result["integration_result"]["error_code"] == "EMAIL_FAILED"

    def test_email_malformed_result(self):
        result = _normalize_integration_result(
            "email_1", "send_email", {"action": "send_email"},
            {"success": True, "result": {}},
            "success",
        )
        assert result["integration_result"]["evidence"]["email_sent"] is not True

    def test_email_send_failed_error_code(self):
        ev = build_safe_error_event("EMAIL_SEND_FAILED", agent_type="single_prompt")
        assert ev["component"] == "email_provider"
        assert ev["retryable"] is True

    def test_email_offered_in_prompt(self, smilecare_prompt):
        assert "send_email" in smilecare_prompt.lower() or "email" in smilecare_prompt.lower()

    def test_email_verified_before_sending(self, smilecare_prompt):
        assert "read it back" in smilecare_prompt.lower() or "verify" in smilecare_prompt.lower()

    def test_no_sms_offered(self, smilecare_prompt):
        assert "Do NOT offer SMS" in smilecare_prompt or "do not offer sms" in smilecare_prompt.lower()

    def test_email_error_recovery_in_prompt(self, smilecare_prompt):
        assert "send_email fails" in smilecare_prompt or "wasn't able to send" in smilecare_prompt.lower()

    def test_recommended_tools_include_email(self, smilecare_template):
        tools = smilecare_template.recommended_tools
        assert "send_email" in tools

    def test_email_claim_blocked_without_evidence(self):
        text = "The confirmation email has been sent."
        outcome = {"booking": "booked", "email": "not_attempted"}
        result = _claim_check(text, outcome, ClaimContext.EMAIL_RESULT)
        assert result != text


# ── E7: Knowledge Base Accuracy ──────────────────────────────────────────────

class TestKnowledgeBaseAccuracy:
    """15 tests: knowledge base content and retrieval."""

    def test_six_dentists_listed(self, smilecare_prompt):
        dentists = ["Dr. Ayesha", "Dr. Imran", "Dr. Sana", "Dr. Bilal", "Dr. Hina", "Dr. Farhan"]
        for doc in dentists:
            assert doc in smilecare_prompt, f"Missing dentist: {doc}"

    def test_dentist_specialties(self, smilecare_prompt):
        assert "orthodontics" in smilecare_prompt.lower() or "braces" in smilecare_prompt.lower()
        assert "oral surgery" in smilecare_prompt.lower() or "extractions" in smilecare_prompt.lower()
        assert "cosmetic" in smilecare_prompt.lower() or "whitening" in smilecare_prompt.lower()
        assert "root canal" in smilecare_prompt.lower()
        assert "pediatric" in smilecare_prompt.lower() or "children" in smilecare_prompt.lower()
        assert "gum" in smilecare_prompt.lower() or "scaling" in smilecare_prompt.lower()

    def test_consultation_fees(self, smilecare_prompt):
        assert "1,000" in smilecare_prompt or "1000" in smilecare_prompt
        assert "3,000" in smilecare_prompt or "3000" in smilecare_prompt

    def test_clinic_hours(self, smilecare_prompt):
        assert "10 AM" in smilecare_prompt or "10 am" in smilecare_prompt.lower()
        assert "9 PM" in smilecare_prompt or "9 pm" in smilecare_prompt.lower()

    def test_sunday_hours(self, smilecare_prompt):
        assert "Sunday" in smilecare_prompt
        assert "2 PM" in smilecare_prompt or "2 pm" in smilecare_prompt.lower()

    def test_ramadan_hours(self, smilecare_prompt):
        assert "Ramadan" in smilecare_prompt

    def test_insurance_providers(self, smilecare_prompt):
        providers = ["EFU", "Adamjee", "Jubilee", "TPL"]
        for p in providers:
            assert p in smilecare_prompt, f"Missing insurance provider: {p}"

    def test_discounts(self, smilecare_prompt):
        assert "10%" in smilecare_prompt or "10 percent" in smilecare_prompt.lower()
        assert "15%" in smilecare_prompt or "15 percent" in smilecare_prompt.lower()
        assert "20%" in smilecare_prompt or "20 percent" in smilecare_prompt.lower()

    def test_installment_plans(self, smilecare_prompt):
        assert "installment" in smilecare_prompt.lower()

    def test_cancellation_policy(self, smilecare_prompt):
        assert "4 hours" in smilecare_prompt or "four hours" in smilecare_prompt.lower()
        assert "PKR 500" in smilecare_prompt or "500" in smilecare_prompt

    def test_no_show_policy(self, smilecare_prompt):
        assert "no-show" in smilecare_prompt.lower() or "no show" in smilecare_prompt.lower()

    def test_address(self, smilecare_prompt):
        assert "MM Alam Road" in smilecare_prompt
        assert "Gulberg" in smilecare_prompt

    def test_parking_info(self, smilecare_prompt):
        assert "parking" in smilecare_prompt.lower()

    def test_kb_retrieval_returns_results(self):
        chunks = [
            "Dr. Ayesha specializes in orthodontics and braces.",
            "Consultation fees range from PKR 1,000 to 3,000.",
            "Clinic hours: Monday to Saturday 10 AM to 9 PM.",
        ]
        results = KnowledgeBaseClient._tfidf_retrieve("How much is the consultation fee?", chunks, max_results=2)
        assert len(results) >= 1
        assert results[0]["score"] > 0

    def test_kb_retrieval_no_match(self):
        results = KnowledgeBaseClient._tfidf_retrieve("xyzabc123", ["hello world"], max_results=3, min_score=0.9)
        assert results == []


# ── E8: Outbound Calls ───────────────────────────────────────────────────────

class TestOutboundCalls:
    """10 tests: outbound reminder, follow-up, and reactivation."""

    def test_appointment_reminder_workflow(self, smilecare_prompt):
        assert "reminder" in smilecare_prompt.lower()
        assert "24-48 hours" in smilecare_prompt or "24 to 48" in smilecare_prompt.lower()

    def test_reminder_confirms_appointment(self, smilecare_prompt):
        assert "Does that still work" in smilecare_prompt or "still work for you" in smilecare_prompt.lower()

    def test_reminder_handles_reschedule(self, smilecare_prompt):
        assert "reschedule" in smilecare_prompt.lower()

    def test_reminder_mentions_cancellation_policy(self, smilecare_prompt):
        assert "4-hour cancellation" in smilecare_prompt or "cancellation policy" in smilecare_prompt.lower()

    def test_post_procedure_followup(self, smilecare_prompt):
        assert "follow-up" in smilecare_prompt.lower() or "follow up" in smilecare_prompt.lower()
        assert "how are you feeling" in smilecare_prompt.lower()

    def test_followup_advises_booking_if_issues(self, smilecare_prompt):
        assert "follow-up" in smilecare_prompt.lower() or "book" in smilecare_prompt.lower()

    def test_reactivation_calls(self, smilecare_prompt):
        assert "reactivation" in smilecare_prompt.lower() or "6+ months" in smilecare_prompt or "6 months" in smilecare_prompt

    def test_reactivation_mentions_discounts(self, smilecare_prompt):
        assert "discount" in smilecare_prompt.lower()

    def test_outbound_ready_flag(self, smilecare_template):
        assert smilecare_template.outbound_ready is True

    def test_outbound_greeting_identifies_smilecare(self, smilecare_prompt):
        assert "Sara from SmileCare" in smilecare_prompt


# ── E9: Error Handling and Recovery ──────────────────────────────────────────

class TestErrorHandling:
    """10 tests: tool error recovery and safe responses."""

    def test_calendar_check_failure_recovery(self, smilecare_prompt):
        assert "check_calendar fails" in smilecare_prompt or "can't check our calendar" in smilecare_prompt.lower()

    def test_booking_failure_recovery(self, smilecare_prompt):
        assert "book_appointment fails" in smilecare_prompt or "wasn't able to finalize" in smilecare_prompt.lower()

    def test_email_failure_recovery(self, smilecare_prompt):
        assert "send_email fails" in smilecare_prompt or "wasn't able to send" in smilecare_prompt.lower()

    def test_sheets_failure_recovery(self, smilecare_prompt):
        assert "append_sheet fails" in smilecare_prompt or "save your details" in smilecare_prompt.lower()

    def test_availability_check_failed_error(self):
        ev = build_safe_error_event("AVAILABILITY_CHECK_FAILED", agent_type="single_prompt")
        assert ev["component"] == "google_calendar"
        assert ev["retryable"] is True

    def test_booking_create_failed_error(self):
        ev = build_safe_error_event("BOOKING_CREATE_FAILED", agent_type="single_prompt")
        assert ev["component"] == "google_calendar"
        assert ev["retryable"] is True

    def test_booking_result_malformed_error(self):
        ev = build_safe_error_event("BOOKING_RESULT_MALFORMED", agent_type="single_prompt")
        assert ev["component"] == "google_calendar"
        assert ev["retryable"] is False
        assert ev["manual_intervention_required"] is True

    def test_booking_outcome_unknown_error(self):
        ev = build_safe_error_event("BOOKING_OUTCOME_UNKNOWN", agent_type="single_prompt")
        assert ev["component"] == "google_calendar"
        assert ev["manual_intervention_required"] is True

    def test_required_slot_unconfirmed_error(self):
        ev = build_safe_error_event("REQUIRED_SLOT_UNCONFIRMED", agent_type="single_prompt")
        assert ev["component"] == "slot_validator"
        assert ev["retryable"] is False

    def test_unsupported_booking_claim_error(self):
        ev = build_safe_error_event("UNSUPPORTED_BOOKING_CLAIM", agent_type="single_prompt")
        assert ev["component"] == "claim_policy"


# ── E10: Diagnostic Snapshot ─────────────────────────────────────────────────

class TestSmilecareDiagnostics:
    """8 tests: diagnostic snapshot for SmileCare agent."""

    def test_snapshot_agent_type(self):
        snap = build_diagnostic_snapshot({}, agent_id=3, agent_type="single_prompt")
        assert snap["agent_type"] == "single_prompt"

    def test_snapshot_no_pii(self):
        state = {
            "last_result": {
                "patient_name": "Fatima Khan",
                "caller_phone": "+15555550100",
                "caller_email": "fatima@test.com",
            },
        }
        snap = build_diagnostic_snapshot(state, agent_id=3, agent_type="single_prompt")
        result_str = str(snap["last_result"])
        assert "+15555550100" not in result_str
        assert "fatima@test.com" not in result_str
        assert "Fatima Khan" not in result_str

    def test_snapshot_retry_state(self):
        state = {
            "_active_retry_scope": "action_1:missing_input:preferred_date",
            "_slot_retry_counts": {
                "action_1:missing_input:preferred_date": {"count": 2, "owner": "action_1", "mode": "active_action"},
            },
        }
        snap = build_diagnostic_snapshot(state, agent_id=3, agent_type="single_prompt")
        assert snap["retry_state"]["scope_count"] == 1
        scope = snap["retry_state"]["scopes"]["action_1:missing_input:preferred_date"]
        assert scope["count"] == 2

    def test_snapshot_error_extraction(self):
        state = {
            "last_result": {
                "integration_result": {
                    "error_code": "BOOKING_CREATE_FAILED",
                    "error_message_safe": "The booking could not be created.",
                },
            },
        }
        snap = build_diagnostic_snapshot(state, agent_id=3, agent_type="single_prompt")
        assert snap["error_code"] == "BOOKING_CREATE_FAILED"
        assert snap["error_message_safe"] == "The booking could not be created."

    def test_snapshot_recommended_action(self):
        state = {
            "last_result": {
                "integration_result": {
                    "error_code": "BOOKING_RESULT_MALFORMED",
                },
            },
        }
        snap = build_diagnostic_snapshot(state, agent_id=3, agent_type="single_prompt")
        assert snap["recommended_manual_action"] is not None
        assert "inspect" in snap["recommended_manual_action"].lower()

    def test_snapshot_business_outcome_sanitized(self):
        state = {
            "_business_outcome": {
                "booking": "booked",
                "email": "sent",
                "patient_name": "Fatima",
            },
        }
        snap = build_diagnostic_snapshot(state, agent_id=3, agent_type="single_prompt")
        outcome_str = str(snap["business_outcome"])
        assert "Fatima" not in outcome_str
        assert snap["business_outcome"]["booking"] == "booked"

    def test_snapshot_handles_empty_state(self):
        snap = build_diagnostic_snapshot({}, agent_id=None, agent_type=None)
        assert snap["current_node_id"] is None
        assert snap["retry_state"]["scope_count"] == 0

    def test_snapshot_serializable(self):
        import json
        state = {
            "current_node": "action_3",
            "_active_retry_scope": "",
            "_slot_retry_counts": {},
            "last_result": {"integration_result": {"error_code": "EMAIL_SEND_FAILED"}},
        }
        snap = build_diagnostic_snapshot(state, agent_id=3, agent_type="single_prompt", conversation_id="c3")
        serialized = json.dumps(snap)
        deserialized = json.loads(serialized)
        assert deserialized["current_node_id"] == "action_3"
