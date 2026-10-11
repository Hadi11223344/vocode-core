"""
UnifiedStreamingClient — Reusable LLM streaming client with production features.

Used by FlowAgent for telephony flow execution. Provides:
- OpenAI-compatible API streaming (token-by-token)
- PII redaction (via LLMClient middleware pipeline)
- Duplicate response suppression (ported from ChatGPTAgent)
- Sentence collation via vocode's collate_response_async
- EndOfTurn signaling

Independent of both ChatGPTAgent and PlaygroundConversation.
"""

import asyncio
import os
import time
from difflib import SequenceMatcher
from typing import AsyncGenerator, Dict, List, Optional

from loguru import logger

from vocode.streaming.agent.base_agent import GeneratedResponse
from vocode.streaming.agent.streaming_utils import collate_response_async, stream_response_async
from vocode.streaming.models.actions import EndOfTurn
from vocode.streaming.models.message import BaseMessage
from voice_platform.runtime.llm.sanitizer import StreamSanitizer, _sanitize_token


class UnifiedStreamingClient:
    """Reusable LLM streaming client with production features.

    Uses LLMClient.stream() via LLMFactory for provider routing, retry,
    timeout, and PII middleware. Yields GeneratedResponse objects suitable
    for the vocode agent pipeline.
    """

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        use_input_streaming: bool = False,
        provider: str = "openai",
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.use_input_streaming = use_input_streaming
        self.provider = provider
        self._api_key = api_key
        self._base_url = base_url

    async def aclose(self):
        """No-op — LLMClient manages its own session lifecycle."""
        pass

    async def stream_completion(
        self,
        messages: List[Dict[str, str]],
        is_first_response: bool = False,
        last_bot_text: Optional[str] = None,
        initial_greeting: Optional[str] = None,
    ) -> AsyncGenerator[GeneratedResponse, None]:
        """Stream LLM response, yielding GeneratedResponse objects.

        Args:
            messages: OpenAI chat messages list (system + user/assistant)
            is_first_response: Whether this is the first response in the conversation
            last_bot_text: Last bot message text (for duplicate suppression)
            initial_greeting: Initial greeting text (for duplicate suppression)

        Yields:
            GeneratedResponse(message=BaseMessage(text=chunk)) for each sentence chunk
            GeneratedResponse(message=EndOfTurn()) at the end
        """
        from voice_platform.runtime.llm.factory import LLMFactory
        from voice_platform.runtime.llm.middleware import (
            MessagePipeline,
            MiddlewareContext,
            PIIRedactor,
        )
        from voice_platform.runtime.llm.retry import RetryExecutor
        from voice_platform.runtime.llm.timeout import TimeoutExecutor
        from voice_platform.runtime.llm.types import RetryPolicy, TimeoutPolicy

        # 1. Build LLMClient with PII middleware
        pipeline = MessagePipeline([PIIRedactor()])
        ctx = MiddlewareContext(provider=self.provider, model=self.model)

        llm_client = LLMFactory.create(
            self.provider,
            api_key=self._api_key,
            base_url=self._base_url,
            model=self.model,
            retry=RetryExecutor(RetryPolicy(max_retries=3, base_delay=1.0)),
            timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
            middleware=pipeline,
        )

        # 2. Create async generator that yields content strings from StreamChunks
        async def _chunk_generator():
            async for chunk in llm_client.stream(
                messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                context=ctx,
            ):
                if chunk.content:
                    yield chunk.content

        # 3. Choose streaming mode based on synthesizer type
        response_generator = (
            stream_response_async
            if self.use_input_streaming
            else collate_response_async
        )

        accumulated_response = ""
        duplicate_suppressed = False
        # Input-streaming synthesizers (e.g. ElevenLabs WS) are fed partial
        # word-groups, so a marker can span emits → keep the buffered sanitizer.
        # Collate mode (Deepgram/telephony) yields COMPLETE sentences, so each
        # unit is sanitized whole — never held back mid-word (root cause of the
        # broken "t|oday", "g|etting" telephony pronunciation).
        sanitizer = StreamSanitizer() if self.use_input_streaming else None

        async for chunk_text in response_generator(
            conversation_id="flow",
            gen=_chunk_generator(),
            get_functions=False,
        ):
            if not chunk_text:
                continue

            # Suppress empty/whitespace-only chunks at the start
            if not accumulated_response.strip() and not chunk_text.strip():
                continue

            accumulated_response += chunk_text

            # 4. Duplicate suppression — compare against last bot message and initial greeting
            if not duplicate_suppressed:
                for _compare_text in (last_bot_text, initial_greeting):
                    if (
                        _compare_text
                        and len(accumulated_response) >= min(len(_compare_text), 40)
                    ):
                        _lower_acc = accumulated_response.strip().lower()
                        _lower_cmp = _compare_text[:min(len(_compare_text), 80)].strip().lower()
                        _prefix_match = _lower_acc.startswith(_lower_cmp[:40])
                        _similarity = SequenceMatcher(None, _lower_acc[:80], _lower_cmp).ratio()
                        if _prefix_match or _similarity > 0.6:
                            logger.warning(
                                f"UnifiedStreamingClient: suppressing duplicate response: "
                                f"'{accumulated_response[:60]}...'"
                            )
                            duplicate_suppressed = True
                            break

            if not duplicate_suppressed:
                if sanitizer is not None:
                    safe_chunk = sanitizer.feed(chunk_text)
                else:
                    safe_chunk = _sanitize_token(chunk_text)
                if safe_chunk and safe_chunk.strip():
                    yield GeneratedResponse(
                        message=BaseMessage(text=safe_chunk),
                        is_interruptible=True,
                    )

        # Flush remaining buffered text (input-streaming mode only)
        if sanitizer is not None:
            remaining = sanitizer.flush()
            if remaining and remaining.strip() and not duplicate_suppressed:
                yield GeneratedResponse(
                    message=BaseMessage(text=remaining),
                    is_interruptible=True,
                )

        # 5. If entire response was suppressed, yield a minimal fallback
        if duplicate_suppressed and not accumulated_response.strip():
            logger.warning("UnifiedStreamingClient: entire response suppressed as duplicate, yielding fallback")
            yield GeneratedResponse(
                message=BaseMessage(text="How can I help you?"),
                is_interruptible=True,
            )

        # 6. Signal end of turn
        yield GeneratedResponse(
            message=EndOfTurn(),
            is_interruptible=True,
        )
