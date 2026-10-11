"""LLMGenerationService — minimal generation wrapper.

Just generate text from prompts. No routing, no summarization, no classification.
Future runtime services (RoutingService, SummarizationService) build on top of this.

Dependency chain:
    AgentLLMFactory → LLMGenerationService → (ExtractionService, _flex_route, ...)
"""

from __future__ import annotations

from typing import Optional

from loguru import logger

from voice_platform.runtime.llm.factory import AgentLLMFactory


class LLMGenerationService:
    """Minimal generation wrapper. Just generate text from prompts."""

    def __init__(self, factory: AgentLLMFactory) -> None:
        self._factory = factory

    async def generate(
        self,
        *,
        agent_id: int | None,
        user_id: int,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 256,
        temperature: float = 0.0,
    ) -> Optional[str]:
        """Generate text from a system+user prompt using the agent's LLM.

        Returns the raw text content, or None on failure.
        PII redaction is applied via middleware in the LLMClient stack.
        """
        runtime = await self._factory.create_from_agent(agent_id, user_id)
        if runtime is None:
            return None

        try:
            response = await runtime.client.complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                context=runtime.middleware_context,
            )
            return (response.content or "").strip() if response.content else None
        except Exception as e:
            logger.warning(
                f"LLM generation failed ({runtime.model_ref.provider}/{runtime.model_ref.model}): {e}"
            )
            return None
