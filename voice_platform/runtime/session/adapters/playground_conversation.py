"""PlaygroundConversation — manages a single playground conversation's message history.

Relocated from api/playground_routes.py so that runtime never depends on API.
The dependency graph always points inward: API → runtime, never runtime → API.
"""

from __future__ import annotations

import asyncio
import copy as _copy
import json as _json
import time
import uuid as _uuid
from typing import Any, Dict, List, Optional, cast

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.agents.agent_factory import (
    _PROVIDER_MODELS,
    _build_google_drive_tool_actions,
)
from voice_platform.database import (
    Agent,
    KnowledgeBase,
    UserApiKey,
    async_session,
)
from voice_platform.encryption import decrypt
from voice_platform.runtime.prompt_renderer import PromptRenderer, RenderContext
from voice_platform.runtime.services.knowledge import KnowledgeContext, KnowledgeDocument
from voice_platform.runtime.session.runtime_config import WorkflowContext

# ── Constants ─────────────────────────────────────────────────────────

LLM_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": None,
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
    "commandcode": "https://api.commandcode.ai/provider/v1",
    "ollama": None,  # Set dynamically below
}

LLM_DEFAULT_MODELS = {
    "openrouter": "deepseek/deepseek-v4-flash",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "groq": "openai/gpt-oss-120b",
    "commandcode": "deepseek/deepseek-v4-pro",
    "ollama": "qwen3:8b",
}

PLAYGROUND_OPENAI_COMPATIBLE_PROVIDERS = {"openrouter", "openai", "gemini", "groq", "commandcode", "ollama"}
PLAYGROUND_MAX_MESSAGE_CHARS = 4000
PLAYGROUND_MAX_HISTORY_MESSAGES = 20


# ── PlaygroundConversation ────────────────────────────────────────────

class PlaygroundConversation:
    """Manages a single playground conversation's message history."""

    def __init__(self, agent_id: int, system_prompt: str, model: str, api_key: str,
                 base_url: Optional[str] = None, initial_message: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 2048,
                 tools: Optional[List[Dict]] = None, user_id: Optional[int] = None,
                 context_window: Optional[int] = None, agent_timezone: Optional[str] = None):
        self.agent_id = agent_id
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.context_window = context_window
        self.tools = tools or []
        self.user_id = user_id
        self.agent_timezone = agent_timezone
        self.messages: List[Dict] = [
            {"role": "system", "content": system_prompt}
        ]
        self.initial_message = initial_message
        self.created_at = time.time()
        self._http_client: Optional[httpx.AsyncClient] = None
        self.metrics = {
            "turn_count": 0,
            "total_llm_latency_ms": 0.0,
            "avg_llm_latency_ms": 0.0,
            "total_tokens": 0,
            "tool_calls_count": 0,
        }

    def _trim_history(self) -> None:
        """Cap conversation history, summarizing older messages instead of dropping them."""
        if len(self.messages) <= PLAYGROUND_MAX_HISTORY_MESSAGES + 1:
            return
        system_msgs = [m for m in self.messages if m.get("role") == "system"]
        non_system = [m for m in self.messages if m.get("role") != "system"]
        # Keep recent messages intact
        keep_count = PLAYGROUND_MAX_HISTORY_MESSAGES
        recent = non_system[-keep_count:]
        older = non_system[:-keep_count]
        if older:
            # Summarize older messages into a compact context line
            summary_parts = []
            for m in older:
                role = m.get("role", "unknown")
                content = str(m.get("content", ""))[:200]
                summary_parts.append(f"{role}: {content}")
            summary = " | ".join(summary_parts)
            if len(summary) > 1000:
                summary = summary[:1000] + "..."
            summary_msg = {
                "role": "system",
                "content": f"[Previous conversation summary: {summary}]",
            }
            self.messages = system_msgs + [summary_msg] + recent
        else:
            self.messages = system_msgs + recent

    def _get_http_client(self) -> httpx.AsyncClient:
        """Return a reusable httpx.AsyncClient (created lazily)."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=60)
        return self._http_client

    async def aclose(self) -> None:
        """Close the underlying HTTP client to release connections."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()

    @staticmethod
    def _parse_error_response(response: httpx.Response) -> str:
        """Extract a human-readable error message from an LLM API error response."""
        try:
            err_body = response.json()
            err_obj = err_body.get("error", err_body)
            if isinstance(err_obj, dict):
                msg = err_obj.get("message", "")
                # Gemini includes failed_generation with details about tool call failures
                failed_gen = err_obj.get("failed_generation", "")
                if not msg:
                    details = err_obj.get("details", [])
                    if isinstance(details, list) and details:
                        parts = []
                        for d in details:
                            if isinstance(d, dict):
                                reason = d.get("reason", "")
                                location = d.get("location", "")
                                if reason:
                                    parts.append(f"{reason}" + (f" ({location})" if location else ""))
                        msg = "; ".join(parts) if parts else str(err_obj)[:200]
                    else:
                        msg = str(err_obj)[:200]
                if failed_gen:
                    msg = f"{msg}. Failed generation: {str(failed_gen)[:300]}"
                return msg
            return str(err_body)[:200]
        except Exception:
            return response.text[:200]

    def _is_ollama(self) -> bool:
        """Check if this conversation uses an Ollama backend."""
        return self.base_url is not None and "11434" in self.base_url

    def _ollama_raw_url(self) -> str:
        """Get the raw Ollama API URL (non-OpenAI-compatible)."""
        return self.base_url.rstrip("/").replace("/v1", "") + "/api/chat"

    def _build_ollama_payload(self, stream: bool = False) -> dict:
        """Build payload for the raw Ollama /api/chat endpoint."""
        ollama_messages = []
        for msg in self.messages:
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
        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": stream,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
                "num_ctx": self.context_window or (65536 if self.tools else 32768),
            },
        }
        if "qwen3" in self.model:
            payload["think"] = False
        if self.tools:
            payload["tools"] = self.tools
        return payload

    async def _ollama_chat_completion(self) -> dict:
        """Non-streaming completion via raw Ollama API with think=false.

        Now delegates to OllamaAdapter via LLMClient, preserving dict return format.
        """
        result = await self._llm_complete()
        return result

    async def _chat_completion(self, stream: bool = False) -> dict:
        """Call the LLM API with current messages and optional tools.

        Now delegates to LLMClient (which handles retry, timeout, provider routing,
        and Ollama raw API internally). Preserves dict return format for backward compat.
        """
        if stream:
            # Streaming path is still handled by stream_message (Phase 7)
            return await self._chat_completion_stream_legacy()

        return await self._llm_complete()

    async def _llm_complete(self) -> dict:
        """Use LLMClient.complete() and return result in OpenAI dict format."""
        from voice_platform.runtime.llm.factory import LLMFactory
        from voice_platform.runtime.llm.retry import RetryExecutor
        from voice_platform.runtime.llm.timeout import TimeoutExecutor
        from voice_platform.runtime.llm.types import ProviderConfig, RetryPolicy, TimeoutPolicy

        provider = "ollama" if self._is_ollama() else "openai"
        config = None
        if self._is_ollama():
            config = ProviderConfig(options={
                "num_ctx": self.context_window or (65536 if self.tools else 32768),
            })

        client = LLMFactory.create(
            provider,
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            retry=RetryExecutor(RetryPolicy(max_retries=3, base_delay=1.0)),
            timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
            config=config,
        )

        response = await client.complete(
            self.messages,
            tools=self.tools or None,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )

        # Convert CompletionResponse back to OpenAI dict format for callers
        message: Dict = {"role": "assistant", "content": response.content}
        if response.tool_calls:
            message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in response.tool_calls
            ]

        return {
            "choices": [{
                "message": message,
                "finish_reason": response.finish_reason,
            }],
            "usage": response.usage or {"total_tokens": 0},
        }

    async def _chat_completion_stream_legacy(self) -> dict:
        """Legacy streaming path — will be replaced in Phase 7."""
        url = f"{self.base_url}/chat/completions" if self.base_url else "https://api.openai.com/v1/chat/completions"

        payload = {
            "model": self.model,
            "messages": self.messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if self.tools:
            payload["tools"] = self.tools
            payload["tool_choice"] = "auto"

        client = self._get_http_client()
        max_retries = 3
        for attempt in range(max_retries + 1):
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )

            if response.status_code == 200:
                return response.json()

            if response.status_code in (401, 403):
                err_msg = self._parse_error_response(response)
                raise ValueError(
                    f"API access denied ({response.status_code}): {err_msg}"
                )

            if response.status_code == 429 and attempt < max_retries:
                retry_after = response.headers.get("retry-after")
                if retry_after:
                    try:
                        delay = min(float(retry_after), 10.0)
                    except ValueError:
                        delay = 2.0 ** attempt
                else:
                    delay = 2.0 ** attempt
                logger.warning(
                    f"Playground LLM 429 rate limited (attempt {attempt + 1}/{max_retries + 1}), "
                    f"retrying in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
                continue

            if response.status_code >= 500 and attempt < max_retries:
                delay = 2.0 ** attempt
                logger.warning(
                    f"Playground LLM {response.status_code} server error (attempt {attempt + 1}/{max_retries + 1}), "
                    f"retrying in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
                continue

            err_msg = self._parse_error_response(response)
            raise ValueError(
                f"LLM API error ({response.status_code}): {err_msg}"
            )

        raise ValueError("LLM API request failed after max retries")

    async def _execute_tool(self, tool_name: str, params: dict, context: Optional[dict] = None) -> dict:
        """Execute a platform tool via ToolRuntime."""
        from voice_platform.database import async_session
        from voice_platform.integrations.plugins.registry import build_default_plugin_registry
        from voice_platform.runtime.tools import (
            IntegrationResolver,
            ToolAdapter,
            ToolCaller,
            ToolCallerType,
            ToolExecutionRequest,
            ToolRuntime,
            build_default_tool_registry,
        )

        if not self.user_id:
            return {"status": "error", "message": "No user_id configured for tool execution"}

        try:
            async with async_session() as session:
                tool_registry = build_default_tool_registry()
                if not tool_registry.supports(tool_name):
                    return {"status": "error", "message": f"Unknown tool: {tool_name}"}

                definition = tool_registry.get(tool_name)
                resolver = IntegrationResolver(session, self.user_id)
                plugin_registry = build_default_plugin_registry()
                adapter = ToolAdapter(plugin_registry)
                runtime = ToolRuntime(adapter=adapter, resolver=resolver)

                request = ToolExecutionRequest(
                    arguments=params,
                    caller=ToolCaller(
                        caller_type=ToolCallerType.PLAYGROUND,
                        user_id=self.user_id,
                    ),
                    execution_id=str(_uuid.uuid4()),
                    agent_timezone=getattr(self, 'agent_timezone', None),
                )
                result = await runtime.execute(definition, request)
                return {"status": "success", "result": result.to_dict()}
        except Exception as e:
            logger.error(f"Playground tool execution failed for {tool_name}: {e}")
            return {"status": "error", "message": str(e)[:200]}

    async def _run_with_tools(self, max_iterations: int = 5) -> dict:
        """Execute LLM call with tool loop until a text response is returned.

        Returns a dict with {text: str, metrics: dict} for latency/token tracking.
        """
        start = time.time()
        total_tokens = 0
        tool_calls = 0
        for iteration in range(max_iterations):
            if iteration > 0:
                await asyncio.sleep(0.5)
            data = await self._chat_completion(stream=False)
            total_tokens += data.get("usage", {}).get("total_tokens", 0)
            message = data["choices"][0]["message"]

            if not message.get("tool_calls"):
                llm_latency_ms = (time.time() - start) * 1000
                self.metrics["turn_count"] += 1
                self.metrics["total_llm_latency_ms"] += llm_latency_ms
                self.metrics["avg_llm_latency_ms"] = (
                    self.metrics["total_llm_latency_ms"] / self.metrics["turn_count"]
                )
                self.metrics["total_tokens"] += total_tokens
                self.metrics["tool_calls_count"] += tool_calls
                return {
                    "text": message.get("content", ""),
                    "metrics": {
                        "llm_latency_ms": round(llm_latency_ms, 1),
                        "tokens": total_tokens,
                        "tool_calls": tool_calls,
                        "turn": self.metrics["turn_count"],
                    },
                }

            self.messages.append(message)

            for i, tool_call in enumerate(message["tool_calls"]):
                function_name = tool_call["function"]["name"]
                tool_calls += 1
                try:
                    arguments = json.loads(tool_call["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {}

                tool_result = await self._execute_tool(function_name, arguments)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", f"call_{i}"),
                    "content": json.dumps(tool_result),
                })
        llm_latency_ms = (time.time() - start) * 1000
        self.metrics["turn_count"] += 1
        self.metrics["total_llm_latency_ms"] += llm_latency_ms
        self.metrics["avg_llm_latency_ms"] = (
            self.metrics["total_llm_latency_ms"] / self.metrics["turn_count"]
        )
        self.metrics["total_tokens"] += total_tokens
        self.metrics["tool_calls_count"] += tool_calls
        logger.warning("Playground tool loop exceeded max iterations; returning fallback message")
        return {
            "text": "I apologize, but I'm having trouble completing that action. Please try again.",
            "metrics": {
                "llm_latency_ms": round(llm_latency_ms, 1),
                "tokens": total_tokens,
                "tool_calls": tool_calls,
                "turn": self.metrics["turn_count"],
            },
        }

    async def send_message(self, user_message: str) -> dict:
        """Send a message and get the agent's response with metrics.

        Returns a dict: {text: str, metrics: dict}
        """
        start = time.time()
        self.messages.append({"role": "user", "content": user_message})
        self._trim_history()

        try:
            if self.tools:
                result = await self._run_with_tools()
                assistant_message = result["text"]
                msg_metrics = result["metrics"]
            else:
                data = await self._chat_completion(stream=False)
                assistant_message = data["choices"][0]["message"].get("content", "")
                llm_latency_ms = (time.time() - start) * 1000
                total_tokens = data.get("usage", {}).get("total_tokens", 0)
                self.metrics["turn_count"] += 1
                self.metrics["total_llm_latency_ms"] += llm_latency_ms
                self.metrics["avg_llm_latency_ms"] = (
                    self.metrics["total_llm_latency_ms"] / self.metrics["turn_count"]
                )
                self.metrics["total_tokens"] += total_tokens
                msg_metrics = {
                    "llm_latency_ms": round(llm_latency_ms, 1),
                    "tokens": total_tokens,
                    "tool_calls": 0,
                    "turn": self.metrics["turn_count"],
                }

            self.messages.append({"role": "assistant", "content": assistant_message})
            return {"text": assistant_message, "metrics": msg_metrics}

        except Exception as e:
            # P6: Remove the dangling user message so history stays consistent
            if self.messages and self.messages[-1].get("role") == "user":
                self.messages.pop()
            error_msg = f"Error generating response: {str(e)[:200]}"
            logger.error(f"Playground LLM error: {e}")
            return {"text": error_msg, "metrics": {}}

    async def stream_message(self, user_message: str):
        """Stream a response token by token.

        Yields either text tokens (str) or a final metrics dict.
        The metrics dict is yielded last with key '_metrics'.
        """
        start = time.time()
        self.messages.append({"role": "user", "content": user_message})
        self._trim_history()

        try:
            # When tools are configured, we must use non-streaming for tool loop,
            # then yield the final result in chunks for UX (preserving formatting).
            if self.tools:
                try:
                    result = await self._run_with_tools()
                    full_response = result["text"]
                    self.messages.append({"role": "assistant", "content": full_response})
                    # Yield in chunks that preserve newlines and whitespace
                    pos = 0
                    while pos < len(full_response):
                        # Find next sentence/line boundary within ~80 chars
                        end = min(pos + 80, len(full_response))
                        if end < len(full_response):
                            # Look for natural break points
                            for delim in ('\n', '. ', '! ', '? ', '; ', ', '):
                                idx = full_response.rfind(delim, pos, end + 2)
                                if idx > pos:
                                    end = idx + len(delim)
                                    break
                        yield full_response[pos:end]
                        pos = end
                        # Small delay for streaming effect
                        await asyncio.sleep(0.01)
                    yield {"_metrics": result["metrics"]}
                    return
                except Exception as e:
                    # P6: Remove the dangling user message so history stays consistent
                    if self.messages and self.messages[-1].get("role") == "user":
                        self.messages.pop()
                    logger.error(f"Playground tool stream error: {e}")
                    err_text = str(e)[:200]
                    yield f"\n[Error: {err_text}]"
                    yield {"_metrics": {}}
                    return

            # ── Unified streaming via LLMClient.stream() ──
            from voice_platform.runtime.llm.factory import LLMFactory
            from voice_platform.runtime.llm.retry import RetryExecutor
            from voice_platform.runtime.llm.timeout import TimeoutExecutor
            from voice_platform.runtime.llm.types import ProviderConfig, RetryPolicy, TimeoutPolicy

            provider = "ollama" if self._is_ollama() else "openai"
            config = None
            if self._is_ollama():
                config = ProviderConfig(options={
                    "num_ctx": self.context_window or (65536 if self.tools else 32768),
                })

            llm_client = LLMFactory.create(
                provider,
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                retry=RetryExecutor(RetryPolicy(max_retries=3, base_delay=1.0)),
                timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=60.0)),
                config=config,
            )

            full_response = ""
            total_tokens = 0
            try:
                async for chunk in llm_client.stream(
                    self.messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                ):
                    if chunk.content:
                        full_response += chunk.content
                        yield chunk.content
                    if chunk.finish_reason == "stop":
                        break
            except Exception as e:
                if self.messages and self.messages[-1].get("role") == "user":
                    self.messages.pop()
                logger.error(f"Playground stream error: {e}")
                yield f"\n[Error: {str(e)[:200]}]"
                yield {"_metrics": {}}
                return

            self.messages.append({"role": "assistant", "content": full_response})
            llm_latency_ms = (time.time() - start) * 1000
            self.metrics["turn_count"] += 1
            self.metrics["total_llm_latency_ms"] += llm_latency_ms
            self.metrics["avg_llm_latency_ms"] = (
                self.metrics["total_llm_latency_ms"] / self.metrics["turn_count"]
            )
            self.metrics["total_tokens"] += total_tokens
            yield {
                "_metrics": {
                    "llm_latency_ms": round(llm_latency_ms, 1),
                    "tokens": total_tokens,
                    "tool_calls": 0,
                    "turn": self.metrics["turn_count"],
                }
            }

        except Exception as e:
            logger.error(f"Playground stream error: {e}")
            yield f"\n[Error: {str(e)[:200]}]"
            yield {"_metrics": {}}


# ── Helper: Build conversation from agent config ──────────────────────

async def _build_playground_conversation(agent: Agent, user_id: int) -> PlaygroundConversation:
    """Create a PlaygroundConversation from an agent config."""
    from voice_platform.config import settings

    provider = str(agent.llm_provider).lower()
    if provider not in PLAYGROUND_OPENAI_COMPATIBLE_PROVIDERS:
        raise ValueError(
            f"Provider '{provider}' is not supported by Playground chat transport yet. "
            "Use openai, gemini, groq, commandcode, or ollama for Playground testing."
        )

    llm_model = cast(Optional[str], agent.llm_model)
    model = llm_model or LLM_DEFAULT_MODELS.get(provider, "openai/gpt-oss-120b")

    # Validate model belongs to provider (same as build_agent_config)
    valid_models = _PROVIDER_MODELS.get(provider)
    if valid_models and model not in valid_models:
        fallback = LLM_DEFAULT_MODELS.get(provider, "openai/gpt-oss-120b")
        logger.warning(
            f"Playground: Agent #{agent.id} has model '{model}' not valid for provider '{provider}'. "
            f"Falling back to '{fallback}'."
        )
        model = fallback

    base_url = LLM_BASE_URLS.get(provider)

    # Resolve API key (same logic as agent_factory)
    api_key: Optional[str] = None
    session_factory = cast(Any, async_session)
    async with session_factory() as session:
        key_result = await session.execute(
            select(UserApiKey).where(
                UserApiKey.user_id == user_id,
                UserApiKey.service == provider,
                UserApiKey.is_active == True,
            )
        )
        user_key = key_result.scalar_one_or_none()
        if user_key:
            api_key = decrypt(user_key.api_key)

    llm_api_key = cast(Optional[str], agent.llm_api_key)
    if not api_key:
        if llm_api_key:
            api_key = llm_api_key
        elif provider == "openrouter":
            api_key = settings.openrouter_api_key
        elif provider == "openai":
            api_key = settings.openai_api_key
        elif provider == "groq":
            api_key = settings.groq_api_key
        elif provider == "gemini":
            api_key = settings.gemini_api_key
        elif provider == "ollama":
            api_key = settings.ollama_api_key
        elif provider == "commandcode":
            api_key = settings.commandcode_api_key

    if not api_key:
        raise ValueError(f"No API key available for {provider}. Add it in API Keys settings.")

    # Resolve base URL for Ollama dynamically
    if provider == "ollama":
        base_url = settings.ollama_base_url
    else:
        base_url = LLM_BASE_URLS.get(provider)

    # ── Prepare playground-specific context for PromptRenderer ────────
    # Fetch workflow context as structured WorkflowContext
    workflow_ctx_obj: Optional[WorkflowContext] = None
    try:
        from voice_platform.telephony.inbound_handler import _get_workflow_context
        workflow_ctx_str = await _get_workflow_context(user_id, cast(Optional[int], agent.id))
        if workflow_ctx_str:
            workflow_ctx_obj = WorkflowContext(steps=())
            logger.info(f"Injected workflow context ({len(workflow_ctx_str)} chars) into playground prompt for agent #{agent.id}")
    except Exception as e:
        logger.warning(f"Failed to inject workflow context into playground: {e}")

    # Fetch KB content as structured KnowledgeContext
    knowledge_ctx_obj: Optional[KnowledgeContext] = None
    kb_id = getattr(agent, "knowledge_base_id", None)
    if kb_id:
        try:
            from voice_platform.database import async_session as _async_session
            async with _async_session() as _session:
                kb_result = await _session.execute(
                    select(KnowledgeBase).where(
                        KnowledgeBase.id == kb_id,
                        KnowledgeBase.user_id == user_id,
                        KnowledgeBase.is_active == True,
                    )
                )
                kb = kb_result.scalar_one_or_none()
                if kb and kb.content:
                    knowledge_ctx_obj = KnowledgeContext(documents=(
                        KnowledgeDocument(
                            title=kb.name or "Knowledge Base",
                            content=kb.content[:8000],
                            source=kb.name,
                        ),
                    ))
                    logger.info(
                        f"Injected KB #{kb_id} content ({len(kb.content[:8000])} chars) "
                        f"into playground system prompt for agent #{agent.id}"
                    )
        except Exception as e:
            logger.warning(f"Failed to inject KB #{kb_id} into playground prompt: {e}")

    # Fetch drive tool actions (drift fix: playground now checks drive_tool_actions like live calls)
    drive_tool_actions: list = []
    try:
        drive_tool_actions = await _build_google_drive_tool_actions(agent)
    except Exception as e:
        logger.warning(f"Failed to fetch drive tool actions for playground: {e}")

    # Gemini tool calling warning flag
    _gemini_warning = (provider == "gemini" and bool(agent.tools_config))

    # ── Prompt Assembly (delegated to PromptRenderer) ───────────────────
    render_result = PromptRenderer.render(RenderContext(
        db_agent=agent,
        tool_actions=[],
        skipped_tools=[],
        drive_tool_actions=drive_tool_actions,
        tools_config=getattr(agent, 'tools_config', None),
        is_playground=True,
        workflow=workflow_ctx_obj,
        knowledge=knowledge_ctx_obj,
        gemini_warning=_gemini_warning,
    ))
    system_prompt = render_result.prompt

    # Load tools from agent's tools_config with MCP bindings injection
    tools: List[Dict] = []
    if agent.tools_config:
        try:
            tool_names = _json.loads(agent.tools_config) if isinstance(agent.tools_config, str) else agent.tools_config
            if isinstance(tool_names, list):
                from voice_platform.actions.platform_tools import PLATFORM_TOOLS

                # Load MCP bindings for this agent
                mcp_bindings: Dict = {}
                if hasattr(agent, "mcp_bindings_json") and agent.mcp_bindings_json:
                    try:
                        mcp_bindings = _json.loads(agent.mcp_bindings_json)
                    except Exception:
                        pass

                # Load tool instructions
                tool_instructions = getattr(agent, "tool_instructions", None)

                for name in tool_names:
                    tool_def = PLATFORM_TOOLS.get(name)
                    if not tool_def:
                        continue

                    tool_description: str = tool_def["description"]
                    params_schema: Dict = _copy.deepcopy(tool_def["parameters"])

                    # Inject MCP resource bindings into tool schema
                    if mcp_bindings and name == "read_drive_file":
                        drive_bindings = mcp_bindings.get("drive", {})
                        file_ids = drive_bindings.get("file_ids", [])
                        if file_ids:
                            tool_description += (
                                f"\n\nBound files: {len(file_ids)} file(s) configured. "
                                f"You MUST use one of the provided file IDs when reading."
                            )
                            props = params_schema.get("properties", {})
                            if "file_id" in props:
                                props["file_id"]["enum"] = file_ids

                    elif mcp_bindings and name in ("book_appointment", "create_event", "check_calendar"):
                        cal_bindings = mcp_bindings.get("calendar", {})
                        cal_ids = cal_bindings.get("calendar_ids", [])
                        if cal_ids:
                            tool_description += (
                                f"\n\nBound calendars: {len(cal_ids)} calendar(s) configured. "
                                f"Use the provided calendar IDs when creating or checking events."
                            )

                    # Append per-agent tool instructions
                    if tool_instructions:
                        tool_description += f"\n\nInstructions: {tool_instructions}"

                    tools.append({
                        "type": "function",
                        "function": {
                            "name": tool_def["name"],
                            "description": tool_description,
                            "parameters": params_schema,
                        },
                    })
                logger.info(f"Loaded {len(tools)} tools for playground agent #{agent.id} (bindings: {bool(mcp_bindings)})")
        except Exception as e:
            logger.warning(f"Failed to load playground tools for agent #{agent.id}: {e}")

    return PlaygroundConversation(
        agent_id=int(cast(Any, agent.id)),
        system_prompt=system_prompt,
        model=model,
        api_key=api_key,
        base_url=base_url,
        initial_message=cast(Optional[str], agent.initial_message),
        temperature=float(cast(Any, agent.temperature) or 0.7),
        max_tokens=int(cast(Any, agent.max_tokens)),
        tools=tools if tools else None,
        user_id=user_id,
        context_window=getattr(agent, 'context_window', None),
        agent_timezone=getattr(agent, 'timezone', None),
    )
