"""
Voice Platform — Knowledge Base Client
=========================================

RAG-style knowledge retrieval for voice agents (inspired by Retell AI).

How it works:
    1. Users create knowledge bases from text, URLs, or files
    2. Content is chunked into retrievable segments
    3. During calls, the transcript is used to find relevant chunks
    4. Matching chunks are injected into the LLM prompt as context

This provides the agent with domain-specific knowledge without
stuffing everything into the system prompt.

Retrieval uses TF-IDF keyword matching (no external vector DB needed).
"""

import json
import math
import re
from collections import Counter
from typing import Optional

from loguru import logger


class KnowledgeBaseClient:
    """
    Lightweight keyword-based knowledge retrieval.
    
    Uses TF-IDF scoring for relevance matching — no external 
    vector database or embedding API required.
    """
    
    @staticmethod
    def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        """
        Split text into overlapping chunks for retrieval.
        
        Args:
            text: Raw text content
            chunk_size: Target characters per chunk
            overlap: Character overlap between chunks
        
        Returns:
            List of text chunks
        """
        if not text:
            return []
        
        # Clean up whitespace
        text = re.sub(r'\n{3,}', '\n\n', text.strip())
        
        # Try to split on paragraph boundaries first
        paragraphs = re.split(r'\n\n+', text)
        
        chunks = []
        current_chunk = ""
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            if len(current_chunk) + len(para) + 2 <= chunk_size:
                current_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                
                # If single paragraph is too long, split by sentences
                if len(para) > chunk_size:
                    sentences = re.split(r'(?<=[.!?])\s+', para)
                    current_chunk = ""
                    for sent in sentences:
                        if len(current_chunk) + len(sent) + 1 <= chunk_size:
                            current_chunk = f"{current_chunk} {sent}" if current_chunk else sent
                        else:
                            if current_chunk:
                                chunks.append(current_chunk.strip())
                            current_chunk = sent
                else:
                    current_chunk = para
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # Add overlap between chunks
        if overlap > 0 and len(chunks) > 1:
            overlapped = [chunks[0]]
            for i in range(1, len(chunks)):
                prev_tail = chunks[i - 1][-overlap:] if len(chunks[i - 1]) > overlap else chunks[i - 1]
                overlapped.append(f"...{prev_tail}\n{chunks[i]}")
            chunks = overlapped
        
        return chunks
    
    @staticmethod
    def _tfidf_retrieve(
        query: str,
        chunks: list[str],
        max_results: int = 3,
        min_score: float = 0.05,
    ) -> list[dict]:
        """Legacy TF-IDF retrieval (fallback when embeddings unavailable)."""
        if not query or not chunks:
            return []

        def tokenize(text: str) -> list[str]:
            return re.findall(r'\b[a-zA-Z]{2,}\b', text.lower())

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        query_tf = Counter(query_tokens)
        chunk_tokens = [tokenize(c) for c in chunks]
        doc_count = len(chunks)

        df: Counter[str] = Counter()
        for tokens in chunk_tokens:
            for word in set(tokens):
                df[word] += 1

        idf = {}
        for word, freq in df.items():
            idf[word] = math.log((doc_count + 1) / (freq + 1)) + 1

        results = []
        for idx, tokens in enumerate(chunk_tokens):
            if not tokens:
                continue
            chunk_tf = Counter(tokens)
            score = 0.0
            for word in query_tf:
                if word in chunk_tf:
                    tf_query = query_tf[word] / len(query_tokens)
                    tf_chunk = chunk_tf[word] / len(tokens)
                    word_idf = idf.get(word, 1.0)
                    score += tf_query * tf_chunk * word_idf * word_idf
            if score >= min_score:
                results.append({"chunk": chunks[idx], "score": round(score, 4), "index": idx})

        from typing import cast
        results.sort(key=lambda x: cast(float, x["score"]), reverse=True)
        return results[:max_results]

    @staticmethod
    async def retrieve(
        query: str,
        chunks: list[str],
        chunk_embeddings: Optional[list[list[float]]] = None,
        max_results: int = 3,
        min_score: float = 0.05,
        embedding_model: str = "text-embedding-3-small",
        embedding_provider: str = "openai",
    ) -> list[dict]:
        """
        Find the most relevant chunks for a query.

        **Semantic search (preferred):** If `chunk_embeddings` are provided,
        generates a query embedding and uses cosine similarity for ranking.

        **TF-IDF fallback:** If embeddings are not available, falls back to
        keyword-based TF-IDF scoring.

        Args:
            query: Search query (e.g. transcript text)
            chunks: List of text chunks to search
            chunk_embeddings: Pre-computed embeddings parallel to chunks
            max_results: Maximum chunks to return
            min_score: Minimum relevance score threshold
            embedding_model: Model for query embedding generation
            embedding_provider: Provider for query embedding generation

        Returns:
            List of {chunk, score, index} sorted by relevance
        """
        # ── Semantic retrieval via embeddings ──────────────────────
        if chunk_embeddings and chunks and len(chunk_embeddings) == len(chunks):
            from voice_platform.integrations.embeddings import EmbeddingService

            query_vectors = await EmbeddingService.embed_texts(
                [query],
                model=embedding_model,
                provider=embedding_provider,
            )
            if query_vectors and query_vectors[0]:
                query_vec = query_vectors[0]
                results = []
                for idx, emb in enumerate(chunk_embeddings):
                    if emb and len(emb) == len(query_vec):
                        score = EmbeddingService.cosine_similarity(query_vec, emb)
                        if score >= min_score:
                            results.append({
                                "chunk": chunks[idx],
                                "score": round(score, 4),
                                "index": idx,
                            })
                if results:
                    from typing import cast
                    results.sort(key=lambda x: cast(float, x["score"]), reverse=True)
                    logger.debug(f"KB semantic retrieval: {len(results)} matches for query")
                    return results[:max_results]

        # ── TF-IDF fallback ──────────────────────────────────────
        return KnowledgeBaseClient._tfidf_retrieve(query, chunks, max_results, min_score)
    
    @staticmethod
    def format_context(results: list[dict], kb_name: str = "Knowledge Base") -> str:
        """
        Format retrieved chunks as LLM context injection.
        
        Returns a string that can be appended to the agent's prompt.
        """
        if not results:
            return ""
        
        parts = [f"\n## Related {kb_name} Contexts"]
        for i, r in enumerate(results, 1):
            parts.append(f"\n[Context {i}] (relevance: {r['score']:.2f})")
            parts.append(r["chunk"])
        
        return "\n".join(parts)
    
    @staticmethod
    async def fetch_url_content(url: str) -> str:
        """
        Fetch text content from a URL for knowledge base ingestion.
        
        Strips HTML tags and returns clean text.
        """
        from voice_platform.utils.ssrf import is_safe_url as _is_safe_url

        # SEC-05: SSRF blocklist — reject internal/private URLs
        if not _is_safe_url(url):
            raise ValueError(f"URL blocked for security: {url}")

        import httpx

        try:
            # Follow redirects manually with SSRF re-check on each hop
            current_url = url
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False, verify=True) as client:
                for _ in range(5):  # max 5 redirects
                    response = await client.get(current_url)
                    if response.status_code in (301, 302, 303, 307, 308):
                        redirect_url = str(response.headers.get("location", ""))
                        if not redirect_url:
                            break
                        # Resolve relative redirects
                        if redirect_url.startswith("/"):
                            redirect_url = httpx.URL(current_url).copy_with(path=redirect_url)
                        redirect_url = str(redirect_url)
                        # Re-check SSRF on redirect target
                        if not _is_safe_url(redirect_url):
                            raise ValueError(f"Redirect URL blocked for security: {redirect_url}")
                        current_url = redirect_url
                        continue
                    response.raise_for_status()
                    break
                else:
                    raise ValueError("Too many redirects (max 5)")

                content = response.text

                # Strip HTML tags if it's HTML content
                if "<html" in content.lower() or "<body" in content.lower():
                    # Simple HTML tag stripping
                    content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
                    content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL)
                    content = re.sub(r'<[^>]+>', ' ', content)
                    content = re.sub(r'\s+', ' ', content)
                    content = content.strip()

                return content[:50000]  # Cap at 50K chars

        except Exception as e:
            logger.error(f"Failed to fetch URL {url}: {e}")
            raise ValueError(f"Could not fetch content from {url}: {e}")

    @staticmethod
    async def invalidate_cache(kb_id: int) -> bool:
        """KB-02: Explicitly clear the Redis cache for a knowledge base.

        Call this after updating KB content to ensure agents use fresh data.
        Returns True if cache was cleared (or didn't exist), False on error.
        """
        cache_key = f"kb:{kb_id}:chunks"
        try:
            import redis.asyncio as aioredis

            from voice_platform.config import settings

            redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
            await redis_client.delete(cache_key)
            await redis_client.aclose()
            logger.info(f"KB-02: Invalidated cache for KB {kb_id}")
            return True
        except Exception:
            logger.warning(f"KB-02: Redis unavailable, could not invalidate cache for KB {kb_id}")
            return False
