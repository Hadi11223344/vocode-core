"""Anthropic adapter — accessed via OpenRouter (OpenAI-compatible endpoint)."""

from voice_platform.runtime.llm.adapters.openai import OpenAIAdapter
from voice_platform.runtime.llm.types import ProviderCapability


class AnthropicAdapter(OpenAIAdapter):
    """Anthropic provider adapter via OpenRouter (OpenAI-compatible)."""

    capabilities = ProviderCapability(
        supports_tools=True,
        supports_streaming=True,
        supports_embeddings=False,
        supports_audio=False,
        supports_realtime=False,
        supports_reasoning=True,
        supports_json_schema=True,
        supports_images=True,
        supports_vision=True,
        supports_system_messages=True,
    )
