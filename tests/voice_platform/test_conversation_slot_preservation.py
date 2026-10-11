"""Regression tests for preserving confirmed flow slots across short replies."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from voice_platform.flow import nodes as flow_nodes
from voice_platform.flow.nodes import (
    _build_context_summary,
    _build_slot_aware_instruction,
    create_node_handlers,
)
from voice_platform.flow.slots import SlotEngine
from voice_platform.flow.state import make_initial_state


CONTACT_VARIABLES = ["patient_name", "caller_phone", "caller_email"]


def _contact_state(extracted_vars: dict[str, str], *, confirmed: list[str]):
    node = {
        "id": "conversation_contact",
        "type": "conversation",
        "data": {
            "label": "Contact Details",
            "config": {
                "prompt": "Confirm the patient's contact details.",
                "variables_to_extract": CONTACT_VARIABLES,
            },
        },
    }
    state = make_initial_state(
        user_id=1,
        agent_id=1,
        nodes_by_id={"conversation_contact": node},
        outgoing={"conversation_contact": []},
    )
    engine = SlotEngine(CONTACT_VARIABLES, extracted_vars)
    for name in confirmed:
        engine.confirm(name)
    state.update(
        {
            "current_node": "conversation_contact",
            "extracted_vars": dict(extracted_vars),
            "pending_variables_to_extract": list(CONTACT_VARIABLES),
            "_conversation_phase": "wait",
            "_slots": engine.to_dict(),
            "_slot_engine": engine.to_engine_dict(),
            "last_result": {"response": "Is that all correct?"},
            "result": {"response": "Is that all correct?"},
            "transcript": "Agent: Is that all correct?",
        }
    )
    return state


async def _ignore_event(event: dict) -> None:
    return None


@pytest.mark.asyncio
async def test_yes_preserves_confirmed_name_phone_and_email(monkeypatch):
    state = _contact_state(
        {
            "patient_name": "Alex Patient",
            "caller_name": "Alex Patient",
            "caller_phone": "+15555550100",
            "phone": "+15555550100",
            "caller_email": "patient1@example.com",
            "email": "patient1@example.com",
        },
        confirmed=CONTACT_VARIABLES,
    )
    extraction = AsyncMock(return_value={"caller_email": "[EMAIL]"})
    monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "yes")
    monkeypatch.setattr(flow_nodes, "_extract_variables", extraction)

    result = await create_node_handlers()["conversation"](
        state,
        {
            "configurable": {
                "event_callback": _ignore_event,
                "user_id": 1,
                "agent": SimpleNamespace(id=1),
            }
        },
    )

    extraction.assert_not_awaited()
    assert result["extracted_vars"]["patient_name"] == "Alex Patient"
    assert result["extracted_vars"]["caller_phone"] == "+15555550100"
    assert result["extracted_vars"]["caller_email"] == "patient1@example.com"
    assert result["_slots_missing"] == []


@pytest.mark.asyncio
async def test_retry_extracts_only_the_still_missing_phone(monkeypatch):
    state = _contact_state(
        {
            "patient_name": "Alex Patient",
            "caller_name": "Alex Patient",
            "caller_email": "patient1@example.com",
            "email": "patient1@example.com",
        },
        confirmed=["patient_name", "caller_email"],
    )
    requested: list[list[str]] = []

    async def _extract(variables, state, config):
        requested.append(list(variables))
        return {"caller_phone": "+15555550100"}

    monkeypatch.setattr(flow_nodes, "interrupt", lambda _: "+15555550100")
    monkeypatch.setattr(flow_nodes, "_extract_variables", _extract)

    result = await create_node_handlers()["conversation"](
        state,
        {
            "configurable": {
                "event_callback": _ignore_event,
                "user_id": 1,
                "agent": SimpleNamespace(id=1),
            }
        },
    )

    assert requested == [["caller_phone"]]
    assert result["extracted_vars"]["caller_email"] == "patient1@example.com"
    assert result["extracted_vars"]["caller_phone"] == "+15555550100"
    assert result["_slots_missing"] == []


def test_llm_context_is_redacted_without_mutating_validated_state():
    state = _contact_state(
        {
            "patient_name": "Alex Patient",
            "caller_phone": "+15555550100",
            "caller_email": "patient1@example.com",
        },
        confirmed=CONTACT_VARIABLES,
    )
    state["transcript"] = (
        "Caller: My phone is +15555550100 and email is "
        "patient1@example.com"
    )

    summary = _build_context_summary(state)

    assert "patient1@example.com" not in summary
    assert "+15555550100" not in summary
    assert "[EMAIL]" in summary
    assert "[PHONE]" in summary
    assert state["extracted_vars"]["caller_email"] == "patient1@example.com"
    assert state["extracted_vars"]["caller_phone"] == "+15555550100"


@pytest.mark.parametrize(
    ("variable_name", "value", "expected"),
    [
        ("patient_name", "Alex Patient", "Alex Patient"),
        ("caller_phone", "+15555550100", "ending in 8369"),
        ("caller_email", "patient1@example.com", "p***@example.com"),
    ],
)
def test_prefilled_slot_generates_masked_confirmation_question(
    variable_name,
    value,
    expected,
):
    engine = SlotEngine([variable_name], {variable_name: value})

    instruction = _build_slot_aware_instruction(
        "Confirm the saved contact detail.",
        "Contact Details",
        engine,
    )

    assert "Is that correct?" in instruction
    assert expected in instruction
