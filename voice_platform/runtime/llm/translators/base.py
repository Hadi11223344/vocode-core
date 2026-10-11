"""Base translator interface for converting raw SDK responses to runtime types.

Frozen now so that future chunk types (ToolCallFragment, ReasoningChunk,
AudioChunk, ImageChunk) can be added without touching adapters.
"""

from abc import ABC, abstractmethod
from typing import Any

from voice_platform.runtime.llm.types import CompletionResponse, StreamChunk


class ProviderTranslator(ABC):
    """Translates raw SDK responses into runtime types.

    Each provider has its own translator implementation. Adapters delegate
    response parsing to translators, keeping adapters focused on transport.
    """

    @abstractmethod
    def translate_completion(self, raw: Any) -> CompletionResponse:
        """Translate a non-streaming SDK response into CompletionResponse."""
        ...

    @abstractmethod
    def translate_stream_chunk(self, raw: Any) -> StreamChunk | None:
        """Translate a single streaming SDK chunk into StreamChunk.

        Return None to skip this chunk (e.g. empty delta, usage-only chunk).
        """
        ...
