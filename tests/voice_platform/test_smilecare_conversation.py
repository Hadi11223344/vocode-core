"""Phase 7: SmileCare-style end-to-end conversation regression tests."""

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import MemorySaver

from voice_platform.flow.compiler import compile_flow, create_initial_state
from voice_platform.flow.nodes import create_node_handlers


def _make_smilecare_graph():
    """A simplified SmileCare graph with emergency branching."""
    return {
        "nodes": [
            {"id": "trigger", "data": {"nodeType": "trigger"}},
            {
                "id": "ask_service",
                "data": {
                    "nodeType": "conversation",
                    "label": "Ask Service",
                    "config": {
                        "prompt": "What dental service do you need?",
                        "variables_to_extract": ["service_requested", "is_emergency"],
                    },
                },
            },
            {
                "id": "check_emergency",
                "data": {
                    "nodeType": "condition",
                    "label": "Check Emergency",
                    "config": {"expression": "is_emergency == true"},
                },
            },
            {
                "id": "emergency_action",
                "data": {"nodeType": "action", "label": "Emergency Action"},
            },
            {
                "id": "book_appointment",
                "data": {
                    "nodeType": "action",
                    "label": "Book Appointment",
                    "config": {
                        "required_inputs": ["service_requested"],
                        "optional_inputs": ["insurance_provider"],
                    },
                },
            },
            {"id": "end", "data": {"nodeType": "end"}},
        ],
        "edges": [
            {"source": "trigger", "target": "ask_service"},
            {"source": "ask_service", "target": "check_emergency"},
            {"source": "check_emergency", "target": "emergency_action", "sourceHandle": "yes"},
            {"source": "check_emergency", "target": "book_appointment", "sourceHandle": "no"},
            {"source": "emergency_action", "target": "end"},
            {"source": "book_appointment", "target": "end"},
        ],
    }


def _make_handlers(extracted_vars):
    """Create handlers for a SmileCare test, injecting the extracted variables."""
    handlers = create_node_handlers()

    async def _conversation(state, config):
        return {
            "extracted_vars": {**state.get("extracted_vars", {}), **extracted_vars},
            "_slots_missing": [],
            "_conversation_phase": "generate",
            "result": {},
            "messages": [],
            "transcript": "",
        }

    async def _action(state, config):
        node_id = state["current_node"]
        return {"last_result": {"branch": node_id}}

    handlers["conversation"] = _conversation
    handlers["action"] = _action
    return handlers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_emergency,expected_branch",
    [
        ("true", "emergency_action"),
        ("yes", "emergency_action"),
        ("false", "book_appointment"),
        ("no", "book_appointment"),
        ("", "book_appointment"),  # missing defaults to false
    ],
)
async def test_smilecare_emergency_branch(is_emergency, expected_branch):
    """is_emergency should route the conversation to emergency or booking."""
    graph = _make_smilecare_graph()
    extracted = {"service_requested": "scaling"}
    if is_emergency:
        extracted["is_emergency"] = is_emergency
    handlers = _make_handlers(extracted)
    compiled = compile_flow(graph, checkpointer=MemorySaver(), node_handlers=handlers)
    state = create_initial_state(graph, user_id=1, agent_id=1, max_retries=0)

    result = await compiled.ainvoke(
        state,
        config={"configurable": {"thread_id": f"t-emergency-{is_emergency or 'missing'}"}},
    )
    assert result["last_result"]["branch"] == expected_branch
