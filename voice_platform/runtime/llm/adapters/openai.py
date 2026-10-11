"""OpenAI adapter — uses AsyncOpenAI SDK via SDKSession."""

from typing import Any, AsyncGenerator

from voice_platform.runtime.llm.adapters.base import ProviderAdapter
from voice_platform.runtime.llm.exceptions import (
    AuthenticationError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
)
from voice_platform.runtime.llm.session import ProviderSession
from voice_platform.runtime.llm.translators.openai import OpenAITranslator
from voice_platform.runtime.llm.types import (
    CompletionResponse,
    ProviderCapability,
    ProviderConfig,
    StreamChunk,
)


class OpenAIAdapter(ProviderAdapter):
    """OpenAI provider adapter via AsyncOpenAI SDK."""

    capabilities = ProviderCapability(
        supports_tools=True,
        supports_streaming=True,
        supports_embeddings=True,
        supports_audio=True,
        supports_realtime=True,
        supports_reasoning=True,
        supports_json_schema=True,
        supports_images=True,
        supports_vision=True,
        supports_system_messages=True,
    )

    def __init__(
        self,
        *,
        session: ProviderSession,
        model: str,
        config: ProviderConfig | None = None,
    ):
        super().__init__(
            session=session,
            model=model,
            config=config,
            translator=OpenAITranslator(),
        )

    def translate_messages(self, messages: list[dict]) -> list[dict]:
        """OpenAI uses the canonical message format — no translation needed."""
        return messages

    async def complete(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> CompletionResponse:
        client = self._session.sdk_client
        params: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            params["tools"] = tools
            params["tool_choice"] = kwargs.pop("tool_choice", "auto")
        params.update(kwargs)
        try:
            response = await client.chat.completions.create(**params)
            return self._translator.translate_completion(response)
        except Exception as e:
            raise self._translate_exception(e) from e

    async def stream(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk, None]:
        client = self._session.sdk_client
        params: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            params["tools"] = tools
            params["tool_choice"] = kwargs.pop("tool_choice", "auto")
        params.update(kwargs)
        try:
            stream = await client.chat.completions.create(**params)
            async for chunk in stream:
                translated = self._translator.translate_stream_chunk(chunk)
                if translated is not None:
                    yield translated
        except Exception as e:
            raise self._translate_exception(e) from e

    @staticmethod
    def _translate_exception(e: Exception) -> ProviderError:
        """Translate OpenAI SDK exceptions into runtime exceptions."""
        exc_type = type(e).__name__
        status = getattr(e, "status_code", None)
        if status == 401 or status == 403 or "AuthenticationError" in exc_type:
            return AuthenticationError(str(e))
        if status == 429 or "RateLimitError" in exc_type:
            retry_after = getattr(e, "retry_after", None)
            return RateLimitError(str(e), retry_after=retry_after)
        if status and 500 <= status < 600:
            return ProviderUnavailableError(str(e))
        return ProviderError(str(e))
