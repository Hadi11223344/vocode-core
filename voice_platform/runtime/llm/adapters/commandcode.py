"""CommandCode adapter — OpenAI-compatible endpoint."""

from voice_platform.runtime.llm.adapters.openai import OpenAIAdapter
from voice_platform.runtime.llm.types import ProviderCapability


class CommandCodeAdapter(OpenAIAdapter):
    """CommandCode provider adapter via OpenAI-compatible endpoint."""

    capabilities = ProviderCapability(
        supports_tools=True,
        supports_streaming=True,
        supports_embeddings=False,
        supports_audio=False,
        supports_realtime=False,
        supports_reasoning=True,
        supports_json_schema=True,
        supports_images=False,
        supports_vision=False,
        supports_system_messages=True,
    )
