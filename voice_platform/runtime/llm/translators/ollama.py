"""Ollama response translator — handles raw /api/chat responses.

Ollama's raw API returns a different format from OpenAI:
- Non-streaming: {"message": {"content": "...", "tool_calls": [...]}, "done": true, ...}
- Streaming: {"message": {"content": "..."}, "done": false} per line
"""

import json
from typing import Any

from voice_platform.runtime.llm.types import CompletionResponse, StreamChunk, ToolCall
from voice_platform.runtime.llm.translators.base import ProviderTranslator


class OllamaTranslator(ProviderTranslator):
    """Translates raw Ollama /api/chat responses into runtime types."""

    def translate_completion(self, raw: Any) -> CompletionResponse:
        """Translate a non-streaming Ollama response.

        raw is a dict from the JSON response body.
        """
        if hasattr(raw, "json"):
            data = raw.json()
        elif isinstance(raw, dict):
            data = raw
        else:
            data = {}

        msg = data.get("message", {})
        content = msg.get("content", "")
        tool_calls = None
        if msg.get("tool_calls"):
            tool_calls = [
                ToolCall(
                    id=tc.get("id", f"call_{i}"),
                    name=tc.get("function", {}).get("name", ""),
                    arguments=tc.get("function", {}).get("arguments", ""),
                )
                for i, tc in enumerate(msg["tool_calls"])
            ]
        usage = None
        if data.get("eval_count") is not None:
            usage = {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            }
        return CompletionResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            usage=usage,
        )

    def translate_stream_chunk(self, raw: Any) -> StreamChunk | None:
        """Translate a single streaming Ollama line.

        raw is a dict parsed from a single JSON line.
        """
        if hasattr(raw, "json"):
            data = raw.json()
        elif isinstance(raw, dict):
            data = raw
        elif isinstance(raw, (bytes, str)):
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return None
        else:
            return None

        if data.get("done"):
            return StreamChunk(content=None, finish_reason="stop")

        msg = data.get("message", {})
        content = msg.get("content", "")
        if not content:
            return None
        return StreamChunk(content=content)
