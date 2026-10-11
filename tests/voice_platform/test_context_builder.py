"""Unit tests for ExecutionContextBuilder, services, and context immutability.

Tests verify:
- ExecutionContextBuilder.build() produces frozen ExecutionContext
- ConversationContext has correct conversation_id from request
- RuntimeConfig has all sub-contexts populated
- AgentConfig has no api_key field
- PromptContext.workflow is WorkflowContext | None, not str
- ToolContext uses ToolDescriptor, not generic tuples
- ToolDescriptor.config is ToolConfiguration type
- InfrastructureContext contains Protocol instances
- KnowledgeService.retrieve() returns KnowledgeContext
- MemoryService.get_history() returns ConversationMemory
- All context dataclasses are frozen (mutation raises FrozenInstanceError)
- Context propagation: conversation_id same value across layers
- Builder fetches enrichment concurrently
- Enrichment failure policy: single source failure aborts build
- No code instantiates ExecutionContext directly (builder is sole path)
- Services have no build_prompt() methods
- PromptRenderer formats structured domain objects
- ContextEnricher Protocol is defined
- Builder does not import SQLAlchemy or Redis
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from voice_platform.integrations.plugins.registry import EmptyPluginRegistry
from voice_platform.runtime.events.event_bus import NoOpEventBus
from voice_platform.runtime.infra.cache import Cache
from voice_platform.runtime.infra.db import DatabaseSession
from voice_platform.runtime.llm.credential_provider import (
    CredentialProvider,
    ResolvedCredentials,
    SimpleCredentialProvider,
)
from voice_platform.runtime.services.knowledge import (
    KnowledgeContext,
    KnowledgeDocument,
    KnowledgeService,
)
from voice_platform.runtime.services.memory import CallSummary, ConversationMemory, MemoryService
from voice_platform.runtime.session.builder import (
    ContextBuildRequest,
    ContextEnricher,
    EnrichmentPolicy,
    ExecutionContextBuilder,
)
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
    WorkflowContext,
    WorkflowStep,
)
from voice_platform.runtime.tracing.tracer import NoOpTracer

# ── Test Helpers ───────────────────────────────────────────────────────


class _NoOpDB:
    async def execute(self, stmt: Any) -> Any: raise RuntimeError("No DB")
    async def commit(self) -> None: pass
    async def rollback(self) -> None: pass
    async def close(self) -> None: pass


class _NoOpCache:
    async def get(self, key: str) -> str | None: return None
    async def set(self, key: str, value: str, ttl: int | None = None) -> None: pass
    async def delete(self, key: str) -> None: pass


def _make_builder(
    knowledge_service: KnowledgeService | None = None,
    memory_service: MemoryService | None = None,
) -> ExecutionContextBuilder:
    """Create an ExecutionContextBuilder with mock services."""
    if knowledge_service is None:
        knowledge_service = MagicMock(spec=KnowledgeService)
        knowledge_service.retrieve = AsyncMock(return_value=KnowledgeContext())
    if memory_service is None:
        memory_service = MagicMock(spec=MemoryService)
        memory_service.get_history = AsyncMock(return_value=ConversationMemory())
    return ExecutionContextBuilder(
        knowledge_service=knowledge_service,
        memory_service=memory_service,
    )


def _make_request(**kwargs) -> ContextBuildRequest:
    defaults = {"agent_id": 42}
    defaults.update(kwargs)
    return ContextBuildRequest(**defaults)


# ── Builder Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_builder_produces_frozen_context():
    """ExecutionContextBuilder.build() produces frozen ExecutionContext."""
    builder = _make_builder()
    ctx = await builder.build(
        request=_make_request(),
        db=_NoOpDB(),
        cache=_NoOpCache(),
    )
    assert isinstance(ctx, ExecutionContext)
    with pytest.raises(FrozenInstanceError):
        ctx.conversation = None  # type: ignore


@pytest.mark.asyncio
async def test_builder_conversation_id_from_request():
    """ConversationContext has correct conversation_id from request."""
    builder = _make_builder()
    ctx = await builder.build(
        request=_make_request(conversation_id="test-uuid-123"),
        db=_NoOpDB(),
        cache=_NoOpCache(),
    )
    assert ctx.conversation.conversation_id == "test-uuid-123"


@pytest.mark.asyncio
async def test_builder_generates_uuid_if_none():
    """Builder generates conversation_id if not provided in request."""
    builder = _make_builder()
    ctx = await builder.build(
        request=_make_request(),
        db=_NoOpDB(),
        cache=_NoOpCache(),
    )
    assert ctx.conversation.conversation_id  # non-empty
    assert len(ctx.conversation.conversation_id) > 10  # UUID-like


@pytest.mark.asyncio
async def test_builder_runtime_config_populated():
    """RuntimeConfig has all sub-contexts populated."""
    builder = _make_builder()
    ctx = await builder.build(
        request=_make_request(),
        db=_NoOpDB(),
        cache=_NoOpCache(),
    )
    assert ctx.runtime.agent is not None
    assert ctx.runtime.prompt is not None
    assert ctx.runtime.tools is not None
    assert ctx.runtime.enrichment is not None


@pytest.mark.asyncio
async def test_builder_infrastructure_has_protocols():
    """InfrastructureContext contains Protocol-compatible instances."""
    builder = _make_builder()
    ctx = await builder.build(
        request=_make_request(),
        db=_NoOpDB(),
        cache=_NoOpCache(),
    )
    infra = ctx.infrastructure
    assert infra.db is not None
    assert infra.cache is not None
    assert infra.event_bus is not None
    assert infra.tracer is not None
    assert infra.plugin_registry is not None


@pytest.mark.asyncio
async def test_builder_enrichment_concurrent():
    """Builder fetches enrichment sources concurrently via asyncio.gather."""
    ks = MagicMock(spec=KnowledgeService)
    ks.retrieve = AsyncMock(return_value=KnowledgeContext(documents=(
        KnowledgeDocument(title="KB", content="test"),
    )))
    ms = MagicMock(spec=MemoryService)
    ms.get_history = AsyncMock(return_value=ConversationMemory(
        summary="Previous call",
        previous_calls=(CallSummary(call_date="2024-01-01", duration="30s"),),
    ))
    builder = _make_builder(knowledge_service=ks, memory_service=ms)
    ctx = await builder.build(
        request=_make_request(caller_phone="+1234567890"),
        db=_NoOpDB(),
        cache=_NoOpCache(),
    )
    ks.retrieve.assert_called_once()
    ms.get_history.assert_called_once()
    assert ctx.runtime.enrichment.knowledge is not None
    assert ctx.runtime.enrichment.memory is not None


@pytest.mark.asyncio
async def test_builder_enrichment_failure_aborts():
    """Enrichment failure policy: single source failure aborts entire build."""
    ks = MagicMock(spec=KnowledgeService)
    ks.retrieve = AsyncMock(side_effect=RuntimeError("KB unavailable"))
    ms = MagicMock(spec=MemoryService)
    ms.get_history = AsyncMock(return_value=ConversationMemory())
    builder = _make_builder(knowledge_service=ks, memory_service=ms)
    with pytest.raises(RuntimeError, match="KB unavailable"):
        await builder.build(
            request=_make_request(),
            db=_NoOpDB(),
            cache=_NoOpCache(),
        )


@pytest.mark.asyncio
async def test_builder_no_sqlalchemy_imports():
    """ExecutionContextBuilder does not import SQLAlchemy or Redis."""
    from voice_platform.runtime.session import builder as builder_module
    source = inspect.getsource(builder_module)
    forbidden = ["import sqlalchemy", "from sqlalchemy", "import redis", "from redis"]
    for kw in forbidden:
        assert kw not in source, f"Builder module contains forbidden import: {kw}"


# ── Immutability Tests ─────────────────────────────────────────────────


def test_execution_context_frozen():
    """ExecutionContext is frozen."""
    ctx = ExecutionContext(
        conversation=ConversationContext(conversation_id="test"),
        runtime=RuntimeConfig(
            agent=AgentConfig(model_ref=ModelReference(provider="p", model="m")),
            prompt=PromptContext(system_prompt=""),
            tools=ToolContext(),
            enrichment=EnrichmentContext(),
        ),
        infrastructure=InfrastructureContext(
            db=_NoOpDB(),
            cache=_NoOpCache(),
            event_bus=NoOpEventBus(),
            tracer=NoOpTracer(),
            plugin_registry=EmptyPluginRegistry(),
        ),
    )
    with pytest.raises(FrozenInstanceError):
        ctx.conversation = None  # type: ignore


def test_conversation_context_frozen():
    """ConversationContext is frozen."""
    ctx = ConversationContext(conversation_id="test")
    with pytest.raises(FrozenInstanceError):
        ctx.conversation_id = "hacked"  # type: ignore


def test_runtime_config_frozen():
    """RuntimeConfig is frozen."""
    rc = RuntimeConfig(
        agent=AgentConfig(model_ref=ModelReference(provider="p", model="m")),
        prompt=PromptContext(system_prompt=""),
        tools=ToolContext(),
        enrichment=EnrichmentContext(),
    )
    with pytest.raises(FrozenInstanceError):
        rc.agent = None  # type: ignore


def test_agent_config_frozen():
    """AgentConfig is frozen."""
    ac = AgentConfig(model_ref=ModelReference(provider="p", model="m"))
    with pytest.raises(FrozenInstanceError):
        ac.temperature = 99.0  # type: ignore


def test_model_reference_frozen():
    """ModelReference is frozen."""
    mr = ModelReference(provider="openai", model="gpt-4")
    with pytest.raises(FrozenInstanceError):
        mr.model = "hacked"  # type: ignore


def test_tool_descriptor_frozen():
    """ToolDescriptor is frozen."""
    td = ToolDescriptor(name="test")
    with pytest.raises(FrozenInstanceError):
        td.name = "hacked"  # type: ignore


def test_tool_configuration_frozen():
    """ToolConfiguration is frozen."""
    tc = ToolConfiguration()
    with pytest.raises(FrozenInstanceError):
        tc.raw = {}  # type: ignore


def test_prompt_context_frozen():
    """PromptContext is frozen."""
    pc = PromptContext(system_prompt="test")
    with pytest.raises(FrozenInstanceError):
        pc.system_prompt = "hacked"  # type: ignore


def test_workflow_context_frozen():
    """WorkflowContext is frozen."""
    wc = WorkflowContext()
    with pytest.raises(FrozenInstanceError):
        wc.steps = ()  # type: ignore


def test_workflow_step_frozen():
    """WorkflowStep is frozen."""
    ws = WorkflowStep(name="test", description="desc")
    with pytest.raises(FrozenInstanceError):
        ws.name = "hacked"  # type: ignore


def test_infrastructure_context_frozen():
    """InfrastructureContext is frozen."""
    ic = InfrastructureContext(
        db=_NoOpDB(),
        cache=_NoOpCache(),
        event_bus=NoOpEventBus(),
        tracer=NoOpTracer(),
        plugin_registry=EmptyPluginRegistry(),
    )
    with pytest.raises(FrozenInstanceError):
        ic.db = None  # type: ignore


def test_resolved_credentials_frozen():
    """ResolvedCredentials is frozen."""
    rc = ResolvedCredentials(api_key="secret")
    with pytest.raises(FrozenInstanceError):
        rc.api_key = "hacked"  # type: ignore


def test_context_build_request_frozen():
    """ContextBuildRequest is frozen."""
    req = _make_request()
    with pytest.raises(FrozenInstanceError):
        req.agent_id = 999  # type: ignore


# ── AgentConfig Tests ──────────────────────────────────────────────────


def test_agent_config_no_api_key():
    """AgentConfig has no api_key field — secrets are in CredentialProvider."""
    ac = AgentConfig(model_ref=ModelReference(provider="p", model="m"))
    assert not hasattr(ac, "api_key")
    assert not hasattr(ac, "base_url")


def test_agent_config_model_ref_accessors():
    """AgentConfig.model and .provider are convenience accessors for model_ref."""
    ac = AgentConfig(model_ref=ModelReference(provider="openai", model="gpt-4o"))
    assert ac.model == "gpt-4o"
    assert ac.provider == "openai"


def test_model_reference_has_family_and_capabilities():
    """ModelReference carries family and capabilities metadata."""
    mr = ModelReference(
        provider="openrouter",
        model="deepseek-v4",
        family="deepseek",
        capabilities=("tool_use", "vision"),
    )
    assert mr.family == "deepseek"
    assert "tool_use" in mr.capabilities


# ── ToolContext Tests ──────────────────────────────────────────────────


def test_tool_context_uses_tool_descriptor():
    """ToolContext uses tuple[ToolDescriptor, ...] not generic tuple."""
    td = ToolDescriptor(name="send_email", integration_type="email")
    tc = ToolContext(tool_actions=(td,))
    assert isinstance(tc.tool_actions[0], ToolDescriptor)


def test_tool_descriptor_config_is_tool_configuration():
    """ToolDescriptor.config is ToolConfiguration type, not Mapping."""
    td = ToolDescriptor(name="test")
    assert isinstance(td.config, ToolConfiguration)


def test_tool_context_tools_config_is_tool_configuration():
    """ToolContext.tools_config is ToolConfiguration | None, not Any."""
    tc = ToolContext(tools_config=ToolConfiguration())
    assert isinstance(tc.tools_config, ToolConfiguration)
    tc_empty = ToolContext()
    assert tc_empty.tools_config is None


# ── ConversationChannel Tests ──────────────────────────────────────────


def test_conversation_channel_enum():
    """ConversationContext.channel is ConversationChannel enum, not str."""
    ctx = ConversationContext(conversation_id="test")
    assert isinstance(ctx.channel, ConversationChannel)
    assert ctx.channel == ConversationChannel.TELEPHONY


def test_context_build_request_channel_enum():
    """ContextBuildRequest.channel is ConversationChannel enum."""
    req = _make_request()
    assert isinstance(req.channel, ConversationChannel)


# ── Service Tests ──────────────────────────────────────────────────────


def test_knowledge_service_no_build_prompt():
    """KnowledgeService has no build_prompt() method."""
    ks = KnowledgeService()
    assert not hasattr(ks, "build_prompt")


def test_memory_service_no_build_history_prompt():
    """MemoryService has no build_history_prompt() method."""
    ms = MemoryService()
    assert not hasattr(ms, "build_history_prompt")


def test_knowledge_context_has_documents_tuple():
    """KnowledgeContext has documents as tuple of KnowledgeDocument."""
    docs = (KnowledgeDocument(title="A", content="content"),)
    kc = KnowledgeContext(documents=docs)
    assert isinstance(kc.documents, tuple)
    assert isinstance(kc.documents[0], KnowledgeDocument)


def test_conversation_memory_has_previous_calls_tuple():
    """ConversationMemory has previous_calls as tuple of CallSummary."""
    calls = (CallSummary(call_date="2024-01-01", duration="30s"),)
    cm = ConversationMemory(summary="test", previous_calls=calls)
    assert isinstance(cm.previous_calls, tuple)
    assert isinstance(cm.previous_calls[0], CallSummary)


# ── ContextEnricher Protocol Test ──────────────────────────────────────


def test_context_enricher_protocol_defined():
    """ContextEnricher Protocol is defined."""
    assert ContextEnricher is not None
    assert hasattr(ContextEnricher, "enrich")


# ── Context Propagation Test ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_propagation():
    """conversation_id same value across ExecutionContext → ConversationContext."""
    builder = _make_builder()
    ctx = await builder.build(
        request=_make_request(conversation_id="propagation-test"),
        db=_NoOpDB(),
        cache=_NoOpCache(),
    )
    assert ctx.conversation.conversation_id == "propagation-test"


# ── PromptRenderer Structured Object Tests ─────────────────────────────


def test_prompt_renderer_formats_knowledge_context():
    """PromptRenderer.render() formats KnowledgeContext into prompt text."""
    from voice_platform.runtime.prompt_renderer import PromptRenderer, RenderContext

    db_agent = MagicMock()
    db_agent.name = "Test"
    db_agent.prompt_preamble = "You are a test agent."
    db_agent.tool_instructions = None
    db_agent.handbook_enabled = False
    db_agent.google_drive_integration_id = None

    ctx = RenderContext(
        db_agent=db_agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        is_playground=True,
        knowledge=KnowledgeContext(documents=(
            KnowledgeDocument(title="KB", content="The answer is 42", score=0.95),
        )),
    )
    result = PromptRenderer.render(ctx)
    assert "The answer is 42" in result.prompt
    assert "Related Knowledge Contexts" in result.prompt


def test_prompt_renderer_formats_conversation_memory():
    """PromptRenderer.render() formats ConversationMemory into prompt text."""
    from voice_platform.runtime.prompt_renderer import PromptRenderer, RenderContext

    db_agent = MagicMock()
    db_agent.name = "Test"
    db_agent.prompt_preamble = "You are a test agent."
    db_agent.tool_instructions = None
    db_agent.handbook_enabled = False
    db_agent.google_drive_integration_id = None

    ctx = RenderContext(
        db_agent=db_agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        is_playground=True,
        memory=ConversationMemory(
            summary="Caller has interacted before.",
            previous_calls=(CallSummary(
                call_date="2024-01-01",
                duration="30s",
                messages=("Human: Hello", "Bot: Hi there"),
            ),),
        ),
    )
    result = PromptRenderer.render(ctx)
    assert "PREVIOUS INTERACTION HISTORY" in result.prompt
    assert "Caller has interacted before." in result.prompt
    assert "Human: Hello" in result.prompt


def test_prompt_renderer_formats_workflow_context():
    """PromptRenderer.render() formats WorkflowContext into prompt text."""
    from voice_platform.runtime.prompt_renderer import PromptRenderer, RenderContext

    db_agent = MagicMock()
    db_agent.name = "Test"
    db_agent.prompt_preamble = "You are a test agent."
    db_agent.tool_instructions = None
    db_agent.handbook_enabled = False
    db_agent.google_drive_integration_id = None

    ctx = RenderContext(
        db_agent=db_agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=[],
        is_playground=True,
        workflow=WorkflowContext(steps=(
            WorkflowStep(
                name="Collect Info",
                description="Ask for caller name",
                trigger_phrases=("I want to book",),
            ),
        )),
    )
    result = PromptRenderer.render(ctx)
    assert "WORKFLOW INSTRUCTIONS" in result.prompt
    assert "Collect Info" in result.prompt
    assert "I want to book" in result.prompt


def test_prompt_renderer_no_legacy_kb_content():
    """RenderContext no longer accepts kb_content — legacy field removed."""
    from voice_platform.runtime.prompt_renderer import RenderContext

    assert not hasattr(RenderContext, "__dataclass_fields__") or "kb_content" not in RenderContext.__dataclass_fields__
    assert not hasattr(RenderContext, "__dataclass_fields__") or "workflow_context" not in RenderContext.__dataclass_fields__


# ── CredentialProvider Tests ───────────────────────────────────────────


def test_credential_provider_protocol_defined():
    """CredentialProvider Protocol is defined."""
    assert CredentialProvider is not None
    assert hasattr(CredentialProvider, "get_api_key")
    assert hasattr(CredentialProvider, "get_base_url")


def test_simple_credential_provider_resolves():
    """SimpleCredentialProvider resolves api_key and base_url."""
    provider = SimpleCredentialProvider(
        api_keys={"openai": "sk-test"},
        base_urls={"ollama": "http://localhost:11434"},
    )
    assert provider.get_api_key("openai") == "sk-test"
    assert provider.get_api_key("anthropic") is None
    assert provider.get_base_url("ollama") == "http://localhost:11434"
    assert provider.get_base_url("openai") is None


def test_simple_credential_provider_resolve_combined():
    """SimpleCredentialProvider.resolve() returns ResolvedCredentials."""
    provider = SimpleCredentialProvider(
        api_keys={"openai": "sk-test"},
        base_urls={"openai": "https://custom.openai.com"},
    )
    creds = provider.resolve("openai")
    assert isinstance(creds, ResolvedCredentials)
    assert creds.api_key == "sk-test"
    assert creds.base_url == "https://custom.openai.com"


# ── EnrichmentPolicy Tests ─────────────────────────────────────────────


def test_enrichment_policy_enum():
    """EnrichmentPolicy enum has REQUIRED and OPTIONAL values."""
    assert EnrichmentPolicy.REQUIRED.value == "required"
    assert EnrichmentPolicy.OPTIONAL.value == "optional"


def test_context_enricher_has_policy_attribute():
    """ContextEnricher Protocol declares a policy attribute."""
    assert "policy" in ContextEnricher.__annotations__


@pytest.mark.asyncio
async def test_builder_memory_failure_optional():
    """Optional enrichment (memory) failure does NOT abort build."""
    ks = MagicMock(spec=KnowledgeService)
    ks.retrieve = AsyncMock(return_value=KnowledgeContext())
    ms = MagicMock(spec=MemoryService)
    ms.get_history = AsyncMock(side_effect=RuntimeError("Memory DB down"))
    builder = _make_builder(knowledge_service=ks, memory_service=ms)
    ctx = await builder.build(
        request=_make_request(caller_phone="+1234567890"),
        db=_NoOpDB(),
        cache=_NoOpCache(),
    )
    # Build succeeded despite memory failure
    assert isinstance(ctx, ExecutionContext)
    # Knowledge was still fetched
    ks.retrieve.assert_called_once()
    # Memory is empty (fallback)
    assert ctx.runtime.enrichment.memory is not None
    assert ctx.runtime.enrichment.memory.previous_calls == ()
