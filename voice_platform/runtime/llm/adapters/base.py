"""Base provider adapter interface.

Adapters are transport-only: they translate messages, call the SDK via
ProviderSession, and delegate response parsing to a ProviderTranslator.
They know nothing about retry, timeout, PII, or business logic.
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator

from voice_platform.runtime.llm.types import (
    CompletionResponse,
    ProviderCapability,
    ProviderConfig,
    StreamChunk,
)
from voice_platform.runtime.llm.session import ProviderSession
from voice_platform.runtime.llm.translators.base import ProviderTranslator


class ProviderAdapter(ABC):
    """Transport-only adapter for a single LLM provider.

    Responsibilities:
    - translate_messages(): OpenAI format → provider-native format
    - complete(): non-streaming completion via SDK
    - stream(): streaming completion via SDK
    - capabilities: static capability descriptor (class-level constant)

    Does NOT handle: retry, timeout, PII, logging, caching, fallback.
    """

    # Class-level constant — instantiated exactly once, never recomputed.
    capabilities: ProviderCapability

    def __init__(
        self,
        *,
        session: ProviderSession,
        model: str,
        config: ProviderConfig | None = None,
        translator: ProviderTranslator | None = None,
    ):
        self._session = session
        self._model = model
        self._config = config or ProviderConfig()
        self._translator = translator

    @property
    def model(self) -> str:
        return self._model

    @property
    def session(self) -> ProviderSession:
        return self._session

    @abstractmethod
    def translate_messages(self, messages: list[dict]) -> list[dict]:
        """Translate OpenAI-format messages into provider-native format."""
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> CompletionResponse:
        """Non-streaming completion."""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Streaming completion. Yields StreamChunk objects."""
        ...
        yield  # type: ignore[unreachable]
