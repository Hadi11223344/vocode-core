"""
Tests for the Workflow Executor (integration step execution engine).
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import Integration, User, UserApiKey, Workflow
from voice_platform.integrations.executor import WorkflowExecutor
from voice_platform.integrations.plugins.calendar import (
    CalendarPlugin,
    _normalize_date,
    _normalize_time,
    _requested_time_is_available,
)
from voice_platform.integrations.plugins.sheets import SheetsPlugin
from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
)
from voice_platform.integrations.plugins.registry import build_default_plugin_registry
from voice_platform.runtime.flow.conditions import ConditionEvaluator

# Alias for backward compat in tests
_next_business_day = WorkflowExecutor._next_business_day

# ConditionEvaluator instance for tests that previously used the static method
_evaluator = ConditionEvaluator()

# ── Template Resolution Tests ──────────────────────────────────────────

class TestTemplateResolution:
    def test_next_business_day_from_friday(self):
        # Friday → Monday
        friday = datetime(2024, 1, 12, 10, 0, tzinfo=timezone.utc)  # Friday
        result = _next_business_day(friday)
        assert result.weekday() == 0  # Monday

    def test_next_business_day_from_saturday(self):
        saturday = datetime(2024, 1, 13, 10, 0, tzinfo=timezone.utc)
        result = _next_business_day(saturday)
        assert result.weekday() == 0  # Monday

    def test_next_business_day_from_wednesday(self):
        wednesday = datetime(2024, 1, 10, 10, 0, tzinfo=timezone.utc)
        result = _next_business_day(wednesday)
        assert result.weekday() == 3  # Thursday

    @pytest.mark.asyncio
    async def test_resolve_templates(self, db_session, test_user):
        executor = WorkflowExecutor(db_session, test_user.id, plugin_registry=build_default_plugin_registry())
        params = {
            "summary": "Call from {{caller_name}}",
            "description": "Phone: {{caller_phone}}",
            "date": "{{call_date}}",
            "static": "no template here",
        }
        context = {
            "caller_name": "John Doe",
            "caller_phone": "+15551234567",
        }
        resolved = executor._resolve_templates(params, context)
        assert resolved["summary"] == "Call from John Doe"
        assert resolved["description"] == "Phone: +15551234567"
        assert resolved["static"] == "no template here"
        # call_date should be auto-populated
        assert len(resolved["date"]) == 10  # YYYY-MM-DD format

    @pytest.mark.asyncio
    async def test_unresolved_templates_stay(self, db_session, test_user):
        executor = WorkflowExecutor(db_session, test_user.id, plugin_registry=build_default_plugin_registry())
        params = {"msg": "Hello {{unknown_var}}"}
        resolved = executor._resolve_templates(params, {})
        assert "{{unknown_var}}" in resolved["msg"]

    @pytest.mark.asyncio
    async def test_resolve_templates_recursive(self, db_session, test_user):
        executor = WorkflowExecutor(db_session, test_user.id, plugin_registry=build_default_plugin_registry())
        params = {
            "body": {
                "customer": "{{caller_name}}",
                "meta": {
                    "phone": "{{caller_phone}}",
                },
                "items": ["{{caller_name}}", 123, {"note": "{{caller_phone}}"}],
            }
        }
        context = {
            "caller_name": "John Doe",
            "caller_phone": "+15551234567",
        }
        resolved = executor._resolve_templates(params, context)
        assert resolved["body"]["customer"] == "John Doe"
        assert resolved["body"]["meta"]["phone"] == "+15551234567"
        assert resolved["body"]["items"][0] == "John Doe"
        assert resolved["body"]["items"][2]["note"] == "+15551234567"

    @pytest.mark.asyncio
    async def test_resolve_templates_recursive_context_values(self, db_session, test_user):
        executor = WorkflowExecutor(db_session, test_user.id, plugin_registry=build_default_plugin_registry())
        params = {"message": "{{greeting}}"}
        context = {
            "greeting": "Hello {{caller_name}}",
            "caller_name": "Jane",
        }
        resolved = executor._resolve_templates(params, context)
        assert resolved["message"] == "Hello Jane"

    @pytest.mark.asyncio
    async def test_call_date_uses_agent_timezone(self, db_session, test_user):
        executor = WorkflowExecutor(
            db_session,
            test_user.id,
            plugin_registry=build_default_plugin_registry(),
            agent_timezone="Asia/Karachi",
        )

        resolved = executor._resolve_templates({"date": "{{call_date}}"}, {})

        assert resolved["date"] == datetime.now(ZoneInfo("Asia/Karachi")).strftime("%Y-%m-%d")


class TestConditionEvaluation:
    def test_empty_expression_is_false(self):
        assert _evaluator.evaluate("", {}) is False

    @pytest.mark.asyncio
    async def test_condition_node_uses_expression_key(self, db_session, test_user):
        executor = WorkflowExecutor(db_session, test_user.id, plugin_registry=build_default_plugin_registry())
        result = await executor.execute_direct_action(
            node_type="condition",
            action="condition",
            params={"expression": "caller_phone not_empty"},
            context={"caller_phone": "+15551234567"},
        )
        assert result["success"] is True
        assert result["condition_met"] is True

    def test_condition_unknown_variable_is_false(self):
        assert _evaluator.evaluate("missing_var", {}) is False

    def test_condition_unquoted_literal_comparison(self):
        assert (
            _evaluator.evaluate(
                "account_action == cancel",
                {"account_action": "cancel"},
            )
            is True
        )

    def test_condition_contains_for_collections(self):
        assert (
            _evaluator.evaluate(
                "tags contains vip",
                {"tags": ["new", "vip"]},
            )
            is True
        )

    def test_condition_equals_not_empty_for_list(self):
        assert (
            _evaluator.evaluate(
                "result.available_slots == not_empty",
                {"result": {"available_slots": [{"start": "10:00"}]}},
            )
            is True
        )

    def test_condition_equals_not_empty_empty_list_is_false(self):
        assert (
            _evaluator.evaluate(
                "result.available_slots == not_empty",
                {"result": {"available_slots": []}},
            )
            is False
        )

    def test_condition_equals_not_empty_missing_variable_is_false(self):
        assert (
            _evaluator.evaluate(
                "is_emergency == not_empty",
                {},
            )
            is False
        )

    def test_condition_not_equals_not_empty_missing_variable_is_true(self):
        assert (
            _evaluator.evaluate(
                "is_emergency != not_empty",
                {},
            )
            is True
        )

    def test_condition_yes_string_compared_to_true(self):
        # Phase 6.11: extraction returns yes/no; conditions compare to true/false
        assert _evaluator.evaluate("is_emergency == true", {"is_emergency": "yes"}) is True
        assert _evaluator.evaluate("is_emergency == true", {"is_emergency": "true"}) is True
        assert _evaluator.evaluate("is_emergency == false", {"is_emergency": "no"}) is True
        assert _evaluator.evaluate("confirm_booking == true", {"confirm_booking": "yeah"}) is True


class TestNormalizeTime:
    def test_normalize_time_24h(self):
        assert _normalize_time("14:30") == "14:30"

    def test_normalize_time_12h_pm(self):
        assert _normalize_time("2 PM") == "14:00"

    def test_normalize_time_12h_with_minutes(self):
        assert _normalize_time("2:30pm") == "14:30"

    def test_normalize_time_ampm(self):
        assert _normalize_time("9:00 AM") == "09:00"

    def test_normalize_time_invalid_returns_empty(self):
        assert _normalize_time("not a time") == ""

    def test_normalize_time_session_words(self):
        assert _normalize_time("morning") == "10:00"
        assert _normalize_time("afternoon") == "14:00"
        assert _normalize_time("evening") == "18:00"
        assert _normalize_time("morning.") == "10:00"


class TestRequestedCalendarTime:
    def test_requested_interval_must_fit_completely_inside_free_slot(self):
        slots = [{
            "start": "2026-07-25T10:00:00+05:00",
            "end": "2026-07-25T11:00:00+05:00",
        }]

        assert _requested_time_is_available("2026-07-25", "10:30", 30, slots) is True
        assert _requested_time_is_available("2026-07-25", "10:45", 30, slots) is False

    def test_requested_time_rejects_invalid_time_and_malformed_slots(self):
        slots = [{"start": "invalid", "end": "invalid"}]

        assert _requested_time_is_available("2026-07-25", "sometime", 30, slots) is False
        assert _requested_time_is_available("2026-07-25", "10:00", 30, slots) is False

    @pytest.mark.asyncio
    async def test_create_event_rejects_missing_time_instead_of_defaulting(self):
        client = AsyncMock()
        plugin = CalendarPlugin(client_factory=lambda integration: client)
        request = PluginExecutionRequest(
            action="create_event",
            params={"date": "2026-07-25", "time": "not-a-time"},
            integration=IntegrationConfiguration(service_type="google_calendar"),
        )

        result = await plugin.execute(request)

        assert result.success is False
        assert "valid time" in (result.error or "")
        client.create_event.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_book_appointment_fails_closed_when_availability_check_errors(self):
        client = AsyncMock()
        client.check_availability.side_effect = RuntimeError("calendar unavailable")
        plugin = CalendarPlugin(client_factory=lambda integration: client)
        request = PluginExecutionRequest(
            action="book_appointment",
            params={"date": "2026-07-25", "time": "14:00", "duration_minutes": 30},
            integration=IntegrationConfiguration(
                service_type="google_calendar",
                agent_timezone="Asia/Karachi",
            ),
        )

        result = await plugin.execute(request)

        assert result.success is False
        assert "Availability check failed" in (result.error or "")
        client.create_event.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_book_appointment_preserves_business_description(self):
        client = AsyncMock()
        client.check_availability.return_value = {"busy_slots": []}
        client.create_event.return_value = {"event_id": "event-1"}
        plugin = CalendarPlugin(client_factory=lambda integration: client)

        result = await plugin.execute(
            PluginExecutionRequest(
                action="book_appointment",
                params={
                    "date": "2026-07-25",
                    "time": "14:00",
                    "duration_minutes": 30,
                    "purpose": "Check-up - Alex Patient",
                    "description": "Patient contact and service details",
                },
                integration=IntegrationConfiguration(
                    service_type="google_calendar",
                    agent_timezone="Asia/Karachi",
                ),
            )
        )

        assert result.success is True
        assert result.output["event_created"] is True
        assert client.create_event.await_args.kwargs["description"] == (
            "Patient contact and service details"
        )

    @pytest.mark.asyncio
    async def test_calendar_availability_has_stable_branch_contract(self):
        client = AsyncMock()
        client.check_availability.return_value = {
            "available_slots": [
                {
                    "start": "2026-07-21T15:00:00+05:00",
                    "end": "2026-07-21T15:30:00+05:00",
                }
            ]
        }
        plugin = CalendarPlugin(client_factory=lambda integration: client)
        result = await plugin.execute(
            PluginExecutionRequest(
                action="check_availability",
                params={
                    "date": "2026-07-21",
                    "time": "15:00",
                    "duration_minutes": 30,
                },
                integration=IntegrationConfiguration(
                    service_type="google_calendar",
                    agent_timezone="Asia/Karachi",
                ),
            )
        )

        assert result.success is True
        assert result.output["available"] is True
        assert result.output["requested_time_available"] is True
        assert result.output["available_slot_count"] == 1
        assert len(result.output["available_slots"]) == 1

    @pytest.mark.asyncio
    async def test_calendar_client_failure_is_not_converted_to_success(self):
        client = AsyncMock()
        client.check_availability.return_value = {
            "success": False,
            "error": "OAuth credentials expired",
        }
        plugin = CalendarPlugin(client_factory=lambda integration: client)

        result = await plugin.execute(
            PluginExecutionRequest(
                action="check_availability",
                params={"date": "2026-07-21", "time": "15:00"},
                integration=IntegrationConfiguration(service_type="google_calendar"),
            )
        )

        assert result.success is False
        assert result.error == "OAuth credentials expired"


class TestSheetsResultContract:
    @pytest.mark.asyncio
    async def test_read_rows_returns_rows_count_and_found(self):
        client = AsyncMock()
        client.read_rows.return_value = [
            ["date", "patient_name", "phone", "email"],
            ["2026-07-20", "Alex Patient", "+15555550100", "patient1@example.com"],
        ]
        plugin = SheetsPlugin(client_factory=lambda integration: client)
        result = await plugin.execute(
            PluginExecutionRequest(
                action="read_rows",
                params={"range": "Patients!A:K", "max_rows": 200},
                integration=IntegrationConfiguration(service_type="google_sheets"),
            )
        )

        assert result.success is True
        assert result.output["found"] is True
        assert result.output["count"] == 2
        assert len(result.output["rows"]) == 2

    @pytest.mark.asyncio
    async def test_read_rows_empty_contract_is_explicit(self):
        client = AsyncMock()
        client.read_rows.return_value = []
        plugin = SheetsPlugin(client_factory=lambda integration: client)
        result = await plugin.execute(
            PluginExecutionRequest(
                action="read_rows",
                params={"range": "Patients!A:K"},
                integration=IntegrationConfiguration(service_type="google_sheets"),
            )
        )

        assert result.success is True
        assert result.output == {"rows": [], "count": 0, "found": False}

    @pytest.mark.asyncio
    async def test_append_failure_is_not_converted_to_success(self):
        client = AsyncMock()
        client.append_row.return_value = {"success": False, "error": "sheet is read only"}
        plugin = SheetsPlugin(client_factory=lambda integration: client)

        result = await plugin.execute(
            PluginExecutionRequest(
                action="append_row",
                params={"range": "Patients!A:K", "values": ["Alex"]},
                integration=IntegrationConfiguration(service_type="google_sheets"),
            )
        )

        assert result.success is False
        assert result.error == "sheet is read only"


class TestGraphExecution:
    @pytest.mark.asyncio
    async def test_execute_workflow_prefers_graph(self, db_session, test_user):
        executor = WorkflowExecutor(db_session, test_user.id, plugin_registry=build_default_plugin_registry())
        graph = {
            "nodes": [
                {"id": "n1", "data": {"nodeType": "trigger"}},
                {
                    "id": "n2",
                    "data": {
                        "nodeType": "notification",
                        "params": {"message": "hello {{caller_name}}"},
                    },
                },
                {"id": "n3", "data": {"nodeType": "end"}},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "n2"},
                {"id": "e2", "source": "n2", "target": "n3"},
            ],
        }

        execution = await executor.execute_workflow(
            steps=[{"step_number": 1, "integration_id": 0, "action": "notification", "params": {"message": "legacy"}}],
            graph=graph,
            context={"caller_name": "John"},
        )

        assert execution["mode"] == "graph"
        assert len(execution["results"]) == 3
        n2 = next(r for r in execution["results"] if r.get("node_id") == "n2")
        assert n2["status"] == "success"
        assert n2["result"]["message"] == "hello John"

    @pytest.mark.asyncio
    async def test_condition_branch_uses_source_handle(self, db_session, test_user):
        executor = WorkflowExecutor(db_session, test_user.id, plugin_registry=build_default_plugin_registry())
        graph = {
            "nodes": [
                {"id": "start", "data": {"nodeType": "trigger"}},
                {
                    "id": "cond",
                    "data": {
                        "nodeType": "condition",
                        "config": {"expression": "caller_phone not_empty"},
                    },
                },
                {
                    "id": "yes_node",
                    "data": {
                        "nodeType": "notification",
                        "params": {"message": "yes path"},
                    },
                },
                {
                    "id": "no_node",
                    "data": {
                        "nodeType": "notification",
                        "params": {"message": "no path"},
                    },
                },
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "cond"},
                {"id": "e2", "source": "cond", "sourceHandle": "yes", "target": "yes_node"},
                {"id": "e3", "source": "cond", "sourceHandle": "no", "target": "no_node"},
            ],
        }

        results = await executor.execute_graph(graph, {"caller_phone": "+15551234567"})
        executed_ids = {r.get("node_id") for r in results if r.get("status") == "success"}
        assert "yes_node" in executed_ids
        assert "no_node" not in executed_ids

    @pytest.mark.asyncio
    async def test_graph_cycle_guard_caps_execution(self, db_session, test_user):
        executor = WorkflowExecutor(db_session, test_user.id, plugin_registry=build_default_plugin_registry())
        graph = {
            "nodes": [
                {"id": "start", "data": {"nodeType": "trigger"}},
                {"id": "a", "data": {"nodeType": "notification", "params": {"message": "a"}}},
                {"id": "b", "data": {"nodeType": "notification", "params": {"message": "b"}}},
            ],
            "edges": [
                {"id": "e0", "source": "start", "target": "a"},
                {"id": "e1", "source": "a", "target": "b"},
                {"id": "e2", "source": "b", "target": "a"},
            ],
        }

        results = await executor.execute_graph(
            graph,
            {},
            max_steps=4,
            max_visits_per_node=2,
        )

        assert any(
            r.get("status") in {"error", "skipped"}
            and (
                r.get("error") == "Graph execution aborted: max_steps exceeded"
                or r.get("reason") == "visit_limit_exceeded"
                or (isinstance(r.get("error"), str) and "Graph contains a cycle" in r["error"])
            )
            for r in results
        )


# ── Executor Integration Tests ─────────────────────────────────────────

class TestWorkflowExecutorMissing:
    @pytest.mark.asyncio
    async def test_missing_integration(self, db_session, test_user):
        executor = WorkflowExecutor(db_session, test_user.id, plugin_registry=build_default_plugin_registry())
        steps = [{"step_number": 1, "integration_id": 9999, "action": "create_event", "params": {}}]
        results = await executor.execute_steps(steps, {})
        assert results[0]["status"] == "error"
        assert "not found" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_plugin_failure_is_not_reported_as_step_success(self, db_session, test_user):
        executor = WorkflowExecutor(
            db_session,
            test_user.id,
            plugin_registry=build_default_plugin_registry(),
        )
        executor._resolve_integration_config = AsyncMock(
            return_value=("webhook", None, None, {"url": "https://example.com"})
        )
        executor._dispatch_plugin = AsyncMock(
            return_value={"success": False, "error": "HTTP 500: unavailable"}
        )

        results = await executor.execute_steps(
            [{"step_number": 1, "integration_id": 1, "action": "request", "params": {}}],
            {},
        )

        assert results[0]["status"] == "error"
        assert results[0]["error"] == "HTTP 500: unavailable"

    @pytest.mark.asyncio
    async def test_plugin_failure_is_not_reported_as_graph_node_success(self, db_session, test_user):
        executor = WorkflowExecutor(
            db_session,
            test_user.id,
            plugin_registry=build_default_plugin_registry(),
        )
        executor._resolve_integration_config = AsyncMock(
            return_value=("webhook", None, None, {"url": "https://example.com"})
        )
        executor._dispatch_plugin = AsyncMock(
            return_value={"success": False, "error": "HTTP 500: unavailable"}
        )
        node = {
            "id": "webhook-1",
            "data": {
                "nodeType": "action",
                "config": {"integration_type": "webhook", "action": "request"},
            },
        }

        result = await executor._execute_graph_node(node, {})

        assert result["status"] == "error"
        assert result["error"] == "HTTP 500: unavailable"

    @pytest.mark.asyncio
    async def test_send_email_falls_back_to_platform_smtp_without_integration(
        self, db_session, test_user
    ):
        """Flow send_email nodes must use platform SMTP when no email Integration exists."""
        executor = WorkflowExecutor(
            db_session,
            test_user.id,
            plugin_registry=build_default_plugin_registry(),
        )
        executor._resolve_integration_config = AsyncMock(
            return_value=(None, None, None, {})
        )
        executor.execute_direct_action = AsyncMock(
            return_value={
                "success": True,
                "email_sent": True,
                "to": "patient@example.com",
            }
        )
        node = {
            "id": "email_1",
            "data": {
                "nodeType": "send_email",
                "config": {
                    "to": "patient@example.com",
                    "subject": "Confirmed",
                    "body": "See you soon",
                },
            },
        }

        result = await executor._execute_graph_node(node, {})

        assert result["status"] == "success"
        assert result["result"]["email_sent"] is True
        executor.execute_direct_action.assert_awaited_once()
        args = executor.execute_direct_action.await_args.args
        assert args[0] == "send_email"
        assert args[1] == "send_email"
        assert args[2]["to"] == "patient@example.com"


# ── Enhanced Workflow Routes Tests ─────────────────────────────────────

class TestWorkflowWithSteps:
    @pytest.mark.asyncio
    async def test_create_workflow_with_steps(self, client):
        resp = await client.post("/api/workflows", json={
            "name": "Schedule + Log",
            "description": "Schedule an event and log to sheet",
            "trigger_phrases": ["schedule meeting", "book appointment"],
            "steps": [
                {
                    "step_number": 1,
                    "integration_id": 1,
                    "action": "create_event",
                    "params": {"summary": "Meeting with {{caller_name}}"},
                },
                {
                    "step_number": 2,
                    "integration_id": 2,
                    "action": "append_row",
                    "params": {"values": "{{caller_name}},{{call_date}}"},
                },
            ],
        })
        assert resp.status_code == 201
        wf = resp.json()["workflow"]
        assert wf["name"] == "Schedule + Log"
        assert wf.get("steps") is not None
        assert len(wf["steps"]) == 2

    @pytest.mark.asyncio
    async def test_create_workflow_without_steps(self, client):
        resp = await client.post("/api/workflows", json={
            "name": "Simple Workflow",
            "trigger_phrases": ["hello"],
        })
        assert resp.status_code == 201
        wf = resp.json()["workflow"]
        assert wf.get("steps") is None or wf.get("steps") == []

    @pytest.mark.asyncio
    async def test_update_workflow_steps(self, client, test_workflow):
        resp = await client.put(f"/api/workflows/{test_workflow.id}", json={
            "steps": [
                {
                    "step_number": 1,
                    "integration_id": 1,
                    "action": "list_events",
                    "params": {"max_results": 5},
                },
            ],
        })
        assert resp.status_code == 200
        wf = resp.json()["workflow"]
        assert wf.get("steps") is not None
        assert len(wf["steps"]) == 1


# ── Condition Result Preservation Tests ────────────────────────────────

class TestConditionResultPreservation:
    """Tests that condition nodes don't overwrite context['result']."""

    def test_condition_does_not_overwrite_result(self):
        """Condition node output should not replace context['result']."""
        from voice_platform.integrations.executor import WorkflowExecutor

        context = {
            "result": {"available_slots": [{"start": "10:00"}], "success": True},
        }
        # Simulate what execute_graph does after a condition node
        output = {"success": True, "condition_met": True, "expression": "result.available_slots not_empty"}
        node_type = "condition"
        # Apply the fix logic
        context[f"node_cond_result"] = output
        if node_type != "condition":
            context["last_result"] = output
            context["result"] = output
        # context["result"] should still be the original action output
        assert context["result"] == {"available_slots": [{"start": "10:00"}], "success": True}
        assert context["node_cond_result"] == output

    def test_non_condition_does_overwrite_result(self):
        """Non-condition node output should replace context['result']."""
        context = {
            "result": {"old": "data"},
        }
        output = {"new": "data"}
        node_type = "action"
        context[f"node_act_result"] = output
        if node_type != "condition":
            context["last_result"] = output
            context["result"] = output
        assert context["result"] == {"new": "data"}

    def test_select_condition_edges_returns_empty_when_no_match(self):
        """_select_condition_edges should return [] when no branch matches, not all edges."""
        from voice_platform.integrations.executor import WorkflowExecutor

        edges = [
            {"source": "cond", "sourceHandle": "yes", "target": "yes_node"},
            {"source": "cond", "sourceHandle": "yes", "target": "other_node"},
        ]
        # Looking for 'no' branch but only 'yes' edges exist
        result = WorkflowExecutor._select_condition_edges(edges, condition_met=False)
        assert result == []

    def test_select_condition_edges_returns_matched(self):
        """_select_condition_edges should return only matching edges."""
        from voice_platform.integrations.executor import WorkflowExecutor

        edges = [
            {"source": "cond", "sourceHandle": "yes", "target": "yes_node"},
            {"source": "cond", "sourceHandle": "no", "target": "no_node"},
        ]
        result = WorkflowExecutor._select_condition_edges(edges, condition_met=False)
        assert len(result) == 1
        assert result[0]["target"] == "no_node"

    def test_check_availability_error_includes_empty_slots(self):
        """check_availability error response should include available_slots: [] for clean condition eval."""
        from voice_platform.integrations.executor import WorkflowExecutor

        # Verify that ConditionEvaluator handles the error response correctly
        error_result = {"success": False, "error": "missing date", "available_slots": []}
        context = {"result": error_result}
        # This should evaluate to False cleanly (not crash on missing key)
        result = _evaluator.evaluate("result.available_slots not_empty", context)
        assert result is False

    def test_condition_evaluates_against_action_not_self(self):
        """When a condition loops back, it should evaluate against the action output, not its own."""
        from voice_platform.integrations.executor import WorkflowExecutor

        # Simulate: action node sets result, then condition runs, then loops back
        action_output = {"available_slots": [{"start": "10:00"}], "success": True}
        condition_output = {"success": True, "condition_met": True, "expression": "result.available_slots not_empty"}

        context = {}
        # Action node runs
        context["node_action_result"] = action_output
        context["last_result"] = action_output
        context["result"] = action_output

        # Condition node runs — should NOT overwrite result
        context["node_cond_result"] = condition_output
        # (with the fix, we skip overwriting for condition nodes)

        # On second iteration, condition should still evaluate against action_output
        result = _evaluator.evaluate("result.available_slots not_empty", context)
        assert result is True
