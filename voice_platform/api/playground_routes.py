"""
Voice Platform — Web Agent Playground Routes
===============================================

Browser-based agent testing via WebSocket text chat (no phone required).

This allows users to test their agent's behavior directly from the browser
by sending text messages and receiving text responses. The agent uses the
same LLM config as phone calls but skips STT/TTS for instant feedback.

For voice testing, the frontend can use the Web Speech API for STT
and the SpeechSynthesis API for TTS — keeping the backend simple.

Routes:
    WS   /api/playground/ws/{agent_id}   — Interactive text chat with an agent
    GET  /api/playground/agents           — List agents available for testing
    POST /api/playground/message          — Single message (REST fallback)
"""

import asyncio
import base64
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.agents.agent_factory import (
    _PROVIDER_MODELS,
    LLM_BASE_URLS,
    LLM_DEFAULT_MODELS,
    PlatformAgentFactory,
    _build_google_drive_tool_actions,
)
from voice_platform.api.playground_voice import PlaygroundVoiceSession
from voice_platform.database import (
    Agent,
    KnowledgeBase,
    PlaygroundSession,
    UserApiKey,
    async_session,
    get_db,
)
from voice_platform.encryption import decrypt
from voice_platform.errors import AgentInactiveError, AgentNotFoundError, NotFoundError
from voice_platform.flow.executor import LangGraphFlowExecutor
from voice_platform.graph_contracts import canonical_content_hash
from voice_platform.integrations.executor import WorkflowExecutor
from voice_platform.middleware.auth_middleware import (
    _wants_bearer_subprotocol,
    get_current_user,
    get_current_user_ws,
)
from voice_platform.middleware.ws_tracker import ws_tracker
from voice_platform.runtime.prompt_renderer import PromptRenderer, RenderContext
from voice_platform.runtime.services.knowledge import KnowledgeContext, KnowledgeDocument
from voice_platform.runtime.services.memory import MemoryService
from voice_platform.runtime.session.adapters.flow import FlowRuntime
from voice_platform.runtime.session.adapters.playground import PlaygroundRuntime
from voice_platform.runtime.session.adapters.playground_conversation import (
    PLAYGROUND_MAX_MESSAGE_CHARS,
    PlaygroundConversation,
    _build_playground_conversation,
)
from voice_platform.runtime.session.builder import ContextBuildRequest, ExecutionContextBuilder
from voice_platform.runtime.session.conversation_context import ConversationChannel
from voice_platform.runtime.session.events import (
    SessionEvent,
    SessionEventFactory,
    SessionEventType,
    TransportEventType,
)
from voice_platform.runtime.session.execution import ConversationInput
from voice_platform.runtime.session.runtime_config import WorkflowContext
from voice_platform.runtime.session.session import ConversationSession, create_conversation_id

router = APIRouter(prefix="/api/playground", tags=["Playground"])

PLAYGROUND_MAX_HISTORY_MESSAGES = 20


# PlaygroundConversation and _build_playground_conversation relocated to
# voice_platform/runtime/session/adapters/playground_conversation.py
# Runtime must never depend on API — dependency graph points inward.


async def _fetch_agent_for_user(db: AsyncSession, agent_id: int, user_id: int) -> Optional[Agent]:
    """Fetch an agent, checking both direct ownership and team membership.

    Eager-loads linked_workflow so Agent.graph resolves the same source of truth
    used by telephony (workflow.graph_json when linked, else agents.graph_json).
    """
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Agent)
        .options(selectinload(Agent.linked_workflow))
        .where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return None

    # Direct ownership
    if agent.user_id == user_id:
        return agent

    # Team membership
    team_id = getattr(agent, "team_id", None)
    if team_id:
        from voice_platform.rbac import get_team_membership

        if await get_team_membership(user_id, team_id):
            return agent

    return None


def _playground_runtime_identity(
    agent: Agent,
    *,
    conversation_id: Optional[str] = None,
    websocket_connection_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    executor_instance_id: Optional[str] = None,
) -> dict:
    """Build sanitized playground runtime identity for diagnostics."""
    from voice_platform.diagnostics import build_runtime_identity

    prompt_version = getattr(agent, "current_prompt_version_id", None)
    identity = build_runtime_identity(
        agent_id=getattr(agent, "id", None),
        agent_name=getattr(agent, "name", None),
        agent_mode=getattr(agent, "mode", "single_prompt"),
        execution_channel="playground",
        conversation_id=conversation_id,
        websocket_connection_id=websocket_connection_id,
        thread_id=thread_id,
        prompt_version_or_hash=str(prompt_version) if prompt_version else None,
        prompt_preamble=getattr(agent, "prompt_preamble", None),
        graph=getattr(agent, "graph", None),
        executor_instance_id=executor_instance_id,
        model_provider=getattr(agent, "llm_provider", None),
        stt_provider=getattr(agent, "stt_provider", None),
        tts_provider=getattr(agent, "tts_provider", None),
    )
    identity["workflow_id"] = getattr(agent, "workflow_id", None)
    identity["context_profile"] = "playground_mock"
    identity["memory_mode"] = "disabled"
    return identity


def _verify_requested_flow_revision(websocket: WebSocket, agent: Agent) -> str | None:
    """Return a safe error when Save & Test does not match the runtime graph."""
    query_params = getattr(websocket, "query_params", {})
    requested_workflow_id = query_params.get("workflow_id")
    expected_graph_hash = query_params.get("graph_hash")

    if requested_workflow_id:
        try:
            parsed_workflow_id = int(requested_workflow_id)
        except (TypeError, ValueError):
            return "Invalid workflow revision. Return to the editor and use Save & Test again."
        if getattr(agent, "workflow_id", None) != parsed_workflow_id:
            return "The agent is not running the workflow revision requested by this playground."

    if expected_graph_hash:
        current_graph_hash = canonical_content_hash(getattr(agent, "graph", None))
        if expected_graph_hash != current_graph_hash:
            return "The workflow changed before the playground opened. Reload from the editor."

    return None


# ── WebSocket Endpoint ────────────────────────────────────────────────

@router.websocket("/ws/{agent_id}")
async def playground_ws(websocket: WebSocket, agent_id: int):
    """
    WebSocket endpoint for interactive agent testing.
    
    Preferred auth: websocket subprotocol bearer,<JWT_TOKEN>
    Legacy auth: /api/playground/ws/{agent_id}?token=JWT_TOKEN
    
    Client sends: {"type": "message", "text": "Hello"}
    Server sends: {"type": "token", "text": "Hi"} (streaming tokens)
                  {"type": "message_end"} (end of response)
                  {"type": "initial_message", "text": "..."} (agent greeting)
                  {"type": "error", "text": "..."} (error)
    """
    try:
        user = await get_current_user_ws(websocket)
    except Exception:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    user_id = int(cast(Any, user.id))
    if not ws_tracker.can_connect(user_id):
        await websocket.close(code=1013, reason="Too many concurrent connections")
        return

    from voice_platform.runtime.session.factory import ConversationSessionFactory
    from voice_platform.runtime.session.service_container import ServiceContainer
    from voice_platform.runtime.transport.websocket import WebSocketTransport

    transport = WebSocketTransport(websocket=websocket, user_id=user_id)

    # Fetch agent
    try:
        session_factory = cast(Any, async_session)
        async with session_factory() as db:
            agent = await _fetch_agent_for_user(db, agent_id, user_id)

        if not agent:
            await websocket.send_json({"type": "error", "text": "Agent not found", "fatal": True})
            await websocket.close()
            return

        if not bool(cast(Any, agent.is_active)):
            await websocket.send_json({"type": "error", "text": "Agent is inactive", "fatal": True})
            await websocket.close()
            return
    except Exception as e:
        await websocket.send_json({"type": "error", "text": str(e)[:200]})
        await websocket.close()
        return

    # Build session via factory
    services: ServiceContainer = websocket.app.state.services
    factory = ConversationSessionFactory(service_container=services)

    try:
        session = await factory.create(
            agent=agent,
            user_id=user_id,
            channel=ConversationChannel.PLAYGROUND_CHAT,
            agent_id=agent_id,
        )
    except Exception as e:
        await websocket.send_json({"type": "error", "text": str(e)[:200]})
        await websocket.close()
        return

    await transport.start()

    # Rate limiting
    _last_msg_time = 0.0
    _MIN_MSG_INTERVAL = 1.0
    _ws_connection_id = str(uuid.uuid4())
    _executor_instance_id = str(uuid.uuid4())
    _conversation_id = getattr(session, "conversation_id", None) or str(uuid.uuid4())

    try:
        # Start session and stream initial events
        async for event in session.start():
            await transport.send(event)
        await transport.send(SessionEventFactory.runtime_identity(
            _playground_runtime_identity(
                agent,
                conversation_id=_conversation_id,
                websocket_connection_id=_ws_connection_id,
                executor_instance_id=_executor_instance_id,
            )
        ))

        # Main event loop
        while True:
            transport_event = await transport.receive()
            if transport_event is None:
                # Timeout — send ping
                await transport.send(SessionEventFactory.pong())
                continue

            if transport_event.type == TransportEventType.TEXT:
                text = transport_event.payload.get("text", "")
                now = time.time()
                if now - _last_msg_time < _MIN_MSG_INTERVAL:
                    await transport.send(SessionEventFactory.error(
                        "Please wait a moment before sending another message."
                    ))
                    continue
                _last_msg_time = now

                async for event in session.receive_message(text):
                    await transport.send(event)

            elif transport_event.type == TransportEventType.RESET:
                await session.end()
                # Re-fetch agent to validate ownership
                sf = cast(Any, async_session)
                async with sf() as db:
                    agent = await _fetch_agent_for_user(db, agent_id, user_id)
                if not agent:
                    await transport.send(SessionEventFactory.error("Agent not found or access revoked"))
                    break
                if not bool(cast(Any, agent.is_active)):
                    await transport.send(SessionEventFactory.error("Agent is inactive"))
                    break
                session = await factory.create(
                    agent=agent,
                    user_id=user_id,
                    channel=ConversationChannel.PLAYGROUND_CHAT,
                    agent_id=agent_id,
                )
                _executor_instance_id = str(uuid.uuid4())
                _conversation_id = getattr(session, "conversation_id", None) or str(uuid.uuid4())
                async for event in session.start():
                    await transport.send(event)
                await transport.send(SessionEventFactory.runtime_identity(
                    _playground_runtime_identity(
                        agent,
                        conversation_id=_conversation_id,
                        websocket_connection_id=_ws_connection_id,
                        executor_instance_id=_executor_instance_id,
                    )
                ))
                await transport.send(SessionEventFactory.reset_ack())

            elif transport_event.type == TransportEventType.PING:
                await transport.send(SessionEventFactory.pong())

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"Playground WS error: {e}")
    finally:
        await session.end()
        await transport.close()


# ── REST Endpoints ────────────────────────────────────────────────────

@router.get("/agents")
async def list_playground_agents(
    active_only: bool = False,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all agents available for playground testing."""
    query = select(Agent).where(Agent.user_id == user.id)
    if active_only:
        query = query.where(Agent.is_active == True)
    query = query.order_by(Agent.updated_at.desc())
    result = await db.execute(query)
    agents = result.scalars().all()
    
    return {
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "llm_provider": a.llm_provider,
                "llm_model": a.llm_model,
                "initial_message": a.initial_message,
                "is_active": a.is_active,
                "language": getattr(a, "language", None),
                "stt_language": getattr(a, "stt_language", None),
                "mode": getattr(a, "mode", None),
            }
            for a in agents
        ]
    }


class SingleMessageRequest(BaseModel):
    agent_id: int
    message: str
    conversation_history: Optional[List[Dict]] = None


@router.post("/message")
async def send_single_message(
    request: SingleMessageRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    REST endpoint for single message exchange (non-streaming fallback).
    
    Useful for simple testing or when WebSocket isn't available.
    """
    agent = await _fetch_agent_for_user(db, request.agent_id, int(cast(Any, user.id)))
    if not agent:
        raise AgentNotFoundError(request.agent_id)
    if not bool(cast(Any, agent.is_active)):
        raise AgentInactiveError(request.agent_id)

    message_text = request.message.strip()
    if not message_text:
        raise HTTPException(422, "Message cannot be empty")
    if len(message_text) > PLAYGROUND_MAX_MESSAGE_CHARS:
        raise HTTPException(
            422,
            f"Message too long. Maximum {PLAYGROUND_MAX_MESSAGE_CHARS} characters.",
        )
    
    try:
        conversation = await _build_playground_conversation(agent, user.id)
        
        # Inject conversation history if provided
        if request.conversation_history:
            normalized_history = [
                {
                    "role": msg.get("role"),
                    "content": msg.get("content", ""),
                }
                for msg in request.conversation_history
                if msg.get("role") in ("user", "assistant")
            ][-PLAYGROUND_MAX_HISTORY_MESSAGES:]

            if normalized_history:
                # Frontend may include the latest user turn in history while also
                # passing it as `message`; avoid double-injecting the same turn.
                last_msg = normalized_history[-1]
                if (
                    last_msg.get("role") == "user"
                    and isinstance(last_msg.get("content"), str)
                    and last_msg.get("content", "").strip() == message_text
                ):
                    normalized_history = normalized_history[:-1]

            for msg in normalized_history:
                conversation.messages.append(msg)
        
        msg_result = await conversation.send_message(message_text)

        return {
            "response": msg_result["text"],
            "metrics": msg_result.get("metrics", {}),
            "agent": {"name": agent.name, "model": conversation.model},
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to generate response: {str(e)[:200]}")


@router.get("/scenarios/{agent_id}")
async def get_agent_scenarios(
    agent_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return pre-built test scenarios based on agent template/type.

    These are quick-test utterances that simulate common caller
    interactions so users can validate agent behavior instantly.
    """
    agent = await _fetch_agent_for_user(db, agent_id, int(cast(Any, user.id)))
    if not agent:
        raise AgentNotFoundError(agent_id)
    if not bool(cast(Any, agent.is_active)):
        raise AgentInactiveError(agent_id)

    # Derive scenarios from template_id or agent name/prompt
    template_id = getattr(agent, "template_id", None)
    scenarios = _derive_scenarios(
        template_id, str(agent.name), str(agent.prompt_preamble or "")
    )

    return {"scenarios": scenarios}


def _derive_scenarios(
    template_id: Optional[str], name: str, prompt: str
) -> List[Dict[str, str]]:
    """Generate contextual test scenarios based on agent domain."""
    # Base scenarios always available
    base: List[Dict[str, str]] = [
        {
            "id": "greeting",
            "label": "Standard Greeting",
            "text": "Hello, can you hear me?",
        },
        {
            "id": "confused",
            "label": "Confused Caller",
            "text": "I don't understand what you're saying.",
        },
        {
            "id": "goodbye",
            "label": "Say Goodbye",
            "text": "Thanks, bye!",
        },
    ]

    # Template-specific scenarios
    template_scenarios: Dict[str, List[Dict[str, str]]] = {
        "restaurant-booking": [
            {
                "id": "book_table",
                "label": "Book a Table",
                "text": "I'd like to book a table for 4 people on Friday at 7 PM.",
            },
            {
                "id": "dietary",
                "label": "Dietary Restrictions",
                "text": "Do you have gluten-free options?",
            },
            {
                "id": "cancel",
                "label": "Cancel Reservation",
                "text": "I need to cancel my reservation from last week.",
            },
        ],
        "healthcare-scheduler": [
            {
                "id": "appointment",
                "label": "Schedule Appointment",
                "text": "I need to schedule a checkup for next Tuesday morning.",
            },
            {
                "id": "symptoms",
                "label": "Describe Symptoms",
                "text": "I've had a headache and fever for two days.",
            },
            {
                "id": "insurance",
                "label": "Insurance Question",
                "text": "Do you accept Blue Cross insurance?",
            },
        ],
        "salon-appointment": [
            {
                "id": "book_cut",
                "label": "Book Haircut",
                "text": "I'd like to book a haircut for Saturday at 2 PM.",
            },
            {
                "id": "services",
                "label": "Ask Services",
                "text": "What services do you offer?",
            },
            {
                "id": "pricing",
                "label": "Ask Pricing",
                "text": "How much is a color and cut?",
            },
        ],
        "ecommerce-support": [
            {
                "id": "order_status",
                "label": "Order Status",
                "text": "Where is my order? I placed it three days ago.",
            },
            {
                "id": "return",
                "label": "Return Item",
                "text": "I want to return the shoes I bought last week.",
            },
            {
                "id": "refund",
                "label": "Request Refund",
                "text": "I'd like a refund for my last purchase.",
            },
        ],
        "real-estate": [
            {
                "id": "viewing",
                "label": "Schedule Viewing",
                "text": "Can I schedule a viewing for the property on Main Street?",
            },
            {
                "id": "price",
                "label": "Ask Price",
                "text": "What is the asking price for this property?",
            },
            {
                "id": "neighborhood",
                "label": "Neighborhood Info",
                "text": "Tell me about the neighborhood and nearby schools.",
            },
        ],
        "hotel-booking": [
            {
                "id": "book_room",
                "label": "Book a Room",
                "text": "I'd like to book a double room for next weekend.",
            },
            {
                "id": "amenities",
                "label": "Ask Amenities",
                "text": "Do you have a pool and gym?",
            },
            {
                "id": "checkout",
                "label": "Late Checkout",
                "text": "Can I get a late checkout until 2 PM?",
            },
        ],
    }

    if template_id and template_id in template_scenarios:
        return base + template_scenarios[template_id]

    # Fallback: derive from prompt keywords
    prompt_lower = prompt.lower()
    if any(w in prompt_lower for w in ["restaurant", "table", "reservation", "book", "dining"]):
        return base + template_scenarios.get("restaurant-booking", [])
    if any(w in prompt_lower for w in ["health", "doctor", "clinic", "appointment", "medical", "patient"]):
        return base + template_scenarios.get("healthcare-scheduler", [])
    if any(w in prompt_lower for w in ["salon", "hair", "spa", "beauty", "nail"]):
        return base + template_scenarios.get("salon-appointment", [])
    if any(w in prompt_lower for w in ["support", "help", "issue", "ticket", "order", "return", "refund", "shipping"]):
        return base + template_scenarios.get("ecommerce-support", [])
    if any(w in prompt_lower for w in ["property", "house", "real estate", "listing", "mortgage"]):
        return base + template_scenarios.get("real-estate", [])
    if any(w in prompt_lower for w in ["hotel", "room", "booking", "check-in", "check-out", "reservation"]):
        return base + template_scenarios.get("hotel-booking", [])

    return base


# ── Flow Playground (Conversational Flow Agents) ─────────────────────
# NOTE: The legacy FlowPlaygroundConversation class has been removed.
# The WebSocket endpoint below uses LangGraphFlowExecutor instead.


@router.websocket("/ws/{agent_id}/flow")
async def playground_flow_ws(websocket: WebSocket, agent_id: int):
    """
    WebSocket endpoint for interactive flow playground testing.

    Executes the agent's graph_json in real-time, streaming node-by-node
    execution events to the frontend.

    Client sends:
        {"type": "start"} — Start the flow (sends initial agent response)
        {"type": "message", "text": "..."} — Send a user message
        {"type": "set_context", "context": {...}} — Update mock context
        {"type": "reset"} — Reset the flow
        {"type": "ping"}

    Server sends:
        {"type": "flow_start", ...} — Flow started
        {"type": "node_start", ...} — Node execution started
        {"type": "agent_token", "text": "..."} — Streaming LLM token
        {"type": "agent_response", "text": "..."} — Complete LLM response
        {"type": "node_result", ...} — Node execution finished
        {"type": "edge_traversed", ...} — Edge traversal
        {"type": "flow_end", ...} — Flow completed
        {"type": "error", "text": "..."} — Error occurred
        {"type": "pong"} — Ping response

    Authentication: Bearer token via WebSocket subprotocol.
    """
    # ── Auth ──────────────────────────────────────────────────────
    user = None
    try:
        user = await get_current_user_ws(websocket)
    except Exception:
        await websocket.close(code=4001)
        return
    if user is None:
        await websocket.close(code=4001)
        return

    flow_user_id = cast(int, user.id)

    if not ws_tracker.can_connect(flow_user_id):
        await websocket.close(code=1013, reason="Too many concurrent connections")
        return

    # ── Fetch agent ───────────────────────────────────────────────
    session_factory = cast(Any, async_session)
    async with session_factory() as db:
        agent = await _fetch_agent_for_user(db, agent_id, flow_user_id)
    if agent is None:
        await websocket.close(code=4004)
        return

    revision_error = _verify_requested_flow_revision(websocket, agent)
    if revision_error:
        await websocket.close(code=4009, reason=revision_error)
        return

    # Gate on Agent.graph (canonical) — same source telephony uses via Agent.graph
    if agent.mode != "conversational_flow" or not getattr(agent, "graph", None):
        await websocket.close(code=4003)
        return

    # ── Build session via factory ─────────────────────────────────
    from voice_platform.runtime.session.factory import ConversationSessionFactory
    from voice_platform.runtime.session.service_container import ServiceContainer
    from voice_platform.runtime.transport.websocket import WebSocketTransport

    services: ServiceContainer = websocket.app.state.services
    factory = ConversationSessionFactory(service_container=services)

    try:
        session = await factory.create(
            agent=agent,
            user_id=flow_user_id,
            channel=ConversationChannel.PLAYGROUND_FLOW,
            agent_id=agent_id,
        )
    except Exception as e:
        logger.error(f"Flow playground session creation error: {e}", exc_info=True)
        await websocket.close(code=4003)
        return

    transport = WebSocketTransport(websocket=websocket, user_id=flow_user_id)
    await transport.start()

    # Access the underlying FlowRuntime executor for flow-specific operations
    flow_executor = session._runtime._executor  # type: ignore[attr-defined]
    _ws_connection_id = str(uuid.uuid4())
    _executor_instance_id = getattr(flow_executor, "_executor_instance_id", None) or str(uuid.uuid4())
    if not getattr(flow_executor, "_executor_instance_id", None):
        flow_executor._executor_instance_id = _executor_instance_id
    _conversation_id = getattr(session, "conversation_id", None) or str(uuid.uuid4())

    # Send initial context to client (M-14: include thread_id for reconnection)
    await transport.send(SessionEventFactory.context(
        context=flow_executor.context,
        thread_id=flow_executor._thread_id,
    ))
    await transport.send(SessionEventFactory.runtime_identity(
        _playground_runtime_identity(
            agent,
            conversation_id=_conversation_id,
            websocket_connection_id=_ws_connection_id,
            thread_id=flow_executor._thread_id,
            executor_instance_id=_executor_instance_id,
        )
    ))

    # ── Main event loop ───────────────────────────────────────────
    try:
        while True:
            transport_event = await transport.receive()
            if transport_event is None:
                # Timeout — send ping
                await transport.send(SessionEventFactory.pong())
                continue

            if transport_event.type == TransportEventType.START:
                # M-14: Accept thread_id in start message for reconnection
                reconnect_thread_id = transport_event.payload.get("thread_id")
                if reconnect_thread_id and isinstance(reconnect_thread_id, str):
                    flow_executor._thread_id = reconnect_thread_id
                    flow_executor._config = {
                        "configurable": {"thread_id": reconnect_thread_id},
                        "recursion_limit": 50,
                    }
                    logger.info(f"Playground: reconnecting to thread_id={reconnect_thread_id[:8]}")

                # Start the flow — stream events from session.start()
                try:
                    async for event in session.start():
                        await transport.send(event)
                except Exception as e:
                    logger.error(f"Flow playground start error: {e}", exc_info=True)
                    await transport.send(SessionEventFactory.error(str(e)[:200]))

            elif transport_event.type == TransportEventType.TEXT:
                text = transport_event.payload.get("text", "")
                try:
                    async for event in session.receive_message(text):
                        await transport.send(event)
                except Exception as e:
                    logger.error(f"Flow playground message error: {e}", exc_info=True)
                    await transport.send(SessionEventFactory.error(str(e)[:200]))

            elif transport_event.type == TransportEventType.SET_CONTEXT:
                ctx = transport_event.payload.get("context", {})
                await flow_executor.update_context_async(ctx)
                await transport.send(SessionEventFactory.context_updated(
                    context=flow_executor.context,
                ))

            elif transport_event.type == TransportEventType.RESET:
                await session.end()
                async with session_factory() as db:
                    refreshed_agent = await _fetch_agent_for_user(
                        db, agent_id, flow_user_id
                    )
                if refreshed_agent is None:
                    await transport.send(SessionEventFactory.error("Agent not found or access revoked"))
                    break
                revision_error = _verify_requested_flow_revision(websocket, refreshed_agent)
                if revision_error:
                    await transport.send(SessionEventFactory.error(revision_error))
                    break
                agent = refreshed_agent
                session = await factory.create(
                    agent=agent,
                    user_id=flow_user_id,
                    channel=ConversationChannel.PLAYGROUND_FLOW,
                    agent_id=agent_id,
                )
                flow_executor = session._runtime._executor  # type: ignore[attr-defined]
                _executor_instance_id = getattr(
                    flow_executor, "_executor_instance_id", None
                ) or str(uuid.uuid4())
                _conversation_id = getattr(
                    session, "conversation_id", None
                ) or str(uuid.uuid4())
                await transport.send(SessionEventFactory.reset_ack())
                await transport.send(SessionEventFactory.context(
                    context=flow_executor.context,
                    thread_id=flow_executor._thread_id,
                ))
                await transport.send(SessionEventFactory.runtime_identity(
                    _playground_runtime_identity(
                        agent,
                        conversation_id=_conversation_id,
                        websocket_connection_id=_ws_connection_id,
                        thread_id=flow_executor._thread_id,
                        executor_instance_id=_executor_instance_id,
                    )
                ))

            elif transport_event.type == TransportEventType.PING:
                await transport.send(SessionEventFactory.pong())

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Flow playground WebSocket error: {e}", exc_info=True)
    finally:
        await session.end()
        await transport.close()


# ── Production Voice WebSocket ────────────────────────────────────────

@router.websocket("/ws/{agent_id}/voice")
async def playground_voice_ws(websocket: WebSocket, agent_id: int):
    """
    WebSocket endpoint for production voice testing in the playground.

    Uses the agent's configured STT/TTS providers for real audio synthesis
    and transcription, instead of browser-based Web Speech API.

    Client sends:
        {"type": "synthesize", "text": "..."} — Synthesize text to audio
        {"type": "transcribe", "audio": "<base64>", "sample_rate": 16000} — Transcribe audio
        {"type": "ping"}

    Server sends:
        {"type": "voice_ready", "audio_format": {"encoding": "linear16", "sample_rate": 16000}}
        {"type": "audio", "data": "<base64>"} — Synthesized audio
        {"type": "transcript", "text": "..."} — Transcribed text
        {"type": "error", "text": "..."}
        {"type": "pong"}
    """
    try:
        user = await get_current_user_ws(websocket)
    except Exception:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # Enforce concurrent connection limit
    voice_user_id = int(cast(Any, user.id))
    if not ws_tracker.can_connect(voice_user_id):
        await websocket.close(code=1013, reason="Too many concurrent connections")
        return

    subprotocol = "bearer" if _wants_bearer_subprotocol(websocket) else None
    if subprotocol:
        await websocket.accept(subprotocol=subprotocol)
    else:
        await websocket.accept()

    await ws_tracker.add(voice_user_id, websocket)

    voice_session: Optional[PlaygroundVoiceSession] = None

    try:
        # Load agent and build voice session
        try:
            session_factory = cast(Any, async_session)
            async with session_factory() as db:
                agent = await _fetch_agent_for_user(db, agent_id, voice_user_id)
                # Load user API keys for TTS/STT provider resolution
                key_result = await db.execute(
                    select(UserApiKey).where(
                        UserApiKey.user_id == int(cast(Any, user.id)),
                        UserApiKey.is_active.is_(True),
                    )
                )
                user_api_keys = key_result.scalars().all()

            if not agent:
                await websocket.send_json({"type": "error", "text": "Agent not found", "fatal": True})
                await websocket.close()
                return
            if not bool(cast(Any, agent.is_active)):
                await websocket.send_json({"type": "error", "text": "Agent is inactive", "fatal": True})
                await websocket.close()
                return

            voice_session = PlaygroundVoiceSession(
                agent=agent,
                user_id=int(cast(Any, user.id)),
                user_api_keys=user_api_keys,
            )
        except Exception as e:
            await websocket.send_json({"type": "error", "text": str(e)[:200]})
            await websocket.close()
            return

        # Send voice session info
        try:
            await voice_session._init_synthesizer()
            audio_format = voice_session.get_audio_format()
            await websocket.send_json({
                "type": "voice_ready",
                "audio_format": audio_format,
                "tts_provider": voice_session._tts_provider,
                "tts_voice": voice_session._tts_voice,
            })
        except Exception as e:
            await websocket.send_json({"type": "error", "text": f"Voice init failed: {str(e)[:150]}"})

        try:
            while True:
                data = await websocket.receive_json()

                if data.get("type") == "synthesize":
                    text = data.get("text", "").strip()
                    if not text:
                        continue
                    if len(text) > PLAYGROUND_MAX_MESSAGE_CHARS:
                        await websocket.send_json({
                            "type": "error",
                            "text": f"Text too long. Maximum {PLAYGROUND_MAX_MESSAGE_CHARS} characters.",
                        })
                        continue

                    try:
                        audio_bytes = await voice_session.synthesize_text(text)
                        if audio_bytes:
                            audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
                            await websocket.send_json({
                                "type": "audio",
                                "data": audio_b64,
                                "format": voice_session.get_audio_format(),
                            })
                        else:
                            await websocket.send_json({
                                "type": "error",
                                "text": "TTS synthesis returned no audio",
                            })
                    except Exception as e:
                        await websocket.send_json({
                            "type": "error",
                            "text": f"TTS error: {str(e)[:150]}",
                        })

                elif data.get("type") == "transcribe":
                    audio_b64 = data.get("audio", "")
                    sample_rate = data.get("sample_rate", 16000)
                    audio_encoding = data.get("encoding", "linear16")
                    if not audio_b64:
                        continue

                    try:
                        audio_bytes = base64.b64decode(audio_b64)
                        transcript = await voice_session.transcribe_audio(
                            [audio_bytes], sample_rate=sample_rate, encoding=audio_encoding
                        )
                        if transcript:
                            await websocket.send_json({
                                "type": "transcript",
                                "text": transcript,
                            })
                        else:
                            await websocket.send_json({
                                "type": "transcript",
                                "text": "",
                            })
                    except Exception as e:
                        await websocket.send_json({
                            "type": "error",
                            "text": f"STT error: {str(e)[:150]}",
                        })

                elif data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.debug(f"Voice playground WS error: {e}")
        finally:
            if voice_session is not None:
                await voice_session.close()
    finally:
        await ws_tracker.remove(voice_user_id, websocket)


# ── Session Recording API ─────────────────────────────────────────────


class SaveSessionRequest(BaseModel):
    agent_id: int
    session_type: str = "chat"  # chat or flow
    messages: List[Dict] = Field(default_factory=list)
    trace_events: Optional[List[Dict]] = None
    context: Optional[Dict] = None
    voice_mode: str = "text"
    tts_provider: Optional[str] = None
    turn_count: int = 0
    total_tokens: int = 0
    total_latency_ms: float = 0.0


@router.post("/sessions")
async def save_session(
    request: SaveSessionRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save a playground session for later replay."""
    if request.session_type not in ("chat", "flow"):
        raise HTTPException(status_code=400, detail="Invalid session_type. Must be 'chat' or 'flow'.")
    agent = await _fetch_agent_for_user(db, request.agent_id, int(cast(Any, user.id)))
    if not agent:
        raise AgentNotFoundError(request.agent_id)

    session = PlaygroundSession(
        user_id=int(cast(Any, user.id)),
        agent_id=request.agent_id,
        session_type=request.session_type,
        messages_json=json.dumps(request.messages),
        trace_events_json=json.dumps(request.trace_events) if request.trace_events else None,
        context_json=json.dumps(request.context) if request.context else None,
        voice_mode=request.voice_mode,
        tts_provider=request.tts_provider,
        turn_count=request.turn_count,
        total_tokens=request.total_tokens,
        total_latency_ms=request.total_latency_ms,
        status="ended",
        ended_at=datetime.now(timezone.utc),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return {"session": session.to_dict()}


@router.get("/sessions")
async def list_sessions(
    agent_id: Optional[int] = None,
    session_type: Optional[str] = None,
    limit: int = 20,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List saved playground sessions."""
    limit = min(max(limit, 1), 50)
    query = select(PlaygroundSession).where(
        PlaygroundSession.user_id == int(cast(Any, user.id))
    )
    if agent_id:
        query = query.where(PlaygroundSession.agent_id == agent_id)
    if session_type:
        query = query.where(PlaygroundSession.session_type == session_type)
    query = query.order_by(PlaygroundSession.created_at.desc()).limit(limit)
    result = await db.execute(query)
    sessions = result.scalars().all()

    return {
        "sessions": [
            {
                "id": s.id,
                "agent_id": s.agent_id,
                "agent_name": s.agent.name if s.agent else None,
                "session_type": s.session_type,
                "turn_count": s.turn_count,
                "status": s.status,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in sessions
        ]
    }


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a full playground session for replay."""
    result = await db.execute(
        select(PlaygroundSession).where(
            PlaygroundSession.id == session_id,
            PlaygroundSession.user_id == int(cast(Any, user.id)),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise NotFoundError("Session not found")

    return {"session": session.to_dict()}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a saved playground session."""
    result = await db.execute(
        select(PlaygroundSession).where(
            PlaygroundSession.id == session_id,
            PlaygroundSession.user_id == int(cast(Any, user.id)),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise NotFoundError("Session not found")

    await db.delete(session)
    await db.commit()

    return {"deleted": True}
