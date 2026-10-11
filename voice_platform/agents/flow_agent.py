"""
FlowAgent — LangGraph-based flow execution agent for telephony calls.

Executes conversational flow graphs during real phone calls by plugging into
the vocode streaming conversation pipeline as a BaseAgent subclass.

On each transcription:
1. First call: starts the LangGraph flow, runs to first conversation node
2. Subsequent calls: resumes flow with Command(resume=user_text)
3. Conversation nodes: streams LLM response via UnifiedStreamingClient
4. Action nodes: executes via WorkflowExecutor (existing)
5. Condition nodes: deterministic routing (existing)

The flow pauses at each conversation node (interrupt) and resumes
when the next transcription arrives.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from loguru import logger

from vocode.streaming.action.abstract_factory import AbstractActionFactory
from vocode.streaming.action.default_factory import DefaultActionFactory
from vocode.streaming.agent.base_agent import (
    AgentResponseMessage,
    AgentResponseStop,
    GeneratedResponse,
    RespondAgent,
)
from vocode.streaming.models.actions import EndOfTurn
from vocode.streaming.models.agent import ChatGPTAgentConfig
from vocode.streaming.models.message import BaseMessage
from vocode.streaming.utils.worker import InterruptibleEventFactory
from voice_platform.agents.streaming_client import UnifiedStreamingClient
from voice_platform.flow.nodes import _strip_workflow_from_prompt
from voice_platform.flow.state import FlowState
from voice_platform.runtime.session.state_manager import StateManager

# Sentinel values for queue signaling
_END_OF_TURN = object()
_FLOW_END = object()
_ERROR = object()

@dataclass
class FlowLLMConfig:
    """Lightweight LLM config for flow node handlers.

    Mimics the PlaygroundConversation interface subset that node handlers use:
    - messages[0] is the system prompt
    - _is_ollama() for provider detection
    - model/temperature/max_tokens for LLM calls
    - _flow_mode = True to disable tool definitions in LLM calls
    """

    model: str
    temperature: float
    max_tokens: int
    api_key: str
    base_url: Optional[str]
    messages: List[Dict] = field(default_factory=list)
    initial_message: Optional[str] = None
    agent_timezone: Optional[str] = None
    user_id: Optional[int] = None
    _flow_mode: bool = True
    # L-1: Cache the httpx.AsyncClient so it's reused across LLM calls instead of creating a new one each time
    _cached_http_client: Optional[httpx.AsyncClient] = field(default=None, repr=False)

    def _is_ollama(self) -> bool:
        return "ollama" in (self.base_url or "").lower() or "localhost:11434" in (
            self.base_url or ""
        )

    def _get_http_client(self) -> httpx.AsyncClient:
        # L-1: Reuse cached client if available to avoid creating a new connection pool per call
        if self._cached_http_client is not None:
            return self._cached_http_client
        client = httpx.AsyncClient(timeout=60.0)
        self._cached_http_client = client
        return client


class FlowAgent(RespondAgent[ChatGPTAgentConfig]):
    """Agent that executes a conversational flow graph during phone calls.

    Plugs into the vocode streaming conversation pipeline as a RespondAgent.
    The StreamingConversation, TranscriptionsWorker, and AgentResponsesWorker
    remain unchanged — they just see a different agent implementation.
    """

    def __init__(
        self,
        agent_config: ChatGPTAgentConfig,
        graph_json: dict,
        agent_id: int,
        user_id: int,
        action_factory: AbstractActionFactory = DefaultActionFactory(),
        state_manager: Optional[StateManager] = None,
    ):
        super().__init__(agent_config, action_factory)
        self._graph_json = graph_json
        self._agent_id = agent_id
        self._user_id = user_id
        self._caller_phone = agent_config.flow_caller_phone or ""
        self._db_agent: Optional[Any] = None
        self._state_manager = state_manager

        # Build FlowLLMConfig from agent_config
        self._llm_config = FlowLLMConfig(
            model=agent_config.model_name,
            temperature=agent_config.temperature,
            max_tokens=agent_config.max_tokens,
            api_key=agent_config.openai_api_key or "",
            base_url=agent_config.base_url_override,
            messages=[
                {"role": "system", "content": _strip_workflow_from_prompt(agent_config.prompt_preamble)}
            ],
            initial_message=(
                agent_config.initial_message.text
                if agent_config.initial_message
                else None
            ),
        )

        # Build streaming client
        self._streaming_client = UnifiedStreamingClient(
            api_key=agent_config.openai_api_key or "",
            base_url=agent_config.base_url_override,
            model=agent_config.model_name,
            temperature=agent_config.temperature,
            max_tokens=agent_config.max_tokens,
        )

        # Flow state (lazy init)
        self._flow_started = False
        self._compiled_graph = None
        self._checkpointer: Optional[Any] = None
        self._thread_id = str(uuid.uuid4())
        self._langgraph_config = {"configurable": {"thread_id": self._thread_id}, "recursion_limit": 50}
        self._flow_state: Optional[FlowState] = None
        self._response_queue: Optional[asyncio.Queue] = None
        self._greeting_task: Optional[asyncio.Task] = None

    def start(self):
        """Start the agent worker and kick off flow execution for greeting."""
        super().start()
        self._greeting_task = asyncio.create_task(self._start_flow_and_greet())
        # Track lifecycle via ConversationSession if attached
        session = getattr(self, "_conversation_session", None)
        if session is not None:
            asyncio.create_task(self._consume_session_events(session))

    async def _consume_session_events(self, session):
        """Drain ConversationSession.start() async generator.

        ConversationSession.start() is an AsyncGenerator, not a coroutine,
        so it cannot be passed directly to asyncio.create_task(). This wrapper
        consumes the generator, which transitions the session state from
        INIT → STARTING → RUNNING. TelephonyRuntime.start() yields nothing,
        so only the state transition matters.
        """
        try:
            async for _event in session.start():
                pass
        except Exception as e:
            logger.debug(f"Session start completed: {e}")

    async def _ensure_compiled(self):
        """Lazily compile the LangGraph flow and create node handlers."""
        if self._compiled_graph is not None:
            return

        # Set streaming mode based on synthesizer type (conversation_state_manager is attached by now)
        try:
            self._streaming_client.use_input_streaming = (
                self.conversation_state_manager.using_input_streaming_synthesizer()
            )
        except Exception:
            logger.debug("FlowAgent: could not check synthesizer type, defaulting to collate mode")

        # Resolve checkpointer via StateManager if available, otherwise fallback
        if self._state_manager is not None:
            self._checkpointer = await self._state_manager.get_checkpointer()
        else:
            from voice_platform.database import DATABASE_URL

            if DATABASE_URL.startswith("postgresql"):
                from voice_platform.flow.executor import get_checkpointer

                self._checkpointer = await get_checkpointer()
            else:
                from langgraph.checkpoint.memory import MemorySaver

                self._checkpointer = MemorySaver()

        # Look up db_agent from DB if not already loaded
        if self._db_agent is None and self._agent_id:
            from voice_platform.database import Agent, async_session

            async with async_session() as session:
                self._db_agent = await session.get(Agent, self._agent_id)

        if self._db_agent is None:
            raise RuntimeError(
                f"FlowAgent: could not load agent {self._agent_id} from DB"
            )

        # Create flow state
        from voice_platform.flow.compiler import create_initial_state

        self._flow_state = create_initial_state(
            graph_json=self._graph_json,
            user_id=self._user_id,
            agent_id=self._agent_id,
            agent_timezone=getattr(self._db_agent, "timezone", None) or "",
            caller_phone=self._caller_phone,
        )

        # Compile the graph (handlers created internally with builder caching)
        from voice_platform.flow.compiler import compile_flow

        self._compiled_graph = compile_flow(
            graph_json=self._graph_json,
            checkpointer=self._checkpointer,
        )

        # Build langgraph config with instance-specific deps for RunnableConfig DI
        self._langgraph_config = {
            "configurable": {
                "thread_id": self._thread_id,
                "streaming_client": self._streaming_client,
                "event_callback": self._telephony_event_callback,
                "playground_conv": self._llm_config,
                "agent": self._db_agent,
                "user_id": self._user_id,
            },
            "recursion_limit": 50,
        }

        logger.info(
            f"FlowAgent: compiled graph for agent {self._agent_id}, "
            f"thread_id={self._thread_id[:8]}"
        )

    async def _start_flow_and_greet(self):
        """Start the flow and stream the first conversation node's response as greeting.

        When a static initial_message is configured, speak it immediately (Deepgram
        cache makes this near-instant) BEFORE graph compile / LLM. That removes the
        15–20s silent opening that happened when telephony waited for a full LLM turn.
        """
        self._response_queue = asyncio.Queue()
        spoke_static_greeting = False

        try:
            greeting = (self._llm_config.initial_message or "").strip()
            if greeting:
                # Instant opening line — do not wait for compile or LLM.
                self.agent_responses_consumer.consume_nonblocking(
                    self.interruptible_event_factory.create_interruptible_agent_response_event(
                        AgentResponseMessage(
                            message=BaseMessage(text=greeting),
                            is_first=True,
                        ),
                        is_interruptible=True,
                    )
                )
                self.agent_responses_consumer.consume_nonblocking(
                    self.interruptible_event_factory.create_interruptible_agent_response_event(
                        AgentResponseMessage(message=EndOfTurn()),
                        is_interruptible=True,
                    )
                )
                spoke_static_greeting = True
                logger.info(
                    f"FlowAgent: spoke static greeting immediately "
                    f"({len(greeting)} chars) before compile"
                )

            await self._ensure_compiled()

            if spoke_static_greeting and self._flow_state is not None:
                # Tell conversation_1 not to re-speak / re-LLM the opener.
                self._flow_state["_greeting_already_spoken"] = True
                self._flow_state["_initial_message_sent"] = True

            # Drain agent_token events to TTS concurrently while the graph runs,
            # so any later speech starts at first collated sentence — not after
            # the full ainvoke completes.
            drain_task = asyncio.create_task(self._drain_greeting_queue())

            # Run flow to first interrupt (conversation node)
            from voice_platform.database import async_session
            async with async_session() as db_session:
                invoke_config = {
                    **self._langgraph_config,
                    "configurable": {
                        **self._langgraph_config["configurable"],
                        "db_session": db_session,
                    },
                }
                result = await self._compiled_graph.ainvoke(
                    self._flow_state,
                    config=invoke_config,
                )
            self._flow_state = {**self._flow_state, **result}
            self._flow_started = True

            # Signal drain to finish and wait for it
            await self._response_queue.put(_END_OF_TURN)
            try:
                await asyncio.wait_for(drain_task, timeout=30.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                drain_task.cancel()

            # Check if flow ended immediately (no conversation nodes)
            snapshot = await self._compiled_graph.aget_state(self._langgraph_config)
            is_interrupted = bool(
                snapshot.next
                or (
                    snapshot.tasks
                    and any(task.interrupts for task in snapshot.tasks)
                )
            )

            if not is_interrupted:
                logger.warning(
                    "FlowAgent: flow ended without conversation nodes — no wait interrupt"
                )
            elif not spoke_static_greeting:
                # Fallback already drained via concurrent task; nothing more to send.
                pass

        except asyncio.CancelledError:
            logger.info("FlowAgent: greeting task cancelled (caller interrupted)")
            raise
        except Exception as e:
            logger.error(f"FlowAgent: error during flow start: {e}", exc_info=True)
            if not spoke_static_greeting:
                # Send fallback greeting only if we never spoke anything
                self.agent_responses_consumer.consume_nonblocking(
                    self.interruptible_event_factory.create_interruptible_agent_response_event(
                        AgentResponseMessage(
                            message=BaseMessage(text="Hello! How can I help you today?"),
                            is_first=True,
                        ),
                        is_interruptible=True,
                    )
                )
                self.agent_responses_consumer.consume_nonblocking(
                    self.interruptible_event_factory.create_interruptible_agent_response_event(
                        AgentResponseMessage(message=EndOfTurn()),
                        is_interruptible=True,
                    )
                )
        finally:
            # Set initial_message_tracker so idle check / interrupt handling starts
            try:
                conv = self.conversation_state_manager._conversation
                conv.initial_message_tracker.set()
            except Exception:
                logger.warning("FlowAgent: could not set initial_message_tracker")

    async def _drain_greeting_queue(self):
        """Forward queued agent tokens to TTS while ainvoke is running."""
        is_first = True
        try:
            while True:
                item = await self._response_queue.get()
                if item is _END_OF_TURN:
                    self.agent_responses_consumer.consume_nonblocking(
                        self.interruptible_event_factory.create_interruptible_agent_response_event(
                            AgentResponseMessage(message=EndOfTurn()),
                            is_interruptible=True,
                        )
                    )
                    break
                elif item is _FLOW_END:
                    break
                elif item is _ERROR:
                    logger.warning("FlowAgent: error event during greeting drain")
                    # Keep draining — flow may still emit a farewell
                    continue
                elif isinstance(item, GeneratedResponse):
                    self.agent_responses_consumer.consume_nonblocking(
                        self.interruptible_event_factory.create_interruptible_agent_response_event(
                            AgentResponseMessage(
                                message=item.message,
                                is_first=is_first,
                            ),
                            is_interruptible=True,
                        )
                    )
                    is_first = False
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"FlowAgent: greeting drain error: {e}")

    async def _telephony_event_callback(self, event: dict):
        """Bridge between LangGraph node handlers and the response queue.

        Called during ainvoke() by node handlers. Pushes tokens/errors to the
        response queue which is drained by generate_response() after ainvoke()
        returns (at interrupt).
        """
        if self._response_queue is None:
            return

        event_type = event.get("event") or event.get("type")

        if event_type == "agent_token":
            token = event.get("text", "")
            if token and token.strip():
                await self._response_queue.put(
                    GeneratedResponse(
                        message=BaseMessage(text=token),
                        is_interruptible=True,
                    )
                )
        elif event_type == "agent_response":
            await self._response_queue.put(_END_OF_TURN)
        elif event_type == "flow_end":
            await self._response_queue.put(_FLOW_END)
        elif event_type == "error":
            logger.error(f"FlowAgent: flow error: {event.get('text', '')}")
            await self._response_queue.put(_ERROR)
        elif event_type in (
            "node_start",
            "node_result",
            "edge_traversed",
            "condition_branch",
            "variables_extracted",
            "info",
            "debug",
            "flow_start",
        ):
            logger.debug(
                f"FlowAgent: event {event_type} — node={event.get('node_id', '')}"
            )

    async def generate_response(
        self,
        human_input,
        conversation_id: str,
        is_interrupt: bool = False,
        bot_was_in_medias_res: bool = False,
    ) -> AsyncGenerator[GeneratedResponse, None]:
        """Generate response by starting or resuming the LangGraph flow.

        Called by handle_generate_response() (inherited from RespondAgent)
        when a transcription arrives.
        """
        async for response in self._flow_response_stream(human_input):
            yield response

    async def _flow_response_stream(
        self, human_input: str
    ) -> AsyncGenerator[GeneratedResponse, None]:
        """Generate flow response by starting or resuming the LangGraph flow."""
        from langgraph.errors import GraphRecursionError
        from langgraph.types import Command

        # MEDIUM-18: Cancel greeting task on caller interruption instead of awaiting
        # This prevents delaying the caller's response until a long greeting finishes
        if self._greeting_task and not self._greeting_task.done():
            self._greeting_task.cancel()
            try:
                await self._greeting_task
            except asyncio.CancelledError:
                logger.info("FlowAgent: greeting task cancelled (caller interrupted)")
            except Exception:
                logger.warning("FlowAgent: greeting task errored, proceeding with user input")

        self._response_queue = asyncio.Queue()

        # Fix #11: Check if flow has already ended before trying to resume
        if self._flow_started and self._compiled_graph is not None:
            try:
                snapshot = await self._compiled_graph.aget_state(self._langgraph_config)
                has_pending = bool(
                    snapshot.next
                    or (snapshot.tasks and any(task.interrupts for task in snapshot.tasks))
                )
                if not has_pending:
                    logger.info("FlowAgent: flow has already ended, using direct LLM fallback")
                    async for response in self._direct_llm_fallback(human_input):
                        yield response
                    return
            except Exception as e:
                logger.warning(f"FlowAgent: could not check flow state: {e}, proceeding with resume")

        # If flow hasn't started yet (e.g. greeting task failed or was cancelled)
        if not self._flow_started:
            try:
                await self._ensure_compiled()
                from voice_platform.database import async_session
                async with async_session() as db_session:
                    invoke_config = {**self._langgraph_config,
                                     "configurable": {**self._langgraph_config["configurable"],
                                                      "db_session": db_session}}
                    result = await self._compiled_graph.ainvoke(
                        self._flow_state, config=invoke_config
                    )
                self._flow_state = {**self._flow_state, **result}
                self._flow_started = True
                # Drain greeting tokens (already sent via start, discard)
                while not self._response_queue.empty():
                    item = self._response_queue.get_nowait()
                    if item is _END_OF_TURN or item is _FLOW_END:
                        break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"FlowAgent: error starting flow: {e}", exc_info=True)
                yield GeneratedResponse(
                    message=BaseMessage(
                        text="I apologize, but I'm having trouble right now."
                    ),
                    is_interruptible=True,
                )
                yield GeneratedResponse(
                    message=EndOfTurn(), is_interruptible=True
                )
                return

        # Resume flow with user's text
        try:
            from voice_platform.database import async_session
            async with async_session() as db_session:
                invoke_config = {**self._langgraph_config,
                                 "configurable": {**self._langgraph_config["configurable"],
                                                  "db_session": db_session}}
                result = await self._compiled_graph.ainvoke(
                    Command(resume=human_input),
                    config=invoke_config,
                )
            self._flow_state = {**self._flow_state, **result}
        except asyncio.CancelledError:
            logger.info("FlowAgent: ainvoke cancelled (caller interrupted)")
            raise
        except GraphRecursionError:
            logger.error("FlowAgent: recursion limit (50) hit — graph too deep or cycle detected")
            yield GeneratedResponse(
                message=BaseMessage(
                    text="I'm having difficulty continuing this conversation. Could you repeat that?"
                ),
                is_interruptible=True,
            )
            yield GeneratedResponse(message=EndOfTurn(), is_interruptible=True)
            return
        except Exception as e:
            logger.error(f"FlowAgent: error resuming flow: {e}", exc_info=True)
            yield GeneratedResponse(
                message=BaseMessage(
                    text="I apologize, but I'm having trouble right now."
                ),
                is_interruptible=True,
            )
            yield GeneratedResponse(message=EndOfTurn(), is_interruptible=True)
            return

        # Check if flow ended
        try:
            snapshot = await self._compiled_graph.aget_state(self._langgraph_config)
            is_interrupted = bool(
                snapshot.next
                or (
                    snapshot.tasks
                    and any(task.interrupts for task in snapshot.tasks)
                )
            )
        except Exception:
            is_interrupted = True  # Assume interrupted on error

        # Drain response queue
        # Fix #1 & #2: Properly handle _FLOW_END — drain remaining tokens first,
        # then yield EndOfTurn + AgentResponseStop. Only add fallback farewell if
        # no tokens were received from the flow (e.g. end node had no farewell message).
        had_tokens = False
        try:
            while True:
                item = await self._response_queue.get()
                if item is _END_OF_TURN:
                    yield GeneratedResponse(
                        message=EndOfTurn(), is_interruptible=True
                    )
                    break
                elif item is _FLOW_END:
                    # Drain any remaining tokens (e.g. farewell from end_call node)
                    remaining_tokens = []
                    while not self._response_queue.empty():
                        extra = self._response_queue.get_nowait()
                        if isinstance(extra, GeneratedResponse):
                            remaining_tokens.append(extra)
                    # Yield any remaining tokens first
                    for token in remaining_tokens:
                        had_tokens = True
                        yield token
                    # If no tokens were received at all, yield a fallback farewell
                    if not had_tokens:
                        yield GeneratedResponse(
                            message=BaseMessage(
                                text="Thank you for calling. Have a great day!"
                            ),
                            is_interruptible=True,
                        )
                    yield GeneratedResponse(
                        message=EndOfTurn(), is_interruptible=True
                    )
                    # Signal conversation stop
                    self.agent_responses_consumer.consume_nonblocking(
                        self.interruptible_event_factory.create_interruptible_agent_response_event(
                            AgentResponseStop(),
                            is_interruptible=False,
                        )
                    )
                    return
                elif item is _ERROR:
                    # Log the error but DON'T terminate — the flow may continue
                    # to an end/conversation node with a spoken message. Drain
                    # remaining queue items without a long blocking wait when
                    # speech tokens are already queued behind the error.
                    logger.warning(
                        "FlowAgent: error event received during flow execution, "
                        "continuing to drain queue for farewell/end events"
                    )
                    try:
                        next_item = self._response_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        try:
                            next_item = await asyncio.wait_for(
                                self._response_queue.get(), timeout=0.5
                            )
                        except asyncio.TimeoutError:
                            # No more events came — yield error fallback
                            if not had_tokens:
                                yield GeneratedResponse(
                                    message=BaseMessage(
                                        text="I apologize, but I'm having trouble right now."
                                    ),
                                    is_interruptible=True,
                                )
                            yield GeneratedResponse(
                                message=EndOfTurn(), is_interruptible=True
                            )
                            return
                    # Process the next item by putting it back and continuing
                    await self._response_queue.put(next_item)
                    continue
                had_tokens = True
                yield item
        except Exception:
            # If we break out unexpectedly, ensure EndOfTurn is always sent
            if not had_tokens:
                yield GeneratedResponse(
                    message=BaseMessage(
                        text="I apologize, but I'm having trouble right now."
                    ),
                    is_interruptible=True,
                )
            yield GeneratedResponse(message=EndOfTurn(), is_interruptible=True)
            raise

    async def _direct_llm_fallback(
        self, human_input: str
    ) -> AsyncGenerator[GeneratedResponse, None]:
        """Fallback: call LLM directly when the flow has already ended.

        Uses the UnifiedStreamingClient with the agent's system prompt and
        the user's input, bypassing the LangGraph flow entirely.
        """
        messages = list(self._llm_config.messages)
        messages.append({"role": "system", "content": "The structured flow has ended. Continue as a helpful assistant."})
        messages.append({"role": "user", "content": human_input})
        try:
            async for response in self._streaming_client.stream_completion(
                messages=messages,
                is_first_response=False,
            ):
                yield response
        except Exception as e:
            logger.error(f"FlowAgent: direct LLM fallback error: {e}", exc_info=True)
            yield GeneratedResponse(
                message=BaseMessage(
                    text="I apologize, but I'm having trouble right now."
                ),
                is_interruptible=True,
            )
            yield GeneratedResponse(
                message=EndOfTurn(), is_interruptible=True
            )

    def get_agent_config(self):
        return self.agent_config

    async def terminate(self):
        """Clean up resources when the agent is shutting down."""
        if self._streaming_client is not None:
            await self._streaming_client.aclose()
        # HIGH-2 / MEDIUM-15: Close cached httpx client to prevent connection leak
        if self._llm_config._cached_http_client is not None:
            try:
                await self._llm_config._cached_http_client.aclose()
            except Exception:
                pass
            self._llm_config._cached_http_client = None
        if self._greeting_task and not self._greeting_task.done():
            self._greeting_task.cancel()
        # Track lifecycle via ConversationSession if attached
        session = getattr(self, "_conversation_session", None)
        if session is not None:
            await session.end()
