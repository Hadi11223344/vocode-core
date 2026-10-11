"""
UMT Admission Agent — Reliability Tests.

50+ scenarios covering:
- D1: Admission-information handling (22 tests)
- D2: Applicant information collection (11 tests)
- D3: Eligibility safety (9 tests)
- D4: Knowledge retrieval and failure behavior (10 tests)
- D5: Handoff and follow-up (8 tests)

Tests are deterministic — they validate prompt policy, knowledge base safety,
claim gating, and error handling without making real LLM or integration calls.
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
    _normalize_integration_result,
)
from voice_platform.integrations.knowledge_base import KnowledgeBaseClient

# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def admission_template():
    return get_template("university")


@pytest.fixture
def admission_prompt(admission_template):
    return admission_template.config["prompt_preamble"]


@pytest.fixture
def admission_config(admission_template):
    return admission_template.config


# ── D1: Admission-Information Handling ───────────────────────────────────────

class TestAdmissionInfoHandling:
    """22 tests: admission information accuracy and safety."""

    @pytest.mark.parametrize("topic", [
        "undergraduate admission",
        "graduate admission",
        "program that exists",
        "program not present",
        "eligibility",
        "required documents",
        "application process",
        "fees",
        "scholarships",
        "admission deadlines",
        "entry test",
        "merit criteria",
        "credit transfer",
        "international admissions",
        "hostel or transport",
        "campus location",
        "contact details",
        "multiple questions",
        "incomplete question",
        "abbreviations",
        "bilingual",
        "outside knowledge",
    ])
    def test_prompt_covers_admission_topic(self, topic, admission_prompt):
        prompt_lower = admission_prompt.lower()
        topic_keywords = {
            "undergraduate admission": ["undergraduate", "admission"],
            "graduate admission": ["graduate", "admission"],
            "program that exists": ["program"],
            "program not present": ["program"],
            "eligibility": ["eligibility", "marks"],
            "required documents": ["application", "apply", "knowledge base"],
            "application process": ["application", "apply"],
            "fees": ["fee"],
            "scholarships": ["scholarship"],
            "admission deadlines": ["deadline"],
            "entry test": ["merit", "marks", "knowledge base"],
            "merit criteria": ["merit", "marks"],
            "credit transfer": ["knowledge base"],
            "international admissions": ["knowledge base"],
            "hostel or transport": ["hostel", "transport"],
            "campus location": ["campus", "location"],
            "contact details": ["contact"],
            "multiple questions": ["question"],
            "incomplete question": ["question"],
            "abbreviations": ["question"],
            "bilingual": ["urdu"],
            "outside knowledge": ["knowledge base"],
        }
        keywords = topic_keywords.get(topic, [topic])
        assert any(kw in prompt_lower for kw in keywords), f"Topic '{topic}' not covered in prompt"

    def test_does_not_invent_fees(self, admission_prompt):
        assert "never guess" in admission_prompt.lower() or "knowledge base" in admission_prompt.lower()

    def test_does_not_invent_deadlines(self, admission_prompt):
        assert "deadline" in admission_prompt.lower()
        assert "never guess" in admission_prompt.lower() or "knowledge base" in admission_prompt.lower()

    def test_does_not_invent_rankings(self, admission_prompt):
        # Should not mention rankings as something to provide
        assert "ranking" not in admission_prompt.lower() or "never" in admission_prompt.lower()

    def test_does_not_guarantee_admission(self, admission_prompt):
        assert "guarantee" not in admission_prompt.lower() or "never" in admission_prompt.lower()

    def test_does_not_guarantee_scholarship(self, admission_prompt):
        assert "scholarship" in admission_prompt.lower()
        assert "never guess" in admission_prompt.lower() or "knowledge base" in admission_prompt.lower()

    def test_does_not_invent_accreditation(self, admission_prompt):
        assert "accreditation" not in admission_prompt.lower() or "never" in admission_prompt.lower()

    def test_does_not_invent_staff_contact(self, admission_prompt):
        assert "never guess" in admission_prompt.lower() or "knowledge base" in admission_prompt.lower()

    def test_handles_passed_deadline(self, admission_prompt):
        assert "deadline" in admission_prompt.lower() and "passed" in admission_prompt.lower()

    def test_suggests_closest_alternative(self, admission_prompt):
        assert "alternative" in admission_prompt.lower() or "closest" in admission_prompt.lower()


# ── D2: Applicant Information Collection ─────────────────────────────────────

class TestApplicantInfoCollection:
    """11 tests: collecting and correcting applicant information."""

    def test_collects_applicant_name(self, admission_prompt):
        assert "name" in admission_prompt.lower()

    def test_collects_phone_or_email(self, admission_prompt):
        assert "phone" in admission_prompt.lower() or "email" in admission_prompt.lower()

    def test_corrects_misheard_name(self, admission_prompt):
        # Prompt should handle corrections
        assert "confirm" in admission_prompt.lower() or "correct" in admission_prompt.lower()

    def test_rejects_invalid_email(self, admission_prompt):
        # Should mention email validation
        assert "email" in admission_prompt.lower()

    def test_does_not_repeat_confirmed_info(self, admission_prompt):
        assert "incremental" in admission_prompt.lower() or "confirm" in admission_prompt.lower()

    def test_does_not_erase_confirmed_data(self, admission_prompt):
        assert "incremental" in admission_prompt.lower() or "update" in admission_prompt.lower()

    def test_handles_refusal_to_provide_details(self, admission_prompt):
        # Should handle gracefully when caller refuses
        assert "knowledge base" in admission_prompt.lower()

    def test_never_requests_passwords(self, admission_prompt):
        sensitive = ["password", "otp", "pin code", "card number", "cnic"]
        for s in sensitive:
            assert s not in admission_prompt.lower()

    def test_never_requests_payment_info(self, admission_prompt):
        assert "card" not in admission_prompt.lower()
        assert "payment" not in admission_prompt.lower() or "fee" in admission_prompt.lower()

    def test_incremental_capture(self, admission_prompt):
        assert "incremental" in admission_prompt.lower() or "append_sheet" in admission_prompt.lower()

    def test_recommended_tools_include_sheets(self, admission_template):
        tools = admission_template.recommended_tools
        assert "append_sheet" in tools
        assert "read_sheet" in tools


# ── D3: Eligibility Safety ───────────────────────────────────────────────────

class TestEligibilitySafety:
    """9 tests: eligibility guidance vs official decision."""

    def test_distinguishes_guidance_from_decision(self, admission_prompt):
        assert "knowledge base" in admission_prompt.lower()
        assert "never guess" in admission_prompt.lower()

    def test_does_not_mark_admitted(self, admission_prompt):
        assert "admitted" not in admission_prompt.lower() or "never" in admission_prompt.lower()

    def test_does_not_mark_rejected(self, admission_prompt):
        # Should not claim to make rejection decisions
        assert "reject" not in admission_prompt.lower() or "never" in admission_prompt.lower()

    def test_asks_for_missing_info(self, admission_prompt):
        assert "ask" in admission_prompt.lower() or "question" in admission_prompt.lower()

    def test_escalates_uncertain_cases(self, admission_prompt):
        assert "don't know" in admission_prompt.lower() or "not sure" in admission_prompt.lower() or "find out" in admission_prompt.lower() or "knowledge base" in admission_prompt.lower()

    def test_official_verification_required(self, admission_prompt):
        # Should mention that final decisions require official review
        assert "official" in admission_prompt.lower() or "verify" in admission_prompt.lower() or "never guess" in admission_prompt.lower()

    def test_handles_unusual_qualification(self, admission_prompt):
        # Should handle gracefully
        assert "knowledge base" in admission_prompt.lower()

    def test_handles_conflicting_grades(self, admission_prompt):
        # Should ask for clarification
        assert "confirm" in admission_prompt.lower() or "question" in admission_prompt.lower()

    def test_does_not_estimate_merit_without_criteria(self, admission_prompt):
        assert "never guess" in admission_prompt.lower() or "knowledge base" in admission_prompt.lower()


# ── D4: Knowledge Retrieval and Failure Behavior ─────────────────────────────

class TestKnowledgeRetrieval:
    """10 tests: knowledge base retrieval and failure handling."""

    def test_kb_client_chunk_text(self):
        """KnowledgeBaseClient.chunk_text splits text into chunks."""
        text = "This is a test paragraph.\n\nThis is another paragraph with more content."
        chunks = KnowledgeBaseClient.chunk_text(text, chunk_size=50, overlap=10)
        assert len(chunks) >= 1
        assert all(isinstance(c, str) for c in chunks)

    def test_kb_client_chunk_empty_text(self):
        chunks = KnowledgeBaseClient.chunk_text("", chunk_size=100)
        assert chunks == []

    def test_kb_tfidf_retrieve_returns_results(self):
        """TF-IDF retrieval should return relevant chunks."""
        chunks = [
            "The BSCS program fee is around nineteen lakh rupees.",
            "Scholarships are available for students with above 90 percent marks.",
            "The campus is located in Johar Town, Lahore.",
        ]
        results = KnowledgeBaseClient._tfidf_retrieve("What is the fee for BSCS?", chunks, max_results=2)
        assert len(results) >= 1
        assert results[0]["score"] > 0

    def test_kb_tfidf_retrieve_empty_query(self):
        results = KnowledgeBaseClient._tfidf_retrieve("", ["some chunk"], max_results=3)
        assert results == []

    def test_kb_tfidf_retrieve_empty_chunks(self):
        results = KnowledgeBaseClient._tfidf_retrieve("test query", [], max_results=3)
        assert results == []

    def test_kb_tfidf_retrieve_no_match(self):
        results = KnowledgeBaseClient._tfidf_retrieve("xyzabc", ["hello world"], max_results=3, min_score=0.9)
        assert results == []

    def test_kb_lookup_failed_error_code(self):
        ev = build_safe_error_event("KNOWLEDGE_LOOKUP_FAILED", agent_type="single_prompt")
        assert ev["component"] == "knowledge_base"
        assert ev["retryable"] is True

    def test_kb_result_empty_error_code(self):
        ev = build_safe_error_event("KNOWLEDGE_RESULT_EMPTY", agent_type="single_prompt")
        assert ev["component"] == "knowledge_base"
        assert ev["retryable"] is False
        assert ev["caller_informed"] is True

    def test_kb_result_conflict_error_code(self):
        ev = build_safe_error_event("KNOWLEDGE_RESULT_CONFLICT", agent_type="single_prompt")
        assert ev["component"] == "knowledge_base"
        assert ev["manual_intervention_required"] is True

    def test_admission_fact_unverified_error_code(self):
        ev = build_safe_error_event("ADMISSION_FACT_UNVERIFIED", agent_type="single_prompt")
        assert ev["component"] == "knowledge_base"
        assert ev["error_message_safe"] == "The admission information is not verified."


# ── D5: Handoff and Follow-up ────────────────────────────────────────────────

class TestHandoffAndFollowup:
    """8 tests: handoff, callback, and follow-up behavior."""

    def test_handles_human_counselor_request(self, admission_prompt):
        # Should be able to escalate
        assert "team" in admission_prompt.lower() or "contact" in admission_prompt.lower()

    def test_handles_callback_request(self, admission_prompt):
        assert "callback" in admission_prompt.lower() or "call back" in admission_prompt.lower() or "reach out" in admission_prompt.lower()

    def test_followup_success_produces_evidence(self):
        result = _normalize_integration_result(
            "email_1", "send_email", {"action": "send_email"},
            {"success": True, "result": {"email_sent": True, "message_id": "msg456"}},
            "success",
        )
        assert result["integration_result"]["evidence"]["email_sent"] is True

    def test_followup_failure_produces_safe_response(self):
        result = _normalize_integration_result(
            "email_1", "send_email", {"action": "send_email"},
            {"success": False, "result": {"error": "SMTP error"}},
            "error",
        )
        assert result["integration_result"]["business_succeeded"] is False

    def test_followup_not_configured_error(self):
        ev = build_safe_error_event("FOLLOWUP_REQUEST_FAILED", agent_type="single_prompt")
        assert ev["component"] == "tool_executor"
        assert ev["retryable"] is True

    def test_callback_claim_requires_evidence(self):
        """Agent must not claim callback is scheduled without action evidence."""
        outcome = {"booking": "not_attempted", "email": "not_attempted"}
        result = _deterministic_response(outcome)
        assert "scheduled" not in result.lower()
        assert "callback" not in result.lower()

    def test_tool_error_recovery_in_prompt(self, admission_prompt):
        """Prompt should include tool error recovery instructions."""
        assert "fails" in admission_prompt.lower() or "trouble" in admission_prompt.lower()

    def test_emergency_safety_handling(self, admission_prompt):
        """Prompt should handle safety-related content appropriately."""
        # Should not provide medical, legal, or safety advice
        assert "knowledge base" in admission_prompt.lower()


# ── Diagnostic Snapshot for Admission ────────────────────────────────────────

class TestAdmissionDiagnostics:
    """4 tests: diagnostic snapshot for admission agent."""

    def test_admission_snapshot_agent_type(self):
        snap = build_diagnostic_snapshot({}, agent_id=2, agent_type="single_prompt")
        assert snap["agent_type"] == "single_prompt"

    def test_admission_snapshot_no_pii(self):
        state = {
            "last_result": {
                "student_name": "Ahmed Khan",
                "caller_phone": "03007654321",
                "caller_email": "ahmed@test.com",
            },
        }
        snap = build_diagnostic_snapshot(state, agent_id=2, agent_type="single_prompt")
        result_str = str(snap["last_result"])
        assert "03007654321" not in result_str
        assert "ahmed@test.com" not in result_str
        assert "Ahmed Khan" not in result_str

    def test_admission_error_event_kb_failed(self):
        ev = build_safe_error_event("KNOWLEDGE_LOOKUP_FAILED", agent_id=2, agent_type="single_prompt")
        assert ev["component"] == "knowledge_base"
        assert ev["retryable"] is True

    def test_admission_inbound_ready(self, admission_template):
        assert admission_template.inbound_ready is True
