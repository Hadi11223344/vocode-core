"""ConversationSessionFactory — single construction point for ConversationSession.

Orchestrates session creation by delegating to builders:
- ExecutionContextBuilder (or inline playground context builder)
- Runtime selection (PlaygroundRuntime / FlowRuntime)
- ConversationSession final assembly

Factory receives ServiceContainer once at construction.
No per-call service injection. No transport parameter.
Factory is an assembler, not a god object.
"""

from __future__ import annotations

from typing import Any

from voice_platform.integrations.plugins.registry import EmptyPluginRegistry, PluginRegistry
from voice_platform.runtime.events.event_bus import NoOpEventBus
from voice_platform.runtime.session.context import ExecutionContext
from voice_platform.runtime.session.conversation_context import ConversationChannel, ConversationContext
from voice_platform.runtime.session.events import SessionEvent
from voice_platform.runtime.session.execution import ExecutionRuntime, RuntimeKind
from voice_platform.runtime.session.infrastructure_context import InfrastructureContext
from voice_platform.runtime.session.runtime_config import (
    AgentConfig,
    EnrichmentContext,
    ModelReference,
    PromptContext,
    RuntimeConfig,
    ToolContext,
)
from voice_platform.runtime.session.service_container import ServiceContainer
from voice_platform.runtime.session.session import ConversationSession, create_conversation_id
from voice_platform.runtime.tracing.tracer import NoOpTracer


class _NoOpDB:
    async def execute(self, stmt): raise RuntimeError("No DB in playground")
    async def commit(self): pass
    async def rollback(self): pass
    async def close(self): pass


class _NoOpCache:
    async def get(self, key): return None
    async def set(self, key, value, ttl=None): pass
    async def delete(self, key): pass


class ConversationSessionFactory:
    """Orchestrates ConversationSession construction for playground paths.

    Receives ServiceContainer once at construction. Callers never pass
    PluginRegistry or other services per-call.

    Factory is an assembler — delegates to builders, does not implement
    business logic inline.
    """

    def __init__(self, service_container: ServiceContainer) -> None:
        self._services = service_container

    async def create(
        self,
        agent: Any,
        user_id: int,
        channel: ConversationChannel,
        agent_id: int | None = None,
    ) -> ConversationSession:
        """Create a ConversationSession for the given agent and channel.

        Args:
            agent: The Agent model instance.
            user_id: The authenticated user's ID.
            channel: Playground chat or flow channel.
            agent_id: Override agent_id (defaults to agent.id).

        Returns:
            A ready-to-start ConversationSession.

        Raises:
            ValueError: If agent mode is unsupported for the channel.
        """
        resolved_agent_id = agent_id or int(getattr(agent, "id", 0))
        context = self._build_execution_context(resolved_agent_id, user_id, agent, channel)
        runtime = await self._build_runtime(agent, user_id, channel)
        return ConversationSession(
            runtime=runtime,
            context=context,
            plugin_registry=self._services.plugin_registry,
        )

    def _build_execution_context(
        self,
        agent_id: int,
        user_id: int,
        agent: Any,
        channel: ConversationChannel,
    ) -> ExecutionContext:
        """Build ExecutionContext for playground sessions.

        Playground sessions are lightweight — no DB/cache infrastructure needed,
        no cross-call memory. Uses no-op infrastructure defaults.
        """
        return ExecutionContext(
            conversation=ConversationContext(
                conversation_id=create_conversation_id(),
                user_id=user_id,
                agent_id=agent_id,
                channel=channel,
            ),
            runtime=RuntimeConfig(
                agent=AgentConfig(
                    model_ref=ModelReference(
                        provider=getattr(agent, "llm_provider", None) or "openai",
                        model=getattr(agent, "llm_model", None) or "gpt-4o-mini",
                    ),
                    temperature=getattr(agent, "temperature", 0.7),
                    max_tokens=getattr(agent, "max_tokens", 2048),
                ),
                prompt=PromptContext(
                    system_prompt=getattr(agent, "prompt_preamble", "") or "",
                    is_playground=True,
                ),
                tools=ToolContext(),
                enrichment=EnrichmentContext(),
            ),
            infrastructure=InfrastructureContext(
                db=_NoOpDB(),
                cache=_NoOpCache(),
                event_bus=NoOpEventBus(),
                tracer=NoOpTracer(),
                plugin_registry=self._services.plugin_registry,
            ),
        )

    async def _build_runtime(
        self,
        agent: Any,
        user_id: int,
        channel: ConversationChannel,
    ) -> ExecutionRuntime:
        """Select and construct the appropriate ExecutionRuntime.

        Delegates to playground_conversation module for PlaygroundConversation
        construction, and to flow.executor for LangGraphFlowExecutor.
        """
        if channel == ConversationChannel.PLAYGROUND_CHAT:
            return await self._build_playground_runtime(agent, user_id)
        elif channel == ConversationChannel.PLAYGROUND_FLOW:
            return await self._build_flow_runtime(agent, user_id)
        else:
            raise ValueError(
                f"Unsupported channel for ConversationSessionFactory: {channel}. "
                "Telephony sessions are constructed via agent_factory (M9.5)."
            )

    async def _build_playground_runtime(self, agent: Any, user_id: int) -> ExecutionRuntime:
        """Build PlaygroundRuntime for playground chat."""
        from voice_platform.runtime.session.adapters.playground import PlaygroundRuntime
        from voice_platform.runtime.session.adapters.playground_conversation import (
            _build_playground_conversation,
        )

        conv = await _build_playground_conversation(agent, user_id)
        return PlaygroundRuntime(conv=conv)

    async def _build_flow_runtime(self, agent: Any, user_id: int) -> ExecutionRuntime:
        """Build FlowRuntime for playground flow.

        Uses Agent.graph (workflow.graph_json when linked, else agents.graph_json)
        so Playground and Telephony share the same graph source of truth.
        """
        from voice_platform.flow.executor import LangGraphFlowExecutor
        from voice_platform.runtime.session.adapters.flow import FlowRuntime
        from voice_platform.runtime.session.adapters.playground_conversation import (
            _build_playground_conversation,
        )

        graph_json = getattr(agent, "graph", None)
        if not graph_json:
            raise ValueError(
                f"Agent #{getattr(agent, 'id', '?')} has no conversational graph "
                "(Agent.graph is empty)."
            )
        playground_conv = await _build_playground_conversation(agent, user_id)
        flow_executor = LangGraphFlowExecutor(
            agent=agent,
            graph=graph_json,
            playground_conv=playground_conv,
            user_id=user_id,
        )
        flow_executor._event_callback_failed = False
        return FlowRuntime(executor=flow_executor)
