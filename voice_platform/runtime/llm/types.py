"""Type definitions for the unified LLM client stack.

All dataclasses are frozen/immutable. ProviderCapability is a class-level
constant on each adapter — instantiated exactly once, never recomputed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from voice_platform.runtime.llm.client import LLMClient
    from voice_platform.runtime.llm.middleware import MiddlewareContext
    from voice_platform.runtime.session.runtime_config import ModelReference


@dataclass(frozen=True)
class ProviderCapability:
    """Static capability descriptor for a provider adapter.

    Queried by LLMClient before calls to validate that the requested
    feature is supported. Eliminates `if provider ==` branching.
    """

    supports_tools: bool = False
    supports_streaming: bool = True
    supports_embeddings: bool = False
    supports_audio: bool = False
    supports_realtime: bool = False
    supports_reasoning: bool = False
    supports_json_schema: bool = False
    supports_images: bool = False
    supports_vision: bool = False
    supports_system_messages: bool = True
    max_context: int | None = None
    requires_non_streaming_for_tools: bool = False  # Ollama-specific


@dataclass
class ToolCall:
    """A single tool/function call requested by the LLM."""

    id: str
    name: str
    arguments: str  # JSON string


@dataclass
class CompletionResponse:
    """Response from a non-streaming LLM completion."""

    content: str
    tool_calls: list[ToolCall] | None = None
    finish_reason: str = "stop"
    usage: dict | None = None


@dataclass
class StreamChunk:
    """A single chunk from a streaming LLM response."""

    content: str | None = None
    tool_call: ToolCall | None = None
    finish_reason: str | None = None


@dataclass(frozen=True)
class RetryPolicy:
    """Retry configuration. Supports both status-code and predicate-based retry decisions."""

    max_retries: int = 3
    base_delay: float = 1.0  # delay = 2 ** attempt * base_delay
    respect_retry_after: bool = True
    retry_after_cap: float = 10.0
    retry_on_status: set[int] = field(
        default_factory=lambda: {429, 500, 502, 503, 504}
    )
    retry_if: Callable[[Exception], bool] | None = None
    """Optional exception predicate. If provided, exceptions matching this
    predicate are retried (e.g. connection resets, DNS errors, transient
    provider-specific exceptions). Evaluated in addition to retry_on_status."""


@dataclass(frozen=True)
class TimeoutPolicy:
    """Timeout configuration with phased timeouts.

    Initially only total_timeout is enforced. connection_timeout and
    first_byte_timeout are nullable for forward compatibility.
    """

    connection_timeout: float | None = None
    first_byte_timeout: float | None = None
    total_timeout: float = 60.0


@dataclass
class ProviderConfig:
    """Opaque configuration object for provider-specific options.

    Passes through LLMFactory without changing the public API.
    Examples: Ollama num_ctx, think; OpenAI organization_id; etc.
    """

    options: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)


@dataclass(frozen=True)
class LLMRuntime:
    """Immutable value object bundling a constructed LLMClient with its context.

    Returned by AgentLLMFactory. Carries ModelReference for logging, tracing,
    telemetry, and cost accounting without future DB lookups.
    """

    client: "LLMClient"
    middleware_context: "MiddlewareContext"
    model_ref: "ModelReference"
