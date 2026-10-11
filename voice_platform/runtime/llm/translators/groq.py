"""Groq response translator — handles Groq OpenAI-compatible responses."""

from voice_platform.runtime.llm.translators.openai import OpenAITranslator


class GroqTranslator(OpenAITranslator):
    """Groq uses OpenAI-compatible response format."""
    pass
