"""
Voice Platform — Embedding Service
====================================

Generates text embeddings for semantic knowledge base retrieval.

Uses the OpenAI SDK with provider-specific base URLs, meaning it works
with OpenAI, Gemini, Groq, and any other OpenAI-compatible embedding API.

Fallback: if no API key is available, falls back to TF-IDF keyword matching
in KnowledgeBaseClient (zero external dependency mode).
"""

import json
from typing import Optional

from loguru import logger

from voice_platform.config import settings
from voice_platform.encryption import decrypt


class EmbeddingService:
    """
    Generates vector embeddings for text chunks.

    Uses EmbeddingClient (runtime/embeddings/client.py) which wraps the
    OpenAI SDK via ProviderSession with retry and timeout.
    All major providers (OpenAI, Gemini, Groq) support OpenAI-compatible
    embedding endpoints.
    """

    _client = None
    _embedding_client = None

    @classmethod
    def _get_embedding_client(cls, provider: str = "openai", api_key: Optional[str] = None):
        """Lazy-init the EmbeddingClient with a ProviderSession."""
        if cls._embedding_client is not None:
            return cls._embedding_client

        from voice_platform.runtime.embeddings.client import EmbeddingClient
        from voice_platform.runtime.llm.retry import RetryExecutor
        from voice_platform.runtime.llm.session import ProviderSession
        from voice_platform.runtime.llm.timeout import TimeoutExecutor
        from voice_platform.runtime.llm.types import RetryPolicy, TimeoutPolicy

        key = api_key
        base_url = None

        if provider == "openai":
            key = key or settings.openai_api_key
            base_url = settings.openai_api_base
        elif provider == "gemini":
            key = key or settings.gemini_api_key
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        elif provider == "groq":
            key = key or settings.groq_api_key
            base_url = "https://api.groq.com/openai/v1"

        if not key:
            logger.warning(f"No API key for embedding provider '{provider}'")
            return None

        session = ProviderSession(api_key=key, base_url=base_url, timeout=30.0)
        cls._embedding_client = EmbeddingClient(
            session=session,
            retry=RetryExecutor(RetryPolicy(max_retries=2, base_delay=1.0)),
            timeout=TimeoutExecutor(TimeoutPolicy(total_timeout=30.0)),
        )
        return cls._embedding_client

    @classmethod
    def _get_client(cls, provider: str = "openai", api_key: Optional[str] = None):
        """Backward compat — returns the SDK client from the session."""
        ec = cls._get_embedding_client(provider, api_key)
        if ec is None:
            return None
        return ec._session.sdk_client

    @classmethod
    async def embed_texts(
        cls,
        texts: list[str],
        model: str = "text-embedding-3-small",
        provider: str = "openai",
        api_key: Optional[str] = None,
    ) -> Optional[list[list[float]]]:
        """
        Generate embeddings for a list of text strings.

        Args:
            texts: List of text chunks to embed
            model: Embedding model name
            provider: LLM provider to route through
            api_key: Optional override API key

        Returns:
            List of embedding vectors, or None if the API call fails
        """
        if not texts:
            return []

        ec = cls._get_embedding_client(provider, api_key)
        if ec is None:
            return None

        return await ec.embed(texts, model=model)

    @classmethod
    def cosine_similarity(cls, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        import math

        if not a or not b or len(a) != len(b):
            return 0.0

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)


class LocalEmbeddingService:
    """
    Self-hosted embedding generation using sentence-transformers.

    Runs entirely locally — zero API cost, zero external dependency.
    Uses all-MiniLM-L6-v2 by default (384-dim, fast, high quality).
    Automatically uses MPS (Metal) on Apple Silicon, CUDA on NVIDIA.
    """

    _model = None
    _model_name = "all-MiniLM-L6-v2"

    @classmethod
    def _get_model(cls):
        """Lazy-load the sentence-transformers model."""
        if cls._model is not None:
            return cls._model

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            logger.warning("sentence-transformers not installed — local embeddings unavailable")
            return None

        import torch

        # Auto-detect best device: CUDA > MPS (Apple Silicon) > CPU
        if torch.cuda.is_available():
            device = "cuda"
        elif torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

        logger.info(f"Loading embedding model {cls._model_name} on {device} ...")
        cls._model = SentenceTransformer(cls._model_name, device=device)
        logger.info(f"Embedding model loaded ({cls._model.get_sentence_embedding_dimension()} dims)")
        return cls._model

    @classmethod
    def encode(cls, texts: list[str]) -> Optional[list[list[float]]]:
        """
        Generate embeddings for a list of text strings locally.

        Args:
            texts: List of text chunks to embed

        Returns:
            List of embedding vectors, or None if the model is unavailable
        """
        if not texts:
            return []

        model = cls._get_model()
        if model is None:
            return None

        try:
            # encode returns a numpy array of shape (n_texts, embedding_dim)
            embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
            vectors = embeddings.tolist()
            logger.info(f"Generated {len(vectors)} local embeddings ({len(vectors[0])} dims)")
            return vectors
        except Exception as e:
            logger.warning(f"Local embedding generation failed: {e}")
            return None

    @classmethod
    def retrieve(
        cls,
        query: str,
        chunks: list[str],
        chunk_embeddings: list[list[float]],
        max_results: int = 3,
    ) -> list[dict]:
        """
        Retrieve the most relevant chunks for a query using cosine similarity.

        Args:
            query: User query text
            chunks: List of text chunks (parallel to embeddings)
            chunk_embeddings: Pre-computed embeddings for each chunk
            max_results: Number of top chunks to return

        Returns:
            List of dicts with keys: text, score, index
        """
        if not query or not chunks or not chunk_embeddings:
            return []

        if len(chunks) != len(chunk_embeddings):
            logger.warning("Chunk/embedding count mismatch in retrieve()")
            return []

        # Encode the query
        query_embedding = cls.encode([query])
        if query_embedding is None or not query_embedding:
            return []

        query_vec = query_embedding[0]

        # Score all chunks
        import math

        q_norm = math.sqrt(sum(x * x for x in query_vec))
        if q_norm == 0:
            return []

        scored = []
        for idx, (chunk, emb) in enumerate(zip(chunks, chunk_embeddings)):
            if not emb or len(emb) != len(query_vec):
                continue

            dot = sum(x * y for x, y in zip(query_vec, emb))
            c_norm = math.sqrt(sum(x * x for x in emb))
            if c_norm == 0:
                continue

            score = dot / (q_norm * c_norm)
            scored.append({"chunk": chunk, "score": round(score, 4), "index": idx})

        # Sort by score descending and return top-N
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:max_results]
