"""Phase 6.4 regression tests: optional_inputs for action nodes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_platform.flow.nodes import create_node_handlers


@pytest.mark.asyncio
async def test_action_optional_inputs_does_not_skip_execution(monkeypatch):
    """6.4: Missing template variables listed in optional_inputs should not cause an action node to skip."""
    handlers = create_node_handlers()
    action_handler = handlers["action"]

    # Patch out external dependencies
    monkeypatch.setattr(
        "voice_platform.flow.nodes._extract_variables",
        AsyncMock(return_value={}),
    )

    mock_executor_instance = MagicMock()
    mock_executor_instance._execute_graph_node = AsyncMock(
        return_value={"status": "success", "result": {"row": "logged"}}
    )

    def _mock_executor(*args, **kwargs):
        return mock_executor_instance

    with patch("voice_platform.integrations.executor.WorkflowExecutor", _mock_executor):
        state = {
            "current_node": "sheets_1",
            "nodes_by_id": {
                "sheets_1": {
                    "id": "sheets_1",
                    "data": {
                        "label": "Log Patient",
                        "config": {
                            "integration_type": "google_sheets",
                            "action": "append_row",
                            "optional_inputs": ["insurance_provider"],
                            "params": {
                                "range": "Patients!A:J",
                                "values": [
                                    "{{current_date}}",
                                    "{{patient_name}}",
                                    "{{caller_phone}}",
                                    "{{service_requested}}",
                                    "{{preferred_dentist}}",
                                    "{{preferred_date}}",
                                    "{{preferred_time}}",
                                    "{{is_new_patient}}",
                                    "{{insurance_provider}}",
                                    "confirmed",
                                ],
                            },
                        },
                    },
                }
            },
            "extracted_vars": {
                "current_date": "2026-07-17",
                "patient_name": "Alex Patient",
                "caller_phone": "03001234567",
                "service_requested": "scaling",
                "preferred_dentist": "Ayesha",
                "preferred_date": "2026-07-18",
                "preferred_time": "14:30",
                "is_new_patient": "new",
                # insurance_provider intentionally missing
            },
            # _build_template_context reads top-level caller_phone before extracted_vars
            "caller_phone": "03001234567",
            "result": {},
            "last_result": {},
            "agent_timezone": "Asia/Karachi",
            "transcript": [],
        }

        config = {
            "configurable": {
                "agent": SimpleNamespace(id=1),
                "user_id": 1,
                "db_session": MagicMock(),
            }
        }

        result = await action_handler(state, config)

    assert result["last_result"].get("success") is True
    assert result["result"].get("row") == "logged"
    assert result["result"].get("skipped") is not True
    mock_executor_instance._execute_graph_node.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_required_inputs_fail_fast_without_llm_extraction(monkeypatch):
    """Missing required_inputs should return on_missing immediately without LLM extraction."""
    handlers = create_node_handlers()
    action_handler = handlers["action"]

    # If _extract_variables is called, the test should fail — extraction is not
    # needed for required_inputs and was the source of multi-second timeouts.
    extraction_mock = AsyncMock(side_effect=RuntimeError("_extract_variables should not be called"))
    monkeypatch.setattr("voice_platform.flow.nodes._extract_variables", extraction_mock)

    state = {
        "current_node": "action_3",
        "nodes_by_id": {
            "action_3": {
                "id": "action_3",
                "data": {
                    "label": "Book Appointment",
                    "config": {
                        "integration_type": "google_calendar",
                        "action": "create_event",
                        "required_inputs": ["caller_email"],
                        "params": {
                            "title": "{{service_requested}} - {{patient_name}}",
                            "date": "{{preferred_date}}",
                            "time": "{{preferred_time}}",
                        },
                    },
                },
            }
        },
        "extracted_vars": {
            "service_requested": "root canal",
            "patient_name": "Zahra",
            "preferred_date": "2026-07-18",
            "preferred_time": "10:00",
            # caller_email intentionally missing
        },
        "result": {},
        "last_result": {},
        "transcript": [],
    }

    config = {
        "configurable": {
            "agent": SimpleNamespace(id=1),
            "user_id": 1,
        }
    }

    result = await action_handler(state, config)

    assert extraction_mock.call_count == 0
    assert result["last_result"].get("branch") == "on_missing"
    assert "caller_email" in result["_action_error"]["error"]
    assert result["result"].get("success") is False
    assert result["_action_error"]["node_id"] == "action_3"
    assert "caller_email" in result["_action_error"]["error"]


@pytest.mark.asyncio
async def test_action_missing_inputs_emits_info_not_hard_error(monkeypatch):
    """Call 107: missing required inputs must soft-route without FlowAgent error-drain."""
    handlers = create_node_handlers()
    action_handler = handlers["action"]
    monkeypatch.setattr(
        "voice_platform.flow.nodes._extract_variables",
        AsyncMock(side_effect=RuntimeError("should not extract")),
    )

    events: list[dict] = []

    async def _capture(event: dict) -> None:
        events.append(event)

    state = {
        "current_node": "action_1",
        "nodes_by_id": {
            "action_1": {
                "id": "action_1",
                "data": {
                    "label": "Check Existing Patient",
                    "config": {
                        "integration_type": "google_sheets",
                        "action": "read_rows",
                        "required_inputs": ["patient_name"],
                        "params": {"query": "{{patient_name}}"},
                    },
                },
            }
        },
        "extracted_vars": {"visit_type": "booking", "is_emergency": "false"},
        "result": {},
        "last_result": {},
        "transcript": [],
    }
    config = {
        "configurable": {
            "agent": SimpleNamespace(id=14),
            "user_id": 1,
            "event_callback": _capture,
        }
    }

    result = await action_handler(state, config)

    assert result["last_result"].get("branch") == "on_missing"
    assert any(e.get("event") == "info" for e in events)
    assert not any(e.get("event") == "error" for e in events)
    node_results = [e for e in events if e.get("event") == "node_result"]
    assert node_results
    assert node_results[0].get("status") == "missing_input"
