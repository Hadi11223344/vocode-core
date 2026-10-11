import json
import os
import random
import time
from difflib import SequenceMatcher
from typing import Any, AsyncGenerator, Dict, List, Optional, TypeVar, Union

import httpx
import sentry_sdk
from loguru import logger
from openai import DEFAULT_MAX_RETRIES as OPENAI_DEFAULT_MAX_RETRIES
from openai import AsyncAzureOpenAI, AsyncOpenAI, NotFoundError, RateLimitError

from vocode import sentry_span_tags
from vocode.streaming.action.abstract_factory import AbstractActionFactory
from vocode.streaming.action.default_factory import DefaultActionFactory
from vocode.streaming.agent.base_agent import GeneratedResponse, RespondAgent, StreamedResponse
from vocode.streaming.agent.openai_utils import (
    format_openai_chat_messages_from_transcript,
    openai_get_tokens,
    vector_db_result_to_openai_chat_message,
)
from vocode.streaming.agent.streaming_utils import collate_response_async, stream_response_async
from vocode.streaming.models.actions import FunctionCallActionTrigger
from vocode.streaming.models.agent import ChatGPTAgentConfig
from vocode.streaming.models.events import Sender
from vocode.streaming.models.message import BaseMessage, BotBackchannel, LLMToken
from vocode.streaming.models.transcript import Message
from vocode.streaming.vector_db.factory import VectorDBFactory
from vocode.utils.sentry_utils import CustomSentrySpans, sentry_create_span

ChatGPTAgentConfigType = TypeVar("ChatGPTAgentConfigType", bound=ChatGPTAgentConfig)


def instantiate_openai_client(agent_config: ChatGPTAgentConfig, model_fallback: bool = False):
    if agent_config.azure_params:
        return AsyncAzureOpenAI(
            azure_endpoint=agent_config.azure_params.base_url,
            api_key=agent_config.azure_params.api_key,
            api_version=agent_config.azure_params.api_version,
            max_retries=0 if model_fallback else OPENAI_DEFAULT_MAX_RETRIES,
        )
    else:
        if agent_config.openai_api_key is not None:
            logger.info("Using OpenAI API key override")
        if agent_config.base_url_override is not None:
            logger.info(f"Using OpenAI base URL override: {agent_config.base_url_override}")
        return AsyncOpenAI(
            api_key=agent_config.openai_api_key or os.environ.get("OPENAI_API_KEY", ""),
            base_url=agent_config.base_url_override or "https://api.openai.com/v1",
            max_retries=0 if model_fallback else OPENAI_DEFAULT_MAX_RETRIES,
        )


class ChatGPTAgent(RespondAgent[ChatGPTAgentConfigType]):
    openai_client: Union[AsyncOpenAI, AsyncAzureOpenAI]

    def __init__(
        self,
        agent_config: ChatGPTAgentConfigType,
        action_factory: AbstractActionFactory = DefaultActionFactory(),
        vector_db_factory=VectorDBFactory(),
        **kwargs,
    ):
        super().__init__(
            agent_config=agent_config,
            action_factory=action_factory,
            **kwargs,
        )
        self.openai_client = instantiate_openai_client(
            agent_config, model_fallback=agent_config.llm_fallback is not None
        )

        if not self.openai_client.api_key:
            # Allow empty API key for local providers (e.g., Ollama) that don't require auth
            base_url = agent_config.base_url_override or ""
            if "localhost:11434" not in base_url and "host.docker.internal:11434" not in base_url:
                raise ValueError("OPENAI_API_KEY must be set in environment or passed in")

        if self.agent_config.vector_db_config:
            self.vector_db = vector_db_factory.create_vector_db(self.agent_config.vector_db_config)

    def get_tools(self):
        assert self.agent_config.actions
        if not self.action_factory:
            return None
        return [
            self.action_factory.create_action(action_config).get_openai_function()
            for action_config in self.agent_config.actions
            if isinstance(action_config.action_trigger, FunctionCallActionTrigger)
        ]

    def get_functions(self):
        return self.get_tools()

    def get_chat_parameters(self, messages: Optional[List] = None, use_functions: bool = True):
        assert self.transcript is not None
        is_azure = self._is_azure_model()

        messages = messages or format_openai_chat_messages_from_transcript(
            self.transcript,
            self.get_model_name_for_tokenizer(),
            self.functions,
            self.agent_config.prompt_preamble,
        )

        parameters: Dict[str, Any] = {
            "messages": messages,
            "max_tokens": self.agent_config.max_tokens,
            "temperature": self.agent_config.temperature,
        }

        if is_azure:
            assert self.agent_config.azure_params is not None
            parameters["model"] = self.agent_config.azure_params.deployment_name
        else:
            parameters["model"] = self.agent_config.model_name

        if use_functions and self.functions:
            parameters["tools"] = [
                {"type": "function", "function": f}
                for f in self.functions
            ]
            parameters["tool_choice"] = "auto"
            tool_names = [f.get("name", "?") for f in self.functions]
            logger.info(
                f"LLM tools: {len(self.functions)} functions passed: {tool_names}"
            )
        else:
            logger.warning(
                f"LLM tools: NO functions passed (use_functions={use_functions}, "
                f"self.functions={'set' if self.functions else 'None'})"
            )

        return parameters

    def _is_azure_model(self) -> bool:
        return self.agent_config.azure_params is not None

    async def _retrieve_live_kb_context(self) -> Optional[str]:
        """GAP-01: Retrieve KB chunks relevant to the last human message.

        Called before each LLM generation to inject up-to-date knowledge
        based on what the caller actually said, not a static generic query.
        """
        kb_id = getattr(self.agent_config, "knowledge_base_id", None)
        if not kb_id:
            return None

        # Get last human message from transcript
        if self.transcript is None:
            return None
        last_user_msg = self.transcript.get_last_user_message()
        if not last_user_msg:
            return None
        # get_last_user_message() returns (idx, to_string()) where to_string()
        # formats as "HUMAN: <text>". Strip the sender prefix so TF-IDF
        # retrieval isn't polluted with "HUMAN" appearing in every query.
        raw_text = last_user_msg[1] if isinstance(last_user_msg, tuple) else str(last_user_msg)
        last_human_message = raw_text.split(": ", 1)[-1] if ": " in raw_text else raw_text
        if not last_human_message or not last_human_message.strip():
            return None

        try:
            from voice_platform.database import KnowledgeBase, async_session
            from voice_platform.integrations.knowledge_base import KnowledgeBaseClient

            # KB-02: Try Redis cache first (1-hour TTL)
            cache_key = f"kb:{kb_id}:chunks"
            chunks: List[str] = []
            try:
                import redis.asyncio as aioredis

                from voice_platform.config import settings
                redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
                cached = await redis_client.get(cache_key)
                if cached:
                    chunks = json.loads(cached)
                    logger.debug(f"KB-02: Cache hit for KB {kb_id}")
                await redis_client.aclose()
            except Exception:
                pass  # Redis unavailable — fall through to DB

            if not chunks:
                async with async_session() as session:
                    kb = await session.get(KnowledgeBase, kb_id)
                    if not kb or not kb.is_active:
                        return None

                    if kb.chunks_json:
                        import json as _json
                        chunks = _json.loads(kb.chunks_json) if isinstance(kb.chunks_json, str) else kb.chunks_json
                    if not chunks and kb.content:
                        chunks = KnowledgeBaseClient.chunk_text(kb.content, chunk_size=kb.chunk_size or 500)

                    # KB-02: Populate Redis cache
                    if chunks:
                        try:
                            import redis.asyncio as aioredis

                            from voice_platform.config import settings
                            redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
                            await redis_client.setex(cache_key, 3600, json.dumps(chunks))
                            await redis_client.aclose()
                        except Exception:
                            pass

            if not chunks:
                return None

            # KB-03: Raised min_score from 0.05 → 0.15 to filter noise
            results = await KnowledgeBaseClient.retrieve(
                query=last_human_message,
                chunks=chunks,
                max_results=3,
                min_score=0.15,
            )

            if not results:
                return None

            kb_context = KnowledgeBaseClient.format_context(results, kb.name)

            # ── Inject cached Drive documents ────────────────────────────────
            # If this conversation has cached Drive documents, append them
            # to the KB context so the agent can reference them.
            conv_id = getattr(self, "conversation_id", None)
            if conv_id:
                try:
                    from voice_platform.actions.platform_tools import get_cached_documents
                    cached_docs = get_cached_documents(conv_id)
                    if cached_docs:
                        doc_parts = ["\n\n## Documents from Google Drive"]
                        for doc in cached_docs:
                            doc_parts.append(f"\n### {doc['filename']}\n{doc['content'][:800]}")
                        kb_context += "\n".join(doc_parts)
                        logger.info(f"Injected {len(cached_docs)} cached Drive document(s) into context")
                except Exception as doc_err:
                    logger.warning(f"Failed to inject Drive documents: {doc_err}")

            return kb_context
        except Exception as e:
            logger.warning(f"Live KB retrieval failed: {e}")
            return None

    def get_model_name_for_tokenizer(self):
        if not self.agent_config.azure_params:
            return self.agent_config.model_name
        else:
            return self.agent_config.azure_params.openai_model_name

    def apply_model_fallback(self, chat_parameters: Dict[str, Any]):
        if self.agent_config.llm_fallback is None:
            return
        if self.agent_config.llm_fallback.provider == "openai":
            self.agent_config.model_name = self.agent_config.llm_fallback.model_name
            if isinstance(self.openai_client, AsyncAzureOpenAI):
                self.agent_config.azure_params = None
        else:
            if self.agent_config.azure_params:
                self.agent_config.azure_params.deployment_name = (
                    self.agent_config.llm_fallback.model_name
                )
                if isinstance(self.openai_client, AsyncOpenAI):
                    # TODO: handle OpenAI fallback to Azure
                    pass

        self.openai_client = instantiate_openai_client(self.agent_config, model_fallback=False)
        chat_parameters["model"] = self.agent_config.llm_fallback.model_name

    async def _create_openai_stream_with_fallback(
        self, chat_parameters: Dict[str, Any]
    ) -> AsyncGenerator:
        try:
            stream = await self.openai_client.chat.completions.create(**chat_parameters)
        except (NotFoundError, RateLimitError) as e:
            logger.error(
                f"{'Model not found' if isinstance(e, NotFoundError) else 'Rate limit error'} for model_name: {chat_parameters.get('model')}. Applying fallback.",
                exc_info=True,
            )
            self.apply_model_fallback(chat_parameters)
            stream = await self.openai_client.chat.completions.create(**chat_parameters)
        return stream

    def _is_ollama(self) -> bool:
        base_url = self.agent_config.base_url_override or ""
        return "11434" in base_url

    async def _create_ollama_stream(self, chat_parameters: Dict[str, Any]) -> AsyncGenerator:
        """
        Create a streaming chat completion via LLMClient (OllamaAdapter).
        Yields FakeChunk objects compatible with openai_get_tokens.
        """
        from voice_platform.runtime.llm.factory import LLMFactory
        from voice_platform.runtime.llm.retry import RetryExecutor
        from voice_platform.runtime.llm.timeout import TimeoutExecutor
        from voice_platform.runtime.llm.types import ProviderConfig, RetryPolicy, TimeoutPolicy

        messages = chat_parameters.get("messages", [])
        model_name = chat_parameters.get("model", "")
        has_tools = bool(chat_parameters.get("tools"))
        default_ctx = 65536 if has_tools else 32768
        num_ctx = getattr(self.agent_config, 'context_window', None) or default_ctx

        config = ProviderConfig(options={"num_ctx": num_ctx})
        client = LLMFactory.create(
            "ollama",
            api_key=self.agent_config.openai_api_key or "ollama",
            base_url=self.agent_config.base_url_override,
            model=model_name,
            retry=RetryExecutor(RetryPolicy(max_retries=3, base_delay=1.0)),
            timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=120.0)),
            config=config,
        )

        class FakeFunction:
            def __init__(self, name, arguments):
                self.name = name
                self.arguments = arguments

        class FakeToolCall:
            def __init__(self, name, arguments):
                self.function = FakeFunction(name, arguments)

        class FakeDelta:
            def __init__(self, content=None, tool_calls=None):
                self.content = content
                self.tool_calls = tool_calls
                self.function_call = None

        class FakeChoice:
            def __init__(self, delta, finish_reason=None):
                self.delta = delta
                self.finish_reason = finish_reason

        class FakeChunk:
            def __init__(self, choices):
                self.choices = choices
            def model_dump(self):
                return {"choices": [{"delta": {"content": c.delta.content}, "finish_reason": c.finish_reason} for c in self.choices]}

        tools = chat_parameters.get("tools")
        if has_tools:
            # Non-streaming mode for tool calls
            response = await client.complete(
                messages,
                tools=tools,
                temperature=chat_parameters.get("temperature", 0.7),
                max_tokens=chat_parameters.get("max_tokens", 2048),
            )
            if response.content:
                words = response.content.split(" ")
                for i, word in enumerate(words):
                    token = word + (" " if i < len(words) - 1 else "")
                    yield FakeChunk([FakeChoice(FakeDelta(content=token))])

            if response.tool_calls:
                fake_tcs = []
                for tc in response.tool_calls:
                    fake_tcs.append(FakeToolCall(
                        name=tc.name,
                        arguments=tc.arguments,
                    ))
                yield FakeChunk([FakeChoice(FakeDelta(tool_calls=fake_tcs))])

            yield FakeChunk([FakeChoice(FakeDelta(), finish_reason="stop")])
        else:
            # Streaming mode
            async for chunk in client.stream(
                messages,
                temperature=chat_parameters.get("temperature", 0.7),
                max_tokens=chat_parameters.get("max_tokens", 2048),
            ):
                if chunk.content:
                    yield FakeChunk([FakeChoice(FakeDelta(content=chunk.content))])
                if chunk.finish_reason == "stop":
                    yield FakeChunk([FakeChoice(FakeDelta(), finish_reason="stop")])

    async def _create_openai_stream(self, chat_parameters: Dict[str, Any]) -> AsyncGenerator:
        logger.debug(f"LLM request parameters: {chat_parameters}")
        if self._is_ollama():
            logger.debug("Creating Ollama stream via LLMClient...")
            stream = self._create_ollama_stream(chat_parameters)
            return stream

        # Use LLMClient.stream() for OpenAI-compatible providers
        from voice_platform.runtime.llm.factory import LLMFactory
        from voice_platform.runtime.llm.retry import RetryExecutor
        from voice_platform.runtime.llm.timeout import TimeoutExecutor
        from voice_platform.runtime.llm.types import RetryPolicy, TimeoutPolicy

        # Handle model fallback
        if self.agent_config.llm_fallback is not None and self.openai_client.max_retries == 0:
            logger.debug("Creating OpenAI stream with fallback...")
            try:
                stream = await self._create_openai_stream_with_fallback(chat_parameters)
                return stream
            except Exception:
                self.apply_model_fallback(chat_parameters)

        provider = "openai"
        base_url = self.agent_config.base_url_override or "https://api.openai.com/v1"

        client = LLMFactory.create(
            provider,
            api_key=self.agent_config.openai_api_key or os.environ.get("OPENAI_API_KEY", ""),
            base_url=base_url,
            model=chat_parameters.get("model", self.agent_config.model_name),
            retry=RetryExecutor(RetryPolicy(max_retries=3, base_delay=1.0)),
            timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
        )

        # Build a FakeChunk-yielding generator for openai_get_tokens compatibility
        class FakeDelta:
            def __init__(self, content=None, tool_calls=None):
                self.content = content
                self.tool_calls = tool_calls
                self.function_call = None

        class FakeChoice:
            def __init__(self, delta, finish_reason=None):
                self.delta = delta
                self.finish_reason = finish_reason

        class FakeChunk:
            def __init__(self, choices):
                self.choices = choices
            def model_dump(self):
                return {"choices": [{"delta": {"content": c.delta.content}, "finish_reason": c.finish_reason} for c in self.choices]}

        async def _stream_gen():
            tools = chat_parameters.get("tools")
            async for chunk in client.stream(
                chat_parameters.get("messages", []),
                tools=tools,
                temperature=chat_parameters.get("temperature", 0.7),
                max_tokens=chat_parameters.get("max_tokens", 2048),
            ):
                if chunk.content:
                    yield FakeChunk([FakeChoice(FakeDelta(content=chunk.content))])
                if chunk.finish_reason == "stop":
                    yield FakeChunk([FakeChoice(FakeDelta(), finish_reason="stop")])

        logger.debug("OpenAI stream created via LLMClient")
        return _stream_gen()

    def should_backchannel(self, human_input: str) -> bool:
        return (
            not self.is_first_response()
            and not human_input.strip().endswith("?")
            and random.random() < self.agent_config.backchannel_probability
        )

    def choose_backchannel(self) -> Optional[BotBackchannel]:
        backchannel = None
        if self.transcript is not None:
            last_bot_message: Optional[Message] = None
            for event_log in self.transcript.event_logs[::-1]:
                if isinstance(event_log, Message) and event_log.sender == Sender.BOT:
                    last_bot_message = event_log
                    break
            if last_bot_message and last_bot_message.text.strip().endswith("?"):
                return BotBackchannel(text=self.post_question_bot_backchannel_randomizer())
        return backchannel

    def _get_last_bot_message_text(self) -> Optional[str]:
        """Return the text of the last non-backchannel bot message, or None."""
        if not self.transcript:
            return None
        for event_log in self.transcript.event_logs[::-1]:
            if (
                isinstance(event_log, Message)
                and event_log.sender == Sender.BOT
                and not event_log.is_backchannel
                and event_log.text.strip()
            ):
                return event_log.text.strip()
        return None

    async def generate_response(
        self,
        human_input: str,
        conversation_id: str,
        is_interrupt: bool = False,
        bot_was_in_medias_res: bool = False,
    ) -> AsyncGenerator[GeneratedResponse, None]:
        assert self.transcript is not None

        chat_parameters = {}
        if self.agent_config.vector_db_config:
            try:
                docs_with_scores = await self.vector_db.similarity_search_with_score(
                    self.transcript.get_last_user_message()[1]
                )
                docs_with_scores_str = "\n\n".join(
                    [
                        "Document: "
                        + doc[0].metadata["source"]
                        + f" (Confidence: {doc[1]})\n"
                        + doc[0].lc_kwargs["page_content"].replace(r"\n", "\n")
                        for doc in docs_with_scores
                    ]
                )
                vector_db_result = (
                    f"Found {len(docs_with_scores)} similar documents:\n{docs_with_scores_str}"
                )
                messages = format_openai_chat_messages_from_transcript(
                    self.transcript,
                    self.agent_config.model_name,
                    self.functions,
                    self.agent_config.prompt_preamble,
                )
                messages.insert(-1, vector_db_result_to_openai_chat_message(vector_db_result))
                chat_parameters = self.get_chat_parameters(messages)
            except Exception as e:
                logger.error(f"Error while hitting vector db: {e}", exc_info=True)
                chat_parameters = self.get_chat_parameters()
        else:
            chat_parameters = self.get_chat_parameters()

        # GAP-01: Inject live KB context retrieved from the caller's last message
        kb_context = await self._retrieve_live_kb_context()
        if kb_context:
            messages = chat_parameters.get("messages", [])
            if messages:
                # Insert KB context as a system message right before the last user message
                messages.insert(-1, {"role": "system", "content": kb_context})
                chat_parameters["messages"] = messages
                logger.debug("Injected live KB context into LLM messages")

        chat_parameters["stream"] = True

        openai_chat_messages: List = chat_parameters.get("messages", [])

        # Pre-LLM PII redaction: sanitize user messages before sending to LLM provider
        from vocode.streaming.utils.pii_redaction import redact_pii_from_messages
        chat_parameters["messages"] = redact_pii_from_messages(openai_chat_messages)
        openai_chat_messages = chat_parameters["messages"]

        backchannelled = "false"
        backchannel: Optional[BotBackchannel] = None
        if (
            self.agent_config.use_backchannels
            and not bot_was_in_medias_res
            and self.should_backchannel(human_input)
        ):
            backchannel = self.choose_backchannel()
        elif self.agent_config.first_response_filler_message and self.is_first_response():
            backchannel = BotBackchannel(text=self.agent_config.first_response_filler_message)

        if backchannel is not None:
            # The LLM needs the backchannel context manually - otherwise we're in a race condition
            # between sending the response and generating ChatGPT's response
            openai_chat_messages.append({"role": "assistant", "content": backchannel.text})
            yield GeneratedResponse(
                message=backchannel,
                is_interruptible=True,
            )
            backchannelled = "true"

        span_tags = sentry_span_tags.value
        if span_tags:
            span_tags["prior_backchannel"] = backchannelled
            sentry_span_tags.set(span_tags)

        first_sentence_total_span = sentry_create_span(
            sentry_callable=sentry_sdk.start_span, op=CustomSentrySpans.LLM_FIRST_SENTENCE_TOTAL
        )

        ttft_span = sentry_create_span(
            sentry_callable=sentry_sdk.start_span, op=CustomSentrySpans.TIME_TO_FIRST_TOKEN
        )

        logger.debug(f"Creating OpenAI stream ({self.agent_config.model_name})...")
        stream_start_time = time.time()
        stream = await self._create_openai_stream(chat_parameters)
        logger.debug(f"OpenAI stream created in {time.time() - stream_start_time:.2f}s")

        response_generator = collate_response_async
        using_input_streaming_synthesizer = (
            self.conversation_state_manager.using_input_streaming_synthesizer()
        )
        if using_input_streaming_synthesizer:
            response_generator = stream_response_async
        
        logger.debug(f"Starting response generator (using_input_streaming={using_input_streaming_synthesizer})")
        last_bot_text = self._get_last_bot_message_text()
        # C2: Also check against the initial greeting to prevent duplicate greetings
        # after tool calls (LLM may re-emit greeting when it can't see tool history)
        initial_greeting_text = None
        if self.agent_config.initial_message:
            initial_greeting_text = self.agent_config.initial_message.text.strip()
        accumulated_response = ""
        duplicate_suppressed = False
        async for message in response_generator(
            conversation_id=conversation_id,
            gen=openai_get_tokens(
                stream,
            ),
            get_functions=True,
            sentry_span=ttft_span,
        ):
            if first_sentence_total_span:
                first_sentence_total_span.finish()

            ResponseClass = (
                StreamedResponse if using_input_streaming_synthesizer else GeneratedResponse
            )
            MessageType = LLMToken if using_input_streaming_synthesizer else BaseMessage
            if isinstance(message, str):
                # Suppress empty/whitespace-only chunks that produce <silence>
                # messages to the caller (LLM sometimes emits leading whitespace)
                if not message.strip() and not accumulated_response.strip():
                    continue
                accumulated_response += message
                # Suppress duplicate responses — if the first ~60 chars match
                # the last bot message, skip this entire response.
                # Use both prefix match and similarity ratio to catch reworded
                # greetings (e.g. "Welcome to SmileCare" vs "Sara speaking from SmileCare")
                # C2: Also check against the initial greeting to prevent duplicate
                # greetings after tool calls
                for _compare_text in (last_bot_text, initial_greeting_text):
                    if (
                        not duplicate_suppressed
                        and _compare_text
                        and len(accumulated_response) >= min(len(_compare_text), 40)
                    ):
                        _lower_acc = accumulated_response.strip().lower()
                        _lower_cmp = _compare_text[:min(len(_compare_text), 80)].strip().lower()
                        _prefix_match = _lower_acc.startswith(_lower_cmp[:40])
                        _similarity = SequenceMatcher(None, _lower_acc[:80], _lower_cmp).ratio()
                        if _prefix_match or _similarity > 0.6:
                            logger.warning(
                                f"Suppressing duplicate bot response: '{accumulated_response[:60]}...'"
                            )
                            duplicate_suppressed = True
                            return
                yield ResponseClass(
                    message=MessageType(text=message),
                    is_interruptible=True,
                )
            else:
                yield ResponseClass(
                    message=message,
                    is_interruptible=True,
                )

    async def terminate(self):
        if hasattr(self, "vector_db") and self.vector_db is not None:
            await self.vector_db.tear_down()
        return await super().terminate()
