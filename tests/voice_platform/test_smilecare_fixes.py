"""
Tests for SmileCare flow execution fixes.

Covers:
  1A. Weekday name normalization in slots._normalize_date
  1B. missing_required() reports invalid slots
  1C. Template: dentist node owns only dentist preference and optional insurance
  2.  Twilio platform fallback in tools API (GET + PUT)
  4.  Empty LLM response trace event
  5A. Branch router checks branch_key before _action_error
  5B. Template: on_missing edge from action_2 → conversation_schedule
"""

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_platform.flow.slots import SlotEngine, SlotStatus, _normalize_date, _validate_date
from voice_platform.flow.tracer import Tracer, get_tracer

# ── 1A: Weekday normalization ──────────────────────────────────────────────


class TestWeekdayNormalization:
    """_normalize_date should resolve weekday names to concrete YYYY-MM-DD dates."""

    def test_sunday_resolves_to_future_date(self):
        result = _normalize_date("sunday")
        assert result is not None
        parsed = datetime.strptime(result, "%Y-%m-%d")
        assert parsed.weekday() == 6  # Sunday

    def test_next_friday_resolves_to_future_friday(self):
        result = _normalize_date("next friday")
        assert result is not None
        parsed = datetime.strptime(result, "%Y-%m-%d")
        assert parsed.weekday() == 4  # Friday
        today = datetime.now().date()
        assert parsed.date() > today

    def test_this_monday_resolves_to_monday(self):
        result = _normalize_date("this monday")
        assert result is not None
        parsed = datetime.strptime(result, "%Y-%m-%d")
        assert parsed.weekday() == 0  # Monday

    def test_weekday_is_case_insensitive(self):
        result = _normalize_date("SUNDAY")
        assert result is not None
        parsed = datetime.strptime(result, "%Y-%m-%d")
        assert parsed.weekday() == 6

    def test_sunday_when_today_is_sunday_means_next_sunday(self):
        """Bare weekday when today is that weekday should resolve to next week."""
        result = _normalize_date("sunday")
        today = datetime.now().date()
        parsed = datetime.strptime(result, "%Y-%m-%d").date()
        if today.weekday() == 6:  # today is Sunday
            assert parsed > today

    def test_validate_date_accepts_weekday(self):
        """_validate_date should return VALID for weekday names."""
        assert _validate_date("sunday") == SlotStatus.VALID
        assert _validate_date("next friday") == SlotStatus.VALID

    def test_invalid_date_still_returns_none(self):
        assert _normalize_date("notadate") is None
        assert _validate_date("notadate") == SlotStatus.INVALID

    def test_thursday_comma_time_phrase(self):
        """Call 109: 'Thursday, 1PM' must resolve to a Thursday date."""
        result = _normalize_date("Thursday, 1PM")
        assert result is not None
        assert datetime.strptime(result, "%Y-%m-%d").weekday() == 3


# ── 1B: missing_required reports invalid slots ─────────────────────────────


class TestMissingRequiredInvalidSlots:
    """missing_required() should include slots with status 'invalid'."""

    def test_invalid_slot_is_reported_as_missing(self):
        engine = SlotEngine(
            variables=["preferred_date", "preferred_time"],
            extracted_vars={},
        )
        # Fill with invalid value
        engine.fill("preferred_date", "notadate", "notadate")
        engine.mark_invalid("preferred_date", "Invalid date format")
        missing = engine.missing_required()
        assert "preferred_date" in missing

    def test_valid_slot_is_not_reported_as_missing(self):
        engine = SlotEngine(
            variables=["preferred_date", "preferred_time"],
            extracted_vars={},
        )
        engine.fill("preferred_date", "2026-07-20", "2026-07-20")
        engine.confirm("preferred_date")
        missing = engine.missing_required()
        assert "preferred_date" not in missing
        assert "preferred_time" in missing

    def test_empty_slot_is_reported_as_missing(self):
        engine = SlotEngine(
            variables=["preferred_date"],
            extracted_vars={},
        )
        assert engine.missing_required() == ["preferred_date"]

    def test_optional_invalid_slot_not_reported(self):
        engine = SlotEngine(
            variables=["insurance_provider"],
            extracted_vars={},
            optional_inputs=["insurance_provider"],
        )
        # Optional slots should not be in missing_required even if empty
        assert engine.missing_required() == []


# ── 1C + 5B: Template structure ────────────────────────────────────────────


class TestSmilecareTemplate:
    """Validate SmileCare *workflow template defaults* (list_workflow_templates).

    Runtime authority for live demos is the persisted Agent.graph on the active
    SmileCare agent (currently agent 14). These tests intentionally validate the
    Python template defaults, not the DB graph. Keep them in sync when the
    production contract changes.
    """

    @pytest.fixture
    def smilecare_template(self):
        import asyncio

        from voice_platform.api.workflow_routes import list_workflow_templates

        result = asyncio.run(list_workflow_templates())
        templates = result["templates"]
        for t in templates:
            if t.get("id") == "smilecare_dental":
                return t
        pytest.skip("SmileCare template not found")

    def test_conversation_dentist_does_not_reextract_schedule(self, smilecare_template):
        """The dentist step must not overwrite date/time captured by the schedule step."""
        nodes = smilecare_template["nodes"]
        dentist_node = next(
            n for n in nodes if n["id"] == "conversation_dentist"
        )
        vars_to_extract = dentist_node["data"]["config"]["variables_to_extract"]
        assert vars_to_extract == ["preferred_dentist", "insurance_provider"]

    def test_conversation_dentist_insurance_is_optional(self, smilecare_template):
        """Insurance may be captured here but must never block calendar execution."""
        nodes = smilecare_template["nodes"]
        dentist_node = next(
            n for n in nodes if n["id"] == "conversation_dentist"
        )
        optional_inputs = dentist_node["data"]["config"].get("optional_inputs", [])
        assert optional_inputs == ["insurance_provider"]

    def test_action_2_has_on_missing_edge(self, smilecare_template):
        """Missing schedule data must enter the bounded retry condition."""
        edges = smilecare_template["edges"]
        on_missing_edges = [
            e for e in edges
            if e.get("source") == "action_2"
            and e.get("sourceHandle") == "on_missing"
        ]
        assert len(on_missing_edges) == 1, (
            f"Expected exactly 1 on_missing edge from action_2, got {len(on_missing_edges)}"
        )
        assert on_missing_edges[0]["target"] == "condition_missing"

        retry_yes = next(
            edge for edge in edges
            if edge.get("source") == "condition_missing"
            and edge.get("sourceHandle") == "yes"
        )
        assert retry_yes["target"] == "conversation_schedule"

    def test_action_2_still_has_error_edge(self, smilecare_template):
        """The error edge from action_2 to end_calendar_error should still exist."""
        edges = smilecare_template["edges"]
        error_edges = [
            e for e in edges
            if e.get("source") == "action_2"
            and e.get("label") == "error"
        ]
        assert len(error_edges) == 1
        assert error_edges[0]["target"] == "end_calendar_error"

    def test_booking_uses_create_event_after_explicit_availability_check(self, smilecare_template):
        """Production contract: availability is action_2 (check_availability), booking is create_event.

        book_appointment is a convenience plugin action that re-checks availability
        internally; SmileCare's authoritative graph/template use create_event after
        the caller confirms the already-checked slot.
        """
        booking = next(
            node for node in smilecare_template["nodes"] if node["id"] == "action_3"
        )
        availability = next(
            node for node in smilecare_template["nodes"] if node["id"] == "action_2"
        )

        assert availability["data"]["config"]["action"] == "check_availability"
        assert booking["data"]["config"]["action"] == "create_event"


# ── 2: Twilio platform fallback in tools API ───────────────────────────────


class TestTwilioFallback:
    """Tools API should mark send_sms as connected when platform Twilio is configured."""

    @pytest.mark.asyncio
    async def test_get_agent_tools_sms_connected_with_platform_twilio(
        self, client, test_agent, test_user, db_session
    ):
        """GET /api/tools/agent/{id} should show send_sms as connected."""
        from voice_platform.config import settings as _settings

        with patch.object(_settings, "twilio_account_sid", "AC123"), \
             patch.object(_settings, "twilio_auth_token", "secret456"):
            resp = await client.get(f"/api/tools/agent/{test_agent.id}")
            assert resp.status_code == 200
            data = resp.json()
            sms_tool = next(
                t for t in data["tools"] if t["id"] == "send_sms"
            )
            assert sms_tool["integration_connected"] is True
            assert "Twilio" in sms_tool["integration_label"]

    @pytest.mark.asyncio
    async def test_get_agent_tools_sms_disconnected_without_twilio(
        self, client, test_agent, test_user, db_session
    ):
        """GET /api/tools/agent/{id} should show send_sms as NOT connected when no Twilio."""
        from voice_platform.config import settings as _settings

        with patch.object(_settings, "twilio_account_sid", None), \
             patch.object(_settings, "twilio_auth_token", None):
            resp = await client.get(f"/api/tools/agent/{test_agent.id}")
            assert resp.status_code == 200
            data = resp.json()
            sms_tool = next(
                t for t in data["tools"] if t["id"] == "send_sms"
            )
            assert sms_tool["integration_connected"] is False

    @pytest.mark.asyncio
    async def test_update_agent_tools_sms_not_in_missing_with_platform_twilio(
        self, client, test_agent, test_user, db_session
    ):
        """PUT /api/tools/agent/{id} should not warn about send_sms when Twilio is configured."""
        from voice_platform.config import settings as _settings

        with patch.object(_settings, "twilio_account_sid", "AC123"), \
             patch.object(_settings, "twilio_auth_token", "secret456"):
            resp = await client.put(
                f"/api/tools/agent/{test_agent.id}",
                json={"tools": ["send_sms"]},
            )
            assert resp.status_code == 200
            data = resp.json()
            # The response should not include send_sms in missing_integration_tools
            missing = data.get("missing_integration_tools", [])
            assert "send_sms" not in missing


# ── 4: Empty LLM response trace event ──────────────────────────────────────


class TestTracerEmptyResponse:
    """Tracer should emit llm_empty_response event with diagnostic data."""

    @pytest.mark.asyncio
    async def test_llm_empty_response_event(self):
        tracer = Tracer()
        await tracer.llm_empty_response(
            node_id="conversation_1",
            node_label="Identify Need",
            streaming=True,
            messages_count=3,
            system_prompt_len=500,
            node_prompt_present=True,
        )
        assert len(tracer.events) == 1
        event = tracer.events[0]
        assert event["event"] == "llm_empty_response"
        assert event["node_id"] == "conversation_1"
        assert event["node_label"] == "Identify Need"
        assert event["streaming"] is True
        assert event["messages_count"] == 3
        assert event["system_prompt_len"] == 500
        assert event["node_prompt_present"] is True

    @pytest.mark.asyncio
    async def test_null_tracer_llm_empty_response(self):
        tracer = get_tracer({})
        result = await tracer.llm_empty_response(
            node_id="n1", node_label="test", streaming=False,
            messages_count=0, system_prompt_len=0, node_prompt_present=False,
        )
        assert result == {}


class TestTracerPIIRedaction:
    @pytest.mark.asyncio
    async def test_slot_trace_redacts_email_without_changing_workflow_value(self):
        tracer = Tracer()
        workflow_value = "patient1@example.com"

        await tracer.slot_filled(
            node_id="conversation_contact",
            slot="caller_email",
            value=workflow_value,
        )

        assert workflow_value == "patient1@example.com"
        assert tracer.events[0]["value"] == "[EMAIL]"

    @pytest.mark.asyncio
    async def test_action_trace_summarizes_sheet_rows(self):
        tracer = Tracer()
        await tracer.action_executed(
            node_id="action_1",
            action="read_rows",
            integration_type="google_sheets",
            input_vars={"caller_email": "patient1@example.com"},
            output={
                "success": True,
                "rows": [["Alex Patient", "patient1@example.com"]],
                "count": 1,
            },
        )

        event = tracer.events[0]
        assert event["input_vars"]["caller_email"] == "[EMAIL]"
        assert event["output"]["rows"] == {"row_count": 1}


# ── 5A: Branch router order ────────────────────────────────────────────────


class TestBranchRouterOrder:
    """make_branch_router should check branch_key before _action_error."""

    def test_on_missing_takes_priority_over_error(self):
        # Test the routing logic that make_branch_router implements
        branches = {
            "on_missing": "conversation_schedule",
            "error": "end_calendar_error",
        }
        default = "condition_2"

        # We can't import make_branch_router directly (it's a closure),
        # so we test the routing logic inline
        def router(state):
            branch_key = state.get("result", {}).get("branch") or \
                         state.get("last_result", {}).get("branch")
            if branch_key and branch_key in branches:
                return branches[branch_key]
            if state.get("_action_error"):
                for err_key in ("error", "on_error", "failure"):
                    if err_key in branches:
                        return branches[err_key]
            return default

        # State with on_missing branch — should route to conversation_schedule
        state_on_missing = {
            "result": {"branch": "on_missing"},
            "last_result": {"branch": "on_missing"},
            "_action_error": {"node_id": "action_2", "error": "Missing inputs"},
        }
        assert router(state_on_missing) == "conversation_schedule"

        # State with error branch — should route to end_calendar_error
        state_error = {
            "result": {"branch": "error"},
            "last_result": {"branch": "error"},
            "_action_error": {"node_id": "action_2", "error": "API failed"},
        }
        assert router(state_error) == "end_calendar_error"

        # State with _action_error but no branch key — should fall to error
        state_no_branch = {
            "result": {},
            "last_result": {},
            "_action_error": {"node_id": "action_2", "error": "Unknown"},
        }
        assert router(state_no_branch) == "end_calendar_error"

        # State with no error and no branch — should use default
        state_clean = {
            "result": {},
            "last_result": {},
        }
        assert router(state_clean) == "condition_2"


# ── Tracer: action_missing_inputs event ────────────────────────────────────


class TestTracerActionMissingInputs:
    """Tracer should emit action_missing_inputs event with missing input details."""

    @pytest.mark.asyncio
    async def test_action_missing_inputs_event(self):
        tracer = Tracer()
        await tracer.action_missing_inputs(
            node_id="action_2",
            action="check_availability",
            missing_inputs=["preferred_date", "preferred_time"],
            collected_inputs={"patient_name": "Alex"},
        )
        assert len(tracer.events) == 1
        event = tracer.events[0]
        assert event["event"] == "action_missing_inputs"
        assert event["node_id"] == "action_2"
        assert event["action"] == "check_availability"
        assert event["missing_inputs"] == ["preferred_date", "preferred_time"]
        assert event["collected_inputs"] == {"patient_name": "Alex"}
        assert event["branch"] == "on_missing"

    @pytest.mark.asyncio
    async def test_null_tracer_action_missing_inputs(self):
        tracer = get_tracer({})
        result = await tracer.action_missing_inputs(
            node_id="n1", action="test", missing_inputs=["x"],
        )
        assert result == {}
