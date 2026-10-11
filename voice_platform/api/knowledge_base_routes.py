"""
Voice Platform — Knowledge Base API Routes
===========================================

CRUD for knowledge bases with file upload support (.txt and .pdf).
"""

import json
from typing import Any, List, Optional, cast

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.database import Agent, KnowledgeBase, async_session, get_db
from voice_platform.errors import AppError, KnowledgeBaseNotFoundError, ValidationError
from voice_platform.integrations.embeddings import LocalEmbeddingService
from voice_platform.integrations.knowledge_base import KnowledgeBaseClient
from voice_platform.middleware.auth_middleware import get_current_user

router = APIRouter(prefix="/api/knowledge-bases", tags=["Knowledge Base"])


# ── Request/Response Schemas ─────────────────────────────────────

class KBCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    source_type: str = "text"
    content: Optional[str] = None
    source_url: Optional[str] = None
    chunk_size: int = 500
    max_chunks_per_query: int = 3
    agent_ids: List[int] = []


class KBUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    chunk_size: Optional[int] = None
    max_chunks_per_query: Optional[int] = None
    agent_ids: Optional[List[int]] = None


def _parse_agent_ids_json(value: Optional[str]) -> List[int]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    agent_ids: List[int] = []
    seen = set()
    for item in parsed:
        try:
            agent_id = int(item)
        except (TypeError, ValueError):
            continue
        if agent_id in seen:
            continue
        seen.add(agent_id)
        agent_ids.append(agent_id)
    return agent_ids


async def _sync_agent_kb_links(
    db: AsyncSession,
    user_id: int,
    agent_ids: List[int],
    kb: KnowledgeBase,
):
    """Keep KnowledgeBase.agent_ids_json and Agent.knowledge_base_id aligned."""
    desired_ids: List[int] = []
    seen = set()
    for agent_id in agent_ids:
        if agent_id in seen:
            continue
        seen.add(agent_id)
        desired_ids.append(agent_id)

    current_result = await db.execute(
        select(Agent).where(
            Agent.user_id == user_id,
            Agent.knowledge_base_id == kb.id,
        )
    )
    current_agents = list(current_result.scalars().all())
    desired_set = set(desired_ids)

    for agent in current_agents:
        if agent.id not in desired_set:
            agent.knowledge_base_id = None  # type: ignore[assignment]

    linked_ids: List[int] = []
    if desired_ids:
        target_result = await db.execute(
            select(Agent).where(
                Agent.user_id == user_id,
                Agent.id.in_(desired_ids),
            )
        )
        target_map: dict[int, Any] = {cast(int, agent.id): agent for agent in target_result.scalars().all()}
        for agent_id in desired_ids:
            agent = target_map.get(agent_id)
            if not agent:
                continue
            cast(Any, agent).knowledge_base_id = cast(int, kb.id)
            linked_ids.append(agent_id)

    cast(Any, kb).agent_ids_json = json.dumps(linked_ids) if linked_ids else None


# ── Routes ──────────────────────────────────────────────────────

@router.get("")
async def list_knowledge_bases(
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all knowledge bases for the current user."""
    result = await db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.user_id == user.id)
        .order_by(KnowledgeBase.updated_at.desc())
    )
    items = result.scalars().all()
    return {"knowledge_bases": [kb.to_dict() for kb in items]}


@router.get("/{kb_id}")
async def get_knowledge_base(
    kb_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single knowledge base with full details."""
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise KnowledgeBaseNotFoundError(kb_id)
    return {"knowledge_base": kb.to_dict()}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    request: KBCreateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a knowledge base from text, URL, or with empty content
    (use POST /{kb_id}/upload for file uploads).
    """
    import json as _json

    content = request.content or ""
    chunks = []

    if content:
        chunks = KnowledgeBaseClient.chunk_text(content, chunk_size=request.chunk_size)

    # Generate embeddings for semantic RAG
    embeddings = None
    if chunks:
        embeddings = LocalEmbeddingService.encode(chunks)

    kb = KnowledgeBase(
        user_id=user.id,
        name=request.name,
        description=request.description,
        source_type=request.source_type,
        content=content,
        source_url=request.source_url,
        chunks_json=_json.dumps(chunks) if chunks else None,
        embeddings_json=_json.dumps(embeddings) if embeddings else None,
        embedding_model="all-MiniLM-L6-v2" if embeddings else None,
        embedding_provider="local" if embeddings else None,
        agent_ids_json=_json.dumps(request.agent_ids) if request.agent_ids else None,
        chunk_size=request.chunk_size,
        max_chunks_per_query=request.max_chunks_per_query,
    )
    db.add(kb)
    await db.flush()
    await _sync_agent_kb_links(db, user.id, request.agent_ids, kb)
    await db.commit()
    await db.refresh(kb)

    return {"knowledge_base": kb.to_dict(), "message": "Knowledge base created"}


@router.put("/{kb_id}")
async def update_knowledge_base(
    kb_id: int,
    request: KBUpdateRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update KB metadata and agent links."""
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise KnowledgeBaseNotFoundError(kb_id)

    import json as _json

    if request.name is not None:
        kb.name = request.name
    if request.description is not None:
        kb.description = request.description
    if request.is_active is not None:
        kb.is_active = request.is_active
    if request.chunk_size is not None:
        kb.chunk_size = request.chunk_size
    if request.max_chunks_per_query is not None:
        kb.max_chunks_per_query = request.max_chunks_per_query
    if request.agent_ids is not None:
        await _sync_agent_kb_links(db, user.id, request.agent_ids, kb)

    await db.commit()
    await db.refresh(kb)
    return {"knowledge_base": kb.to_dict(), "message": "Knowledge base updated"}


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a knowledge base and clear agent links."""
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise KnowledgeBaseNotFoundError(kb_id)

    # Clear ALL agent links (not just agent_ids_json — agents may be linked
    # via knowledge_base_id through direct updates or older records)
    agent_result = await db.execute(
        select(Agent).where(
            Agent.knowledge_base_id == kb_id,
            Agent.user_id == user.id,
        )
    )
    for agent in agent_result.scalars().all():
        agent.knowledge_base_id = None  # type: ignore

    await db.delete(kb)
    await db.commit()
    return {"message": "Knowledge base deleted"}


@router.post("/{kb_id}/upload")
async def upload_kb_file(
    kb_id: int,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a .txt or .pdf file to a knowledge base.

    - Max file size: 10MB
    - Supported: .txt, .pdf
    - Content is extracted, chunked, and stored.
    """
    import json as _json

    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise KnowledgeBaseNotFoundError(kb_id)

    # Validate file type
    filename = (file.filename or "").lower()
    if not filename.endswith(('.pdf', '.txt', '.md', '.docx')):
        raise ValidationError(
            field="file",
            message="Only PDF, TXT, MD, and DOCX files are supported.",
            suggestion="Upload a supported document format.",
        )

    # Read and validate size (10MB)
    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise ValidationError(
            field="file",
            message="File too large. Maximum 10MB.",
            suggestion="Upload a smaller file or split it into multiple documents.",
        )

    # Extract text
    try:
        text = _extract_text_from_file(contents, filename)
    except Exception as e:
        raise HTTPException(422, f"Could not extract text from file: {e}")

    if not text or not text.strip():
        raise HTTPException(422, "File appears to be empty or unreadable")

    # Chunk, embed, and store
    chunks = KnowledgeBaseClient.chunk_text(text, chunk_size=kb.chunk_size or 500)
    embeddings = LocalEmbeddingService.encode(chunks) if chunks else None

    kb.source_type = "file"
    kb.content = text[:50000]  # Store preview/cap at 50K
    kb.chunks_json = _json.dumps(chunks) if chunks else None
    kb.embeddings_json = _json.dumps(embeddings) if embeddings else None
    kb.embedding_model = "all-MiniLM-L6-v2" if embeddings else None
    kb.embedding_provider = "local" if embeddings else None

    await db.commit()
    await db.refresh(kb)

    return {
        "knowledge_base": kb.to_dict(),
        "message": f"File uploaded and chunked into {len(chunks)} segments",
        "filename": file.filename,
        "text_length": len(text),
    }


@router.get("/{kb_id}/preview")
async def preview_kb_content(
    kb_id: int,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the first 2000 chars of KB content for preview."""
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise KnowledgeBaseNotFoundError(kb_id)

    return {
        "content_preview": (kb.content or "")[:2000],
        "chunks_preview": _get_chunks_preview(kb),
    }


# ── Helper Functions ─────────────────────────────────────────────

def _extract_text_from_file(contents: bytes, filename: str) -> str:
    """Extract plain text from .txt, .md, .pdf, or .docx file bytes."""
    if filename.endswith((".txt", ".md")):
        # Try UTF-8 first, fallback to latin-1
        try:
            return contents.decode("utf-8")
        except UnicodeDecodeError:
            return contents.decode("latin-1")

    if filename.endswith(".pdf"):
        try:
            from io import BytesIO

            from PyPDF2 import PdfReader

            reader = PdfReader(BytesIO(contents))
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
            return "\n\n".join(parts)
        except ImportError:
            raise ValueError("PyPDF2 not installed. Run: pip install PyPDF2")

    if filename.endswith(".docx"):
        try:
            from io import BytesIO

            from docx import Document

            doc = Document(BytesIO(contents))
            parts = []
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    parts.append(text)
            return "\n\n".join(parts)
        except ImportError:
            raise ValueError("python-docx not installed. Run: pip install python-docx")

    raise ValueError(f"Unsupported file type: {filename}")


@router.post("/{kb_id}/query")
async def query_knowledge_base(
    kb_id: int,
    request: dict,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Semantic search against a knowledge base.

    Uses local sentence-transformer embeddings (cosine similarity) for retrieval.
    Falls back to TF-IDF keyword matching if embeddings are not available.
    """
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user.id,
        )
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise KnowledgeBaseNotFoundError(kb_id)

    query = request.get("query", "").strip()
    max_results = int(request.get("max_results", kb.max_chunks_per_query or 3))
    if not query:
        raise ValidationError(
            field="query",
            message="Query text is required.",
            suggestion="Provide a non-empty query string.",
        )

    # Load chunks
    chunks: list[str] = []
    if kb.chunks_json:
        try:
            chunks = json.loads(kb.chunks_json)
        except Exception:
            pass

    if not chunks:
        return {"chunks": [], "message": "Knowledge base has no indexed content"}

    # Semantic retrieval via embeddings
    embeddings = None
    if kb.embeddings_json:
        try:
            embeddings = json.loads(kb.embeddings_json)
        except Exception:
            pass

    results: list[dict] = []
    if embeddings and len(embeddings) == len(chunks):
        results = LocalEmbeddingService.retrieve(
            query=query,
            chunks=chunks,
            chunk_embeddings=embeddings,
            max_results=max_results,
        )
        logger.info(f"KB {kb_id} semantic query: '{query[:40]}...' → {len(results)} chunks")
    else:
        # Fallback to TF-IDF
        results = await KnowledgeBaseClient.retrieve(query=query, chunks=chunks, max_results=max_results)
        logger.info(f"KB {kb_id} TF-IDF query (no embeddings): '{query[:40]}...' → {len(results)} chunks")

    return {
        "chunks": results,
        "method": "semantic" if embeddings else "tfidf",
        "model": kb.embedding_model or "tfidf",
    }


def _get_chunks_preview(kb: KnowledgeBase) -> List[dict]:
    """Return first 3 chunks for preview."""
    if not kb.chunks_json:
        return []
    try:
        chunks = json.loads(kb.chunks_json)
        return [
            {"index": i, "text": c[:200] + "..." if len(c) > 200 else c}
            for i, c in enumerate(chunks[:3])
        ]
    except Exception:
        return []
