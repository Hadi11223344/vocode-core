"""Deterministic SmileCare booking journey through real flow action handlers."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from voice_platform.api.workflow_routes import list_workflow_templates
from voice_platform.database import Integration
from voice_platform.flow.compiler import compile_flow, create_initial_state
from voice_platform.flow.nodes import (
    _normalize_sheets_lookup_output,
    create_node_handlers,
    merge_node_result,
)
from voice_platform.flow.slots import normalize_variable
from voice_platform.integrations.plugins.base import PluginExecutionRequest
from voice_platform.integrations.plugins.calendar import CalendarPlugin
from voice_platform.integrations.plugins.email import EmailPlugin
from voice_platform.integrations.plugins.registry import DefaultPluginRegistry
from voice_platform.integrations.plugins.sheets import SheetsPlugin
from voice_platform.runtime.flow.conditions import ConditionEvaluator


class FakeSheetsClient:
    def __init__(self) -> None:
        self.appended_rows: list[list[str]] = []

    async def read_rows(self, cell_range=None, max_rows=100):
        return [
            [
                "date", "patient_name", "phone", "email", "service", "dentist",
                "preferred_date", "preferred_time", "is_new_patient", "insurance", "status",
            ],
            [
                "2026-07-01", "Alex Patient", "+15555550100",
                "patient1@example.com", "routine check-up", "",
                "", "", "existing", "", "active",
            ],
        ]

    async def append_row(self, values, range=None):
        self.appended_rows.append(list(values))
        return {"updated_range": range, "updated_rows": 1, "row_appended": True}


class FakeCalendarClient:
    def __init__(self, appointment_date: str) -> None:
        self.appointment_date = appointment_date
        self.availability_calls: list[dict] = []
        self.created_events: list[dict] = []

    async def check_availability(self, **kwargs):
        self.availability_calls.append(dict(kwargs))
        return {
            "available_slots": [
                {
                    "start": f"{self.appointment_date}T15:00:00+05:00",
                    "end": f"{self.appointment_date}T15:30:00+05:00",
                }
            ],
            "busy_slots": [],
        }

    async def create_event(self, **kwargs):
        self.created_events.append(dict(kwargs))
        return {"id": "evt_smilecare_1", "html_link": "https://calendar.test/event/1", "event_created": True}


class FakeEmailClient:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_email(self, **kwargs):
        self.sent.append(dict(kwargs))
        return {"message_id": "mail_smilecare_1", "email_sent": True}


@pytest.mark.parametrize(
    ("patient_rows", "expected_found", "expected_count"),
    [
        (
            [
                ["date", "patient_name", "phone"],
                ["2026-07-01", "Alex Patient", "+15555550100"],
            ],
            True,
            1,
        ),
        (
            [
                ["date", "patient_name", "phone"],
                ["2026-07-01", "Different Patient", "03001111111"],
            ],
            False,
            0,
        ),
    ],
)
def test_sheets_lookup_normalization_matches_condition_contract(
    patient_rows,
    expected_found,
    expected_count,
):
    output, extracted_vars = _normalize_sheets_lookup_output(
        {
            "prefill": True,
            "integration_type": "google_sheets",
            "action": "read_rows",
            "has_header": True,
            "prefill_match_column": 2,
            "prefill_match_value": "{{caller_phone}}",
            "prefill_mapping": {1: "patient_name", 2: "caller_phone"},
        },
        {"success": True, "rows": patient_rows},
        {"caller_phone": "+15555550100"},
        {"extracted_vars": {"caller_phone": "+15555550100"}},
    )

    assert output["found"] is expected_found
    assert output["count"] == expected_count
    assert ConditionEvaluator().evaluate(
        "result.found == true",
        {"result": output},
    ) is expected_found
    if expected_found:
        assert extracted_vars["patient_name"] == "Alex Patient"
    else:
        assert output["rows"] == []
        assert "patient_name" not in extracted_vars


@pytest.mark.asyncio
async def test_exact_smilecare_conversation_reaches_truthful_booking_confirmation(
    db_session,
    test_user,
    monkeypatch,
):
    templates = (await list_workflow_templates())["templates"]
    template = next(item for item in templates if item["id"] == "smilecare_dental")
    graph = {"nodes": template["nodes"], "edges": template["edges"]}

    local_now = datetime.now(ZoneInfo("Asia/Karachi"))
    appointment_date = (local_now.date() + timedelta(days=1)).isoformat()
    sheets_client = FakeSheetsClient()
    calendar_client = FakeCalendarClient(appointment_date)
    email_client = FakeEmailClient()

    registry = DefaultPluginRegistry()
    registry.register("google_sheets", SheetsPlugin(client_factory=lambda _: sheets_client))
    registry.register("google_calendar", CalendarPlugin(client_factory=lambda _: calendar_client))
    registry.register("email", EmailPlugin(client_factory=lambda _: email_client))

    from voice_platform.integrations.plugins import registry as registry_module

    monkeypatch.setattr(registry_module, "build_default_plugin_registry", lambda: registry)

    for service_type in ("google_sheets", "google_calendar", "email"):
        db_session.add(
            Integration(
                user_id=test_user.id,
                service_type=service_type,
                name=f"Fake {service_type}",
                config_json=json.dumps({"deterministic_test": True}),
                is_active=True,
            )
        )
    await db_session.flush()

    scripted_values = {
        "conversation_1": {
            "visit_type": "booking",
            "is_emergency": "false",
            "patient_name": "Alex",
            "caller_name": "Alex",
        },
        "conversation_contact": {
            "patient_name": "Alex Patient",
            "caller_name": "Alex Patient",
            "caller_phone": "+15555550100",
            "phone": "+15555550100",
            "caller_email": "patient1@example.com",
            "email": "patient1@example.com",
        },
        "conversation_visit": {
            "service_requested": "routine check-up",
            "is_new_patient": "existing",
        },
        "conversation_schedule": {
            "preferred_date": appointment_date,
            "preferred_time": "15:00",
        },
        "conversation_dentist": {
            "preferred_dentist": normalize_variable(
                "preferred_dentist", "I'm not sure, please recommend"
            ),
        },
        "confirm_booking": {"confirm_booking": "yes"},
    }

    handlers = create_node_handlers()
    visited: list[str] = []
    emitted: list[dict] = []

    async def deterministic_conversation(state, config):
        node_id = state["current_node"]
        visited.append(node_id)
        extracted = {**state.get("extracted_vars", {}), **scripted_values.get(node_id, {})}
        return {
            "extracted_vars": extracted,
            "result": merge_node_result(state.get("result"), scripted_values.get(node_id, {})),
            "last_result": scripted_values.get(node_id, {}),
            "pending_variables_to_extract": [],
            "_slots_missing": [],
            "retry_count": 0,
            "_conversation_phase": "generate",
        }

    async def event_callback(event: dict):
        emitted.append(event)
        if event.get("event") == "node_start":
            visited.append(str(event.get("node_id")))

    handlers["conversation"] = deterministic_conversation
    compiled = compile_flow(graph, node_handlers=handlers)
    state = create_initial_state(
        graph,
        user_id=test_user.id,
        agent_id=101,
        agent_timezone="Asia/Karachi",
        caller_phone="+15555550100",
    )

    result = await compiled.ainvoke(
        state,
        config={
            "recursion_limit": 100,
            "configurable": {
                "thread_id": "smilecare-deterministic-booking",
                "conversation_id": "smilecare-test-conversation",
                "user_id": test_user.id,
                "agent_id": 101,
                "agent": SimpleNamespace(id=101, integration_overrides_json=None),
                "db_session": db_session,
                "event_callback": event_callback,
            },
        },
    )

    required_path = [
        "action_1",
        "condition_patient_found",
        "conversation_contact",
        "conversation_visit",
        "conversation_schedule",
        "conversation_dentist",
        "action_2",
        "condition_2",
        "confirm_booking",
        "condition_confirm",
        "action_3",
        "sheets_1",
        "email_1",
        "end_1",
    ]
    assert all(node_id in visited for node_id in required_path)
    assert "conversation_4" not in visited
    assert result["extracted_vars"]["caller_email"] == "patient1@example.com"
    assert result["extracted_vars"]["preferred_dentist"] == "any available dentist"
    assert result["result"]["requested_time_available"] is True

    # create_event path: availability checked once at action_2 (not via book_appointment recheck)
    assert len(calendar_client.availability_calls) == 1
    assert calendar_client.availability_calls[0]["date"] == appointment_date
    assert len(calendar_client.created_events) == 1
    created = calendar_client.created_events[0]
    assert created["start"].startswith(f"{appointment_date}T15:00")
    assert "Alex Patient" in created["summary"]
    assert "+15555550100" in created["description"]
    # Email is sent by email_1; create_event description contract does not include email.
    assert "patient1@example.com" not in created["description"]
    assert "routine check-up" in created["description"]
    assert "any available dentist" in created["description"]

    assert len(sheets_client.appended_rows) == 1
    assert sheets_client.appended_rows[0][0] == local_now.date().isoformat()
    assert "patient1@example.com" in sheets_client.appended_rows[0]
    assert len(email_client.sent) == 1
    assert email_client.sent[0]["to"] == "patient1@example.com"
    assert any(
        event.get("event") == "agent_token" and "appointment is confirmed" in event.get("text", "")
        for event in emitted
    )
    lookup_event = next(
        event
        for event in emitted
        if event.get("event") == "node_result" and event.get("node_id") == "action_1"
    )
    # Initial extract is first name only ("Alex"); sheet rows store full name
    # ("Alex Patient"). Prefill is exact-match, so found=False and conversation_contact
    # recovers the full contact fields — that is the production contract.
    assert lookup_event["result"]["found"] is False
    assert "conversation_contact" in visited


@pytest.mark.asyncio
async def test_check_availability_no_time_sets_requested_time_available_false():
    """A1: check_availability must always set requested_time_available, even when no time is provided."""
    from voice_platform.integrations.plugins.base import IntegrationConfiguration
    plugin = CalendarPlugin(client_factory=lambda _: FakeCalendarClient("2026-07-21"))
    result = await plugin.execute(PluginExecutionRequest(
        action="check_availability",
        params={"date": "2026-07-21"},
        integration=IntegrationConfiguration(
            service_type="google_calendar",
            config={"calendar_id": "primary", "timezone": "Asia/Karachi"},
            user_id=1,
        ),
    ))
    output = result.to_dict()
    assert output["success"] is True
    assert output["requested_time_available"] is False
    assert "available_slots" in output
    assert "available_slot_count" in output


def test_sanitize_event_preserves_row_count():
    """A2: _sanitize_event should preserve rows as {row_count: N} in node_result events."""
    from voice_platform.flow.nodes import _sanitize_event
    event = {
        "event": "node_result",
        "node_id": "action_1",
        "result": {
            "success": True,
            "rows": [["header"], ["data1", "data2"]],
            "count": 2,
            "found": True,
        },
    }
    sanitized = _sanitize_event(event)
    assert sanitized["result"]["rows"] == {"row_count": 2}
    assert sanitized["result"]["found"] is True
    assert sanitized["result"]["count"] == 2


@pytest.mark.asyncio
async def test_retry_counter_isolated_between_conditions():
    """A3: _slot_retry_count should be isolated between configured retry scopes."""
    from voice_platform.flow.nodes import create_node_handlers
    from voice_platform.flow.state import make_initial_state

    handlers = create_node_handlers()
    condition_handler = handlers["condition"]

    nodes_by_id = {
        "cond_a": {
            "id": "cond_a",
            "type": "condition",
            "data": {"label": "Cond A", "config": {"expression": "_slot_retry_count < 2", "retry_mode": "configured", "retry_scope": "cond_a:alt_time_retry"}},
        },
        "cond_b": {
            "id": "cond_b",
            "type": "condition",
            "data": {"label": "Cond B", "config": {"expression": "_slot_retry_count < 2", "retry_mode": "configured", "retry_scope": "cond_b:alt_time_retry"}},
        },
    }

    async def _noop(event: dict):
        pass

    # Simulate cond_a incrementing the counter to 2 (exhausted)
    state_a = make_initial_state(
        user_id=1, agent_id=1, nodes_by_id=nodes_by_id,
        outgoing={"cond_a": [], "cond_b": []},
    )
    state_a.update({
        "current_node": "cond_a",
        "_active_retry_scope": "",
        "_slot_retry_counts": {"cond_a:alt_time_retry": {"count": 1, "owner": "cond_a", "mode": "configured"}},
    })
    result_a = await condition_handler(state_a, {
        "configurable": {"conversation_id": "test", "event_callback": _noop},
    })
    assert result_a["_slot_retry_counts"]["cond_a:alt_time_retry"]["count"] == 2
    assert result_a["_retry_context"] == "cond_a"

    # Now cond_b evaluates — its own configured scope starts at 0, then increments to 1
    state_b = make_initial_state(
        user_id=1, agent_id=1, nodes_by_id=nodes_by_id,
        outgoing={"cond_a": [], "cond_b": []},
    )
    state_b.update({
        "current_node": "cond_b",
        "_active_retry_scope": "",
        "_slot_retry_counts": {"cond_a:alt_time_retry": {"count": 2, "owner": "cond_a", "mode": "configured"}},
    })
    result_b = await condition_handler(state_b, {
        "configurable": {"conversation_id": "test", "event_callback": _noop},
    })
    # cond_b initializes its own configured scope at 0, then increments to 1
    assert result_b["_slot_retry_counts"]["cond_b:alt_time_retry"]["count"] == 1
    assert result_b["_retry_context"] == "cond_b"


# ---------------------------------------------------------------------------
# RC1/RC2: merge_node_result regression tests
# ---------------------------------------------------------------------------


def test_merge_node_result_strips_stale_transient_keys():
    """B1: Stale branch/error from previous result must be stripped."""
    previous = {"available": True, "branch": "on_missing", "error": "Missing inputs"}
    current = {"success": True, "available": True, "requested_time_available": True}
    merged = merge_node_result(previous, current)
    assert "branch" not in merged
    assert "error" not in merged
    assert merged["available"] is True
    assert merged["requested_time_available"] is True
    assert merged["success"] is True


def test_merge_node_result_preserves_current_transient_keys():
    """B2: Current-node transient keys must remain intact."""
    previous = {"available": True, "branch": "old_branch"}
    current = {"success": False, "branch": "on_missing", "error": "Missing inputs"}
    merged = merge_node_result(previous, current)
    assert merged["branch"] == "on_missing"
    assert merged["error"] == "Missing inputs"
    assert merged["available"] is True


def test_merge_node_result_does_not_mutate_inputs():
    """B3: Neither input dictionary should be mutated."""
    previous = {"available": True, "branch": "on_missing", "error": "Missing"}
    current = {"success": True, "requested_time_available": True}
    prev_copy = dict(previous)
    curr_copy = dict(current)
    merge_node_result(previous, current)
    assert previous == prev_copy
    assert current == curr_copy


def test_merge_node_result_handles_none_inputs():
    """B4: None inputs should be treated as empty dicts."""
    merged = merge_node_result(None, None)
    assert merged == {}
    merged2 = merge_node_result(None, {"success": True})
    assert merged2 == {"success": True}
    merged3 = merge_node_result({"available": True}, None)
    assert merged3 == {"available": True}


def test_merge_node_result_preserves_persistent_keys():
    """B5: Non-transient keys from previous must survive."""
    previous = {
        "available": True,
        "requested_time_available": True,
        "found": True,
        "count": 1,
        "branch": "on_missing",
    }
    current = {"success": True}
    merged = merge_node_result(previous, current)
    assert merged["available"] is True
    assert merged["requested_time_available"] is True
    assert merged["found"] is True
    assert merged["count"] == 1
    assert "branch" not in merged


# ---------------------------------------------------------------------------
# RC1: Stale branch routing tests
# ---------------------------------------------------------------------------


def test_stale_branch_cleared_after_successful_action():
    """B6: After a successful action, stale branch must be gone from result."""
    from voice_platform.flow.compiler import _routing_branch_key

    # Simulate state after a prior on_missing failure
    state_after_missing = {
        "result": {
            "success": False,
            "error": "Missing required inputs: patient_name",
            "branch": "on_missing",
            "available": True,
        },
        "last_result": {"success": False, "branch": "on_missing"},
    }
    # Verify stale branch is present before fix
    assert _routing_branch_key(state_after_missing) == "on_missing"

    # Simulate successful action output (no branch key)
    output = {"success": True, "available": True, "requested_time_available": True}
    merged = merge_node_result(state_after_missing["result"], output)

    # After merge, branch must be gone
    assert "branch" not in merged
    assert "error" not in merged
    assert merged["requested_time_available"] is True

    # Routing branch key should now be empty
    new_state = {"result": merged, "last_result": output}
    assert _routing_branch_key(new_state) == ""


def test_stale_error_cleared_after_success():
    """B7: Stale error from prior node must be cleared after successful action."""
    previous = {"success": False, "error": "Missing required inputs: patient_name", "available": True}
    current = {"success": True, "available": True, "requested_time_available": True}
    merged = merge_node_result(previous, current)
    assert "error" not in merged
    assert merged["success"] is True


# ---------------------------------------------------------------------------
# RC5: flow_end emitted exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flow_end_emitted_once(db_session, test_user, monkeypatch):
    """B8: Backend must emit exactly one flow_end event for normal completion."""
    templates = (await list_workflow_templates())["templates"]
    template = next(item for item in templates if item["id"] == "smilecare_dental")
    graph = {"nodes": template["nodes"], "edges": template["edges"]}

    local_now = datetime.now(ZoneInfo("Asia/Karachi"))
    appointment_date = (local_now.date() + timedelta(days=1)).isoformat()
    sheets_client = FakeSheetsClient()
    calendar_client = FakeCalendarClient(appointment_date)
    email_client = FakeEmailClient()

    registry = DefaultPluginRegistry()
    registry.register("google_sheets", SheetsPlugin(client_factory=lambda _: sheets_client))
    registry.register("google_calendar", CalendarPlugin(client_factory=lambda _: calendar_client))
    registry.register("email", EmailPlugin(client_factory=lambda _: email_client))

    from voice_platform.integrations.plugins import registry as registry_module

    monkeypatch.setattr(registry_module, "build_default_plugin_registry", lambda: registry)

    for service_type in ("google_sheets", "google_calendar", "email"):
        db_session.add(
            Integration(
                user_id=test_user.id,
                service_type=service_type,
                name=f"Fake {service_type}",
                config_json=json.dumps({"deterministic_test": True}),
                is_active=True,
            )
        )
    await db_session.flush()

    scripted_values = {
        "conversation_1": {"visit_type": "booking", "is_emergency": "false", "patient_name": "Alex", "caller_name": "Alex"},
        "conversation_contact": {"patient_name": "Alex Patient", "caller_name": "Alex Patient", "caller_phone": "+15555550100", "phone": "+15555550100", "caller_email": "patient1@example.com", "email": "patient1@example.com"},
        "conversation_visit": {"service_requested": "routine check-up", "is_new_patient": "existing"},
        "conversation_schedule": {"preferred_date": appointment_date, "preferred_time": "15:00"},
        "conversation_dentist": {"preferred_dentist": normalize_variable("preferred_dentist", "please recommend")},
        "confirm_booking": {"confirm_booking": "yes"},
    }

    handlers = create_node_handlers()
    emitted: list[dict] = []

    async def deterministic_conversation(state, config):
        node_id = state["current_node"]
        extracted = {**state.get("extracted_vars", {}), **scripted_values.get(node_id, {})}
        return {
            "extracted_vars": extracted,
            "result": merge_node_result(state.get("result"), scripted_values.get(node_id, {})),
            "last_result": scripted_values.get(node_id, {}),
            "pending_variables_to_extract": [],
            "_slots_missing": [],
            "retry_count": 0,
            "_conversation_phase": "generate",
        }

    async def event_callback(event: dict):
        emitted.append(event)

    handlers["conversation"] = deterministic_conversation
    compiled = compile_flow(graph, node_handlers=handlers)
    state = create_initial_state(
        graph,
        user_id=test_user.id,
        agent_id=101,
        agent_timezone="Asia/Karachi",
        caller_phone="+15555550100",
    )

    await compiled.ainvoke(
        state,
        config={
            "recursion_limit": 100,
            "configurable": {
                "thread_id": "smilecare-flow-end-test",
                "conversation_id": "smilecare-test-conversation",
                "user_id": test_user.id,
                "agent_id": 101,
                "agent": SimpleNamespace(id=101, integration_overrides_json=None),
                "db_session": db_session,
                "event_callback": event_callback,
            },
        },
    )

    # FlowExecutor emits flow_end after ainvoke returns — simulate that here
    await event_callback({"event": "flow_end", "total_nodes": len(emitted)})

    flow_end_events = [e for e in emitted if e.get("event") == "flow_end"]
    assert len(flow_end_events) == 1, f"Expected 1 flow_end, got {len(flow_end_events)}: {flow_end_events}"


# ---------------------------------------------------------------------------
# Full booking chain tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_booking_chain_reaches_action3_sheets_email_end(
    db_session, test_user, monkeypatch,
):
    """B9: Available slot must reach the complete booking chain and return a booking ID."""
    templates = (await list_workflow_templates())["templates"]
    template = next(item for item in templates if item["id"] == "smilecare_dental")
    graph = {"nodes": template["nodes"], "edges": template["edges"]}

    local_now = datetime.now(ZoneInfo("Asia/Karachi"))
    appointment_date = (local_now.date() + timedelta(days=1)).isoformat()
    sheets_client = FakeSheetsClient()
    calendar_client = FakeCalendarClient(appointment_date)
    email_client = FakeEmailClient()

    registry = DefaultPluginRegistry()
    registry.register("google_sheets", SheetsPlugin(client_factory=lambda _: sheets_client))
    registry.register("google_calendar", CalendarPlugin(client_factory=lambda _: calendar_client))
    registry.register("email", EmailPlugin(client_factory=lambda _: email_client))

    from voice_platform.integrations.plugins import registry as registry_module

    monkeypatch.setattr(registry_module, "build_default_plugin_registry", lambda: registry)

    for service_type in ("google_sheets", "google_calendar", "email"):
        db_session.add(
            Integration(
                user_id=test_user.id,
                service_type=service_type,
                name=f"Fake {service_type}",
                config_json=json.dumps({"deterministic_test": True}),
                is_active=True,
            )
        )
    await db_session.flush()

    scripted_values = {
        "conversation_1": {"visit_type": "booking", "is_emergency": "false", "patient_name": "Alex", "caller_name": "Alex"},
        "conversation_contact": {"patient_name": "Alex Patient", "caller_name": "Alex Patient", "caller_phone": "+15555550100", "phone": "+15555550100", "caller_email": "patient1@example.com", "email": "patient1@example.com"},
        "conversation_visit": {"service_requested": "routine check-up", "is_new_patient": "existing"},
        "conversation_schedule": {"preferred_date": appointment_date, "preferred_time": "15:00"},
        "conversation_dentist": {"preferred_dentist": normalize_variable("preferred_dentist", "please recommend")},
        "confirm_booking": {"confirm_booking": "yes"},
    }

    handlers = create_node_handlers()
    visited: list[str] = []
    emitted: list[dict] = []

    async def deterministic_conversation(state, config):
        node_id = state["current_node"]
        visited.append(node_id)
        extracted = {**state.get("extracted_vars", {}), **scripted_values.get(node_id, {})}
        return {
            "extracted_vars": extracted,
            "result": merge_node_result(state.get("result"), scripted_values.get(node_id, {})),
            "last_result": scripted_values.get(node_id, {}),
            "pending_variables_to_extract": [],
            "_slots_missing": [],
            "retry_count": 0,
            "_conversation_phase": "generate",
        }

    async def event_callback(event: dict):
        emitted.append(event)
        if event.get("event") == "node_start":
            visited.append(str(event.get("node_id")))

    handlers["conversation"] = deterministic_conversation
    compiled = compile_flow(graph, node_handlers=handlers)
    state = create_initial_state(
        graph,
        user_id=test_user.id,
        agent_id=101,
        agent_timezone="Asia/Karachi",
        caller_phone="+15555550100",
    )

    result = await compiled.ainvoke(
        state,
        config={
            "recursion_limit": 100,
            "configurable": {
                "thread_id": "smilecare-booking-chain-test",
                "conversation_id": "smilecare-test-conversation",
                "user_id": test_user.id,
                "agent_id": 101,
                "agent": SimpleNamespace(id=101, integration_overrides_json=None),
                "db_session": db_session,
                "event_callback": event_callback,
            },
        },
    )

    # FlowExecutor emits flow_end after ainvoke returns — simulate that here
    await event_callback({"event": "flow_end", "total_nodes": len(emitted)})

    # Full booking chain must be visited
    required_chain = ["action_2", "condition_2", "confirm_booking", "condition_confirm", "action_3", "sheets_1", "email_1", "end_1"]
    for node_id in required_chain:
        assert node_id in visited, f"Missing {node_id} in visited chain: {visited}"

    # end_no_slot must NOT be visited
    assert "end_no_slot" not in visited, "end_no_slot was visited despite available=true"

    # action_3 must receive raw phone and email (not redacted)
    assert result["extracted_vars"]["caller_phone"] == "+15555550100"
    assert result["extracted_vars"]["caller_email"] == "patient1@example.com"

    # Calendar must have created an event (booking ID)
    assert len(calendar_client.created_events) == 1
    created = calendar_client.created_events[0]
    assert "+15555550100" in created["description"]
    # Email confirmation is owned by email_1, not the calendar description template.
    assert "patient1@example.com" not in created["description"]

    # Sheets must have received the booking
    assert len(sheets_client.appended_rows) == 1
    assert "patient1@example.com" in sheets_client.appended_rows[0]

    # Email must have been sent after booking
    assert len(email_client.sent) == 1
    assert email_client.sent[0]["to"] == "patient1@example.com"

    # Exactly one flow_end
    flow_end_events = [e for e in emitted if e.get("event") == "flow_end"]
    assert len(flow_end_events) == 1


# ---------------------------------------------------------------------------
# PII safety test
# ---------------------------------------------------------------------------


def test_pii_raw_in_state_redacted_in_logs():
    """B10: _redact_diagnostic_value must redact phone/email in diagnostics but not mutate state."""
    from voice_platform.flow.nodes import _redact_diagnostic_value

    raw_state = {
        "caller_phone": "+15555550100",
        "caller_email": "patient1@example.com",
        "patient_name": "Alex Patient",
    }

    # Redacted diagnostic should show placeholders
    redacted = _redact_diagnostic_value(raw_state)
    assert redacted["caller_phone"] == "[PHONE]"
    assert redacted["caller_email"] == "[EMAIL]"
    assert redacted["patient_name"] == "Alex Patient"

    # Original state must be unchanged
    assert raw_state["caller_phone"] == "+15555550100"
    assert raw_state["caller_email"] == "patient1@example.com"
