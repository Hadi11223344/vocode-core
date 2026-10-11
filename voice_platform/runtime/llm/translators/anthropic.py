"""Anthropic response translator — handles Anthropic via OpenRouter responses.

Anthropic is accessed through OpenRouter which returns OpenAI-compatible format,
so this translator delegates to OpenAITranslator.
"""

from voice_platform.runtime.llm.translators.openai import OpenAITranslator


class AnthropicTranslator(OpenAITranslator):
    """Anthropic via OpenRouter uses OpenAI-compatible response format."""
    pass
