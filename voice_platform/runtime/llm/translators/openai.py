"""OpenAI response translator — handles OpenAI SDK response/chunk types."""

from typing import Any

from voice_platform.runtime.llm.types import CompletionResponse, StreamChunk, ToolCall
from voice_platform.runtime.llm.translators.base import ProviderTranslator


class OpenAITranslator(ProviderTranslator):
    """Translates openai.AsyncOpenAI responses and streaming chunks."""

    def translate_completion(self, raw: Any) -> CompletionResponse:
        choice = raw.choices[0]
        message = choice.message
        tool_calls = None
        if getattr(message, "tool_calls", None):
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                )
                for tc in message.tool_calls
            ]
        usage = None
        if getattr(raw, "usage", None):
            usage = {
                "prompt_tokens": raw.usage.prompt_tokens,
                "completion_tokens": raw.usage.completion_tokens,
                "total_tokens": raw.usage.total_tokens,
            }
        return CompletionResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )

    def translate_stream_chunk(self, raw: Any) -> StreamChunk | None:
        choices = getattr(raw, "choices", None)
        if not choices:
            return None
        choice = choices[0]
        delta = choice.delta
        content = getattr(delta, "content", None)
        tool_call = None
        tool_calls = getattr(delta, "tool_calls", None)
        if tool_calls:
            tc = tool_calls[0]
            tool_call = ToolCall(
                id=getattr(tc, "id", "") or "",
                name=getattr(tc.function, "name", "") or "" if tc.function else "",
                arguments=getattr(tc.function, "arguments", "") or "" if tc.function else "",
            )
        return StreamChunk(
            content=content,
            tool_call=tool_call,
            finish_reason=choice.finish_reason,
        )
