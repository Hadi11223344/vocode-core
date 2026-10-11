"""Gemini adapter — uses OpenAI-compatible endpoint via AsyncOpenAI SDK."""

from voice_platform.runtime.llm.adapters.openai import OpenAIAdapter
from voice_platform.runtime.llm.types import ProviderCapability


class GeminiAdapter(OpenAIAdapter):
    """Gemini provider adapter via OpenAI-compatible endpoint."""

    capabilities = ProviderCapability(
        supports_tools=True,
        supports_streaming=True,
        supports_embeddings=True,
        supports_audio=False,
        supports_realtime=False,
        supports_reasoning=True,
        supports_json_schema=False,  # partial support
        supports_images=True,
        supports_vision=True,
        supports_system_messages=True,
    )
