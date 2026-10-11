"""KnowledgePlugin — knowledge base retrieval integration."""

from __future__ import annotations

import json
from typing import Any, Callable

from loguru import logger

from voice_platform.integrations.plugins.base import (
    IntegrationConfiguration,
    PluginExecutionRequest,
    PluginResult,
)


class KnowledgePlugin:
    """Knowledge base retrieval integration plugin."""

    kinds = ("knowledge_base",)

    def __init__(
        self,
        client_factory: Callable[[IntegrationConfiguration], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    async def execute(self, request: PluginExecutionRequest) -> PluginResult[dict]:
        action = request.action
        params = dict(request.params)
        config = dict(request.integration.config)

        try:
            from voice_platform.integrations.knowledge_base import KnowledgeBaseClient

            if action == "retrieve":
                query = params.get("query", "")
                chunks_json = config.get("chunks_json", "[]")
                try:
                    chunks = json.loads(chunks_json) if isinstance(chunks_json, str) else chunks_json
                except json.JSONDecodeError:
                    chunks = []
                max_results = int(params.get("max_results", config.get("max_chunks_per_query", 3)))
                results = KnowledgeBaseClient.retrieve(query=query, chunks=chunks, max_results=max_results)
                context = KnowledgeBaseClient.format_context(results, kb_name=config.get("name", "Knowledge Base"))
                return PluginResult(success=True, output={
                    "success": True, "chunks_found": len(results), "context": context, "results": results,
                })

            elif action == "chunk_content":
                content = params.get("content", "")
                chunk_size = int(params.get("chunk_size", 500))
                chunks = KnowledgeBaseClient.chunk_text(content, chunk_size=chunk_size)
                return PluginResult(success=True, output={
                    "success": True, "chunk_count": len(chunks), "chunks": chunks,
                })

            else:
                return PluginResult(success=False, error=f"Unknown knowledge_base action: {action}")
        except Exception as e:
            logger.error(f"Knowledge base action {action} failed: {e}")
            return PluginResult(success=False, error=str(e))
