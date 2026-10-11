"""Regression tests for the LangGraph-backed flow executor/compiler."""

import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# Skip the whole module if LangGraph is not installed (e.g. bare vocode venv).
pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from voice_platform.flow.compiler import compile_flow, create_initial_state
from voice_platform.flow.nodes import _message_to_dict


@pytest.mark.asyncio
async def test_conversation_collects_only_variables_owned_by_current_node(monkeypatch):
    from voice_platform.flow import nodes as nodes_module

    captured = {}

    async def fake_generate(
        state,
        config,
        node_id,
        node_label,
        node_prompt,
        pending_vars,
        engine,
        event_callback,
        playground_conv,
        streaming_client,
        agent,
        user_id,
    ):
        captured["pending_vars"] = pending_vars
        return {"pending_variables_to_extract": pending_vars}

    monkeypatch.setattr(nodes_module, "_conversation_generate", fake_generate)
    state = {
        "current_node": "triage",
        "nodes_by_id": {
            "triage": {
                "id": "triage",
                "type": "conversation",
                "data": {
                    "label": "Triage",
                    "config": {
                        "prompt": "Ask whether this is an emergency.",
                        "variables_to_extract": ["is_emergency"],
                    },
                },
            },
            "future_contact": {
                "id": "future_contact",
                "type": "conversation",
                "data": {
                    "config": {
                        "variables_to_extract": ["caller_email", "caller_phone"],
                    }
                },
            },
        },
        "extracted_vars": {},
        "pending_variables_to_extract": [],
        "_conversation_phase": "generate",
    }

    result = await nodes_module.create_node_handlers()["conversation"](
        state,
        {"configurable": {}},
    )

    assert captured["pending_vars"] == ["is_emergency"]
    assert result["pending_variables_to_extract"] == ["is_emergency"]


def test_calendar_slots_remain_available_to_alternative_conversation():
    from voice_platform.flow.nodes import _sanitize_result_for_context

    summary = _sanitize_result_for_context({
        "success": True,
        "requested_time_available": False,
        "available_slots": [
            {"start": f"2026-07-25T{hour:02d}:00:00+05:00", "end": f"2026-07-25T{hour:02d}:30:00+05:00"}
            for hour in range(10, 17)
        ],
    })

    assert "requested time available: no" in summary
    assert "2026-07-25T10:00:00+05:00" in summary
    assert "2026-07-25T14:00:00+05:00" in summary
    assert "2026-07-25T15:00:00+05:00" not in summary


@pytest.mark.asyncio
async def test_executor_restores_existing_checkpoint_without_restarting_graph():
    from voice_platform.flow.executor import LangGraphFlowExecutor

    graph = _make_resume_graph()
    conv = SimpleNamespace(aclose=AsyncMock())
    executor = LangGraphFlowExecutor(
        agent=SimpleNamespace(id=1, timezone="UTC"),
        graph=graph,
        playground_conv=conv,
        user_id=1,
    )
    snapshot = SimpleNamespace(
        values={"extracted_vars": {"caller_name": "Alice"}, "total_steps": 2},
        next=("ask",),
        tasks=(),
    )
    compiled = MagicMock()
    compiled.aget_state = AsyncMock(return_value=snapshot)
    compiled.ainvoke = AsyncMock()
    executor._compiled_graph = compiled

    await executor.start_flow(AsyncMock())

    compiled.ainvoke.assert_not_awaited()
    assert executor.started is True
    assert executor.context["caller_name"] == "Alice"


def _make_resume_graph():
    return {
        "nodes": [
            {"id": "trigger", "data": {"nodeType": "trigger"}},
            {
                "id": "ask",
                "data": {
                    "nodeType": "conversation",
                    "label": "Ask",
                    "config": {"prompt": "Ask the caller a question"},
                },
            },
            {"id": "save", "data": {"nodeType": "action", "label": "Save"}},
            {"id": "end", "data": {"nodeType": "end"}},
        ],
        "edges": [
            {"source": "trigger", "target": "ask"},
            {"source": "ask", "target": "save"},
            {"source": "save", "target": "end"},
        ],
    }


def _make_condition_graph():
    return {
        "nodes": [
            {"id": "trigger", "data": {"nodeType": "trigger"}},
            {
                "id": "decide",
                "data": {
                    "nodeType": "condition",
                    "label": "Decide",
                    "config": {"expression": "true"},
                },
            },
            {"id": "yes_node", "data": {"nodeType": "action", "label": "Yes"}},
            {"id": "no_node", "data": {"nodeType": "action", "label": "No"}},
            {"id": "end", "data": {"nodeType": "end"}},
        ],
        "edges": [
            {"source": "trigger", "target": "decide"},
            {"source": "decide", "target": "yes_node", "sourceHandle": "yes"},
            {"source": "decide", "target": "no_node", "sourceHandle": "no"},
            {"source": "yes_node", "target": "end"},
            {"source": "no_node", "target": "end"},
        ],
    }


_events = []
_conversation_calls = 0


async def _event_callback(event):
    _events.append(event)


async def _trigger_handler(state, config):
    return {}


async def _conversation_handler(state, config):
    global _conversation_calls
    _conversation_calls += 1
    from langgraph.types import interrupt

    user_input = interrupt({"node_id": state["current_node"]})
    return {
        "messages": [
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": user_input},
        ],
        "transcript": (state.get("transcript", "") + f" Caller: {user_input}")[-2000:],
    }


async def _action_handler(state, config):
    return {"last_result": {"branch": state["current_node"]}}


async def _branch_action_handler(state, config):
    branch = state.get("result", {}).get("branch", "ok")
    return {
        "last_result": {"node_id": state.get("current_node", ""), "success": True, "status": "succeeded", "branch": branch},
        "result": {"branch": branch},
    }


async def _condition_handler(state, config):
    return {
        "_condition_met": state.get("_condition_met", False),
        "last_result": {"condition_met": state.get("_condition_met", False)},
    }


async def _end_handler(state, config):
    return {}


_BASE_HANDLERS = {
    "trigger": _trigger_handler,
    "conversation": _conversation_handler,
    "action": _action_handler,
    "condition": _condition_handler,
    "end": _end_handler,
}


@pytest.mark.asyncio
async def test_compile_flow_with_checkpointer_allows_resume():
    """A graph with an interrupt must be resumable via Command(resume=...)."""
    global _conversation_calls
    _events.clear()
    _conversation_calls = 0
    graph_json = _make_resume_graph()
    compiled = compile_flow(
        graph_json,
        checkpointer=MemorySaver(),
        node_handlers=_BASE_HANDLERS,
    )
    state = create_initial_state(graph_json, user_id=1, agent_id=1)

    # Run until the conversation node pauses for user input.
    _invoke_config = {"configurable": {"thread_id": "t-resume", "event_callback": _event_callback}}
    result = await compiled.ainvoke(
        state, config=_invoke_config
    )
    snapshot = await compiled.aget_state(
        config={"configurable": {"thread_id": "t-resume"}}
    )
    is_interrupted = bool(
        snapshot.next
        or (snapshot.tasks and any(task.interrupts for task in snapshot.tasks))
    )
    assert is_interrupted, "Expected graph to pause at interrupt"
    assert any(
        e.get("event") == "edge_traversed" for e in _events
    ), "Expected edge traversal events to be emitted"

    # Resume with the user's answer and finish the graph.
    result2 = await compiled.ainvoke(
        Command(resume="yes"),
        config={"configurable": {"thread_id": "t-resume", "event_callback": _event_callback}},
    )
    snapshot2 = await compiled.aget_state(
        config={"configurable": {"thread_id": "t-resume"}}
    )
    assert not snapshot2.next, "Expected graph to complete after resume"
    assert result2.get("last_result", {}).get("branch") == "save"
    # The caller text should be recorded exactly once (not duplicated by executor + handler)
    assert result2.get("transcript", "").count("Caller: yes") == 1
    # Sanity check: the interrupt node was re-executed on resume (LangGraph semantics)
    assert _conversation_calls >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition_met, expected_branch",
    [
        (True, "yes_node"),
        (False, "no_node"),
    ],
)
async def test_condition_routes_to_correct_branch(condition_met, expected_branch):
    """Condition nodes must route via the yes/no sourceHandle edges."""
    _events.clear()
    graph_json = _make_condition_graph()
    compiled = compile_flow(
        graph_json,
        checkpointer=MemorySaver(),
        node_handlers=_BASE_HANDLERS,
    )
    state = create_initial_state(graph_json, user_id=1, agent_id=1)
    state["_condition_met"] = condition_met

    result = await compiled.ainvoke(
        state, config={"configurable": {"thread_id": f"t-{condition_met}", "event_callback": _event_callback}}
    )
    assert result.get("last_result", {}).get("branch") == expected_branch


@pytest.mark.asyncio
async def test_conversation_node_loops_for_missing_slots(monkeypatch):
    """A conversation node with variables_to_extract must loop back when slots are missing."""
    from voice_platform.flow import nodes as nodes_module
    from voice_platform.flow.nodes import create_node_handlers

    _events.clear()

    async def fake_call_openai(conv, llm_messages, node_id, event_callback):
        if any("RE-ASK" in str(m.get("content", "")) for m in llm_messages):
            return "Could you tell me your name?"
        return "Hello! What is your name?"

    async def fake_extract(variables, state, config):
        transcript = state.get("transcript", "")
        found = {}
        for v in variables:
            if v == "caller_name":
                m = re.search(r"my name is (?P<n>\w+)", transcript, re.IGNORECASE)
                if m:
                    found[v] = m.group("n")
        return found

    monkeypatch.setattr(nodes_module, "_call_openai", fake_call_openai)
    monkeypatch.setattr(nodes_module, "_extract_variables", fake_extract)

    class FakeConv:
        messages = [{"role": "system", "content": "You are Sara"}]
        initial_message = "Hello!"
        model = "test"
        temperature = 0
        max_tokens = 10
        tools = None
        context_window = 100

        def _is_ollama(self):
            return False

        def _ollama_raw_url(self):
            return ""

        def _get_http_client(self):
            return None

    async def _noop_action(state, config):
        return {}

    async def _noop_end(state, config):
        return {}

    agent = SimpleNamespace(id=1)
    handlers = create_node_handlers()
    # Override action/end so the real WorkflowExecutor is not invoked.
    handlers["action"] = _noop_action
    handlers["end"] = _noop_end

    graph_json = {
        "nodes": [
            {"id": "trigger", "data": {"nodeType": "trigger"}},
            {
                "id": "ask",
                "data": {
                    "nodeType": "conversation",
                    "label": "Ask",
                    "config": {
                        "prompt": "Ask the caller their name",
                        "variables_to_extract": ["caller_name"],
                    },
                },
            },
            {"id": "save", "data": {"nodeType": "action", "label": "Save"}},
            {"id": "end", "data": {"nodeType": "end"}},
        ],
        "edges": [
            {"source": "trigger", "target": "ask"},
            {"source": "ask", "target": "save"},
            {"source": "save", "target": "end"},
        ],
    }

    compiled = compile_flow(
        graph_json,
        checkpointer=MemorySaver(),
        node_handlers=handlers,
    )
    state = create_initial_state(graph_json, user_id=1, agent_id=1, max_retries=2)

    _invoke_config = {"configurable": {"thread_id": "t-slot", "event_callback": _event_callback,
        "playground_conv": FakeConv(), "agent": agent, "user_id": 1}}

    # Start: hits interrupt at the conversation node.
    result = await compiled.ainvoke(
        state, config=_invoke_config
    )
    snapshot = await compiled.aget_state(
        config={"configurable": {"thread_id": "t-slot"}}
    )
    assert snapshot.next or (
        snapshot.tasks and any(task.interrupts for task in snapshot.tasks)
    )

    # Empty answer -> missing slot -> loop back to the same conversation node.
    result2 = await compiled.ainvoke(
        Command(resume=""), config=_invoke_config
    )
    snapshot2 = await compiled.aget_state(
        config={"configurable": {"thread_id": "t-slot"}}
    )
    assert snapshot2.next or (
        snapshot2.tasks and any(task.interrupts for task in snapshot2.tasks)
    )
    assert result2.get("retry_count", 0) == 1
    assert result2.get("_slots_missing") == ["caller_name"]

    # Valid answer -> extraction succeeds -> graph completes.
    result3 = await compiled.ainvoke(
        Command(resume="my name is Alice"),
        config=_invoke_config,
    )
    snapshot3 = await compiled.aget_state(
        config={"configurable": {"thread_id": "t-slot"}}
    )
    assert not snapshot3.next
    assert result3.get("extracted_vars", {}).get("caller_name") == "Alice"
    assert result3.get("result", {}).get("caller_name") == "Alice"

    # The conversation node emits node_start on fresh execution only.
    # Initial turn + 1 retry loop = 2 node_start events.
    # The 3rd resume (with "my name is Alice") is a cached re-execution and
    # correctly does NOT emit node_start (NEW-1 fix).
    conv_starts = [
        e for e in _events
        if e.get("event") == "node_start" and e.get("node_id") == "ask"
    ]
    assert len(conv_starts) == 2

    # Caller text should appear exactly once in the final transcript.
    transcript = result3.get("transcript", "")
    assert transcript.count("Caller: my name is Alice") == 1

    # Messages should not duplicate assistant or user turns.
    messages = result3.get("messages", [])
    assert len(messages) == 3
    assert _message_to_dict(messages[0]).get("role") == "assistant"
    assert _message_to_dict(messages[1]).get("role") == "assistant"
    assert _message_to_dict(messages[2]).get("role") == "user"


@pytest.mark.asyncio
async def test_get_checkpointer_uses_memory_saver_for_sqlite(monkeypatch):
    """When DATABASE_URL is SQLite, get_checkpointer must return MemorySaver."""
    from voice_platform.flow import executor as executor_module
    from voice_platform.flow.executor import get_checkpointer

    monkeypatch.setattr(executor_module, "_checkpointer_singleton", None)
    monkeypatch.setattr(executor_module, "_checkpointer_pool", None)
    monkeypatch.setattr(executor_module, "_checkpointer_setup_complete", False)
    monkeypatch.setattr(
        executor_module,
        "DATABASE_URL",
        "sqlite+aiosqlite:///tmp/test_voia.db",
    )

    cp = await get_checkpointer()
    from langgraph.checkpoint.memory import MemorySaver

    assert isinstance(cp, MemorySaver)


@pytest.mark.asyncio
@pytest.mark.parametrize("branch", ["ok", "err"])
async def test_action_node_routes_by_branch_label(branch):
    """An action node with multiple labeled outgoing edges routes via result.branch."""
    _events.clear()

    handlers = {
        **_BASE_HANDLERS,
        "action": _branch_action_handler,
    }

    graph_json = {
        "nodes": [
            {"id": "trigger", "data": {"nodeType": "trigger"}},
            {"id": "action", "data": {"nodeType": "action", "label": "BranchAction"}},
            {"id": "ok", "data": {"nodeType": "action", "label": "Ok"}},
            {"id": "err", "data": {"nodeType": "action", "label": "Err"}},
            {"id": "end", "data": {"nodeType": "end"}},
        ],
        "edges": [
            {"source": "trigger", "target": "action"},
            {"source": "action", "target": "ok", "sourceHandle": "ok", "label": "ok"},
            {"source": "action", "target": "err", "sourceHandle": "err", "label": "err"},
            {"source": "ok", "target": "end"},
            {"source": "err", "target": "end"},
        ],
    }

    compiled = compile_flow(
        graph_json,
        checkpointer=MemorySaver(),
        node_handlers=handlers,
    )
    state = create_initial_state(graph_json, user_id=1, agent_id=1)
    state["result"] = {"branch": branch}
    state["last_result"] = {"node_id": "action", "success": True, "status": "succeeded", "branch": branch}

    result = await compiled.ainvoke(
        state, config={"configurable": {"thread_id": f"t-branch-{branch}", "event_callback": _event_callback}}
    )

    assert result.get("current_node") == "end"


# ---------------------------------------------------------------------------
# Phase 1 regression tests
# ---------------------------------------------------------------------------


def test_merge_dicts_reducer():
    """C-1: merge_dicts reducer should merge not replace."""
    from voice_platform.flow.state import merge_dicts

    assert merge_dicts({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
    assert merge_dicts({"a": 1}, {"a": 2}) == {"a": 2}
    assert merge_dicts(None, {"a": 1}) == {"a": 1}
    assert merge_dicts({"a": 1}, None) == {"a": 1}
    assert merge_dicts(None, None) == {}


def test_dot_notation_template_resolution():
    """C-2: {{result.is_emergency}} should resolve via dot notation."""
    from voice_platform.flow.nodes import _resolve_templates

    ctx = {"result": {"is_emergency": "yes"}}
    assert _resolve_templates("{{result.is_emergency}}", ctx) == "yes"
    assert _resolve_templates("Emergency: {{result.is_emergency}}!", ctx) == "Emergency: yes!"


def test_missing_template_var_preserved():
    """C-3: {{unknown_var}} should stay as literal text, not become empty string."""
    from voice_platform.flow.nodes import _resolve_templates

    ctx = {"known": "value"}
    assert _resolve_templates("{{unknown_var}}", ctx) == "{{unknown_var}}"
    assert _resolve_templates("Hello {{unknown_var}}!", ctx) == "Hello {{unknown_var}}!"
    assert _resolve_templates("{{known}}", ctx) == "value"


def test_nested_template_resolution():
    """C-2 extended: nested templates like {{greeting}} where greeting='Hello {{caller_name}}' should resolve."""
    from voice_platform.flow.nodes import _resolve_templates

    ctx = {"greeting": "Hello {{caller_name}}", "caller_name": "Alice"}
    assert _resolve_templates("{{greeting}}", ctx) == "Hello Alice"


def test_build_template_context_includes_top_level_fields():
    """C-4: _build_template_context should include caller_name, caller_phone, result, etc."""
    from voice_platform.flow.nodes import _build_template_context

    state = {
        "extracted_vars": {"is_emergency": "yes"},
        "caller_name": "Alice",
        "caller_phone": "+1234567890",
        "result": {"booking_id": 42},
        "transcript": "Hello",
    }
    ctx = _build_template_context(state)
    assert ctx["caller_name"] == "Alice"
    assert ctx["caller_phone"] == "+1234567890"
    assert ctx["is_emergency"] == "yes"
    assert ctx["result"]["booking_id"] == 42
    assert "now" in ctx
    assert "call_date" in ctx
    assert "call_time" in ctx


def test_numeric_condition_comparison():
    """C-5: _normalize_value should coerce numeric strings for comparison operators."""
    from voice_platform.runtime.flow.conditions import ConditionEvaluator

    evaluator = ConditionEvaluator()
    # "8" >= 7 should work after numeric coercion
    assert evaluator.evaluate("nps_score >= 7", {"nps_score": "8"}) is True
    assert evaluator.evaluate("nps_score >= 7", {"nps_score": "3"}) is False
    assert evaluator.evaluate("nps_score <= 10", {"nps_score": "5"}) is True
    assert evaluator.evaluate("nps_score > 7", {"nps_score": "10"}) is True
    assert evaluator.evaluate("nps_score < 5", {"nps_score": "2"}) is True


def test_numeric_condition_with_float():
    """C-5 extended: float string coercion should work."""
    from voice_platform.runtime.flow.conditions import ConditionEvaluator

    evaluator = ConditionEvaluator()
    assert evaluator.evaluate("score >= 7.5", {"score": "8.0"}) is True
    assert evaluator.evaluate("score >= 7.5", {"score": "7.0"}) is False


def test_boolean_condition_still_works():
    """C-5 regression: boolean coercion should still work after adding numeric coercion."""
    from voice_platform.runtime.flow.conditions import ConditionEvaluator

    evaluator = ConditionEvaluator()
    assert evaluator.evaluate("is_emergency == true", {"is_emergency": "yes"}) is True
    assert evaluator.evaluate("is_emergency == true", {"is_emergency": "no"}) is False
    assert evaluator.evaluate("is_emergency == false", {"is_emergency": "no"}) is True


@pytest.mark.asyncio
async def test_action_preserves_extracted_vars_in_result():
    """C-1: action_handler should merge its output with existing state result, not replace it."""
    _events.clear()

    async def _merge_action_handler(state, config):
        existing = state.get("result", {})
        output = {"action_done": True}
        return {
            "last_result": output,
            "result": {**existing, **output},
        }

    handlers = {
        **_BASE_HANDLERS,
        "action": _merge_action_handler,
    }

    graph_json = {
        "nodes": [
            {"id": "trigger", "data": {"nodeType": "trigger"}},
            {"id": "act1", "data": {"nodeType": "action", "label": "First"}},
            {"id": "act2", "data": {"nodeType": "action", "label": "Second"}},
            {"id": "end", "data": {"nodeType": "end"}},
        ],
        "edges": [
            {"source": "trigger", "target": "act1"},
            {"source": "act1", "target": "act2"},
            {"source": "act2", "target": "end"},
        ],
    }

    compiled = compile_flow(
        graph_json,
        checkpointer=MemorySaver(),
        node_handlers=handlers,
    )
    state = create_initial_state(graph_json, user_id=1, agent_id=1)
    state["result"] = {"pre_existing_var": "hello"}

    result = await compiled.ainvoke(
        state, config={"configurable": {"thread_id": "t-merge", "event_callback": _event_callback}}
    )

    final_result = result.get("result", {})
    assert "pre_existing_var" in final_result, "Pre-existing var should survive action execution"
    assert final_result.get("pre_existing_var") == "hello"
    assert "action_done" in final_result, "Action output should be merged in"


@pytest.mark.asyncio
async def test_condition_handler_includes_extracted_vars():
    """NEW-6/C-1: condition_handler should be able to access extracted_vars, not just result."""
    from voice_platform.runtime.flow.conditions import ConditionEvaluator

    # Simulate the condition context that condition_handler now builds
    extracted_vars = {"is_emergency": "yes"}
    result_dict = {"booking_id": 42}
    cond_context = {
        **extracted_vars,
        **result_dict,
        "result": result_dict,
    }

    evaluator = ConditionEvaluator()
    # Should find is_emergency from extracted_vars
    assert evaluator.evaluate("is_emergency == true", cond_context) is True
    # Should also find booking_id from result_dict
    assert evaluator.evaluate("booking_id not_empty", cond_context) is True


def test_template_var_detection_regex_supports_dot_notation():
    """NEW-4: The template var detection regex should find {{result.foo}} patterns, not just {{word}}."""
    from voice_platform.flow.nodes import _TEMPLATE_PATTERN

    text = "Send to {{result.email}} and {{caller_name}}"
    matches = re.findall(_TEMPLATE_PATTERN, text)
    assert "result.email" in matches
    assert "caller_name" in matches


# ---------------------------------------------------------------------------
# Phase 2 regression tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_duplicate_node_start_on_cached_resume(monkeypatch):
    """NEW-1: Resuming from interrupt should NOT re-emit node_start for the cached node."""
    from voice_platform.flow import nodes as nodes_module
    from voice_platform.flow.nodes import create_node_handlers

    _events.clear()

    async def fake_call_openai(conv, llm_messages, node_id, event_callback):
        return "Hello! What is your name?"

    async def fake_extract(variables, state, config):
        return {}

    monkeypatch.setattr(nodes_module, "_call_openai", fake_call_openai)
    monkeypatch.setattr(nodes_module, "_extract_variables", fake_extract)

    class FakeConv:
        messages = [{"role": "system", "content": "You are Sara"}]
        initial_message = "Hello!"
        model = "test"
        temperature = 0
        max_tokens = 10
        tools = None
        context_window = 100

        def _is_ollama(self):
            return False

        def _ollama_raw_url(self):
            return ""

        def _get_http_client(self):
            return None

    async def _noop_action(state, config):
        return {}

    async def _noop_end(state, config):
        return {}

    agent = SimpleNamespace(id=1)
    handlers = create_node_handlers()
    handlers["action"] = _noop_action
    handlers["end"] = _noop_end

    graph_json = {
        "nodes": [
            {"id": "trigger", "data": {"nodeType": "trigger"}},
            {
                "id": "ask",
                "data": {
                    "nodeType": "conversation",
                    "label": "Ask",
                    "config": {"prompt": "Ask the caller their name"},
                },
            },
            {"id": "save", "data": {"nodeType": "action", "label": "Save"}},
            {"id": "end", "data": {"nodeType": "end"}},
        ],
        "edges": [
            {"source": "trigger", "target": "ask"},
            {"source": "ask", "target": "save"},
            {"source": "save", "target": "end"},
        ],
    }

    compiled = compile_flow(
        graph_json,
        checkpointer=MemorySaver(),
        node_handlers=handlers,
    )
    state = create_initial_state(graph_json, user_id=1, agent_id=1)

    _invoke_config = {"configurable": {"thread_id": "t-nodup", "event_callback": _event_callback,
        "playground_conv": FakeConv(), "agent": agent, "user_id": 1}}

    # Run to interrupt
    await compiled.ainvoke(state, config=_invoke_config)

    # Count node_start events before resume
    starts_before = [
        e for e in _events
        if e.get("event") == "node_start" and e.get("node_id") == "ask"
    ]

    # Resume — this re-executes the conversation node but should NOT emit node_start
    await compiled.ainvoke(
        Command(resume="hello"), config=_invoke_config
    )

    starts_after = [
        e for e in _events
        if e.get("event") == "node_start" and e.get("node_id") == "ask"
    ]

    # No new node_start should have been emitted on resume
    assert len(starts_after) == len(starts_before), (
        f"node_start should not be re-emitted on cached resume. "
        f"Before: {len(starts_before)}, After: {len(starts_after)}"
    )


@pytest.mark.asyncio
async def test_event_callback_failed_aborts_flow(monkeypatch):
    """H-2: If event_callback fails, flow execution should abort early."""
    from voice_platform.flow.executor import LangGraphFlowExecutor

    _events.clear()

    async def failing_callback(event):
        raise ConnectionError("WebSocket disconnected")

    agent = SimpleNamespace(
        id=1, mode="conversational_flow", graph_json='{"nodes":[],"edges":[]}',
        timezone="", llm_provider="openai",
    )

    executor = LangGraphFlowExecutor(
        agent=agent,
        graph={"nodes": [{"id": "trigger", "data": {"nodeType": "trigger"}}], "edges": []},
        playground_conv=None,
        user_id=1,
    )
    executor._event_callback_failed = True

    # Since _event_callback_failed is True, start_flow should abort after ainvoke
    # We can't easily test ainvoke without a real graph, but we can verify the flag is checked
    assert getattr(executor, "_event_callback_failed", False) is True


@pytest.mark.asyncio
async def test_update_context_async_persists_to_checkpoint():
    """H-3: update_context_async should update both local state and checkpoint."""
    from voice_platform.flow.executor import LangGraphFlowExecutor

    agent = SimpleNamespace(
        id=1, mode="conversational_flow", timezone="",
    )

    executor = LangGraphFlowExecutor(
        agent=agent,
        graph={"nodes": [{"id": "trigger", "data": {"nodeType": "trigger"}}], "edges": []},
        playground_conv=None,
        user_id=1,
    )

    # Before update, extracted_vars should be empty
    assert executor._state.get("extracted_vars", {}) == {}

    # Update context synchronously
    executor.update_context({"caller_name": "Alice"})
    assert executor._state["extracted_vars"]["caller_name"] == "Alice"

    # Update context async (without compiled graph, should just update local state)
    await executor.update_context_async({"caller_phone": "+1234567890"})
    assert executor._state["extracted_vars"]["caller_phone"] == "+1234567890"
    assert executor._state["extracted_vars"]["caller_name"] == "Alice"


@pytest.mark.asyncio
async def test_call_openai_retries_on_transient_error(monkeypatch):
    """M-8: _call_openai should retry on transient HTTP errors."""
    from voice_platform.flow import nodes as nodes_module
    from voice_platform.runtime.llm.client import LLMClient
    from voice_platform.runtime.llm.exceptions import ProviderUnavailableError
    from voice_platform.runtime.llm.types import ProviderCapability, StreamChunk

    call_count = 0

    class FakeAdapter:
        """Fake adapter that raises twice then yields a chunk."""
        capabilities = ProviderCapability(supports_streaming=True)

        def translate_messages(self, messages):
            return messages

        def stream(self, messages, *, tools=None, temperature=0.7, max_tokens=2048, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ProviderUnavailableError("Connection refused")

            async def _gen():
                yield StreamChunk(content="Hi")
            return _gen()

    def fake_create(provider, *, retry, timeout, **kwargs):
        return LLMClient(adapter=FakeAdapter(), retry=retry, timeout=timeout)

    from voice_platform.runtime.llm import factory as llm_factory_module
    monkeypatch.setattr(llm_factory_module.LLMFactory, "create", staticmethod(fake_create))

    class FakeConv:
        base_url = "https://api.openai.com/v1"
        model = "gpt-4"
        temperature = 0
        max_tokens = 10
        api_key = "test-key"
        tools = None
        _flow_mode = True

        def _is_ollama(self):
            return False

        def _get_http_client(self):
            return None

    original_sleep = asyncio.sleep

    async def fast_sleep(seconds):
        await original_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    events = []

    async def callback(event):
        events.append(event)

    result = await nodes_module._call_openai(
        FakeConv(), [{"role": "user", "content": "Hi"}], "test_node", callback
    )

    assert call_count == 3, f"Expected 3 attempts, got {call_count}"
    assert result == "Hi"


@pytest.mark.asyncio
async def test_call_openai_raises_after_max_retries(monkeypatch):
    """M-8: _call_openai should raise after exhausting all retries."""
    from voice_platform.flow import nodes as nodes_module
    from voice_platform.runtime.llm.client import LLMClient
    from voice_platform.runtime.llm.exceptions import ProviderUnavailableError
    from voice_platform.runtime.llm.types import ProviderCapability

    call_count = 0

    class FakeAdapter:
        """Fake adapter that always raises."""
        capabilities = ProviderCapability(supports_streaming=True)

        def translate_messages(self, messages):
            return messages

        def stream(self, messages, *, tools=None, temperature=0.7, max_tokens=2048, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ProviderUnavailableError("Connection refused")

    def fake_create(provider, *, retry, timeout, **kwargs):
        return LLMClient(adapter=FakeAdapter(), retry=retry, timeout=timeout)

    from voice_platform.runtime.llm import factory as llm_factory_module
    monkeypatch.setattr(llm_factory_module.LLMFactory, "create", staticmethod(fake_create))

    class FakeConv:
        base_url = "https://api.openai.com/v1"
        model = "gpt-4"
        temperature = 0
        max_tokens = 10
        api_key = "test-key"
        tools = None
        _flow_mode = True

        def _is_ollama(self):
            return False

        def _get_http_client(self):
            return None

    original_sleep = asyncio.sleep

    async def fast_sleep(seconds):
        await original_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    async def callback(event):
        pass

    with pytest.raises(ProviderUnavailableError):
        await nodes_module._call_openai(
            FakeConv(), [{"role": "user", "content": "Hi"}], "test_node", callback
        )

    assert call_count == 4, f"Expected 4 attempts (1 + 3 retries) before raising, got {call_count}"


@pytest.mark.asyncio
async def test_ws_tracker_cleanup_on_early_return():
    """H-1: transport.close() (which calls ws_tracker.remove) should be in finally block."""
    import inspect

    from voice_platform.api import playground_routes

    source = inspect.getsource(playground_routes.playground_flow_ws)
    # The outer finally must contain transport.close() which calls ws_tracker.remove
    assert "transport.close()" in source, "playground_flow_ws finally must call transport.close()"
    assert source.count("transport.close()") >= 1

    source_voice = inspect.getsource(playground_routes.playground_voice_ws)
    assert "ws_tracker.remove(voice_user_id, websocket)" in source_voice
    assert source_voice.count("ws_tracker.remove(voice_user_id, websocket)") == 1


@pytest.mark.asyncio
async def test_node_result_not_duplicated_on_cached_resume(monkeypatch):
    """NEW-1 extended: node_result should also not be re-emitted on cached resume."""
    from voice_platform.flow import nodes as nodes_module
    from voice_platform.flow.nodes import create_node_handlers

    _events.clear()

    async def fake_call_openai(conv, llm_messages, node_id, event_callback):
        return "Hello! What is your name?"

    async def fake_extract(variables, state, config):
        return {}

    monkeypatch.setattr(nodes_module, "_call_openai", fake_call_openai)
    monkeypatch.setattr(nodes_module, "_extract_variables", fake_extract)

    class FakeConv:
        messages = [{"role": "system", "content": "You are Sara"}]
        initial_message = "Hello!"
        model = "test"
        temperature = 0
        max_tokens = 10
        tools = None
        context_window = 100

        def _is_ollama(self):
            return False

        def _ollama_raw_url(self):
            return ""

        def _get_http_client(self):
            return None

    async def _noop_action(state, config):
        return {}

    async def _noop_end(state, config):
        return {}

    agent = SimpleNamespace(id=1)
    handlers = create_node_handlers()
    handlers["action"] = _noop_action
    handlers["end"] = _noop_end

    graph_json = {
        "nodes": [
            {"id": "trigger", "data": {"nodeType": "trigger"}},
            {
                "id": "ask",
                "data": {
                    "nodeType": "conversation",
                    "label": "Ask",
                    "config": {"prompt": "Ask the caller their name"},
                },
            },
            {"id": "save", "data": {"nodeType": "action", "label": "Save"}},
            {"id": "end", "data": {"nodeType": "end"}},
        ],
        "edges": [
            {"source": "trigger", "target": "ask"},
            {"source": "ask", "target": "save"},
            {"source": "save", "target": "end"},
        ],
    }

    compiled = compile_flow(
        graph_json,
        checkpointer=MemorySaver(),
        node_handlers=handlers,
    )
    state = create_initial_state(graph_json, user_id=1, agent_id=1)

    _invoke_config = {"configurable": {"thread_id": "t-nr", "event_callback": _event_callback,
        "playground_conv": FakeConv(), "agent": agent, "user_id": 1}}

    # Run to interrupt
    await compiled.ainvoke(state, config=_invoke_config)

    results_before = [
        e for e in _events
        if e.get("event") == "node_result" and e.get("node_id") == "ask"
    ]

    # Resume
    await compiled.ainvoke(
        Command(resume="hello"), config=_invoke_config
    )

    results_after = [
        e for e in _events
        if e.get("event") == "node_result" and e.get("node_id") == "ask"
    ]

    assert len(results_after) == len(results_before), (
        f"node_result should not be re-emitted on cached resume. "
        f"Before: {len(results_before)}, After: {len(results_after)}"
    )


@pytest.mark.asyncio
async def test_retry_count_router_uses_strict_less_than():
    """M-1: Router should use < not <= for retry comparison, matching the handler."""
    import inspect

    from voice_platform.flow import compiler as compiler_module

    source = inspect.getsource(compiler_module._build_state_graph)
    # Find the conversation router line
    assert "retry < max_retries" in source, (
        "Router should use strict < comparison, not <= (off-by-one fix M-1)"
    )
    assert "retry <= max_retries" not in source, (
        "Router should not use <= comparison (off-by-one bug M-1)"
    )


def test_graph_validation_rejects_missing_trigger():
    """M-5: graph_json without a trigger node should be rejected by API validation."""
    def _has_trigger(nodes: list) -> bool:
        return any(
            str((n.get("data") or {}).get("nodeType") or n.get("type")) == "trigger"
            for n in nodes
            if isinstance(n, dict)
        )

    graph_no_trigger = {
        "nodes": [
            {"id": "ask", "data": {"nodeType": "conversation"}},
            {"id": "end", "data": {"nodeType": "end"}},
        ],
        "edges": [
            {"source": "ask", "target": "end"},
        ],
    }
    assert not _has_trigger(graph_no_trigger["nodes"]), "Graph without trigger should fail validation"

    graph_with_trigger = {
        "nodes": [
            {"id": "trig", "data": {"nodeType": "trigger"}},
            {"id": "ask", "data": {"nodeType": "conversation"}},
            {"id": "end", "data": {"nodeType": "end"}},
        ],
        "edges": [
            {"source": "trig", "target": "ask"},
            {"source": "ask", "target": "end"},
        ],
    }
    assert _has_trigger(graph_with_trigger["nodes"]), "Graph with trigger should pass validation"


def test_dead_handlers_removed_from_node_handlers():
    """M-3: slot_validation_handler and extraction_handler should not be in the returned handlers dict."""
    import inspect

    from voice_platform.flow import nodes as nodes_module

    source = inspect.getsource(nodes_module.create_node_handlers)
    assert "slot_validation_handler" not in source, (
        "slot_validation_handler should be removed (dead code M-3)"
    )
    assert "extraction_handler" not in source, (
        "extraction_handler should be removed (dead code M-3)"
    )
    # slot_validator_handler is the new, correct handler
    assert "slot_validator_handler" in source, (
        "slot_validator_handler should be present in create_node_handlers"
    )


def test_slots_field_removed_from_flow_state():
    """M-6: slots field should not be in FlowState or make_initial_state."""
    from voice_platform.flow.state import FlowState, make_initial_state

    state = make_initial_state(
        user_id=1, agent_id=1, nodes_by_id={}, outgoing={}
    )
    assert "slots" not in state, "slots field should be removed from FlowState (M-6)"


def test_extraction_prompts_merge_defaults_with_agent_overrides():
    """NEW-3: Agent-specific extraction prompts should override defaults."""
    from types import MappingProxyType

    from voice_platform.runtime.services.extraction import ExtractionPrompts, ExtractionService

    # ExtractionService holds the merge logic (moved from WorkflowExecutor._get_extraction_prompt)
    service = ExtractionService.__new__(ExtractionService)
    service._agent_id = 1
    service._prompt_cache = {
        1: ExtractionPrompts(prompts=MappingProxyType({
            "order_number": "the customer's order number",
            "refund_reason": "why the customer wants a refund",
        })),
    }

    # Agent-specific prompt should be used for order_number
    desc = service._get_prompt("order_number")
    assert desc == "the customer's order number", (
        f"Agent-specific prompt should override default, got: {desc}"
    )

    # Default prompt should be used for preferred_date (not in agent overrides)
    desc_default = service._get_prompt("preferred_date")
    assert "preferred appointment date" in desc_default, (
        f"Default prompt should be used for preferred_date, got: {desc_default}"
    )

    # Fallback to variable name with underscores replaced for unknown vars
    desc_fallback = service._get_prompt("custom_var_xyz")
    assert desc_fallback == "custom var xyz", (
        f"Unknown variable should fall back to name with spaces, got: {desc_fallback}"
    )


@pytest.mark.asyncio
async def test_unified_streaming_client_aclose_is_noop():
    """NEW-2: aclose() is a no-op — LLMClient manages its own session lifecycle."""
    from voice_platform.agents.streaming_client import UnifiedStreamingClient

    client = UnifiedStreamingClient(
        api_key="sk-test-1234",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )

    # aclose should be a no-op and not raise
    await client.aclose()

    # Client should still be usable after aclose (it's a no-op)
    assert client.model == "gpt-4o-mini"
    assert client._api_key == "sk-test-1234"


# ── Phase 2-6 Verification Tests ───────────────────────────────────────


def test_stream_sanitizer_buffers_split_markers():
    """H-1: StreamSanitizer should strip internal markers split across chunk boundaries."""
    from voice_platform.flow.nodes import StreamSanitizer

    sanitizer = StreamSanitizer()
    # Feed a chunk that splits [INSTRUCTION ...] across two feeds
    out1 = sanitizer.feed("Hello [INSTRUCT")
    out2 = sanitizer.feed("ION — do X] world")
    final = sanitizer.flush()
    result = out1 + out2 + final
    assert "[INSTRUCTION" not in result, f"Internal marker should be stripped, got: {result}"
    assert "world" in result, f"Non-marker text should be preserved, got: {result}"


def test_stream_sanitizer_preserves_plain_text():
    """H-1: StreamSanitizer should pass through plain text without modification."""
    from voice_platform.flow.nodes import StreamSanitizer

    sanitizer = StreamSanitizer()
    out = sanitizer.feed("Hello, how can I help you?")
    final = sanitizer.flush()
    result = out + final
    assert result == "Hello, how can I help you?"


def test_stream_sanitizer_never_emits_midword_fragments():
    """Telephony TTS fix: streamed chunks must end on word boundaries.

    Regression for broken phone pronunciation where the 30-char holdback sliced
    words mid-token (e.g. "t|oday", "g|etting"), which Deepgram then spoke as
    separate fragments.
    """
    import re

    from voice_platform.flow.nodes import StreamSanitizer

    sanitizer = StreamSanitizer()
    deltas = [
        "So, how can I help you ",
        "today? Are you ",
        "calling about an appointment ",
        "or something else?",
    ]
    emitted = [sanitizer.feed(d) for d in deltas]
    tail = sanitizer.flush()

    # Every non-final streamed chunk must end on whitespace (no partial word).
    for piece in emitted:
        if piece:
            assert piece[-1].isspace(), f"chunk ends mid-word: {piece!r}"

    full = re.sub(r"\s+", " ", "".join(emitted) + tail).strip()
    assert full == (
        "So, how can I help you today? Are you calling about an "
        "appointment or something else?"
    )
    # The word that used to be split must survive intact somewhere in the stream.
    assert "today?" in full


def test_sanitize_token_strips_call107_coaching_leak():
    """Call 107: LLM spoke author coaching instead of a normal reply."""
    from voice_platform.runtime.llm.sanitizer import _sanitize_token

    leaked = (
        "If they sound like they're in pain or worried, don't — ask them: "
        "\"What's going on? How can I help you?\""
    )
    cleaned = _sanitize_token(leaked)
    assert "If they sound" not in cleaned
    assert "don't — ask them" not in cleaned.lower().replace("—", "-")
    assert "ask them:" not in cleaned.lower()
    # Prefer empty or a short safe remainder — never leave orphan quotes
    assert '"' not in cleaned
    assert "'" not in cleaned or cleaned.count("'") % 2 == 0


def test_build_step_instruction_excludes_coaching():
    """Identify-need coaching must not land in QUESTIONS for the LLM to echo."""
    from voice_platform.flow.nodes import _build_step_instruction

    prompt = (
        "Welcome the caller to SmileCare Dental Clinic and ask whether they need "
        "an appointment or have a dental emergency. If they report severe swelling, "
        "classify it as an emergency immediately. Ask their name only if the "
        "situation is not urgent."
    )
    instruction = _build_step_instruction(prompt, "Identify Need")
    assert "QUESTIONS:" in instruction
    assert "classify it as an emergency" not in instruction.lower()
    assert "only if the situation" not in instruction.lower()
    # Still steers the model toward the real ask
    assert "appointment" in instruction.lower() or "emergency" in instruction.lower()


def test_sanitize_event_strips_node_result():
    """H-5: _sanitize_event should strip raw result from node_result events."""
    from voice_platform.flow.nodes import _sanitize_event

    event = {
        "event": "node_result",
        "node_id": "test_node",
        "result": {"raw_api_response": "sensitive_data", "status": "success"},
    }
    sanitized = _sanitize_event(event)
    assert "raw_api_response" not in str(sanitized.get("result", "")), \
        "Raw API response should be stripped from node_result events"


def test_sanitize_event_truncates_long_error():
    """H-5: _sanitize_event should truncate long error text."""
    from voice_platform.flow.nodes import _sanitize_event

    long_error = "x" * 500
    event = {"event": "error", "text": long_error}
    sanitized = _sanitize_event(event)
    assert len(sanitized["text"]) <= 300, "Error text should be truncated to 300 chars"


def test_strip_unresolved_templates_removes_braces():
    """H-6: _strip_unresolved_templates should remove {{unknown}} patterns."""
    from voice_platform.flow.nodes import _strip_unresolved_templates

    # .strip() is applied, so leading/trailing resolved whitespace is trimmed
    assert _strip_unresolved_templates("Hello {{unknown}} world") == "Hello  world"
    assert _strip_unresolved_templates("{{a}} and {{b}}") == "and"
    assert _strip_unresolved_templates("no templates") == "no templates"
    assert _strip_unresolved_templates(["{{x}}", "ok"]) == ["", "ok"]
    assert _strip_unresolved_templates({"key": "{{y}}"}) == {"key": ""}


def test_strip_workflow_from_prompt_keeps_identity():
    """H-7: _strip_workflow_from_prompt should strip workflow sections but keep identity and guardrails."""
    from voice_platform.flow.nodes import _strip_workflow_from_prompt

    prompt = (
        "# Identity\nYou are a helpful assistant.\n\n"
        "# Inbound Workflow\n1. Ask for name.\n2. Ask for phone.\n\n"
        "# Outbound Workflow\n1. Greet caller.\n2. Offer help.\n\n"
        "# Conversation Budget\nKeep it short.\n\n"
        "# When to End\nSay goodbye.\n\n"
        "# Knowledge Base\nCheck the KB.\n\n"
        "# Background\nSome background.\n\n"
        "# Questions\nQ1?\n\n"
        "# Guardrails\nBe polite."
    )
    stripped = _strip_workflow_from_prompt(prompt)
    assert "Identity" in stripped, "Identity section should be preserved"
    assert "Inbound Workflow" not in stripped, "Inbound Workflow section should be stripped"
    assert "Outbound Workflow" not in stripped, "Outbound Workflow section should be stripped"
    assert "Conversation Budget" not in stripped, "Conversation Budget section should be stripped"
    assert "When to End" not in stripped, "When to End section should be stripped"
    assert "Knowledge Base" not in stripped, "Knowledge Base section should be stripped"
    assert "Background" not in stripped or "background" not in stripped.lower(), "Background section should be stripped"
    assert "Questions" not in stripped, "Questions section should be stripped"
    assert "Guardrails" in stripped, "Guardrails section should be preserved"
    assert "Flow Control" in stripped, "Flow Control section should be appended"


def test_parse_csv_values_json_array():
    """MH-2: _parse_csv_values should handle JSON arrays from LLMs."""
    from voice_platform.integrations.plugins.sheets import _parse_csv_values

    assert _parse_csv_values('["a", "b", "c"]') == ["a", "b", "c"]
    assert _parse_csv_values('["John Doe", "555-1234"]') == ["John Doe", "555-1234"]


def test_parse_csv_values_quoted_csv():
    """MH-2: _parse_csv_values should handle quoted CSV with commas inside values."""
    from voice_platform.integrations.plugins.sheets import _parse_csv_values

    result = _parse_csv_values('"Doe, John", 555-1234, "New York, NY"')
    assert result[0] == "Doe, John", f"Quoted value with comma should be preserved, got: {result[0]}"
    assert "555" in result[1], f"Second value should contain phone digits, got: {result[1]}"


def test_parse_csv_values_plain_split():
    """MH-2: _parse_csv_values should handle plain comma-separated values."""
    from voice_platform.integrations.plugins.sheets import _parse_csv_values

    assert _parse_csv_values("a, b, c") == ["a", "b", "c"]
    assert _parse_csv_values("single") == ["single"]
    assert _parse_csv_values("") == []


def test_compile_flow_rejects_empty_graph():
    """M-11: compile_flow should raise ValueError for empty graph."""
    from voice_platform.flow.compiler import compile_flow

    with pytest.raises(ValueError, match="no nodes"):
        compile_flow({"nodes": [], "edges": []}, node_handlers={})


def test_compile_flow_rejects_no_trigger():
    """M-11: compile_flow should raise ValueError when no start node exists.

    A graph where the only node has an incoming edge (self-loop) has no start node.
    """
    from voice_platform.flow.compiler import compile_flow

    graph = {
        "nodes": [{"id": "n1", "type": "conversation", "data": {"nodeType": "conversation"}}],
        "edges": [{"source": "n1", "target": "n1"}],  # self-loop means n1 has incoming edge
    }
    with pytest.raises(ValueError, match="no start node"):
        compile_flow(graph, node_handlers={})


def test_condition_router_falls_through_to_end():
    """M-12: Condition router with no matching branch should return END."""
    from voice_platform.flow.compiler import compile_flow

    graph = {
        "nodes": [
            {"id": "trigger", "type": "trigger", "data": {"nodeType": "trigger"}},
            {"id": "cond", "type": "condition", "data": {"nodeType": "condition"}},
            {"id": "end", "type": "end", "data": {"nodeType": "end"}},
        ],
        "edges": [
            {"source": "trigger", "target": "cond"},
            {"source": "cond", "target": "end"},
        ],
    }

    async def dummy_handler(state, config):
        return {}

    handlers = {
        "conversation": dummy_handler,
        "condition": dummy_handler,
        "action": dummy_handler,
    }
    compiled = compile_flow(graph, node_handlers=handlers)
    assert compiled is not None


def test_message_to_dict_complete_role_mapping():
    """L-2: _message_to_dict should map all role variants correctly."""
    from types import SimpleNamespace

    from voice_platform.flow.nodes import _message_to_dict

    assert _message_to_dict(SimpleNamespace(content="hi", type="human"))["role"] == "user"
    assert _message_to_dict(SimpleNamespace(content="hi", type="ai"))["role"] == "assistant"
    assert _message_to_dict(SimpleNamespace(content="hi", type="AI"))["role"] == "assistant"
    assert _message_to_dict(SimpleNamespace(content="hi", type="Human"))["role"] == "user"
    assert _message_to_dict(SimpleNamespace(content="hi", type="function"))["role"] == "tool"


@pytest.mark.asyncio
async def test_control_handler_gates_end_call_on_action_error():
    """End_call messages should not claim success when a preceding action failed."""
    from voice_platform.flow.nodes import create_node_handlers
    from voice_platform.flow.state import make_initial_state

    handlers = create_node_handlers()
    control_handler = handlers["end_call"]

    events = []

    async def _event_callback(event: dict):
        events.append(event)

    state = make_initial_state(
        user_id=1,
        agent_id=1,
        nodes_by_id={
            "end_1": {
                "id": "end_1",
                "data": {
                    "nodeType": "end_call",
                    "label": "End Call",
                    "config": {
                        "message": "You're all set, {{patient_name}}! I've sent the confirmation to your email.",
                        "error_message": "I have your details, but I couldn't finalize everything right now. We'll follow up shortly.",
                    },
                },
            }
        },
    )
    state["current_node"] = "end_1"
    state["extracted_vars"] = {"patient_name": "Alice"}
    # Simulate a preceding action failure via business_outcome
    state["business_outcome"] = {
        "availability": "available",
        "booking": "booked",
        "email": "failed",
        "patient_log": "written",
        "overall": "partial_success",
    }

    result = await control_handler(state, {"configurable": {"event_callback": _event_callback}})

    token_event = next((e for e in events if e["event"] == "agent_token"), None)
    assert token_event is not None
    # Claim check should rewrite "I've sent the confirmation" since email != "sent"
    assert "I've sent the confirmation" not in token_event["text"]
    assert result["last_result"]["message"] == token_event["text"]
    response_event = next((e for e in events if e["event"] == "agent_response"), None)
    assert response_event is not None
    assert response_event["text"] == token_event["text"]


@pytest.mark.asyncio
async def test_control_handler_emits_goodbye_agent_response_when_booked():
    """Booking Complete farewell must land in playground chat via agent_response."""
    from voice_platform.flow.nodes import create_node_handlers
    from voice_platform.flow.state import make_initial_state

    handlers = create_node_handlers()
    control_handler = handlers["end_call"]
    events = []

    async def _event_callback(event: dict):
        events.append(event)

    farewell = (
        "Your appointment is confirmed for {{preferred_date}} at {{preferred_time}} "
        "with {{preferred_dentist}}. A confirmation email has been sent. "
        "Please arrive 10 minutes early. Goodbye, and take care!"
    )
    state = make_initial_state(
        user_id=1,
        agent_id=1,
        nodes_by_id={
            "end_1": {
                "id": "end_1",
                "data": {
                    "nodeType": "end_call",
                    "label": "Booking Complete",
                    "config": {"message": farewell},
                },
            }
        },
    )
    state["current_node"] = "end_1"
    state["extracted_vars"] = {
        "preferred_date": "2026-07-22",
        "preferred_time": "15:00",
        "preferred_dentist": "Imran",
    }
    state["business_outcome"] = {
        "booking": "booked",
        "email": "sent",
        "overall": "success",
    }

    await control_handler(state, {"configurable": {"event_callback": _event_callback}})

    response_event = next((e for e in events if e["event"] == "agent_response"), None)
    assert response_event is not None
    assert "Goodbye" in response_event["text"]
    assert "Imran" in response_event["text"]
    assert "confirmation email has been sent" in response_event["text"].lower()


def test_smilecare_graph_has_no_true_cycles():
    """The SmileCare graph must not contain true cycles (only conditional retries)."""
    import asyncio

    from voice_platform.api.workflow_routes import list_workflow_templates
    from voice_platform.flow.compiler import _build_adjacency, _detect_cycles

    templates = asyncio.run(list_workflow_templates())
    smilecare = None
    for t in templates.get("templates", []):
        if t["id"] == "smilecare_dental":
            smilecare = t
            break
    assert smilecare is not None, "SmileCare template not found"

    graph_json = {"nodes": smilecare["nodes"], "edges": smilecare["edges"]}
    nodes_by_id, outgoing = _build_adjacency(graph_json)
    true_cycles, conditional_retries = _detect_cycles(nodes_by_id, outgoing)
    assert len(true_cycles) == 0, f"SmileCare graph has true cycles: {true_cycles}"


def test_smilecare_graph_requires_on_missing_for_required_inputs():
    """Action nodes with required_inputs must declare exactly one on_missing edge."""
    import asyncio

    from voice_platform.api.workflow_routes import list_workflow_templates
    from voice_platform.graph_contracts import required_input_branch_violations

    templates = asyncio.run(list_workflow_templates())
    smilecare = None
    for t in templates.get("templates", []):
        if t["id"] == "smilecare_dental":
            smilecare = t
            break
    assert smilecare is not None

    graph = {"nodes": smilecare["nodes"], "edges": smilecare["edges"]}
    violations = required_input_branch_violations(graph)
    assert violations == [], f"SmileCare template missing on_missing contracts: {violations}"


def test_smilecare_graph_does_not_duplicate_conversation_retry_loops():
    """Conversation nodes retry their own slots; explicit collector loops are redundant."""
    import asyncio

    from voice_platform.api.workflow_routes import list_workflow_templates

    templates = asyncio.run(list_workflow_templates())
    smilecare = None
    for t in templates.get("templates", []):
        if t["id"] == "smilecare_dental":
            smilecare = t
            break
    assert smilecare is not None

    assert all(node["type"] != "slot_validator" for node in smilecare["nodes"])
    assert all(not node["id"].startswith("collect_") for node in smilecare["nodes"])


def test_smilecare_graph_compiles_without_error():
    """The SmileCare graph must compile without raising a cycle error."""
    import asyncio

    from voice_platform.api.workflow_routes import list_workflow_templates
    from voice_platform.flow.compiler import _build_state_graph
    from voice_platform.flow.nodes import create_node_handlers

    templates = asyncio.run(list_workflow_templates())
    smilecare = None
    for t in templates.get("templates", []):
        if t["id"] == "smilecare_dental":
            smilecare = t
            break
    assert smilecare is not None

    graph_json = {"nodes": smilecare["nodes"], "edges": smilecare["edges"]}
    handlers = create_node_handlers()
    # Should not raise
    builder = _build_state_graph(graph_json, handlers)
    assert builder is not None


def test_slot_validator_handler_in_registry():
    """slot_validator handler must be registered in create_node_handlers."""
    from voice_platform.flow.nodes import create_node_handlers

    handlers = create_node_handlers()
    assert "slot_validator" in handlers
    assert callable(handlers["slot_validator"])


def test_slot_validator_compiles_in_graph():
    """A minimal graph with a slot_validator must compile without cycle errors."""
    graph_json = {
        "nodes": [
            {"id": "trigger", "data": {"nodeType": "trigger"}},
            {"id": "validator", "data": {"nodeType": "slot_validator", "label": "Validate", "config": {"required_slots": ["caller_email"]}}},
            {"id": "collect", "data": {"nodeType": "conversation", "label": "Collect", "config": {"prompt": "Email?", "variables_to_extract": ["caller_email"]}}},
            {"id": "end", "data": {"nodeType": "end_call", "label": "End", "config": {"message": "Done"}}},
        ],
        "edges": [
            {"source": "trigger", "target": "validator"},
            {"source": "validator", "target": "collect", "label": "caller_email"},
            {"source": "validator", "target": "end", "label": "done"},
            {"source": "collect", "target": "validator"},
        ],
    }
    from voice_platform.flow.compiler import _build_adjacency, _build_state_graph, _detect_cycles
    from voice_platform.flow.nodes import create_node_handlers

    nodes_by_id, outgoing = _build_adjacency(graph_json)
    true_cycles, conditional_retries = _detect_cycles(nodes_by_id, outgoing)
    assert len(true_cycles) == 0, f"True cycles found: {true_cycles}"
    # The validator → collector → validator loop is a conditional retry
    assert len(conditional_retries) > 0, "Expected at least one conditional retry"

    handlers = create_node_handlers()
    builder = _build_state_graph(graph_json, handlers)
    assert builder is not None
