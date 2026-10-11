"""KnowledgeService — retrieves knowledge from KBs. Does NOT render prompts.

Returns structured KnowledgeContext (domain objects) instead of prompt strings.
PromptRenderer is responsible for converting KnowledgeContext into prompt text.

Extraction logic moved from telephony/inbound_handler._get_knowledge_base_context().
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import Agent, KnowledgeBase
from voice_platform.integrations.knowledge_base import KnowledgeBaseClient


@dataclass(frozen=True)
class KnowledgeDocument:
    """A single retrieved knowledge document."""

    title: str
    content: str
    source: str | None = None
    score: float = 0.0


@dataclass(frozen=True)
class KnowledgeContext:
    """Structured knowledge retrieval result — not a prompt string."""

    documents: tuple[KnowledgeDocument, ...] = ()


class KnowledgeService:
    """Retrieves knowledge from knowledge bases linked to an agent.

    Does NOT render prompts. Returns KnowledgeContext for PromptRenderer to consume.
    """

    async def retrieve(
        self,
        db: AsyncSession,
        agent_id: int,
        agent_config: Any | None = None,
    ) -> KnowledgeContext:
        """Retrieve knowledge documents for the given agent.

        Args:
            db: Async database session.
            agent_id: Agent ID to look up KBs for.
            agent_config: Optional agent config for query building.

        Returns:
            KnowledgeContext with retrieved documents, or empty if none found.
        """
        if agent_id is None:
            return KnowledgeContext()

        try:
            agent_result = await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )
            agent = agent_result.scalar_one_or_none()
            if not agent:
                return KnowledgeContext()

            agent_kb = None
            if getattr(agent, "knowledge_base_id", None):
                kb_result = await db.execute(
                    select(KnowledgeBase).where(
                        KnowledgeBase.id == agent.knowledge_base_id,
                        KnowledgeBase.user_id == agent.user_id,
                        KnowledgeBase.is_active == True,
                    )
                )
                agent_kb = kb_result.scalar_one_or_none()

            if agent_kb:
                all_kbs = [agent_kb]
            else:
                result = await db.execute(
                    select(KnowledgeBase).where(
                        KnowledgeBase.user_id == agent.user_id,
                        KnowledgeBase.is_active == True,
                    )
                )
                all_kbs = list(result.scalars().all())

            agent_kbs = []
            for kb in all_kbs:
                if kb is agent_kb:
                    agent_kbs.append(kb)
                    continue
                try:
                    linked_agents = json.loads(kb.agent_ids_json) if kb.agent_ids_json else []
                    if agent_id in linked_agents or str(agent_id) in [str(a) for a in linked_agents]:
                        agent_kbs.append(kb)
                except (json.JSONDecodeError, TypeError):
                    continue

            if not agent_kbs:
                return KnowledgeContext()

            documents: list[KnowledgeDocument] = []
            for kb in agent_kbs:
                try:
                    chunks = json.loads(kb.chunks_json) if kb.chunks_json else []
                    if not chunks and kb.content:
                        chunks = KnowledgeBaseClient.chunk_text(
                            kb.content, chunk_size=kb.chunk_size or 500
                        )
                    if chunks:
                        query_parts = []
                        if agent_config:
                            preamble = getattr(agent_config, "prompt_preamble", "") or ""
                            if preamble:
                                query_parts.append(preamble[:200])
                            initial_msg = getattr(agent_config, "initial_message", None)
                            if initial_msg:
                                msg_text = getattr(initial_msg, "text", str(initial_msg))
                                query_parts.append(msg_text)
                        query = " ".join(query_parts) if query_parts else (kb.name or "general overview")
                        results = await KnowledgeBaseClient.retrieve(
                            query=query,
                            chunks=chunks,
                            max_results=kb.max_chunks_per_query or 2,
                            min_score=0.01,
                        )
                        if results:
                            for r in results:
                                documents.append(KnowledgeDocument(
                                    title=kb.name or "Knowledge Base",
                                    content=r["chunk"],
                                    source=kb.name,
                                    score=float(r["score"]),
                                ))
                except Exception as e:
                    logger.warning(f"Error retrieving from KB '{kb.name}': {e}")

            return KnowledgeContext(documents=tuple(documents))

        except Exception as e:
            logger.error(f"KB context loading error: {e}")
            return KnowledgeContext()
