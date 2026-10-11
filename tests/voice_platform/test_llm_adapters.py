"""Unit tests for Phase 2: adapters, translators, types, exceptions, session."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from voice_platform.runtime.llm.types import (
    ProviderCapability,
    CompletionResponse,
    StreamChunk,
    ToolCall,
    RetryPolicy,
    TimeoutPolicy,
    ProviderConfig,
)
from voice_platform.runtime.llm.exceptions import (
    ProviderError,
    AuthenticationError,
    RateLimitError,
    ProviderUnavailableError,
    UnsupportedCapability,
)
from voice_platform.runtime.llm.translators import (
    OpenAITranslator,
    OllamaTranslator,
)
from voice_platform.runtime.llm.adapters import (
    OpenAIAdapter,
    GeminiAdapter,
    GroqAdapter,
    AnthropicAdapter,
    OpenRouterAdapter,
    CommandCodeAdapter,
    OllamaAdapter,
)
from voice_platform.runtime.llm.adapters.base import ProviderAdapter
from voice_platform.runtime.llm.session import ProviderSession, SDKSession, HttpSession


# ─── Types ─────────────────────────────────────────────────────────────

class TestTypes:
    def test_provider_capability_is_frozen(self):
        cap = ProviderCapability(supports_tools=True)
        with pytest.raises(Exception):
            cap.supports_tools = False  # type: ignore[misc]

    def test_retry_policy_has_predicate(self):
        rp = RetryPolicy(retry_if=lambda e: True)
        assert rp.retry_if is not None
        assert rp.max_retries == 3

    def test_timeout_policy_phases(self):
        tp = TimeoutPolicy(connection_timeout=10.0, first_byte_timeout=30.0, total_timeout=60.0)
        assert tp.connection_timeout == 10.0
        assert tp.first_byte_timeout == 30.0
        assert tp.total_timeout == 60.0

    def test_timeout_policy_defaults(self):
        tp = TimeoutPolicy()
        assert tp.connection_timeout is None
        assert tp.first_byte_timeout is None
        assert tp.total_timeout == 60.0

    def test_provider_config_passthrough(self):
        pc = ProviderConfig(options={"num_ctx": 65536, "think": False})
        assert pc.get("num_ctx") == 65536
        assert pc.get("think") is False
        assert pc.get("nonexistent", "default") == "default"


# ─── Capabilities ──────────────────────────────────────────────────────

class TestCapabilities:
    def test_openai_capabilities(self):
        assert OpenAIAdapter.capabilities.supports_tools is True
        assert OpenAIAdapter.capabilities.supports_streaming is True
        assert OpenAIAdapter.capabilities.supports_audio is True
        assert OpenAIAdapter.capabilities.requires_non_streaming_for_tools is False

    def test_ollama_capabilities(self):
        assert OllamaAdapter.capabilities.supports_tools is True
        assert OllamaAdapter.capabilities.requires_non_streaming_for_tools is True
        assert OllamaAdapter.capabilities.supports_audio is False

    def test_gemini_capabilities(self):
        assert GeminiAdapter.capabilities.supports_tools is True
        assert GeminiAdapter.capabilities.supports_audio is False

    def test_groq_capabilities(self):
        assert GroqAdapter.capabilities.supports_tools is True
        assert GroqAdapter.capabilities.supports_embeddings is False

    def test_capabilities_are_class_level(self):
        # Same instance, not recomputed
        assert OpenAIAdapter.capabilities is OpenAIAdapter.capabilities


# ─── OllamaAdapter.translate_messages ──────────────────────────────────

class TestOllamaTranslateMessages:
    """Verify byte-for-byte equivalence with existing 4x duplicated logic."""

    def _make_adapter(self):
        session = MagicMock(spec=ProviderSession)
        return OllamaAdapter(session=session, model="qwen3:8b")

    def test_plain_messages_pass_through(self):
        adapter = self._make_adapter()
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        result = adapter.translate_messages(messages)
        assert result == messages

    def test_assistant_tool_calls_converted_to_text(self):
        adapter = self._make_adapter()
        messages = [
            {"role": "assistant", "content": "Sure", "tool_calls": [
                {"function": {"name": "get_time", "arguments": "{}"}},
            ]},
        ]
        result = adapter.translate_messages(messages)
        assert result[0]["role"] == "assistant"
        assert "[Tool call: get_time({})]" in result[0]["content"]
        assert "Sure" in result[0]["content"]

    def test_assistant_tool_calls_empty_content(self):
        adapter = self._make_adapter()
        messages = [
            {"role": "assistant", "content": None, "tool_calls": [
                {"function": {"name": "get_time", "arguments": "{}"}},
            ]},
        ]
        result = adapter.translate_messages(messages)
        assert "[Tool call: get_time({})]" in result[0]["content"]

    def test_tool_role_converted_to_user_with_xml(self):
        adapter = self._make_adapter()
        messages = [
            {"role": "tool", "name": "get_time", "content": "12:00"},
        ]
        result = adapter.translate_messages(messages)
        assert result[0]["role"] == "user"
        assert '<tool_result name="get_time">' in result[0]["content"]
        assert "12:00" in result[0]["content"]
        assert "</tool_result>" in result[0]["content"]

    def test_tool_role_no_name(self):
        adapter = self._make_adapter()
        messages = [
            {"role": "tool", "content": "result data"},
        ]
        result = adapter.translate_messages(messages)
        assert result[0]["role"] == "user"
        assert '<tool_result name="tool">' in result[0]["content"]

    def test_multiple_tool_calls(self):
        adapter = self._make_adapter()
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "get_time", "arguments": "{}"}},
                {"function": {"name": "get_date", "arguments": '{"format": "iso"}'}},
            ]},
        ]
        result = adapter.translate_messages(messages)
        assert "[Tool call: get_time({})]" in result[0]["content"]
        assert '[Tool call: get_date({"format": "iso"})]' in result[0]["content"]


# ─── OllamaAdapter._build_payload ──────────────────────────────────────

class TestOllamaBuildPayload:
    def _make_adapter(self, model="qwen3:8b", config=None):
        session = MagicMock(spec=ProviderSession)
        return OllamaAdapter(session=session, model=model, config=config)

    def test_basic_payload(self):
        adapter = self._make_adapter()
        msgs = [{"role": "user", "content": "Hi"}]
        payload = adapter._build_payload(msgs, stream=True, temperature=0.5, max_tokens=100)
        assert payload["model"] == "qwen3:8b"
        assert payload["stream"] is True
        assert payload["options"]["temperature"] == 0.5
        assert payload["options"]["num_predict"] == 500  # max(100, 500)
        assert payload["options"]["num_ctx"] == 32768  # no tools
        assert payload["think"] is False  # qwen3

    def test_payload_with_tools(self):
        adapter = self._make_adapter()
        msgs = [{"role": "user", "content": "Hi"}]
        tools = [{"type": "function", "function": {"name": "test", "parameters": {}}}]
        payload = adapter._build_payload(msgs, stream=False, tools=tools)
        assert payload["options"]["num_ctx"] == 65536  # tools present
        assert payload["tools"] == [{"type": "function", "function": {"name": "test", "parameters": {}}}]

    def test_payload_non_qwen3_no_think(self):
        adapter = self._make_adapter(model="llama3.3:70b")
        msgs = [{"role": "user", "content": "Hi"}]
        payload = adapter._build_payload(msgs, stream=True)
        assert "think" not in payload

    def test_payload_with_config_num_ctx(self):
        config = ProviderConfig(options={"num_ctx": 131072})
        adapter = self._make_adapter(config=config)
        msgs = [{"role": "user", "content": "Hi"}]
        payload = adapter._build_payload(msgs, stream=True)
        assert payload["options"]["num_ctx"] == 131072


# ─── OpenAITranslator ──────────────────────────────────────────────────

class TestOpenAITranslator:
    def test_translate_completion(self):
        translator = OpenAITranslator()
        # Simulate OpenAI SDK response
        message = MagicMock()
        message.content = "Hello world"
        message.tool_calls = None
        choice = MagicMock()
        choice.message = message
        choice.finish_reason = "stop"
        raw = MagicMock()
        raw.choices = [choice]
        raw.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)

        result = translator.translate_completion(raw)
        assert result.content == "Hello world"
        assert result.finish_reason == "stop"
        assert result.usage["total_tokens"] == 15
        assert result.tool_calls is None

    def test_translate_stream_chunk(self):
        translator = OpenAITranslator()
        delta = MagicMock()
        delta.content = "Hello"
        choice = MagicMock()
        choice.delta = delta
        choice.finish_reason = None
        raw = MagicMock()
        raw.choices = [choice]

        result = translator.translate_stream_chunk(raw)
        assert result is not None
        assert result.content == "Hello"
        assert result.finish_reason is None

    def test_translate_stream_chunk_empty(self):
        translator = OpenAITranslator()
        raw = MagicMock()
        raw.choices = []
        result = translator.translate_stream_chunk(raw)
        assert result is None


# ─── OllamaTranslator ──────────────────────────────────────────────────

class TestOllamaTranslator:
    def test_translate_completion(self):
        translator = OllamaTranslator()
        data = {
            "message": {"content": "Hello world"},
            "done": True,
            "eval_count": 10,
            "prompt_eval_count": 5,
        }
        result = translator.translate_completion(data)
        assert result.content == "Hello world"
        assert result.finish_reason == "stop"
        assert result.usage["total_tokens"] == 15

    def test_translate_completion_with_tool_calls(self):
        translator = OllamaTranslator()
        data = {
            "message": {
                "content": "",
                "tool_calls": [
                    {"function": {"name": "get_time", "arguments": {"h": 12}}},
                ],
            },
            "done": True,
        }
        result = translator.translate_completion(data)
        assert result.tool_calls is not None
        assert result.tool_calls[0].name == "get_time"
        assert result.finish_reason == "tool_calls"

    def test_translate_stream_chunk(self):
        translator = OllamaTranslator()
        data = {"message": {"content": "Hi"}, "done": False}
        result = translator.translate_stream_chunk(data)
        assert result is not None
        assert result.content == "Hi"

    def test_translate_stream_chunk_done(self):
        translator = OllamaTranslator()
        data = {"message": {"content": ""}, "done": True}
        result = translator.translate_stream_chunk(data)
        assert result is not None
        assert result.finish_reason == "stop"
        assert result.content is None

    def test_translate_stream_chunk_empty(self):
        translator = OllamaTranslator()
        data = {"message": {"content": ""}, "done": False}
        result = translator.translate_stream_chunk(data)
        assert result is None

    def test_translate_stream_chunk_from_json_string(self):
        translator = OllamaTranslator()
        raw = json.dumps({"message": {"content": "Hi"}, "done": False})
        result = translator.translate_stream_chunk(raw)
        assert result is not None
        assert result.content == "Hi"


# ─── Session ───────────────────────────────────────────────────────────

class TestProviderSession:
    def test_sdk_and_http_separate(self):
        session = ProviderSession(api_key="sk-test", base_url="https://api.example.com/v1")
        assert session._sdk is not None
        assert session._http is not None
        assert session._sdk is not session._http

    def test_sdk_session_lazy(self):
        session = ProviderSession(api_key="sk-test", base_url="https://api.example.com/v1")
        assert session._sdk._client is None
        # Accessing sdk_client triggers creation
        client = session.sdk_client
        assert client is not None
        assert session._sdk._client is client


# ─── Exception Hierarchy ───────────────────────────────────────────────

class TestExceptions:
    def test_rate_limit_error_has_retry_after(self):
        e = RateLimitError("rate limited", retry_after=5.0)
        assert e.retry_after == 5.0
        assert isinstance(e, ProviderError)

    def test_authentication_error_no_retry(self):
        e = AuthenticationError("bad key")
        assert isinstance(e, ProviderError)

    def test_unsupported_capability(self):
        e = UnsupportedCapability("no tools on streaming")
        assert isinstance(e, ProviderError)
