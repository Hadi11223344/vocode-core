"""Gemini response translator — handles Gemini OpenAI-compatible responses.

Gemini's OpenAI-compatible endpoint returns the same format as OpenAI,
so this translator delegates to OpenAITranslator.
"""

from typing import Any

from voice_platform.runtime.llm.types import CompletionResponse, StreamChunk
from voice_platform.runtime.llm.translators.openai import OpenAITranslator


class GeminiTranslator(OpenAITranslator):
    """Gemini uses OpenAI-compatible response format."""
    pass
