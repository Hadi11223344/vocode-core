"""RuntimeConfig — immutable runtime configuration for a conversation.

Contains agent model settings, prompt context, tool context, and enrichment.
All sub-contexts are frozen dataclasses. Secrets (api_key, base_url) live in
InfrastructureContext, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from voice_platform.runtime.services.knowledge import KnowledgeContext
from voice_platform.runtime.services.memory import ConversationMemory


def _empty_mapping() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True)
class ModelReference:
    """Value object identifying a specific LLM model configuration.

    Replaces the loose `provider: str` + `model: str` pair.
    Carries metadata for provider-specific logic, routing, and versioning.
    """

    provider: str
    model: str
    family: str | None = None
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentConfig:
    """LLM model settings. No secrets — those live in InfrastructureContext."""

    model_ref: ModelReference
    temperature: float = 0.7
    max_tokens: int = 2048

    @property
    def model(self) -> str:
        """Convenience accessor for model name."""
        return self.model_ref.model

    @property
    def provider(self) -> str:
        """Convenience accessor for provider name."""
        return self.model_ref.provider


@dataclass(frozen=True)
class WorkflowStep:
    """A single workflow instruction step."""

    name: str
    description: str
    trigger_phrases: tuple[str, ...] = ()
    requires_approval: bool = False
    instructions: str = ""


@dataclass(frozen=True)
class WorkflowContext:
    """Structured workflow context — not rendered prompt text."""

    steps: tuple[WorkflowStep, ...] = ()


@dataclass(frozen=True)
class PromptContext:
    """Prompt configuration. Workflow is structured, not a rendered string."""

    system_prompt: str
    prompt_version_id: int | None = None
    is_playground: bool = False
    workflow: WorkflowContext | None = None
    gemini_warning: bool = False


@dataclass(frozen=True)
class ToolConfiguration:
    """Typed wrapper for raw tool config. Single config type across all tool objects.

    Replaces the previous Any escape hatch. Builder ensures raw is backed
    by MappingProxyType for true immutability.
    """

    raw: Mapping[str, Any] = field(default_factory=_empty_mapping, hash=False)


@dataclass(frozen=True)
class ToolDescriptor:
    """A single tool with its configuration."""

    name: str
    integration_type: str | None = None
    config: ToolConfiguration = field(default_factory=ToolConfiguration)


@dataclass(frozen=True)
class ToolContext:
    """All tool-related context for a conversation."""

    tool_actions: tuple[ToolDescriptor, ...] = ()
    skipped_tools: tuple[ToolDescriptor, ...] = ()
    drive_tool_actions: tuple[ToolDescriptor, ...] = ()
    tools_config: ToolConfiguration | None = None


@dataclass(frozen=True)
class EnrichmentContext:
    """Enrichment data from services (knowledge, memory). Structured, not prompt text."""

    knowledge: KnowledgeContext | None = None
    memory: ConversationMemory | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    """Immutable runtime configuration. Composition of all runtime sub-contexts."""

    agent: AgentConfig
    prompt: PromptContext
    tools: ToolContext
    enrichment: EnrichmentContext
