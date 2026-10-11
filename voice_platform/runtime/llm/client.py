"""LLMClient — pure orchestrator. Composes middleware → retry → timeout → adapter.

Does NOT have: extract(), embed(), retry(), timeout(), redact_pii(), if provider==
DOES have: capability validation before adapter calls
"""

import inspect
from typing import Any, AsyncGenerator

from loguru import logger

from voice_platform.runtime.llm.adapters.base import ProviderAdapter
from voice_platform.runtime.llm.exceptions import UnsupportedCapability
from voice_platform.runtime.llm.middleware import MessagePipeline, MiddlewareContext
from voice_platform.runtime.llm.retry import RetryExecutor
from voice_platform.runtime.llm.timeout import TimeoutExecutor
from voice_platform.runtime.llm.types import CompletionResponse, ProviderCapability, StreamChunk


class LLMClient:
    """Pure orchestrator. Composes middleware → retry → timeout → adapter.

    LLMClient is the single entry point for LLM completions. It:
    1. Validates capabilities (e.g. tools, streaming) before adapter calls
    2. Applies async middleware pipeline with context
    3. Delegates to retry → timeout → adapter
    """

    def __init__(
        self,
        adapter: ProviderAdapter,
        *,
        retry: RetryExecutor,
        timeout: TimeoutExecutor,
        middleware: MessagePipeline | None = None,
    ):
        self._adapter = adapter
        self._retry = retry
        self._timeout = timeout
        self._middleware = middleware

    @property
    def capabilities(self) -> ProviderCapability:
        """Static capabilities from adapter — computed once at adapter init."""
        return self._adapter.capabilities

    @property
    def adapter(self) -> ProviderAdapter:
        return self._adapter

    def _validate_capabilities(
        self,
        *,
        tools: list[dict] | None = None,
        streaming: bool = False,
        **kwargs: Any,
    ) -> None:
        """Validate that the adapter supports requested features."""
        cap = self._adapter.capabilities
        if tools and not cap.supports_tools:
            raise UnsupportedCapability(
                f"Provider does not support tools: {type(self._adapter).__name__}"
            )
        if streaming and not cap.supports_streaming:
            raise UnsupportedCapability(
                f"Provider does not support streaming: {type(self._adapter).__name__}"
            )
        # Future: validate json_schema, audio, realtime, etc.

    async def complete(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        context: MiddlewareContext | None = None,
        **kwargs: Any,
    ) -> CompletionResponse:
        """Non-streaming completion through the full stack."""
        self._validate_capabilities(tools=tools, streaming=False, **kwargs)

        if self._middleware and context:
            messages = await self._middleware.process(messages, context)

        messages = self._adapter.translate_messages(messages)

        try:
            return await self._retry.execute_async(
                self._timeout.execute,
                self._adapter.complete,
                messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        finally:
            await self.aclose()

    async def stream(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        context: MiddlewareContext | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Streaming completion through the full retry and timeout stack."""
        self._validate_capabilities(tools=tools, streaming=True, **kwargs)

        if self._middleware and context:
            messages = await self._middleware.process(messages, context)

        messages = self._adapter.translate_messages(messages)

        async def _stream_once() -> AsyncGenerator[StreamChunk, None]:
            async for chunk in self._timeout.iterate(
                self._adapter.stream,
                messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            ):
                yield chunk

        try:
            async for chunk in self._retry.execute_stream(_stream_once):
                yield chunk
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        """Close the provider transport session owned by this client."""
        session = getattr(self._adapter, "session", None)
        close = getattr(session, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result
