"""ExecutionContextBuilder — sole construction path for ExecutionContext.

Assembles ExecutionContext from a ContextBuildRequest using injected services.
Fetches independent enrichment sources concurrently via asyncio.gather().
Uses ContextEnricher protocol with per-enricher failure policy (required/optional).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable

from loguru import logger

from voice_platform.integrations.plugins.registry import EmptyPluginRegistry, PluginRegistry
from voice_platform.runtime.events.event_bus import EventBus, NoOpEventBus
from voice_platform.runtime.infra.cache import Cache
from voice_platform.runtime.infra.db import DatabaseSession
from voice_platform.runtime.llm.credential_provider import CredentialProvider
from voice_platform.runtime.services.knowledge import KnowledgeContext, KnowledgeService
from voice_platform.runtime.services.memory import ConversationMemory, MemoryService
from voice_platform.runtime.session.context import ExecutionContext
from voice_platform.runtime.session.conversation_context import (
    ConversationChannel,
    ConversationContext,
)
from voice_platform.runtime.session.infrastructure_context import InfrastructureContext
from voice_platform.runtime.session.runtime_config import (
    AgentConfig,
    EnrichmentContext,
    ModelReference,
    PromptContext,
    RuntimeConfig,
    ToolConfiguration,
    ToolContext,
    ToolDescriptor,
)
from voice_platform.runtime.tracing.tracer import NoOpTracer, Tracer


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(slots=True, frozen=True)
class ContextBuildRequest:
    """Immutable request for ExecutionContextBuilder.build().

    As new inputs are added over time, the method signature stays stable.
    """

    agent_id: int
    user_id: int | None = None
    caller_phone: str | None = None
    caller_name: str | None = None
    channel: ConversationChannel = ConversationChannel.TELEPHONY
    conversation_id: str | None = None  # generated if None
    is_playground: bool = False
    # Future: tenant, locale, timezone, session_type, provider_override, workflow_id


class EnrichmentPolicy(Enum):
    """Failure policy for enrichment sources.

    REQUIRED: failure aborts the entire context build.
    OPTIONAL: failure logs a warning and proceeds with partial enrichment.
    """

    REQUIRED = "required"
    OPTIONAL = "optional"


@runtime_checkable
class ContextEnricher(Protocol):
    """Protocol for pluggable enrichment sources.

    Each enricher declares its failure policy via the `policy` attribute.
    The builder loops over enrichers, applying each one's policy.

    Future enrichers: CRMService, CalendarService, UserProfileService.
    """

    policy: EnrichmentPolicy

    async def enrich(
        self,
        runtime: RuntimeConfig,
        conversation: ConversationContext,
        db: DatabaseSession,
    ) -> RuntimeConfig: ...


class ExecutionContextBuilder:
    """Assembles ExecutionContext from a ContextBuildRequest.

    Single entry point: build(). Internal methods per sub-context.
    Delegates to KnowledgeService and MemoryService for enrichment.
    Fetches independent enrichment sources concurrently.
    Applies per-enricher failure policy (required vs optional).
    """

    def __init__(
        self,
        knowledge_service: KnowledgeService,
        memory_service: MemoryService,
        enrichers: list[ContextEnricher] | None = None,
    ) -> None:
        self._knowledge = knowledge_service
        self._memory = memory_service
        self._enrichers = enrichers or []

    async def build(
        self,
        request: ContextBuildRequest,
        db: DatabaseSession,
        cache: Cache,
        event_bus: EventBus | None = None,
        tracer: Tracer | None = None,
        plugin_registry: PluginRegistry | None = None,
        credential_provider: CredentialProvider | None = None,
    ) -> ExecutionContext:
        """Build a complete immutable ExecutionContext.

        Args:
            request: ContextBuildRequest with agent/user/channel info.
            db: Database session protocol.
            cache: Cache protocol.
            event_bus: Optional event bus (defaults to NoOpEventBus).
            tracer: Optional tracer (defaults to NoOpTracer).
            plugin_registry: Optional plugin registry (defaults to EmptyPluginRegistry).
            credential_provider: Optional credential provider for LLM client creation.

        Returns:
            Frozen ExecutionContext.
        """
        conversation = self._build_conversation(request)
        runtime = await self._build_runtime(request, conversation, db)
        infrastructure = self._build_infrastructure(
            db, cache, event_bus, tracer, plugin_registry, credential_provider
        )
        return ExecutionContext(
            conversation=conversation,
            runtime=runtime,
            infrastructure=infrastructure,
        )

    def _build_conversation(self, request: ContextBuildRequest) -> ConversationContext:
        """Build conversation identity. Owns conversation_id generation."""
        return ConversationContext(
            conversation_id=request.conversation_id or str(uuid.uuid4()),
            user_id=request.user_id,
            agent_id=request.agent_id,
            caller_phone=request.caller_phone,
            caller_name=request.caller_name,
            channel=request.channel,
            metadata=_empty_mapping(),
        )

    async def _build_runtime(
        self,
        request: ContextBuildRequest,
        conversation: ConversationContext,
        db: DatabaseSession,
    ) -> RuntimeConfig:
        """Build runtime configuration with concurrent enrichment."""
        agent = self._build_agent_config(request, db)
        prompt = self._build_prompt_context(request, db)
        tools, enrichment = await self._build_enrichment(request, db)
        return RuntimeConfig(
            agent=agent,
            prompt=prompt,
            tools=tools,
            enrichment=enrichment,
        )

    async def _build_enrichment(
        self,
        request: ContextBuildRequest,
        db: DatabaseSession,
    ) -> tuple[ToolContext, EnrichmentContext]:
        """Fetch enrichment sources concurrently with per-source failure policy.

        Knowledge is REQUIRED — failure aborts the build.
        Memory is OPTIONAL — failure logs warning, proceeds with empty memory.
        Tool context is always fetched (not an enrichment source per se).

        Uses _safe_fetch to apply per-source policy around each coroutine.
        """
        knowledge_result, memory_result, tools = await asyncio.gather(
            self._safe_fetch(
                "knowledge",
                EnrichmentPolicy.REQUIRED,
                self._knowledge.retrieve(db, request.agent_id),
            ),
            self._safe_fetch(
                "memory",
                EnrichmentPolicy.OPTIONAL,
                self._memory.get_history(db, request.caller_phone or ""),
            ),
            self._build_tool_context(request, db),
        )

        knowledge = knowledge_result if isinstance(knowledge_result, KnowledgeContext) else KnowledgeContext()
        memory = memory_result if isinstance(memory_result, ConversationMemory) else ConversationMemory()

        return tools, EnrichmentContext(knowledge=knowledge, memory=memory)

    async def _safe_fetch(
        self,
        name: str,
        policy: EnrichmentPolicy,
        coro: Any,
    ) -> Any:
        """Fetch a single enrichment source, applying its failure policy.

        REQUIRED: re-raise the exception (aborts build).
        OPTIONAL: log warning, return None (proceeds with partial enrichment).
        """
        try:
            return await coro
        except Exception as e:
            if policy == EnrichmentPolicy.REQUIRED:
                logger.error(f"Required enrichment source '{name}' failed: {e}")
                raise
            else:
                logger.warning(f"Optional enrichment source '{name}' failed, proceeding without: {e}")
                return None

    def _build_agent_config(self, request: ContextBuildRequest, db: DatabaseSession) -> AgentConfig:
        """Build agent config. Override in subclasses or extend as needed."""
        return AgentConfig(
            model_ref=ModelReference(provider="openai", model="gpt-4o-mini"),
        )

    def _build_prompt_context(self, request: ContextBuildRequest, db: DatabaseSession) -> PromptContext:
        """Build prompt context. Override in subclasses or extend as needed."""
        return PromptContext(
            system_prompt="",
            is_playground=request.is_playground,
        )

    async def _build_tool_context(self, request: ContextBuildRequest, db: DatabaseSession) -> ToolContext:
        """Build tool context. Override in subclasses or extend as needed."""
        return ToolContext()

    def _build_infrastructure(
        self,
        db: DatabaseSession,
        cache: Cache,
        event_bus: EventBus | None,
        tracer: Tracer | None,
        plugin_registry: PluginRegistry | None,
        credential_provider: CredentialProvider | None,
    ) -> InfrastructureContext:
        """Build infrastructure context with protocol abstractions."""
        return InfrastructureContext(
            db=db,
            cache=cache,
            event_bus=event_bus or NoOpEventBus(),
            tracer=tracer or NoOpTracer(),
            plugin_registry=plugin_registry or EmptyPluginRegistry(),
            credential_provider=credential_provider,
        )
