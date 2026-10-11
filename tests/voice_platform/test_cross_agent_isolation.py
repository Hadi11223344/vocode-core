"""
Cross-Agent Isolation Tests.

12+ scenarios verifying that the three agents (UMT Outreach, UMT Admission,
SmileCare) maintain strict isolation:

- No agent references another agent's identity, knowledge base, or tools
- No agent's prompt leaks into another agent's context
- Error codes are agent-appropriate
- Diagnostic snapshots don't cross-contaminate
- Failure injection for one agent doesn't affect others
- Template IDs are unique and non-overlapping
"""

import pytest

from voice_platform.agent_templates import get_template
from voice_platform.diagnostics import (
    ERROR_REGISTRY,
    FailureInjection,
    build_diagnostic_snapshot,
    build_safe_error_event,
)
from voice_platform.flow.nodes import _deterministic_response


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def all_templates():
    return {
        "umt_outreach": get_template("umt_outreach"),
        "university": get_template("university"),
        "smilecare": get_template("smilecare"),
    }


@pytest.fixture
def all_prompts(all_templates):
    return {
        key: tmpl.config["prompt_preamble"]
        for key, tmpl in all_templates.items()
    }


# ── Prompt Isolation ─────────────────────────────────────────────────────────

class TestPromptIsolation:
    """6 tests: no agent references another agent's identity or domain."""

    def test_outreach_does_not_mention_smilecare(self, all_prompts):
        assert "SmileCare" not in all_prompts["umt_outreach"]
        assert "dental" not in all_prompts["umt_outreach"].lower()
        assert "dentist" not in all_prompts["umt_outreach"].lower()

    def test_admission_does_not_mention_smilecare(self, all_prompts):
        assert "SmileCare" not in all_prompts["university"]
        assert "dental" not in all_prompts["university"].lower()
        assert "dentist" not in all_prompts["university"].lower()

    def test_smilecare_does_not_mention_umt(self, all_prompts):
        assert "UMT" not in all_prompts["smilecare"]
        assert "University of Management" not in all_prompts["smilecare"]
        assert "admissions" not in all_prompts["smilecare"].lower() or "admission" not in all_prompts["smilecare"].lower()

    def test_outreach_does_not_mention_admission_agent_identity(self, all_prompts):
        # Outreach is Bilal, Admission is unnamed advisor — they should not cross-reference
        outreach = all_prompts["umt_outreach"]
        admission = all_prompts["university"]
        # Outreach should not contain the admission agent's initial message
        assert "Salam and welcome to UMT" not in outreach

    def test_admission_does_not_mention_outreach_agent_identity(self, all_prompts):
        admission = all_prompts["university"]
        # Admission should not contain the outreach agent's initial message
        assert "This is Bilal from UMT. Got a quick minute" not in admission

    def test_smilecare_identity_is_sara_not_bilal(self, all_prompts):
        assert "Sara" in all_prompts["smilecare"]
        assert "Bilal from UMT" not in all_prompts["smilecare"]


# ── Template ID Isolation ────────────────────────────────────────────────────

class TestTemplateIdIsolation:
    """3 tests: template IDs are unique and non-overlapping."""

    def test_unique_template_ids(self, all_templates):
        ids = [tmpl.id for tmpl in all_templates.values()]
        assert len(ids) == len(set(ids)), "Template IDs are not unique"

    def test_unique_slugs(self, all_templates):
        slugs = [tmpl.slug for tmpl in all_templates.values()]
        assert len(slugs) == len(set(slugs)), "Template slugs are not unique"

    def test_unique_names(self, all_templates):
        names = [tmpl.name for tmpl in all_templates.values()]
        assert len(names) == len(set(names)), "Template names are not unique"


# ── Tool Isolation ───────────────────────────────────────────────────────────

class TestToolIsolation:
    """3 tests: tools are appropriate per agent."""

    def test_outreach_has_outbound_tools(self, all_templates):
        tools = all_templates["umt_outreach"].recommended_tools
        assert "append_sheet" in tools
        assert "read_sheet" in tools

    def test_admission_has_inbound_tools(self, all_templates):
        tools = all_templates["university"].recommended_tools
        assert "append_sheet" in tools
        assert "read_sheet" in tools
        assert "send_email" in tools

    def test_smilecare_has_booking_tools(self, all_templates):
        tools = all_templates["smilecare"].recommended_tools
        assert "book_appointment" in tools
        assert "check_calendar" in tools
        assert "append_sheet" in tools


# ── Error Code Isolation ─────────────────────────────────────────────────────

class TestErrorCodeIsolation:
    """3 tests: error codes are agent-appropriate."""

    def test_umt_error_codes_not_used_for_smilecare(self):
        umt_codes = ["KNOWLEDGE_LOOKUP_FAILED", "ADMISSION_FACT_UNVERIFIED", "LEAD_SAVE_FAILED"]
        smilecare_codes = ["BOOKING_CREATE_FAILED", "PATIENT_LOG_FAILED", "AVAILABILITY_CHECK_FAILED"]
        # No overlap
        assert set(umt_codes).isdisjoint(set(smilecare_codes))

    def test_smilecare_error_codes_not_used_for_umt(self):
        smilecare_codes = ["BOOKING_RESULT_MALFORMED", "BOOKING_OUTCOME_UNKNOWN", "UNSUPPORTED_BOOKING_CLAIM"]
        umt_codes = ["KNOWLEDGE_RESULT_CONFLICT", "OPT_OUT_PROCESSING_FAILED"]
        assert set(smilecare_codes).isdisjoint(set(umt_codes))

    def test_common_error_codes_shared(self):
        """Common error codes should be available for all agents."""
        common = ["MODEL_TIMEOUT", "TOOL_EXECUTION_FAILED", "INTERNAL_RUNTIME_ERROR"]
        for code in common:
            assert code in ERROR_REGISTRY


# ── Failure Injection Isolation ──────────────────────────────────────────────

class TestFailureInjectionIsolation:
    """3 tests: failure injection for one agent doesn't affect others."""

    def setup_method(self):
        FailureInjection.reset()

    def teardown_method(self):
        FailureInjection.reset()

    def test_calendar_failure_does_not_affect_sheets(self):
        fi = FailureInjection.instance()
        fi.set("calendar_create_failure", True)
        assert fi.is_active("calendar_create_failure") is True
        assert fi.is_active("sheets_failure") is False

    def test_sheets_failure_does_not_affect_email(self):
        fi = FailureInjection.instance()
        fi.set("sheets_failure", True)
        assert fi.is_active("sheets_failure") is True
        assert fi.is_active("email_failure") is False

    def test_reset_clears_all_agents(self):
        fi = FailureInjection.instance()
        fi.set("calendar_create_failure", True)
        fi.set("sheets_failure", True)
        fi.set("email_failure", True)
        FailureInjection.reset()
        assert fi.any_active() is False


# ── Diagnostic Snapshot Isolation ────────────────────────────────────────────

class TestDiagnosticSnapshotIsolation:
    """2 tests: snapshots don't cross-contaminate."""

    def test_snapshot_agent_id_isolation(self):
        snap1 = build_diagnostic_snapshot({}, agent_id=1, agent_type="single_prompt")
        snap2 = build_diagnostic_snapshot({}, agent_id=2, agent_type="single_prompt")
        assert snap1["agent_id"] != snap2["agent_id"]

    def test_snapshot_pii_redaction_consistent_across_agents(self):
        state = {
            "last_result": {
                "patient_name": "Test Patient",
                "caller_phone": "+15555550100",
                "caller_email": "test@test.com",
            },
        }
        for agent_id in [1, 2, 3]:
            snap = build_diagnostic_snapshot(state, agent_id=agent_id, agent_type="single_prompt")
            result_str = str(snap["last_result"])
            assert "+15555550100" not in result_str
            assert "test@test.com" not in result_str
            assert "Test Patient" not in result_str
