"""FlowAgent must speak the static opener before graph compile / LLM."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vocode.streaming.models.agent import ChatGPTAgentConfig
from vocode.streaming.models.message import BaseMessage


@pytest.mark.asyncio
async def test_flow_agent_speaks_static_greeting_before_compile():
    from voice_platform.agents.flow_agent import FlowAgent

    config = ChatGPTAgentConfig(
        openai_api_key="test",
        model_name="gpt-4o-mini",
        prompt_preamble="You are a dental receptionist.",
        initial_message=BaseMessage(text="Hello! Welcome to SmileCare Dental."),
        generate_responses=True,
    )

    agent = FlowAgent(
        agent_config=config,
        graph_json={"nodes": [], "edges": []},
        agent_id=14,
        user_id=1,
    )
    agent.agent_responses_consumer = MagicMock()
    agent.interruptible_event_factory = MagicMock()
    agent.interruptible_event_factory.create_interruptible_agent_response_event = MagicMock(
        side_effect=lambda *a, **k: SimpleNamespace(payload=a[0] if a else None)
    )
    agent.conversation_state_manager = SimpleNamespace(
        _conversation=SimpleNamespace(initial_message_tracker=asyncio.Event())
    )

    spoke_before_compile = {"value": False}

    async def slow_ensure_compiled():
        await asyncio.sleep(0)
        spoke_before_compile["value"] = (
            agent.agent_responses_consumer.consume_nonblocking.call_count >= 2
        )
        agent._flow_state = {
            "_greeting_already_spoken": False,
            "_initial_message_sent": False,
        }
        agent._compiled_graph = MagicMock()
        agent._langgraph_config = {"configurable": {"thread_id": "t"}, "recursion_limit": 50}

        async def fake_ainvoke(state, config=None):
            return {**state, "ok": True}

        agent._compiled_graph.ainvoke = fake_ainvoke

        class _Snap:
            next = ("wait",)
            tasks = []

        agent._compiled_graph.aget_state = AsyncMock(return_value=_Snap())

    with patch.object(agent, "_ensure_compiled", side_effect=slow_ensure_compiled), \
         patch("voice_platform.database.async_session") as mock_session:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock())
        cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.return_value = cm

        await agent._start_flow_and_greet()

    assert spoke_before_compile["value"] is True
    assert agent._flow_state.get("_greeting_already_spoken") is True
    assert agent._flow_state.get("_initial_message_sent") is True
    assert agent.conversation_state_manager._conversation.initial_message_tracker.is_set()
