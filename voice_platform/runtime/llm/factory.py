"""LLMFactory — single point of provider selection.

Receives injected executors (shared singletons). Only factory knows adapter class names.
ProviderConfig passes provider-specific options without factory signature changes.
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.config import settings
from voice_platform.database import Agent
from voice_platform.runtime.llm.adapters import (
    AnthropicAdapter,
    CommandCodeAdapter,
    GeminiAdapter,
    GroqAdapter,
    OllamaAdapter,
    OpenAIAdapter,
    OpenRouterAdapter,
    ProviderAdapter,
)
from voice_platform.runtime.llm.client import LLMClient
from voice_platform.runtime.llm.middleware import MessagePipeline, MiddlewareContext, PIIRedactor
from voice_platform.runtime.llm.retry import RetryExecutor
from voice_platform.runtime.llm.session import ProviderSession
from voice_platform.runtime.llm.timeout import TimeoutExecutor
from voice_platform.runtime.llm.types import LLMRuntime, ProviderConfig, RetryPolicy, TimeoutPolicy
from voice_platform.runtime.session.runtime_config import ModelReference


class LLMFactory:
    """Centralized provider selection. No other code knows adapter names."""

    _ADAPTERS: dict[str, type[ProviderAdapter]] = {
        "openai": OpenAIAdapter,
        "gemini": GeminiAdapter,
        "anthropic": AnthropicAdapter,
        "groq": GroqAdapter,
        "ollama": OllamaAdapter,
        "openrouter": OpenRouterAdapter,
        "commandcode": CommandCodeAdapter,
    }

    @classmethod
    def create(
        cls,
        provider: str,
        *,
        api_key: str,
        base_url: str | None = None,
        model: str,
        retry: RetryExecutor,
        timeout: TimeoutExecutor,
        middleware: MessagePipeline | None = None,
        config: ProviderConfig | None = None,
    ) -> LLMClient:
        """Create LLMClient with injected executors (shared singletons).

        Args:
            provider: Provider name (openai, gemini, groq, ollama, etc.)
            api_key: API key for the provider
            base_url: Base URL override (None for provider default)
            model: Model name
            retry: Injected RetryExecutor (shared singleton)
            timeout: Injected TimeoutExecutor (shared singleton)
            middleware: Optional message pipeline for PII etc.
            config: Provider-specific options (num_ctx, think, etc.)
        """
        adapter_cls = cls._ADAPTERS.get(provider)
        if not adapter_cls:
            raise ValueError(f"Unknown provider: {provider}")

        session = ProviderSession(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout.policy.total_timeout,
        )
        adapter = adapter_cls(session=session, model=model, config=config)

        return LLMClient(
            adapter=adapter,
            retry=retry,
            timeout=timeout,
            middleware=middleware,
        )

    @classmethod
    def supported_providers(cls) -> list[str]:
        """Return list of supported provider names."""
        return list(cls._ADAPTERS.keys())


class AgentLLMFactory:
    """Builds an LLM runtime for a particular agent.

    Resolves provider, model, credentials, and middleware from agent config
    or platform defaults, then constructs an LLMRuntime.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_from_agent(
        self,
        agent_id: int | None,
        user_id: int,
    ) -> LLMRuntime | None:
        """Resolve config and build an LLMRuntime for the given agent.

        Returns None if no API key is available.
        """
        config = await self._resolve_config(agent_id)
        api_key = config["api_key"]
        if not api_key:
            logger.warning(
                f"No API key available for LLM provider '{config['provider']}'. "
                "Skipping LLM call."
            )
            return None
        return self._build_runtime(
            provider=config["provider"],
            model=config["model"],
            api_key=api_key,
            base_url=config["base_url"],
        )

    async def _resolve_config(self, agent_id: int | None) -> dict[str, Any]:
        """Resolve LLM provider, model, API key, and base URL.

        Priority:
            1. Agent config (if agent_id provided)
            2. Platform defaults from settings / .env
        """
        provider = "openrouter"
        model = "deepseek/deepseek-v4-flash"
        api_key: Optional[str] = settings.openrouter_api_key
        base_url: Optional[str] = "https://openrouter.ai/api/v1"

        if agent_id is not None:
            result = await self._session.execute(
                select(Agent).where(Agent.id == agent_id)
            )
            agent = result.scalar_one_or_none()
            if agent:
                provider = (agent.llm_provider or provider).lower()
                model = agent.llm_model or model
                if agent.llm_api_key:
                    api_key = agent.llm_api_key
                else:
                    api_key = self._resolve_platform_api_key(provider)
                base_url = self._resolve_base_url(provider)
            else:
                api_key = self._resolve_platform_api_key(provider)
        else:
            api_key = self._resolve_platform_api_key(provider)

        return {
            "provider": provider,
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
        }

    @staticmethod
    def _resolve_platform_api_key(provider: str) -> Optional[str]:
        if provider == "openrouter":
            return settings.openrouter_api_key
        if provider == "openai":
            return settings.openai_api_key
        if provider == "gemini":
            return settings.gemini_api_key
        if provider == "groq":
            return settings.groq_api_key
        return None

    @staticmethod
    def _resolve_base_url(provider: str) -> Optional[str]:
        urls = {
            "openrouter": "https://openrouter.ai/api/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "groq": "https://api.groq.com/openai/v1",
        }
        return urls.get(provider)

    @staticmethod
    def _build_runtime(
        *,
        provider: str,
        model: str,
        api_key: str,
        base_url: Optional[str],
    ) -> LLMRuntime:
        """Construct LLMRuntime with PII redaction middleware."""
        pipeline = MessagePipeline([PIIRedactor()])
        ctx = MiddlewareContext(
            provider=provider,
            model=model,
        )
        client = LLMFactory.create(
            provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            retry=RetryExecutor(RetryPolicy(max_retries=2, base_delay=1.0)),
            timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=30.0)),
            middleware=pipeline,
        )
        model_ref = ModelReference(provider=provider, model=model)
        return LLMRuntime(
            client=client,
            middleware_context=ctx,
            model_ref=model_ref,
        )
