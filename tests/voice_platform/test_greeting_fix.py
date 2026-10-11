"""Regression tests for the first-turn greeting fix.

Verifies:
- initial_message is used on entry node even when node_prompt exists
- LLM is not called when initial_message is emitted
- greeting is emitted exactly once per execution
- later conversation nodes do not replay the greeting
- no initial_message falls back to LLM generation
- _initial_message_sent flag is set only when greeting is actually emitted
- # Examples / ## Examples sections are stripped from flow prompts
- next Markdown section is preserved after Examples stripping
- "examples" in prose is not removed
- sub-headings inside Examples are removed
- Examples as final section is removed
- fresh sessions start with empty messages and _initial_message_sent=False
- reset produces a new thread_id
- separate sessions each greet once
- reset + new session greets once
"""

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_platform.flow.nodes import _conversation_generate, _strip_workflow_from_prompt
from voice_platform.flow.slots import SlotEngine
from voice_platform.flow.state import FlowState, make_initial_state

# ── Helpers ────────────────────────────────────────────────────────────

def _make_state(messages=None, initial_message_sent=False, **kwargs):
    state = make_initial_state(
        user_id=1,
        agent_id=1,
        agent_timezone="America/New_York",
    )
    state["messages"] = messages or []
    state["_initial_message_sent"] = initial_message_sent
    state.update(kwargs)
    return state


def _make_playground_conv(initial_message="Hello! Welcome to SmileCare Dental. How can I help you today?"):
    conv = SimpleNamespace()
    conv.initial_message = initial_message
    conv.messages = [{"role": "system", "content": "You are a dental receptionist."}]
    conv.model = "gpt-4o-mini"
    conv.temperature = 0.5
    conv.max_tokens = 2048
    conv.api_key = "test-key"
    conv.base_url = None
    conv.tools = []
    conv._is_ollama = MagicMock(return_value=False)
    return conv


def _make_config(event_callback, conv=None):
    return {
        "configurable": {
            "thread_id": "test-thread",
            "event_callback": event_callback,
            "playground_conv": conv or _make_playground_conv(),
            "agent": SimpleNamespace(id=1, timezone="America/New_York"),
            "user_id": 1,
            "db_session": None,
        },
        "recursion_limit": 50,
    }


def _make_engine(pending_vars=None):
    return SlotEngine(
        variables=pending_vars or ["visit_type", "is_emergency", "patient_name"],
        extracted_vars={},
        optional_inputs=["patient_name"],
    )


# ── Test 1: First turn uses initial_message despite non-empty node_prompt ──

@pytest.mark.asyncio
async def test_first_turn_uses_initial_message_with_node_prompt():
    """Entry node with empty messages + non-empty node_prompt + initial_message → uses initial_message."""
    state = _make_state(messages=[])
    events = []

    async def event_callback(event):
        events.append(event)

    conv = _make_playground_conv()
    config = _make_config(event_callback, conv)

    with patch("voice_platform.flow.nodes._call_openai", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "SHOULD NOT BE USED"
        result = await _conversation_generate(
            state=state,
            config=config,
            node_id="conversation_1",
            node_label="Identify Need",
            node_prompt="Welcome the caller to SmileCare Dental Clinic and ask whether they need an appointment or have a dental emergency.",
            pending_vars=["visit_type", "is_emergency", "patient_name"],
            engine=_make_engine(),
            event_callback=event_callback,
            playground_conv=conv,
            streaming_client=None,
            agent=SimpleNamespace(id=1, timezone="America/New_York"),
            user_id=1,
        )

    agent_tokens = [e for e in events if e.get("event") == "agent_token"]
    assert any("Hello! Welcome to SmileCare Dental" in t.get("text", "") for t in agent_tokens), \
        f"Expected initial_message in agent_token events, got: {agent_tokens}"
    mock_llm.assert_not_called()
    assert result.get("_initial_message_sent") is True


# ── Test 1b: Telephony already spoke greeting — no re-emit / no LLM ──

@pytest.mark.asyncio
async def test_greeting_already_spoken_skips_token_and_llm():
    """When FlowAgent already played the static opener, record it without agent_token."""
    state = _make_state(messages=[], _greeting_already_spoken=True, _initial_message_sent=True)
    events = []

    async def event_callback(event):
        events.append(event)

    conv = _make_playground_conv()
    config = _make_config(event_callback, conv)

    with patch("voice_platform.flow.nodes._call_openai", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "SHOULD NOT BE USED"
        result = await _conversation_generate(
            state=state,
            config=config,
            node_id="conversation_1",
            node_label="Identify Need",
            node_prompt="Welcome the caller to SmileCare Dental Clinic.",
            pending_vars=["visit_type"],
            engine=_make_engine(),
            event_callback=event_callback,
            playground_conv=conv,
            streaming_client=None,
            agent=SimpleNamespace(id=1, timezone="America/New_York"),
            user_id=1,
        )

    agent_tokens = [e for e in events if e.get("event") == "agent_token"]
    assert agent_tokens == [], f"Expected no agent_token re-emit, got: {agent_tokens}"
    mock_llm.assert_not_called()
    assert "Hello! Welcome to SmileCare Dental" in (result.get("transcript") or "")
    assert result.get("_initial_message_sent") is True


# ── Test 2: LLM not called when initial_message is used ──

@pytest.mark.asyncio
async def test_llm_not_called_when_initial_message_used():
    """Mock the LLM and assert it is never invoked when the configured initial message is used."""
    state = _make_state(messages=[])
    events = []

    async def event_callback(event):
        events.append(event)

    conv = _make_playground_conv()
    config = _make_config(event_callback, conv)

    with patch("voice_platform.flow.nodes._call_openai", new_callable=AsyncMock) as mock_openai, \
         patch("voice_platform.flow.nodes._call_ollama", new_callable=AsyncMock) as mock_ollama:
        result = await _conversation_generate(
            state=state,
            config=config,
            node_id="conversation_1",
            node_label="Identify Need",
            node_prompt="Welcome the caller to SmileCare Dental Clinic.",
            pending_vars=["visit_type"],
            engine=_make_engine(),
            event_callback=event_callback,
            playground_conv=conv,
            streaming_client=None,
            agent=SimpleNamespace(id=1, timezone="America/New_York"),
            user_id=1,
        )

    mock_openai.assert_not_called()
    mock_ollama.assert_not_called()
    assert result.get("_initial_message_sent") is True


# ── Test 3: Greeting emitted exactly once in one execution ──

@pytest.mark.asyncio
async def test_greeting_emitted_exactly_once():
    """_initial_message_sent flag prevents duplicate emission in same execution."""
    conv = _make_playground_conv()

    # First call: should emit greeting
    state = _make_state(messages=[])
    events = []

    async def event_callback(event):
        events.append(event)

    config = _make_config(event_callback, conv)

    with patch("voice_platform.flow.nodes._call_openai", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "LLM response"
        result1 = await _conversation_generate(
            state=state,
            config=config,
            node_id="conversation_1",
            node_label="Identify Need",
            node_prompt="Welcome the caller.",
            pending_vars=["visit_type"],
            engine=_make_engine(),
            event_callback=event_callback,
            playground_conv=conv,
            streaming_client=None,
            agent=SimpleNamespace(id=1, timezone="America/New_York"),
            user_id=1,
        )

    assert result1.get("_initial_message_sent") is True

    # Second call with the flag set: should NOT emit greeting, should call LLM
    state2 = _make_state(messages=result1.get("messages", []), initial_message_sent=True)
    events2 = []

    async def event_callback2(event):
        events2.append(event)

    config2 = _make_config(event_callback2, conv)

    with patch("voice_platform.flow.nodes._call_openai", new_callable=AsyncMock) as mock_llm2:
        mock_llm2.return_value = "LLM response for second turn"
        result2 = await _conversation_generate(
            state=state2,
            config=config2,
            node_id="conversation_1",
            node_label="Identify Need",
            node_prompt="Welcome the caller.",
            pending_vars=["visit_type"],
            engine=_make_engine(),
            event_callback=event_callback2,
            playground_conv=conv,
            streaming_client=None,
            agent=SimpleNamespace(id=1, timezone="America/New_York"),
            user_id=1,
        )

    agent_tokens2 = [e for e in events2 if e.get("event") == "agent_token"]
    initial_msg_tokens = [
        t for t in agent_tokens2
        if "Hello! Welcome to SmileCare Dental" in t.get("text", "")
    ]
    assert len(initial_msg_tokens) == 0, \
        f"Initial message should not be replayed, got: {initial_msg_tokens}"


# ── Test 4: Later conversation node does not replay greeting ──

@pytest.mark.asyncio
async def test_later_node_does_not_replay_greeting():
    """Second conversation node with messages → does NOT use initial_message."""
    state = _make_state(messages=[
        {"role": "assistant", "content": "Hello! Welcome to SmileCare Dental. How can I help you today?"},
        {"role": "user", "content": "I need an appointment."},
    ])
    events = []

    async def event_callback(event):
        events.append(event)

    conv = _make_playground_conv()
    config = _make_config(event_callback, conv)

    with patch("voice_platform.flow.nodes._call_openai", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "Sure, can I get your name and phone number?"
        result = await _conversation_generate(
            state=state,
            config=config,
            node_id="conversation_2",
            node_label="Contact Details",
            node_prompt="Ask for the caller's name and phone number.",
            pending_vars=["patient_name", "phone_number"],
            engine=_make_engine(["patient_name", "phone_number"]),
            event_callback=event_callback,
            playground_conv=conv,
            streaming_client=None,
            agent=SimpleNamespace(id=1, timezone="America/New_York"),
            user_id=1,
        )

    agent_tokens = [e for e in events if e.get("event") == "agent_token"]
    initial_msg_tokens = [
        t for t in agent_tokens
        if "Hello! Welcome to SmileCare Dental" in t.get("text", "")
    ]
    assert len(initial_msg_tokens) == 0, "Later node should not replay global greeting"
    assert result.get("_initial_message_sent") is not True, "Flag should not be set on later nodes"


# ── Test 5: No initial_message falls back to LLM ──

@pytest.mark.asyncio
async def test_no_initial_message_falls_back_to_llm():
    """No initial_message configured → LLM generates, flag remains False."""
    state = _make_state(messages=[])
    events = []

    async def event_callback(event):
        events.append(event)

    conv = _make_playground_conv(initial_message=None)
    config = _make_config(event_callback, conv)

    with patch("voice_platform.flow.nodes._call_openai", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "Welcome to SmileCare, how can I help?"
        result = await _conversation_generate(
            state=state,
            config=config,
            node_id="conversation_1",
            node_label="Identify Need",
            node_prompt="Welcome the caller.",
            pending_vars=["visit_type"],
            engine=_make_engine(),
            event_callback=event_callback,
            playground_conv=conv,
            streaming_client=None,
            agent=SimpleNamespace(id=1, timezone="America/New_York"),
            user_id=1,
        )

    mock_llm.assert_called_once()
    assert result.get("_initial_message_sent") is not True, \
        "Flag should not be set when no initial_message was configured"


# ── Test 6: Flag set only when greeting is actually emitted ──

@pytest.mark.asyncio
async def test_flag_set_only_when_greeting_emitted():
    """Flag is True only in initial_message branch, not in LLM/exception/fallback branches."""
    state = _make_state(messages=[])
    events = []

    async def event_callback(event):
        events.append(event)

    conv = _make_playground_conv(initial_message=None)
    config = _make_config(event_callback, conv)

    with patch("voice_platform.flow.nodes._call_openai", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = Exception("LLM error")
        result = await _conversation_generate(
            state=state,
            config=config,
            node_id="conversation_1",
            node_label="Identify Need",
            node_prompt="Welcome the caller.",
            pending_vars=["visit_type"],
            engine=_make_engine(),
            event_callback=event_callback,
            playground_conv=conv,
            streaming_client=None,
            agent=SimpleNamespace(id=1, timezone="America/New_York"),
            user_id=1,
        )

    assert result.get("_initial_message_sent") is not True, \
        "Flag should not be set on LLM exception"


# ── Test 7: Examples section is stripped (both # and ##) ──

def test_strip_workflow_removes_examples_section():
    """Both # Examples and ## Examples are removed."""
    # # Examples (SmileCare style)
    prompt1 = """You are a dental receptionist.

# Guardrails
- Be professional.

# Examples
User: My tooth has been hurting a lot since yesterday.
You: Oh, that sounds really uncomfortable. How bad is the pain?

# Emergency
- Severe swelling is an emergency.
"""
    result1 = _strip_workflow_from_prompt(prompt1)
    assert "My tooth has been hurting" not in result1, "# Examples content should be removed"
    assert "Oh, that sounds really uncomfortable" not in result1, "# Examples You: line should be removed"
    assert "# Guardrails" in result1, "# Guardrails should be preserved"
    assert "# Emergency" in result1, "# Emergency should be preserved"

    # ## Examples (customer support style)
    prompt2 = """You are a customer support agent.

## Examples
User: 'Hi, my order hasn't arrived yet.'
You: 'Oh no, I'm sorry about that. Can I get your order number?'

## Guardrails
- Never make up order details.
"""
    result2 = _strip_workflow_from_prompt(prompt2)
    assert "my order hasn't arrived" not in result2, "## Examples content should be removed"
    assert "Oh no, I'm sorry" not in result2, "## Examples You: line should be removed"
    assert "Guardrails" in result2, "## Guardrails should be preserved"


# ── Test 8: Next Markdown section preserved ──

def test_strip_workflow_preserves_next_section():
    """# Guardrails / # Emergency / # Voice Conduct survive stripping."""
    prompt = """You are a dental receptionist.

# Examples
User: My tooth hurts.
You: That sounds uncomfortable.

# Guardrails
- Be professional.
- Do not diagnose.

# Emergency
- Severe swelling is an emergency.

# Voice Conduct
- Speak clearly.
"""
    result = _strip_workflow_from_prompt(prompt)
    assert "# Guardrails" in result, "Guardrails section must survive"
    assert "# Emergency" in result, "Emergency section must survive"
    assert "# Voice Conduct" in result, "Voice Conduct section must survive"
    assert "Do not diagnose" in result, "Guardrails content must survive"
    assert "Severe swelling" in result, "Emergency content must survive"
    assert "Speak clearly" in result, "Voice Conduct content must survive"


# ── Test 9: "examples" in prose is not removed ──

def test_strip_workflow_preserves_examples_in_prose():
    """Word 'examples' in ordinary text is not removed."""
    prompt = """You are a dental receptionist.

Here are some examples of good responses: be polite and concise.

# Guardrails
- Be professional.
"""
    result = _strip_workflow_from_prompt(prompt)
    assert "examples of good responses" in result, \
        "The word 'examples' in prose should not be removed"


# ── Test 10: Sub-headings inside Examples are removed ──

def test_strip_workflow_removes_subheadings_inside_examples():
    """### Emergency example inside ## Examples is removed, ## Guardrails is preserved."""
    prompt = """You are a dental receptionist.

## Examples

### Emergency example
User: I have severe swelling.
You: That sounds like an emergency. Can you come in today?

### Routine example
User: I need a cleaning.
You: Sure! Let me check availability.

## Guardrails
- Be professional.
"""
    result = _strip_workflow_from_prompt(prompt)
    assert "Emergency example" not in result, "Sub-heading inside Examples should be removed"
    assert "Routine example" not in result, "Sub-heading inside Examples should be removed"
    assert "I have severe swelling" not in result, "Example content under sub-heading should be removed"
    assert "## Guardrails" in result, "## Guardrails must be preserved"
    assert "Be professional" in result, "Guardrails content must be preserved"


# ── Test 11: Examples as final section ──

def test_strip_workflow_examples_as_final_section():
    """## Examples at end of prompt is removed to end-of-string."""
    prompt = """You are a dental receptionist.

# Guardrails
- Be professional.

# Examples
User: My tooth hurts.
You: That sounds uncomfortable.
"""
    result = _strip_workflow_from_prompt(prompt)
    assert "My tooth hurts" not in result, "Final Examples section content should be removed"
    assert "That sounds uncomfortable" not in result, "Final Examples You: line should be removed"
    assert "# Guardrails" in result, "Guardrails must be preserved"
    assert "Be professional" in result, "Guardrails content must be preserved"


# ── Test 12: Fresh session has no messages and flag is False ──

def test_new_session_has_no_messages():
    """Fresh make_initial_state has empty messages and _initial_message_sent=False."""
    state = make_initial_state(user_id=1, agent_id=1)
    assert state["messages"] == [], "Fresh state should have empty messages"
    assert state["_initial_message_sent"] is False, "Fresh state should have _initial_message_sent=False"


# ── Test 13: Reset produces new thread_id ──

@pytest.mark.asyncio
async def test_reset_produces_new_thread_id():
    """reset() generates new UUID for thread_id."""
    from voice_platform.flow.executor import LangGraphFlowExecutor

    agent = SimpleNamespace(id=1, timezone="America/New_York")
    graph = {"nodes": [], "edges": []}
    conv = _make_playground_conv()

    executor = LangGraphFlowExecutor(
        agent=agent,
        graph=graph,
        playground_conv=conv,
        user_id=1,
    )
    old_thread_id = executor._thread_id

    await executor.reset()
    new_thread_id = executor._thread_id

    assert old_thread_id != new_thread_id, "reset() should produce a new thread_id"
    assert executor._compiled_graph is None, "reset() should clear compiled graph"
    assert executor.started is False, "reset() should set started=False"


# ── Test 14: Separate sessions each greet once ──

@pytest.mark.asyncio
async def test_separate_sessions_each_greet_once():
    """Two separately created sessions should each emit the greeting once."""
    conv = _make_playground_conv()

    # Session 1
    state1 = _make_state(messages=[])
    events1 = []

    async def cb1(event):
        events1.append(event)

    config1 = _make_config(cb1, conv)

    with patch("voice_platform.flow.nodes._call_openai", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "SHOULD NOT BE USED"
        result1 = await _conversation_generate(
            state=state1, config=config1, node_id="conversation_1",
            node_label="Identify Need", node_prompt="Welcome the caller.",
            pending_vars=["visit_type"], engine=_make_engine(),
            event_callback=cb1, playground_conv=conv, streaming_client=None,
            agent=SimpleNamespace(id=1, timezone="America/New_York"), user_id=1,
        )

    assert result1.get("_initial_message_sent") is True

    # Session 2 — completely fresh state
    state2 = _make_state(messages=[])
    events2 = []

    async def cb2(event):
        events2.append(event)

    config2 = _make_config(cb2, conv)

    with patch("voice_platform.flow.nodes._call_openai", new_callable=AsyncMock) as mock_llm2:
        mock_llm2.return_value = "SHOULD NOT BE USED"
        result2 = await _conversation_generate(
            state=state2, config=config2, node_id="conversation_1",
            node_label="Identify Need", node_prompt="Welcome the caller.",
            pending_vars=["visit_type"], engine=_make_engine(),
            event_callback=cb2, playground_conv=conv, streaming_client=None,
            agent=SimpleNamespace(id=1, timezone="America/New_York"), user_id=1,
        )

    assert result2.get("_initial_message_sent") is True, \
        "Second fresh session should also emit greeting"

    tokens1 = [e for e in events1 if e.get("event") == "agent_token"]
    tokens2 = [e for e in events2 if e.get("event") == "agent_token"]
    assert any("Hello! Welcome to SmileCare Dental" in t.get("text", "") for t in tokens1)
    assert any("Hello! Welcome to SmileCare Dental" in t.get("text", "") for t in tokens2)


# ── Test 15: Reset + new session greets once ──

@pytest.mark.asyncio
async def test_reset_new_session_greets_once():
    """Old session ends, new session starts, new session emits exactly one greeting."""
    conv = _make_playground_conv()

    # First session
    state1 = _make_state(messages=[])
    events1 = []

    async def cb1(event):
        events1.append(event)

    config1 = _make_config(cb1, conv)

    with patch("voice_platform.flow.nodes._call_openai", new_callable=AsyncMock):
        result1 = await _conversation_generate(
            state=state1, config=config1, node_id="conversation_1",
            node_label="Identify Need", node_prompt="Welcome the caller.",
            pending_vars=["visit_type"], engine=_make_engine(),
            event_callback=cb1, playground_conv=conv, streaming_client=None,
            agent=SimpleNamespace(id=1, timezone="America/New_York"), user_id=1,
        )

    assert result1.get("_initial_message_sent") is True

    # Simulate reset: create a completely fresh state (new session)
    state2 = _make_state(messages=[])
    events2 = []

    async def cb2(event):
        events2.append(event)

    config2 = _make_config(cb2, conv)

    with patch("voice_platform.flow.nodes._call_openai", new_callable=AsyncMock):
        result2 = await _conversation_generate(
            state=state2, config=config2, node_id="conversation_1",
            node_label="Identify Need", node_prompt="Welcome the caller.",
            pending_vars=["visit_type"], engine=_make_engine(),
            event_callback=cb2, playground_conv=conv, streaming_client=None,
            agent=SimpleNamespace(id=1, timezone="America/New_York"), user_id=1,
        )

    assert result2.get("_initial_message_sent") is True, \
        "New session after reset should emit greeting once"

    tokens2 = [e for e in events2 if e.get("event") == "agent_token"]
    greeting_tokens = [
        t for t in tokens2
        if "Hello! Welcome to SmileCare Dental" in t.get("text", "")
    ]
    assert len(greeting_tokens) == 1, \
        f"New session should emit exactly one greeting, got {len(greeting_tokens)}"
