"""Ollama adapter — raw /api/chat transport with message translation.

Owns:
- Raw /api/chat transport (not OpenAI-compatible endpoint)
- think=false for qwen3 models
- Non-streaming mode when tools present (stream=false → yield as chunks)
- translate_messages(): tool_calls → text, tool role → user with XML wrapper
- num_ctx configuration
- SDK exception → runtime exception translation
"""

import json
from typing import Any, AsyncGenerator

import httpx
from loguru import logger

from voice_platform.runtime.llm.adapters.base import ProviderAdapter
from voice_platform.runtime.llm.exceptions import (
    AuthenticationError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
)
from voice_platform.runtime.llm.session import ProviderSession
from voice_platform.runtime.llm.translators.ollama import OllamaTranslator
from voice_platform.runtime.llm.types import (
    CompletionResponse,
    ProviderCapability,
    ProviderConfig,
    StreamChunk,
    ToolCall,
)


class OllamaAdapter(ProviderAdapter):
    """Ollama provider adapter using raw /api/chat endpoint.

    Uses raw API instead of OpenAI-compatible endpoint because:
    - think=false parameter (disables qwen3 thinking) is only on /api/chat
    - Streaming protocol drops tool_calls deltas — must use stream=false for tools
    - num_ctx parameter not available via OpenAI-compatible endpoint
    """

    capabilities = ProviderCapability(
        supports_tools=True,
        supports_streaming=True,
        supports_embeddings=True,
        supports_audio=False,
        supports_realtime=False,
        supports_reasoning=True,
        supports_json_schema=False,
        supports_images=False,
        supports_vision=False,
        supports_system_messages=True,
        requires_non_streaming_for_tools=True,  # Ollama-specific
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
            translator=OllamaTranslator(),
        )

    def _raw_url(self) -> str:
        """Get the raw Ollama API URL from the session's base_url."""
        # SDKSession stores base_url; we need to extract it
        base_url = self._session._sdk._base_url
        if base_url is None:
            base_url = "http://localhost:11434"
        return base_url.rstrip("/").replace("/v1", "") + "/api/chat"

    def translate_messages(self, messages: list[dict]) -> list[dict]:
        """Translate OpenAI-format messages into Ollama-native format.

        - assistant tool_calls → text representation
        - tool role → user role with XML wrapper
        """
        ollama_messages = []
        for msg in messages:
            ollama_msg = {"role": msg["role"], "content": msg.get("content", "")}
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                tool_text = "\n".join(
                    f"[Tool call: {tc['function']['name']}({tc['function']['arguments']})]"
                    for tc in msg["tool_calls"]
                )
                ollama_msg["content"] = f"{ollama_msg['content'] or ''}\n{tool_text}".strip()
            if msg["role"] == "tool":
                ollama_msg["role"] = "user"
                tool_name = msg.get("name", "tool")
                ollama_msg["content"] = (
                    f'<tool_result name="{tool_name}">\n'
                    f"{msg.get('content', '')}\n"
                    f"</tool_result>"
                )
            ollama_messages.append(ollama_msg)
        return ollama_messages

    def _build_payload(
        self,
        messages: list[dict],
        *,
        stream: bool,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> dict:
        """Build the raw Ollama /api/chat payload."""
        num_ctx = self._config.get("num_ctx") or (65536 if tools else 32768)
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max(max_tokens, 500),
                "num_ctx": num_ctx,
            },
        }
        if "qwen3" in self._model:
            payload["think"] = False
        if tools:
            ollama_tools = []
            for t in tools:
                if t.get("type") == "function" and "function" in t:
                    ollama_tools.append({
                        "type": "function",
                        "function": t["function"],
                    })
            if ollama_tools:
                payload["tools"] = ollama_tools
        return payload

    async def complete(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> CompletionResponse:
        """Non-streaming completion via raw Ollama /api/chat."""
        url = self._raw_url()
        translated = self.translate_messages(messages)
        payload = self._build_payload(
            translated,
            stream=False,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        client = self._session.http_client
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return self._translator.translate_completion(data)
        except httpx.HTTPStatusError as e:
            raise self._translate_exception(e) from e
        except httpx.HTTPError as e:
            raise ProviderUnavailableError(str(e)) from e

    async def stream(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Streaming completion via raw Ollama /api/chat.

        When tools are present, uses non-streaming mode (stream=false) because
        Ollama's streaming protocol silently drops tool_calls delta chunks.
        The complete response is then yielded as word-level chunks for UX.
        """
        url = self._raw_url()
        translated = self.translate_messages(messages)
        has_tools = bool(tools)
        payload = self._build_payload(
            translated,
            stream=not has_tools,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        client = self._session.http_client
        try:
            if has_tools:
                # Non-streaming mode for tools — get complete response, yield as chunks
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                msg = data.get("message", {})
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls")

                # Yield content in word-level chunks
                if content:
                    words = content.split(" ")
                    for i, word in enumerate(words):
                        token = word + (" " if i < len(words) - 1 else "")
                        yield StreamChunk(content=token)

                # Yield tool calls as a single chunk
                if tool_calls:
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        yield StreamChunk(
                            tool_call=ToolCall(
                                id=tc.get("id", ""),
                                name=func.get("name", ""),
                                arguments=json.dumps(func.get("arguments", {})),
                            )
                        )

                yield StreamChunk(finish_reason="stop")
            else:
                # No tools — safe to stream normally
                async with client.stream("POST", url, json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            if data.get("done"):
                                yield StreamChunk(finish_reason="stop")
                                break
                            msg = data.get("message", {})
                            content = msg.get("content", "")
                            if content:
                                yield StreamChunk(content=content)
                        except (json.JSONDecodeError, KeyError):
                            continue
        except httpx.HTTPStatusError as e:
            raise self._translate_exception(e) from e
        except httpx.HTTPError as e:
            raise ProviderUnavailableError(str(e)) from e

    @staticmethod
    def _translate_exception(e: httpx.HTTPStatusError) -> ProviderError:
        """Translate httpx exceptions into runtime exceptions."""
        status = e.response.status_code
        if status == 401 or status == 403:
            return AuthenticationError(str(e))
        if status == 429:
            retry_after = e.response.headers.get("Retry-After")
            ra = None
            if retry_after:
                try:
                    ra = float(retry_after)
                except (ValueError, TypeError):
                    pass
            return RateLimitError(str(e), retry_after=ra)
        if 500 <= status < 600:
            return ProviderUnavailableError(str(e))
        return ProviderError(str(e))
