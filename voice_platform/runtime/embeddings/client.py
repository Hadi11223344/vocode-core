"""EmbeddingClient — separate from LLMClient.

Completion and embeddings have no overlap. This client handles only
embedding generation via the OpenAI-compatible embeddings API.

Uses ProviderSession for pooled transport. Retry and timeout are
delegated to the reusable executors.
"""

from typing import Any, Optional

from loguru import logger

from voice_platform.runtime.llm.retry import RetryExecutor
from voice_platform.runtime.llm.session import ProviderSession
from voice_platform.runtime.llm.timeout import TimeoutExecutor


class EmbeddingClient:
    """Dedicated client for embedding generation.

    Separate from LLMClient — embeddings API is fundamentally different
    from completions (no streaming, no tools, no PII).
    """

    def __init__(
        self,
        session: ProviderSession,
        *,
        retry: RetryExecutor,
        timeout: TimeoutExecutor,
    ):
        self._session = session
        self._retry = retry
        self._timeout = timeout

    async def embed(
        self,
        texts: list[str],
        model: str = "text-embedding-3-small",
    ) -> list[list[float]] | None:
        """Generate embeddings for a list of text strings.

        Returns list of embedding vectors, or None on failure.
        """
        if not texts:
            return []

        try:
            async def _do_embed():
                client = self._session.sdk_client
                response = await client.embeddings.create(
                    model=model,
                    input=texts,
                )
                return [item.embedding for item in response.data]

            vectors = await self._retry.execute_async(
                self._timeout.execute,
                _do_embed,
            )
            logger.info(f"Generated {len(vectors)} embeddings via {model}")
            return vectors
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return None
