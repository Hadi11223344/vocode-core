"""
Voice Platform — Agent API Routes
====================================

CRUD endpoints for managing voice agents.

Each agent has its own LLM, STT, and TTS configuration that the
frontend can control. Users pick their provider, model, and optionally
supply their own API key.

Routes:
    GET    /api/agents            — List user's agents
    POST   /api/agents            — Create a new agent
    GET    /api/agents/providers   — Available provider options for dropdowns
    GET    /api/agents/{id}       — Get agent details
    PUT    /api/agents/{id}       — Update agent
    DELETE /api/agents/{id}       — Deactivate agent
"""

import json
import re
from typing import Any, Optional, cast  # For optional request fields

from fastapi import APIRouter, Depends, HTTPException, Query, status  # Routing + errors
from loguru import logger  # Logging
from pydantic import BaseModel, Field, model_validator  # Request body validation
from sqlalchemy import select, update  # Database queries
from sqlalchemy.ext.asyncio import AsyncSession  # Async DB session

from vocode.streaming.models.agent import LLM_AGENT_DEFAULT_MAX_TOKENS
from voice_platform.config import settings
from voice_platform.database import (  # Models + DB dependency
    Agent,
    Integration,
    KnowledgeBase,
    PromptVersion,
    User,
    Workflow,
    get_db,
)
from voice_platform.errors import (
    AgentInactiveError,
    AgentNotFoundError,
    AlreadyExistsError,
    KnowledgeBaseNotFoundError,
    NotFoundError,
    ValidationError,
)
from voice_platform.graph_contracts import (
    canonical_content_hash,
    required_input_branch_violations,
)
from voice_platform.middleware.auth_middleware import get_current_user  # Auth check

# Create router with prefix and tag
router = APIRouter(prefix="/api/agents", tags=["Agents"])


# ── Request/Response Schemas ───────────────────────────────────────────

class CreateAgentRequest(BaseModel):
    """Schema for creating a new voice agent."""
    name: str = Field(..., min_length=1, max_length=255, description="Agent display name")
    prompt_preamble: str = Field(..., min_length=1, max_length=10000, description="System prompt")
    initial_message: str = Field(
        default="Hello! Thank you for calling. How can I help you today?",
        description="First thing the agent says when call connects"
    )
    # ── LLM Config ─────────────────────────────────────────────────
    llm_provider: str = Field(default="openrouter", description="LLM provider: openrouter, openai, anthropic, groq")
    llm_model: str = Field(default="deepseek/deepseek-v4-flash", description="Model name")
    llm_api_key: Optional[str] = Field(default=None, description="Custom API key (null=use default)")
    # ── STT Config ─────────────────────────────────────────────────
    stt_provider: str = Field(default="deepgram", description="STT provider")
    stt_language: str = Field(default="en-US", description="Speech recognition language")
    stt_api_key: Optional[str] = Field(default=None, description="Custom STT API key")
    # ── TTS Config ─────────────────────────────────────────────────
    tts_provider: str = Field(default="deepgram", description="TTS provider")
    tts_voice_id: Optional[str] = Field(default="aura-asteria-en", description="Voice ID for TTS")
    tts_api_key: Optional[str] = Field(default=None, description="Custom TTS API key")
    # ── Parameters ─────────────────────────────────────────────────
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="LLM temperature")
    max_tokens: int = Field(default=LLM_AGENT_DEFAULT_MAX_TOKENS, ge=50, le=4096, description="Max tokens per response")
    end_on_goodbye: bool = Field(default=True, description="Auto-end call on goodbye")
    interrupt_sensitivity: str = Field(default="low", description="'low' or 'high'")
    # ── Call Stability Settings ────────────────────────────────────
    allowed_idle_time_seconds: Optional[float] = Field(
        default=60.0, ge=15.0, le=300.0,
        description="Seconds of silence before idle-check triggers (15-300)"
    )
    num_check_human_present_times: Optional[int] = Field(
        default=2, ge=0, le=5,
        description="'Are you there?' retries before auto-ending (0=instant drop, 2=recommended)"
    )
    initial_message_delay: Optional[float] = Field(
        default=0.4, ge=0.0, le=3.0,
        description="Seconds to wait before speaking (gives Twilio WebSocket time to connect)"
    )
    stt_model: Optional[str] = Field(
        default="nova-3",
        description="Deepgram model: 'nova-3' (best accuracy), 'nova-3-phonecall' (telephony), 'nova-2-phonecall' (legacy)"
    )
    endpointing_type: Optional[str] = Field(
        default="auto",
        description="Endpointing strategy: 'auto' (VAD-based), 'punctuation', 'time'"
    )
    filler_audio_enabled: Optional[bool] = Field(
        default=True,
        description="Play filler audio (phrases/typing) while LLM generates response"
    )
    min_interrupt_confidence: Optional[float] = Field(
        default=0.6, ge=0.0, le=1.0,
        description="Min transcription confidence to trigger interrupt (0.6+ prevents noise)"
    )
    stt_smart_format: Optional[bool] = Field(
        default=True,
        description="Enable Deepgram smart formatting (numbers, dates, currencies in transcripts)"
    )
    stt_diarize: Optional[bool] = Field(
        default=True,
        description="Enable speaker diarization (identify speakers in transcript)"
    )
    stt_filter_filler_words: Optional[bool] = Field(
        default=False,
        description="Filter filler words ('um', 'uh') from transcripts"
    )
    analysis_provider: Optional[str] = Field(
        default="auto",
        description="Post-call analysis provider: 'auto' (Deepgram if recording, else LLM), 'deepgram', 'llm'"
    )
    # GAP-03: Webhook URL for post-call event notifications
    webhook_url: Optional[str] = Field(
        default=None, max_length=500,
        description="Webhook URL to receive call_started and call_ended events"
    )
    # GAP-06: Optional team ownership for RBAC
    team_id: Optional[int] = Field(
        default=None, description="Team ID to assign this agent to"
    )
    # GAP-07: Language for STT/TTS auto-configuration
    language: Optional[str] = Field(
        default="en-US", max_length=10,
        description="Agent language (en-US, ur-PK, hi-IN, ar-SA, es-ES, fr-FR, de-DE, auto)"
    )
    # ── Agent Mode & Flow (Retell AI 2.0) ─────────────────────────
    mode: Optional[str] = Field(
        default="single_prompt", max_length=20,
        description="Agent mode: 'single_prompt' or 'conversational_flow'"
    )
    graph_json: Optional[dict] = Field(
        default=None, description="ReactFlow graph data for conversational flow agents"
    )
    workflow_id: Optional[int] = Field(
        default=None, description="Link an existing workflow as the agent's conversational graph"
    )
    extraction_prompts: Optional[dict] = Field(
        default=None, description="Per-agent variable extraction prompts (variable name → description)"
    )
    transition_flexibility: Optional[str] = Field(
        default="flex", max_length=10,
        description="Transition control: 'strict' or 'flex'"
    )
    handbook_enabled: Optional[bool] = Field(
        default=False, description="Enable agent handbook (RAG document)"
    )
    handbook_content: Optional[str] = Field(
        default=None, max_length=10000,
        description="Agent handbook markdown content"
    )
    template_id: Optional[str] = Field(
        default=None, max_length=50,
        description="Template ID this agent was created from"
    )
    # GAP-14: Link to knowledge base for RAG
    knowledge_base_id: Optional[int] = Field(
        default=None, description="Knowledge base ID to link for document retrieval"
    )
    google_drive_integration_id: Optional[int] = Field(
        default=None,
        description="Google Drive MCP integration ID to attach to this agent",
    )
    tool_instructions: Optional[str] = Field(
        default=None, max_length=5000,
        description="Per-agent instructions injected into enabled tool descriptions during calls",
    )
    integration_overrides: Optional[dict] = Field(
        default=None,
        description="Per-agent integration overrides: {google_sheets: 123, google_calendar: 456}",
    )
    mcp_bindings: Optional[dict] = Field(
        default=None,
        description="MCP resource bindings: {drive: {file_ids:[], folder_ids:[]}, calendar: {calendar_ids:[]}}",
    )
    voicemail_message: Optional[str] = Field(
        default=None, max_length=2000,
        description="Message to leave when voicemail is detected on outbound calls",
    )
    outbound_ready: Optional[bool] = Field(
        default=None,
        description="Whether this agent can make outbound calls",
    )
    inbound_ready: Optional[bool] = Field(
        default=None,
        description="Whether this agent can receive inbound calls",
    )
    context_window: Optional[int] = Field(
        default=None,
        description="Ollama context window size (num_ctx). NULL = auto-detect from model.",
    )

    @model_validator(mode="before")
    @classmethod
    def set_provider_default_model(cls, data: Any) -> Any:
        """Apply a provider-specific default model when llm_model is not provided."""
        if not isinstance(data, dict):
            return data
        provider = data.get("llm_provider", "openrouter")
        if data.get("llm_model") is None:
            defaults = {
                "openrouter": "deepseek/deepseek-v4-flash",
                "groq": "openai/gpt-oss-120b",
                "openai": "gpt-4o-mini",
                "gemini": "gemini-2.0-flash",
                "anthropic": "claude-3-haiku-20240307",
                "commandcode": "deepseek/deepseek-v4-pro",
            }
            data["llm_model"] = defaults.get(provider, "deepseek/deepseek-v4-flash")
        return data


def _parse_agent_ids_json(value: Optional[str]) -> list[int]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    agent_ids: list[int] = []
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


async def _sync_agent_knowledge_base_link(
    db: AsyncSession,
    user_id: int,
    agent_id: int,
    previous_kb_id: Optional[int],
    next_kb_id: Optional[int],
):
    if previous_kb_id == next_kb_id:
        return

    kb_ids = [kb_id for kb_id in {previous_kb_id, next_kb_id} if kb_id is not None]
    if not kb_ids:
        return

    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.user_id == user_id,
            KnowledgeBase.id.in_(kb_ids),
        )
    )
    kb_map: dict[int, Any] = {cast(int, kb.id): kb for kb in kb_result.scalars().all()}

    previous_kb = kb_map.get(previous_kb_id) if previous_kb_id is not None else None
    if previous_kb is not None:
        previous_ids = _parse_agent_ids_json(cast(Optional[str], previous_kb.agent_ids_json))
        previous_ids = [existing_id for existing_id in previous_ids if existing_id != agent_id]
        cast(Any, previous_kb).agent_ids_json = json.dumps(previous_ids) if previous_ids else None

    if next_kb_id is not None:
        next_kb = kb_map.get(next_kb_id)
        if not next_kb:
            raise KnowledgeBaseNotFoundError(next_kb_id)
        next_ids = _parse_agent_ids_json(cast(Optional[str], next_kb.agent_ids_json))
        if agent_id not in next_ids:
            next_ids.append(agent_id)
        cast(Any, next_kb).agent_ids_json = json.dumps(next_ids) if next_ids else None

async def _validate_google_drive_integration(
    db: AsyncSession,
    user_id: int,
    integration_id: Optional[int],
) -> Optional[Integration]:
    if integration_id is None:
        return None

    result = await db.execute(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.user_id == user_id,
            Integration.service_type == "google_drive_mcp",
            Integration.is_active == True,
        )
    )
    integration = result.scalar_one_or_none()
    if not integration:
        raise ValidationError(
            field="google_drive_integration_id",
            message="Choose an active Google Drive integration connected to your account.",
            suggestion="Connect Google Drive in Settings → Integrations first, then select the Drive integration here.",
        )

    return integration


async def _validate_integration_overrides(
    db: AsyncSession,
    user_id: int,
    overrides: Optional[dict],
) -> None:
    """Validate that every integration ID in overrides belongs to the user and is active."""
    if not overrides:
        return

    from voice_platform.database import Integration

    override_ids = [int(v) for v in overrides.values() if v is not None]
    if not override_ids:
        return

    result = await db.execute(
        select(Integration).where(
            Integration.id.in_(override_ids),
            Integration.user_id == user_id,
            Integration.is_active == True,
        )
    )
    valid_ids = {cast(int, i.id) for i in result.scalars().all()}
    invalid = [iid for iid in override_ids if iid not in valid_ids]
    if invalid:
        raise ValidationError(
            field="integration_overrides",
            message=f"Invalid integration override(s): {', '.join(str(i) for i in invalid)}. They must be active and belong to your account.",
            suggestion="Check your connected integrations in Settings → Integrations.",
        )


async def _validate_team_ownership(
    db: AsyncSession,
    user_id: int,
    team_id: Optional[int],
) -> None:
    """Validate that the user is a member of the requested team."""
    if team_id is None:
        return

    from voice_platform.rbac import get_team_membership

    if not await get_team_membership(user_id, team_id):
        raise ValidationError(
            field="team_id",
            message="You do not have access to the specified team.",
            suggestion="Choose a team you are a member of.",
        )


def _validate_language(value: Optional[str]) -> None:
    if value is None:
        return
    if not re.match(r"^[a-zA-Z]{2,3}(-[a-zA-Z]{2,3})?$", value):
        raise ValidationError(
            field="language",
            message=f"Invalid language format: {value!r}.",
            suggestion="Use a locale code like en-US, ur-PK, or hi-IN.",
        )


def _validate_agent_config_values(data: dict[str, Any]) -> None:
    """Validate provider-specific field values after basic provider validation."""
    llm_provider = data.get("llm_provider")
    llm_model = data.get("llm_model")
    if llm_provider and llm_model and llm_model not in VALID_LLM_MODELS.get(llm_provider, set()):
        raise ValidationError(
            field="llm_model",
            message=f"Invalid model '{llm_model}' for provider '{llm_provider}'.",
            suggestion=f"Valid models: {', '.join(sorted(VALID_LLM_MODELS.get(llm_provider, set())))}",
        )

    stt_provider = data.get("stt_provider")
    stt_model = data.get("stt_model")
    if stt_provider and stt_model:
        allowed_stt = VALID_STT_MODELS.get(stt_provider)
        if allowed_stt is not None and stt_model not in allowed_stt:
            raise ValidationError(
                field="stt_model",
                message=f"Invalid STT model '{stt_model}' for provider '{stt_provider}'.",
                suggestion=f"Valid models: {', '.join(sorted(allowed_stt))}",
            )

    tts_provider = data.get("tts_provider")
    tts_voice_id = data.get("tts_voice_id")
    if tts_provider and tts_voice_id:
        if tts_provider == "deepgram" and tts_voice_id not in DEEPGRAM_VOICE_IDS:
            raise ValidationError(
                field="tts_voice_id",
                message=f"Invalid Deepgram voice ID: {tts_voice_id!r}.",
                suggestion=f"Valid voices: {', '.join(sorted(DEEPGRAM_VOICE_IDS))}",
            )

    interrupt_sensitivity = data.get("interrupt_sensitivity")
    if interrupt_sensitivity is not None and interrupt_sensitivity not in VALID_INTERRUPT_SENSITIVITY:
        raise ValidationError(
            field="interrupt_sensitivity",
            message=f"Invalid interrupt_sensitivity: {interrupt_sensitivity!r}.",
            suggestion="Choose 'low' or 'high'.",
        )

    endpointing_type = data.get("endpointing_type")
    if endpointing_type is not None and endpointing_type not in VALID_ENDPOINTING_TYPES:
        raise ValidationError(
            field="endpointing_type",
            message=f"Invalid endpointing_type: {endpointing_type!r}.",
            suggestion="Choose 'auto', 'punctuation', or 'time'.",
        )

    _validate_language(data.get("language"))


class UpdateAgentRequest(BaseModel):
    """Schema for updating an existing agent. All fields optional."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    prompt_preamble: Optional[str] = Field(None, min_length=1, max_length=10000)
    initial_message: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None
    stt_provider: Optional[str] = None
    stt_language: Optional[str] = None
    stt_api_key: Optional[str] = None
    tts_provider: Optional[str] = None
    tts_voice_id: Optional[str] = None
    tts_api_key: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=50, le=4096)
    end_on_goodbye: Optional[bool] = None
    interrupt_sensitivity: Optional[str] = None
    is_active: Optional[bool] = None
    # ── Call Stability Settings ────────────────────────────────────
    allowed_idle_time_seconds: Optional[float] = Field(None, ge=15.0, le=300.0)
    num_check_human_present_times: Optional[int] = Field(None, ge=0, le=5)
    initial_message_delay: Optional[float] = Field(None, ge=0.0, le=3.0)
    stt_model: Optional[str] = None
    endpointing_type: Optional[str] = None
    filler_audio_enabled: Optional[bool] = None
    min_interrupt_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    stt_smart_format: Optional[bool] = None
    stt_diarize: Optional[bool] = None
    stt_filter_filler_words: Optional[bool] = None
    analysis_provider: Optional[str] = None
    # GAP-03: Webhook URL for post-call event notifications
    webhook_url: Optional[str] = Field(None, max_length=500)
    # GAP-06: Optional team ownership for RBAC
    team_id: Optional[int] = Field(None, description="Team ID to assign this agent to")
    # GAP-07: Language for STT/TTS auto-configuration
    language: Optional[str] = Field(None, max_length=10)
    # ── Agent Mode & Flow (Retell AI 2.0) ─────────────────────────
    mode: Optional[str] = Field(None, max_length=20)
    graph_json: Optional[dict] = Field(None)
    workflow_id: Optional[int] = Field(
        None,
        description="Link or unlink the canonical conversational workflow.",
    )
    extraction_prompts: Optional[dict] = Field(None)
    transition_flexibility: Optional[str] = Field(None, max_length=10)
    handbook_enabled: Optional[bool] = Field(None)
    handbook_content: Optional[str] = Field(None, max_length=10000)
    template_id: Optional[str] = Field(None, max_length=50)
    # GAP-14: Link/unlink knowledge base for RAG
    knowledge_base_id: Optional[int] = Field(None, description="Knowledge base ID to link for document retrieval")
    google_drive_integration_id: Optional[int] = Field(
        None,
        description="Google Drive MCP integration ID to attach to this agent",
    )
    mcp_bindings: Optional[dict] = Field(
        None,
        description="MCP resource bindings: {drive: {file_ids:[], folder_ids:[]}, calendar: {calendar_ids:[]}}",
    )
    tool_instructions: Optional[str] = Field(None, max_length=5000)
    integration_overrides: Optional[dict] = Field(None)
    voicemail_message: Optional[str] = Field(None, max_length=2000)
    context_window: Optional[int] = Field(None, description="Ollama context window size (num_ctx). NULL = auto-detect.")


# Deepgram Aura voices (verified from https://developers.deepgram.com/docs/tts-rest)
DEEPGRAM_VOICES = [
    {"id": "aura-asteria-en", "name": "Asteria", "gender": "Female", "locale": "en-US", "style": "Conversational"},
    {"id": "aura-luna-en", "name": "Luna", "gender": "Female", "locale": "en-US", "style": "Conversational"},
    {"id": "aura-stella-en", "name": "Stella", "gender": "Female", "locale": "en-US", "style": "Conversational"},
    {"id": "aura-athena-en", "name": "Athena", "gender": "Female", "locale": "en-GB", "style": "Professional"},
    {"id": "aura-hera-en", "name": "Hera", "gender": "Female", "locale": "en-US", "style": "Professional"},
    {"id": "aura-orion-en", "name": "Orion", "gender": "Male", "locale": "en-US", "style": "Conversational"},
    {"id": "aura-arcas-en", "name": "Arcas", "gender": "Male", "locale": "en-US", "style": "Conversational"},
    {"id": "aura-perseus-en", "name": "Perseus", "gender": "Male", "locale": "en-US", "style": "Conversational"},
    {"id": "aura-angus-en", "name": "Angus", "gender": "Male", "locale": "en-IE", "style": "Warm"},
    {"id": "aura-orpheus-en", "name": "Orpheus", "gender": "Male", "locale": "en-US", "style": "Professional"},
    {"id": "aura-helios-en", "name": "Helios", "gender": "Male", "locale": "en-GB", "style": "Professional"},
    {"id": "aura-zeus-en", "name": "Zeus", "gender": "Male", "locale": "en-US", "style": "Authoritative"},
]

DEEPGRAM_VOICE_IDS = {v["id"] for v in DEEPGRAM_VOICES}


# ── Valid Provider Values ──────────────────────────────────────────────
# These lists define what the frontend can select from.
VALID_LLM_PROVIDERS = ["openrouter", "groq", "openai", "gemini", "anthropic", "commandcode", "ollama"]
VALID_STT_PROVIDERS = ["deepgram", "google", "azure", "assemblyai"]
VALID_TTS_PROVIDERS = ["deepgram", "gtts", "elevenlabs", "azure", "cartesia", "polly", "stream_elements"]
VALID_AGENT_MODES = ["single_prompt", "conversational_flow"]
VALID_TRANSITION_FLEX = ["strict", "flex"]
VALID_INTERRUPT_SENSITIVITY = {"low", "high"}
VALID_ENDPOINTING_TYPES = {"auto", "punctuation", "time"}

# Models known to be supported by each provider. Used only for validation
# of explicit user-provided values; provider defaults are still allowed.
VALID_LLM_MODELS: dict[str, set[str]] = {
    "openrouter": {
        "deepseek/deepseek-v4-flash",
    },
    "groq": {
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "qwen/qwen3-32b",
    },
    "openai": {
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
        "gpt-3.5-turbo-1106",
        "gpt-4o-2024-08-06",
        "gpt-4o-mini-2024-07-18",
    },
    "gemini": {
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash-exp",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    },
    "anthropic": {
        "claude-3-haiku-20240307",
        "claude-3-sonnet-20240229",
        "claude-3-5-sonnet-20241022",
        "claude-3-opus-20240229",
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
    },
    "commandcode": {
        "deepseek/deepseek-v4-pro",
    },
    "ollama": {
        "qwen3:8b", "qwen3", "qwen3:32b", "qwen3:4b",
        "gemma4:e4b", "llama3.3", "llama3.3:70b", "gemma3:4b",
    },
}

VALID_STT_MODELS: dict[str, set[str]] = {
    "deepgram": {
        "nova-3",
        "nova-3-phonecall",
        "nova-3-conversationalai",
        "nova-2-phonecall",
        "nova-2",
        "nova-2-meeting",
        "nova-2-conversationalai",
        "nova-1",
        "enhanced",
        "base",
    },
}


# ── Routes ─────────────────────────────────────────────────────────────

@router.get("/voices")
async def list_deepgram_voices():
    """
    Return available Deepgram Aura TTS voices.

    Deepgram Aura provides 12 high-quality neural voices across US, UK, and
    Irish English accents. All voices use the same Deepgram API key as STT.

    Returns:
        List of voice objects with id, name, gender, locale, and style.
    """
    return {"voices": DEEPGRAM_VOICES, "default": "aura-asteria-en"}


@router.get("/providers")
async def get_providers():
    """
    Return all available provider options for agent configuration.
    
    The frontend uses this to populate dropdown menus when creating
    or editing an agent. Each provider lists its supported models/voices.
    
    This endpoint is public (no auth required) so the frontend can
    show options before the user creates an agent.
    
    Returns:
        Dictionary with llm_providers, stt_providers, tts_providers
    """
    return {
        "llm_providers": [
            {
                "id": "openrouter",
                "name": "OpenRouter (DeepSeek V4 Flash)",
                "models": [
                    "deepseek/deepseek-v4-flash",
                ],
            },
            {
                "id": "groq",
                "name": "Groq (Fast Inference)",
                "models": [
                    "openai/gpt-oss-120b", "openai/gpt-oss-20b",
                    "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
                    "qwen/qwen3-32b",
                ],
            },
            {
                "id": "openai",
                "name": "OpenAI",
                "models": [
                    "gpt-4o-mini", "gpt-4o", "gpt-4-turbo",
                    "gpt-3.5-turbo", "gpt-3.5-turbo-1106",
                ],
            },
            {
                "id": "gemini",
                "name": "Google Gemini",
                "models": [
                    "gemini-2.0-flash", "gemini-2.0-flash-lite",
                    "gemini-1.5-pro", "gemini-1.5-flash",
                ],
            },
            {
                "id": "anthropic",
                "name": "Anthropic",
                "models": [
                    "claude-3-haiku-20240307",
                    "claude-3-sonnet-20240229",
                    "claude-3-5-sonnet-20241022",
                    "claude-3-opus-20240229",
                    "claude-sonnet-4-20250514",
                    "claude-opus-4-20250514",
                ],
            },
            {
                "id": "commandcode",
                "name": "CommandCode (Discounted Models)",
                "models": [
                    "deepseek/deepseek-v4-pro",
                ],
            },
            {
                "id": "ollama",
                "name": "Ollama (Local LLM)",
                "models": [
                    "qwen3:8b", "qwen3", "qwen3:32b", "qwen3:4b",
                    "gemma4:e4b", "llama3.3", "llama3.3:70b", "gemma3:4b",
                ],
            },
        ],
        "stt_providers": [
            {
                "id": "deepgram",
                "name": "Deepgram",
                "languages": ["en-US", "en-GB", "ur", "hi", "multi"],
            },
            {
                "id": "google",
                "name": "Google Cloud Speech",
                "languages": ["en-US", "ur-PK", "hi-IN"],
            },
            {
                "id": "azure",
                "name": "Azure Speech",
                "languages": ["en-US", "ur-PK", "hi-IN"],
            },
            {
                "id": "assemblyai",
                "name": "AssemblyAI",
                "languages": ["en"],
            },
        ],
        "tts_providers": [
            {
                "id": "deepgram",
                "name": "Deepgram Aura",
                "voices": [
                    {"id": "aura-asteria-en", "name": "Asteria (Female, US)"},
                    {"id": "aura-luna-en", "name": "Luna (Female, US)"},
                    {"id": "aura-stella-en", "name": "Stella (Female, US)"},
                    {"id": "aura-athena-en", "name": "Athena (Female, UK)"},
                    {"id": "aura-hera-en", "name": "Hera (Female, US)"},
                    {"id": "aura-orion-en", "name": "Orion (Male, US)"},
                    {"id": "aura-arcas-en", "name": "Arcas (Male, US)"},
                    {"id": "aura-perseus-en", "name": "Perseus (Male, US)"},
                    {"id": "aura-angus-en", "name": "Angus (Male, Irish)"},
                    {"id": "aura-orpheus-en", "name": "Orpheus (Male, US)"},
                    {"id": "aura-helios-en", "name": "Helios (Male, UK)"},
                    {"id": "aura-zeus-en", "name": "Zeus (Male, US)"},
                ],
                "note": "Fast, neural voices. Uses same API key as Deepgram STT.",
            },
            {
                "id": "gtts",
                "name": "Google TTS (Free)",
                "voices": [],
                "note": "Free, basic quality. Good for development.",
            },
            {
                "id": "elevenlabs",
                "name": "ElevenLabs",
                "voices": [
                    {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam"},
                    {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"},
                ],
                "note": "High quality, natural voices. Free tier available.",
            },
            {
                "id": "azure",
                "name": "Azure Neural TTS",
                "voices": [
                    {"id": "en-US-AriaNeural", "name": "Aria (Female)"},
                    {"id": "en-US-SteffanNeural", "name": "Steffan (Male)"},
                    {"id": "ur-PK-AsadNeural", "name": "Asad (Urdu Male)"},
                    {"id": "ur-PK-UzmaNeural", "name": "Uzma (Urdu Female)"},
                ],
                "note": "Very natural, supports Urdu.",
            },
            {
                "id": "cartesia",
                "name": "Cartesia",
                "voices": [],
                "note": "Ultra-low latency.",
            },
            {
                "id": "polly",
                "name": "AWS Polly",
                "voices": [
                    {"id": "Matthew", "name": "Matthew (Male)"},
                    {"id": "Joanna", "name": "Joanna (Female)"},
                ],
            },
            {
                "id": "stream_elements",
                "name": "StreamElements (Free)",
                "voices": [],
                "note": "Free, decent quality. No API key required.",
            },
        ],
    }


@router.get("")
async def list_agents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    team_id: Optional[int] = None,
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
):
    """
    List all voice agents belonging to the current user or team.

    GAP-06: When team_id is provided and the user is a team member,
    returns all agents owned by that team. Otherwise returns only
    the user's personal agents.
    """
    from sqlalchemy import func

    from voice_platform.rbac import get_team_membership

    offset = (page - 1) * per_page

    if team_id:
        membership = await get_team_membership(user.id, team_id)
        if membership:
            # Count total for pagination
            count_result = await db.execute(
                select(func.count(Agent.id)).where(
                    Agent.team_id == team_id, Agent.is_active == True
                )
            )
            total = count_result.scalar() or 0

            result = await db.execute(
                select(Agent)
                .where(Agent.team_id == team_id, Agent.is_active == True)
                .order_by(Agent.created_at.desc())
                .offset(offset)
                .limit(per_page)
            )
            agents = result.scalars().all()
            return {
                "agents": [agent.to_dict() for agent in agents],
                "total": total,
                "page": page,
                "per_page": per_page,
            }

    # Fallback: personal agents only (exclude soft-deleted)
    count_result = await db.execute(
        select(func.count(Agent.id)).where(
            Agent.user_id == user.id, Agent.is_active == True
        )
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(Agent)
        .where(Agent.user_id == user.id, Agent.is_active == True)
        .order_by(Agent.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    agents = result.scalars().all()
    return {
        "agents": [agent.to_dict() for agent in agents],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    request: CreateAgentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new voice agent with custom provider configuration.
    
    The frontend sends the desired LLM/STT/TTS provider, model,
    and optionally a custom API key. If no API key is provided,
    the platform's default key (from .env) will be used at call time.
    
    Validation:
        - Provider values must be from the valid lists
        - Temperature must be 0.0-2.0
        - Max tokens must be 50-4096
    
    Args:
        request: Agent configuration from frontend
        user: Authenticated user
        db: Database session
        
    Returns:
        Created agent object (HTTP 201)
    """
    # Validate provider values against allowed lists
    if request.llm_provider not in VALID_LLM_PROVIDERS:
        raise ValidationError(
            field="llm_provider",
            message=f"Invalid LLM provider. Must be one of: {', '.join(VALID_LLM_PROVIDERS)}",
            suggestion="Choose a supported provider from the dropdown.",
        )
    if request.stt_provider not in VALID_STT_PROVIDERS:
        raise ValidationError(
            field="stt_provider",
            message=f"Invalid STT provider. Must be one of: {', '.join(VALID_STT_PROVIDERS)}",
            suggestion="Choose a supported STT provider from the dropdown.",
        )
    if request.tts_provider not in VALID_TTS_PROVIDERS:
        raise ValidationError(
            field="tts_provider",
            message=f"Invalid TTS provider. Must be one of: {', '.join(VALID_TTS_PROVIDERS)}",
            suggestion="Choose a supported TTS provider from the dropdown.",
        )

    # Validate agent mode
    mode = request.mode or "single_prompt"
    if mode not in VALID_AGENT_MODES:
        raise ValidationError(
            field="mode",
            message=f"Invalid agent mode. Must be one of: {', '.join(VALID_AGENT_MODES)}",
            suggestion="Choose 'single_prompt' for simple Q&A or 'conversational_flow' for graph-based routing.",
        )

    # Validate team ownership if provided
    await _validate_team_ownership(db, cast(int, user.id), getattr(request, "team_id", None))

    # Validate transition flexibility only when it matters
    if mode == "conversational_flow":
        flex = request.transition_flexibility or "flex"
        if flex not in VALID_TRANSITION_FLEX:
            raise ValidationError(
                field="transition_flexibility",
                message=f"Invalid transition flexibility. Must be one of: {', '.join(VALID_TRANSITION_FLEX)}",
                suggestion="Choose 'strict' for rigid graph routing or 'flex' for LLM-guided transitions.",
            )

    # Validate graph when mode is conversational_flow
    # Accept either graph_json or workflow_id as the graph source
    linked_workflow: Workflow | None = None
    graph_data = request.graph_json
    if mode == "conversational_flow":
        if not graph_data and request.workflow_id:
            wf_result = await db.execute(
                select(Workflow).where(
                    Workflow.id == request.workflow_id,
                    Workflow.user_id == user.id,
                )
            )
            linked_workflow = wf_result.scalar_one_or_none()
            if linked_workflow is None:
                raise ValidationError(
                    field="workflow_id",
                    message=f"Workflow {request.workflow_id} not found.",
                    suggestion="Ensure the workflow ID belongs to your account.",
                )
            if linked_workflow.agent_id is not None:
                raise ValidationError(
                    field="workflow_id",
                    message=f"Workflow {request.workflow_id} is already assigned to another agent.",
                    suggestion="Unassign the workflow before linking it to a new agent.",
                )
            if linked_workflow.graph_json:
                graph_data = json.loads(linked_workflow.graph_json)
        if not graph_data:
            raise ValidationError(
                field="graph_json",
                message="Conversational flow mode requires a graph_json or a valid workflow_id.",
                suggestion="Design your flow in the Workflows editor and save it before switching to conversational_flow mode.",
            )
        nodes = graph_data.get("nodes")
        edges = graph_data.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValidationError(
                field="graph_json",
                message="graph_json must contain 'nodes' and 'edges' arrays.",
                suggestion="Ensure your graph was exported from the ReactFlow editor.",
            )
        has_trigger = any(
            str((n.get("data") or {}).get("nodeType") or n.get("type")) == "trigger"
            for n in nodes
            if isinstance(n, dict)
        )
        if not has_trigger:
            raise ValidationError(
                field="graph_json",
                message="graph_json must contain at least one trigger (start) node.",
                suggestion="Add a trigger node to your flow — it defines where execution begins.",
            )
        # M-5: Warn about multiple trigger nodes — only the first will be used as entry point
        trigger_count = sum(
            1 for n in nodes
            if isinstance(n, dict) and str((n.get("data") or {}).get("nodeType") or n.get("type")) == "trigger"
        )
        if trigger_count > 1:
            logger.warning(
                f"Agent graph has {trigger_count} trigger nodes — only the first will be used as entry point"
            )
        branch_violations = required_input_branch_violations(graph_data)
        if branch_violations:
            node_id = branch_violations[0]["node_id"]
            raise ValidationError(
                field="graph_json",
                message=f"Action node '{node_id}' is missing its required on_missing recovery edge.",
                suggestion="Add a Missing info edge in the workflow editor before publishing.",
            )

    if request.google_drive_integration_id is not None:
        await _validate_google_drive_integration(
            db,
            cast(int, user.id),
            request.google_drive_integration_id,
        )

    # Validate per-agent integration overrides
    if request.integration_overrides:
        await _validate_integration_overrides(
            db, cast(int, user.id), request.integration_overrides
        )

    # Validate provider-specific field values
    _validate_agent_config_values(request.model_dump())

    # Create the agent record
    agent = Agent(
        user_id=user.id,              # Link to current user
        name=request.name,
        prompt_preamble=request.prompt_preamble,
        initial_message=request.initial_message,
        llm_provider=request.llm_provider,
        llm_model=request.llm_model,
        llm_api_key=request.llm_api_key,
        stt_provider=request.stt_provider,
        stt_language=request.stt_language,
        stt_api_key=request.stt_api_key,
        tts_provider=request.tts_provider,
        tts_voice_id=request.tts_voice_id,
        tts_api_key=request.tts_api_key,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        end_on_goodbye=request.end_on_goodbye,
        interrupt_sensitivity=request.interrupt_sensitivity,
        allowed_idle_time_seconds=request.allowed_idle_time_seconds,
        num_check_human_present_times=request.num_check_human_present_times,
        initial_message_delay=request.initial_message_delay,
        stt_model=request.stt_model,
        endpointing_type=request.endpointing_type,
        filler_audio_enabled=request.filler_audio_enabled,
        min_interrupt_confidence=request.min_interrupt_confidence,
        stt_smart_format=request.stt_smart_format,
        stt_diarize=request.stt_diarize,
        stt_filter_filler_words=request.stt_filter_filler_words,
        analysis_provider=request.analysis_provider,
        webhook_url=request.webhook_url,
        # GAP-06: optional team ownership
        team_id=getattr(request, "team_id", None),
        # GAP-07: language override
        language=getattr(request, "language", "en-US") or "en-US",
        # Retell AI 2.0: agent mode & flow
        mode=getattr(request, "mode", "single_prompt") or "single_prompt",
        graph_json=json.dumps(graph_data) if graph_data else None,
        workflow_id=request.workflow_id,
        extraction_prompts=json.dumps(request.extraction_prompts) if request.extraction_prompts else None,
        transition_flexibility=getattr(request, "transition_flexibility", "flex") or "flex",
        handbook_enabled=getattr(request, "handbook_enabled", False),
        handbook_content=request.handbook_content,
        template_id=request.template_id,
        knowledge_base_id=request.knowledge_base_id,
        google_drive_integration_id=request.google_drive_integration_id,
        tool_instructions=request.tool_instructions,
        integration_overrides_json=json.dumps(request.integration_overrides) if request.integration_overrides else None,
        mcp_bindings_json=json.dumps(request.mcp_bindings) if request.mcp_bindings else None,
        context_window=request.context_window,
    )

    db.add(agent)
    await db.flush()

    if linked_workflow is not None:
        linked_workflow.agent_id = agent.id

    # Create initial prompt version so A/B history starts from the original prompt
    initial_version = PromptVersion(
        agent_id=agent.id,
        version=1,
        prompt_preamble=agent.prompt_preamble,
        is_active=True,
        created_by=user.id,
    )
    db.add(initial_version)
    await db.flush()

    if agent.knowledge_base_id is not None:
        await _sync_agent_knowledge_base_link(
            db,
            cast(int, user.id),
            cast(int, agent.id),
            None,
            cast(Optional[int], agent.knowledge_base_id),
        )
    await db.commit()
    await db.refresh(agent)  # Reload to get auto-generated ID
    
    return {"agent": agent.to_dict()}


@router.get("/{agent_id}")
async def get_agent(
    agent_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get details of a specific agent.
    
    Only returns the agent if it belongs to the current user.
    
    Args:
        agent_id: Database ID of the agent
        user: Authenticated user
        db: Database session
        
    Returns:
        Agent object
        
    Raises:
        404: If agent not found or doesn't belong to user
    """
    # Query by ID first, then verify ownership or team membership
    from voice_platform.rbac import get_team_membership

    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    
    if agent is None:
        raise AgentNotFoundError(agent_id)

    # BUG-04: Allow access if user owns the agent OR is a member of the agent's team
    if agent.user_id != user.id:
        if not agent.team_id or not await get_team_membership(user.id, agent.team_id):
            raise AgentNotFoundError(agent_id)
    
    return {"agent": agent.to_dict()}


@router.put("/{agent_id}")
async def update_agent(
    agent_id: int,
    request: UpdateAgentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update an existing agent's configuration.
    
    Only updates fields that are provided in the request.
    Validates ownership — user can only update their own agents.
    
    Args:
        agent_id: Database ID of the agent to update
        request: Fields to update (only non-None fields are applied)
        user: Authenticated user
        db: Database session
        
    Returns:
        Updated agent object
    """
    # Find the agent (with ownership or team membership check)
    from voice_platform.rbac import get_team_membership

    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    
    if agent is None:
        raise AgentNotFoundError(agent_id)

    # BUG-04: Allow update if user owns the agent OR is a member of the agent's team
    if agent.user_id != user.id:
        if not agent.team_id or not await get_team_membership(user.id, agent.team_id):
            raise AgentNotFoundError(agent_id)
    
    # Get all non-None fields from the request
    # model_dump(exclude_unset=True) only includes fields the client actually sent
    update_data = request.model_dump(exclude_unset=True)

    # Masked API-key values returned by Agent.to_dict() mean "leave unchanged".
    # Never persist the response sentinel as a real provider credential.
    for key_field in ("llm_api_key", "stt_api_key", "tts_api_key"):
        if update_data.get(key_field) == "***":
            del update_data[key_field]

    requested_workflow: Workflow | None = None
    if "workflow_id" in update_data and update_data["workflow_id"] is not None:
        workflow_result = await db.execute(
            select(Workflow).where(
                Workflow.id == update_data["workflow_id"],
                Workflow.user_id == user.id,
                Workflow.is_active == True,
            )
        )
        requested_workflow = workflow_result.scalar_one_or_none()
        if requested_workflow is None or not requested_workflow.graph_json:
            raise ValidationError(
                field="workflow_id",
                message=f"Active workflow {update_data['workflow_id']} with a graph was not found.",
                suggestion="Choose an active workflow that belongs to your account.",
            )
        if (
            requested_workflow.agent_id is not None
            and requested_workflow.agent_id != agent.id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That workflow is already published to another agent.",
            )

    # A linked Workflow owns the graph. Agent updates may echo the same graph
    # back, but must never replace the canonical revision.
    if "graph_json" in update_data and agent.workflow_id is not None:
        requested_workflow_id = update_data.get("workflow_id", agent.workflow_id)
        incoming_graph = update_data["graph_json"]
        if requested_workflow_id == agent.workflow_id:
            if canonical_content_hash(incoming_graph) != canonical_content_hash(agent.graph):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "This agent's graph is owned by its linked workflow. "
                        "Edit and publish the workflow instead."
                    ),
                )
            del update_data["graph_json"]
        elif requested_workflow_id is None:
            # Unlinking cannot silently fork the old canonical graph.
            del update_data["graph_json"]

    if "graph_json" in update_data and update_data["graph_json"]:
        branch_violations = required_input_branch_violations(update_data["graph_json"])
        if branch_violations:
            raise ValidationError(
                field="graph_json",
                message=(
                    f"Action node '{branch_violations[0]['node_id']}' is missing "
                    "its required on_missing recovery edge."
                ),
                suggestion="Add a Missing info edge in the workflow editor before publishing.",
            )

    # Validate provider values if they're being updated
    if "llm_provider" in update_data and update_data["llm_provider"] not in VALID_LLM_PROVIDERS:
        raise HTTPException(400, f"Invalid LLM provider. Must be one of: {VALID_LLM_PROVIDERS}")
    if "stt_provider" in update_data and update_data["stt_provider"] not in VALID_STT_PROVIDERS:
        raise HTTPException(400, f"Invalid STT provider. Must be one of: {VALID_STT_PROVIDERS}")
    if "tts_provider" in update_data and update_data["tts_provider"] not in VALID_TTS_PROVIDERS:
        raise HTTPException(400, f"Invalid TTS provider. Must be one of: {VALID_TTS_PROVIDERS}")

    # Validate mode if being updated
    if "mode" in update_data and update_data["mode"] not in VALID_AGENT_MODES:
        raise HTTPException(400, f"Invalid agent mode. Must be one of: {VALID_AGENT_MODES}")

    # Validate transition_flexibility if being updated
    if "transition_flexibility" in update_data and update_data["transition_flexibility"] not in VALID_TRANSITION_FLEX:
        raise HTTPException(400, f"Invalid transition flexibility. Must be one of: {VALID_TRANSITION_FLEX}")

    # Validate graph_json when switching to conversational_flow (not when already in that mode)
    if "mode" in update_data and update_data["mode"] == "conversational_flow" and agent.mode != "conversational_flow":
        graph = update_data.get("graph_json")
        # Accept workflow_id as alternative to graph_json
        if not graph and update_data.get("workflow_id"):
            wf_result = await db.execute(
                select(Workflow).where(
                    Workflow.id == update_data["workflow_id"],
                    Workflow.user_id == user.id,
                )
            )
            wf = wf_result.scalar_one_or_none()
            if wf is None:
                raise HTTPException(400, f"Workflow {update_data['workflow_id']} not found.")
            if wf.graph_json:
                graph = json.loads(wf.graph_json)
        if not graph:
            graph = agent.graph
        if not graph or not isinstance(graph, dict):
            raise HTTPException(400, "Conversational flow mode requires a valid graph_json or workflow_id.")
        if not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
            raise HTTPException(400, "graph_json must contain 'nodes' and 'edges' arrays.")
        has_trigger = any(
            str((n.get("data") or {}).get("nodeType") or n.get("type")) == "trigger"
            for n in graph.get("nodes", [])
            if isinstance(n, dict)
        )
        if not has_trigger:
            raise HTTPException(400, "graph_json must contain at least one trigger (start) node.")
        # M-5: Warn about multiple trigger nodes
        trigger_count = sum(
            1 for n in graph.get("nodes", [])
            if isinstance(n, dict) and str((n.get("data") or {}).get("nodeType") or n.get("type")) == "trigger"
        )
        if trigger_count > 1:
            logger.warning(
                f"Agent graph has {trigger_count} trigger nodes — only the first will be used as entry point"
            )

    # Validate team ownership if changing team
    if "team_id" in update_data:
        await _validate_team_ownership(db, cast(int, user.id), update_data["team_id"])

    # Validate provider-specific values against the merged effective configuration
    agent_base = {
        "llm_provider": agent.llm_provider,
        "llm_model": agent.llm_model,
        "stt_provider": agent.stt_provider,
        "stt_model": agent.stt_model,
        "tts_provider": agent.tts_provider,
        "tts_voice_id": agent.tts_voice_id,
        "interrupt_sensitivity": agent.interrupt_sensitivity,
        "endpointing_type": agent.endpointing_type,
        "language": agent.language,
    }
    _validate_agent_config_values({**agent_base, **update_data})

    previous_kb_id = cast(Optional[int], agent.knowledge_base_id)
    
    # GAP-08: Auto-versioning when prompt_preamble changes
    if "prompt_preamble" in update_data and update_data["prompt_preamble"] != agent.prompt_preamble:
        # Get next version number
        latest_result = await db.execute(
            select(PromptVersion)
            .where(PromptVersion.agent_id == agent_id)
            .order_by(PromptVersion.version.desc())
            .limit(1)
        )
        latest = latest_result.scalar_one_or_none()
        next_version = (latest.version + 1) if latest else 1

        # Archive the current prompt as a version
        old_version = PromptVersion(
            agent_id=agent_id,
            version=next_version,
            prompt_preamble=agent.prompt_preamble,
            is_active=False,
            created_by=user.id,
        )
        db.add(old_version)
        await db.flush()  # Get old_version.id before creating new version

        # Update agent to new prompt
        agent.prompt_preamble = update_data["prompt_preamble"]

    if "google_drive_integration_id" in update_data:
        await _validate_google_drive_integration(
            db,
            cast(int, user.id),
            cast(Optional[int], update_data["google_drive_integration_id"]),
        )

    # Handle mcp_bindings dict → JSON string conversion
    if "mcp_bindings" in update_data:
        bindings = update_data.pop("mcp_bindings")
        agent.mcp_bindings_json = json.dumps(bindings) if bindings else None

    # Validate and handle integration_overrides dict → JSON string conversion
    if "integration_overrides" in update_data:
        overrides = update_data["integration_overrides"]
        if overrides:
            await _validate_integration_overrides(
                db, cast(int, user.id), overrides
            )
        agent.integration_overrides_json = json.dumps(overrides) if overrides else None
        del update_data["integration_overrides"]

    if "workflow_id" in update_data:
        desired_workflow_id = update_data.pop("workflow_id")
        previous_workflow_id = agent.workflow_id

        if previous_workflow_id is not None and previous_workflow_id != desired_workflow_id:
            previous_workflow = await db.get(Workflow, previous_workflow_id)
            if previous_workflow is not None and previous_workflow.agent_id == agent.id:
                previous_workflow.agent_id = None

        if desired_workflow_id is not None:
            if requested_workflow is None:
                raise ValidationError(
                    field="workflow_id",
                    message=f"Workflow {desired_workflow_id} could not be linked.",
                )
            requested_workflow.agent_id = agent.id
            agent.workflow_id = desired_workflow_id
            agent.graph_json = requested_workflow.graph_json
            agent.mode = "conversational_flow"
            agent.transition_flexibility = (
                requested_workflow.transition_flexibility or "flex"
            )
            update_data.pop("graph_json", None)
        else:
            agent.workflow_id = None
            agent.graph_json = None
            update_data.pop("graph_json", None)
            if "mode" not in update_data:
                agent.mode = "single_prompt"

    # Handle graph_json dict → JSON string conversion (same as mcp_bindings)
    if "graph_json" in update_data:
        graph = update_data["graph_json"]
        agent.graph_json = json.dumps(graph) if graph else None
        del update_data["graph_json"]

    # Handle extraction_prompts dict → JSON string conversion
    if "extraction_prompts" in update_data:
        prompts = update_data["extraction_prompts"]
        agent.extraction_prompts = json.dumps(prompts) if prompts else None
        del update_data["extraction_prompts"]

    # Apply each update to the agent model only for known ORM columns.
    # Fields that need remapping (graph_json, mcp_bindings, integration_overrides)
    # are handled above before this loop.
    allowed_fields = {
        "name",
        "prompt_preamble",
        "initial_message",
        "llm_provider",
        "llm_model",
        "llm_api_key",
        "stt_provider",
        "stt_language",
        "stt_api_key",
        "tts_provider",
        "tts_voice_id",
        "tts_api_key",
        "temperature",
        "max_tokens",
        "end_on_goodbye",
        "interrupt_sensitivity",
        "is_active",
        "allowed_idle_time_seconds",
        "num_check_human_present_times",
        "initial_message_delay",
        "stt_model",
        "endpointing_type",
        "filler_audio_enabled",
        "min_interrupt_confidence",
        "stt_smart_format",
        "stt_diarize",
        "stt_filter_filler_words",
        "analysis_provider",
        "webhook_url",
        "team_id",
        "language",
        "mode",
        "graph_json",
        "transition_flexibility",
        "handbook_enabled",
        "handbook_content",
        "template_id",
        "knowledge_base_id",
        "google_drive_integration_id",
        "tool_instructions",
        "voicemail_message",
        "outbound_ready",
        "inbound_ready",
        "context_window",
    }
    for field, value in update_data.items():
        if field in allowed_fields:
            setattr(agent, field, value)

    if "knowledge_base_id" in update_data:
        await _sync_agent_knowledge_base_link(
            db,
            cast(int, user.id),
            cast(int, agent.id),
            previous_kb_id,
            cast(Optional[int], agent.knowledge_base_id),
        )

    await db.commit()
    await db.refresh(agent)

    return {"agent": agent.to_dict()}


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Deactivate a voice agent (soft delete).
    
    Sets is_active=False rather than deleting the record.
    This preserves call history that references this agent.
    
    Args:
        agent_id: Database ID of the agent to deactivate
        user: Authenticated user
        db: Database session
        
    Returns:
        Confirmation message
    """
    # Find the agent (with ownership or team membership check)
    from voice_platform.rbac import get_team_membership

    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()
    
    if agent is None:
        raise AgentNotFoundError(agent_id)

    # BUG-04: Allow delete if user owns the agent OR is a member of the agent's team
    if agent.user_id != user.id:
        if not agent.team_id or not await get_team_membership(user.id, agent.team_id):
            raise AgentNotFoundError(agent_id)
    
    # AGT-02: Block delete if phone numbers are mapped to this agent
    from voice_platform.database import PhoneNumberMapping
    mapping_result = await db.execute(
        select(PhoneNumberMapping).where(
            PhoneNumberMapping.agent_id == agent_id,
            PhoneNumberMapping.is_active == True,
        )
    )
    active_mappings = mapping_result.scalars().all()
    if active_mappings:
        numbers: list[str] = [str(m.phone_number) for m in active_mappings]  # type: ignore[arg-type]
        raise AlreadyExistsError(
            resource="Phone mapping",
            identifier=", ".join(numbers),  # type: ignore[arg-type]
            message=f"Cannot deactivate: agent is assigned to phone numbers {', '.join(numbers)}.",  # type: ignore[arg-type]
            suggestion="Reassign or delete the phone number mappings first.",
        )

    # Soft delete — mark as inactive instead of deleting
    previous_kb_id = cast(Optional[int], agent.knowledge_base_id)
    if previous_kb_id is not None:
        agent.knowledge_base_id = None  # type: ignore[assignment]
        await _sync_agent_knowledge_base_link(
            db,
            cast(int, user.id),
            cast(int, agent.id),
            previous_kb_id,
            None,
        )
    agent.is_active = False  # type: ignore[assignment]
    await db.commit()
    
    return {"message": f"Agent '{agent.name}' deactivated successfully"}


# ── Agent Templates ───────────────────────────────────────────────────

class CreateFromTemplateRequest(BaseModel):
    """Schema for creating an agent from a pre-built template."""
    template_id: str = Field(..., description="Template ID (e.g. 'support', 'sales')")
    name: Optional[str] = Field(None, description="Override agent name (default: template name)")
    custom_prompt: Optional[str] = Field(None, description="Override system prompt")
    custom_initial_message: Optional[str] = Field(None, description="Override initial message")
    llm_provider: Optional[str] = Field(None, description="Override LLM provider")
    tts_voice_id: Optional[str] = Field(None, description="Override voice")
    team_id: Optional[int] = Field(None, description="Assign to team")
    tools_config: Optional[list[str]] = Field(None, description="Override enabled tools (default: template recommended_tools)")
    knowledge_base_id: Optional[int] = Field(None, description="Knowledge base ID to link for document retrieval")
    google_drive_integration_id: Optional[int] = Field(
        None,
        description="Google Drive MCP integration ID to attach to this agent",
    )
    mcp_bindings: Optional[dict] = Field(
        None,
        description="MCP resource bindings: {drive: {file_ids:[], folder_ids:[]}, calendar: {calendar_ids:[]}}",
    )
    integration_overrides: Optional[dict] = Field(
        None,
        description="Per-agent integration overrides: {google_sheets: 123, google_calendar: 456}",
    )


@router.get("/templates")
async def list_templates(
    category: Optional[str] = None,
    mode: Optional[str] = None,
    outbound: Optional[bool] = None,
):
    """
    List all available agent templates.

    Filters:
        category — support, sales, healthcare, hospitality, ecommerce, realestate, general
        mode — single_prompt or conversational_flow
        outbound — true for outbound-ready templates only

    Returns full template metadata including demo scripts and feature lists.
    """
    from voice_platform.agent_templates import list_templates as _list_templates
    from voice_platform.agent_templates import to_dict

    templates = _list_templates(category=category, mode=mode, outbound=outbound)
    return {"templates": [to_dict(t) for t in templates], "count": len(templates)}


@router.get("/templates/{template_id}")
async def get_template(template_id: str):
    """Get a single template by ID with full config."""
    from voice_platform.agent_templates import get_template, to_dict

    t = get_template(template_id)
    if not t:
        raise NotFoundError(resource="Template", resource_id=template_id)
    return {"template": to_dict(t)}


@router.post("/from-template", status_code=status.HTTP_201_CREATED)
async def create_from_template(
    request: CreateFromTemplateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new agent from a pre-built template.

    The template provides default config (prompt, voice, model, etc.).
    You can override any field. If no overrides are provided, the agent
    is created exactly as the template specifies.

    Returns the created agent with its full config.
    """
    from voice_platform.agent_templates import get_template

    template = get_template(request.template_id)
    if not template:
        raise NotFoundError(resource="Template", resource_id=request.template_id)

    # Dedup guard: if an active agent with the same template_id already exists
    # for this user, return it instead of creating a duplicate
    if request.template_id:
        existing = await db.execute(
            select(Agent).where(
                Agent.user_id == user.id,
                Agent.template_id == request.template_id,
                Agent.is_active == True,
            )
        )
        existing_agent = existing.scalar_one_or_none()
        if existing_agent:
            logger.info(
                f"Reusing existing agent from template: user={user.id}, "
                f"template={template.id}, agent={existing_agent.id}, name={existing_agent.name}"
            )
            return {"agent": existing_agent.to_dict(), "template_id": template.id}

    config = dict(template.config)

    # Apply overrides
    if request.name:
        config["name"] = request.name
    if request.custom_prompt:
        config["prompt_preamble"] = request.custom_prompt
    if request.custom_initial_message:
        config["initial_message"] = request.custom_initial_message
    if request.llm_provider:
        config["llm_provider"] = request.llm_provider
    if request.tts_voice_id:
        config["tts_voice_id"] = request.tts_voice_id
    if request.team_id:
        config["team_id"] = request.team_id
    if request.tools_config is not None:
        config["tools_config"] = request.tools_config
    elif template.recommended_tools:
        config["tools_config"] = template.recommended_tools
    if request.mcp_bindings is not None:
        config["mcp_bindings"] = request.mcp_bindings
    if request.integration_overrides is not None:
        config["integration_overrides"] = request.integration_overrides

    # Validate team ownership if provided
    await _validate_team_ownership(db, cast(int, user.id), request.team_id)

    if request.google_drive_integration_id is not None:
        await _validate_google_drive_integration(
            db,
            cast(int, user.id),
            request.google_drive_integration_id,
        )

    if request.integration_overrides:
        await _validate_integration_overrides(
            db, cast(int, user.id), request.integration_overrides
        )

    # Validate provider
    llm_provider = config.get("llm_provider", "openrouter")
    if llm_provider not in VALID_LLM_PROVIDERS:
        raise ValidationError(
            field="llm_provider",
            message=f"Invalid LLM provider: {llm_provider}",
            suggestion=f"Choose from: {', '.join(VALID_LLM_PROVIDERS)}",
        )

    # Validate provider-specific values derived from the merged config
    _validate_agent_config_values(config)

    # Build agent record
    tools_cfg = config.get("tools_config")
    agent = Agent(
        user_id=user.id,
        name=config["name"],
        prompt_preamble=config["prompt_preamble"],
        initial_message=config.get("initial_message"),
        llm_provider=llm_provider,
        llm_model=config.get("llm_model", settings.default_llm_model or "openai/gpt-oss-120b"),
        stt_provider=config.get("stt_provider", "deepgram"),
        stt_language=config.get("stt_language", "en-US"),
        stt_model=config.get("stt_model", "nova-3"),
        tts_provider=config.get("tts_provider", "deepgram"),
        tts_voice_id=config.get("tts_voice_id", "aura-asteria-en"),
        temperature=config.get("temperature", 0.7),
        max_tokens=config.get("max_tokens", LLM_AGENT_DEFAULT_MAX_TOKENS),
        end_on_goodbye=config.get("end_on_goodbye", True),
        interrupt_sensitivity=config.get("interrupt_sensitivity", "low"),
        allowed_idle_time_seconds=config.get("allowed_idle_time_seconds", 60.0),
        num_check_human_present_times=config.get("num_check_human_present_times", 2),
        initial_message_delay=config.get("initial_message_delay", 0.4),
        endpointing_type=config.get("endpointing_type", "auto"),
        filler_audio_enabled=config.get("filler_audio_enabled", True),
        min_interrupt_confidence=config.get("min_interrupt_confidence", 0.6),
        stt_smart_format=config.get("stt_smart_format", True),
        stt_diarize=config.get("stt_diarize", True),
        stt_filter_filler_words=config.get("stt_filter_filler_words", False),
        analysis_provider=config.get("analysis_provider", "auto"),
        language=config.get("language", "en-US"),
        mode="single_prompt",  # Always start as single_prompt; workflow save switches to conversational_flow
        transition_flexibility=config.get("transition_flexibility", "flex"),
        template_id=template.id,
        team_id=getattr(request, "team_id", None),
        knowledge_base_id=request.knowledge_base_id,
        google_drive_integration_id=request.google_drive_integration_id,
        tools_config=json.dumps(tools_cfg) if tools_cfg else None,
        mcp_bindings_json=json.dumps(config.get("mcp_bindings")) if config.get("mcp_bindings") else None,
        integration_overrides_json=json.dumps(config.get("integration_overrides")) if config.get("integration_overrides") else None,
        voicemail_message=config.get("voicemail_message"),
    )

    db.add(agent)
    await db.flush()

    # Create initial prompt version so A/B history starts from the original prompt
    initial_version = PromptVersion(
        agent_id=agent.id,
        version=1,
        prompt_preamble=agent.prompt_preamble,
        is_active=True,
        created_by=user.id,
    )
    db.add(initial_version)
    await db.flush()

    if agent.knowledge_base_id is not None:
        await _sync_agent_knowledge_base_link(
            db,
            cast(int, user.id),
            cast(int, agent.id),
            None,
            cast(Optional[int], agent.knowledge_base_id),
        )
    await db.commit()
    await db.refresh(agent)

    logger.info(
        f"Agent created from template: user={user.id}, template={template.id}, "
        f"agent={agent.id}, name={agent.name}"
    )
    return {"agent": agent.to_dict(), "template_id": template.id}


# ── GAP-08: Prompt Versioning Routes ──────────────────────────────────

class ABTestRequest(BaseModel):
    """Schema for starting an A/B test between two prompt versions."""
    version_a_id: int
    version_b_id: int
    traffic_split: int = Field(50, ge=10, le=90, description="Percentage of traffic to version A")


@router.get("/{agent_id}/versions")
async def list_prompt_versions(
    agent_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all prompt versions for an agent, newest first."""
    from voice_platform.rbac import get_team_membership as _get_team_membership

    agent_result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise AgentNotFoundError(agent_id)
    if agent.user_id != user.id:
        if not agent.team_id or not await _get_team_membership(user.id, agent.team_id):
            raise AgentNotFoundError(agent_id)

    versions_result = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.agent_id == agent_id)
        .order_by(PromptVersion.version.desc())
    )
    versions = versions_result.scalars().all()

    return {
        "versions": [v.to_dict() for v in versions],
        "current_version_id": agent.current_prompt_version_id,
    }


@router.post("/{agent_id}/versions/{version_id}/rollback")
async def rollback_prompt_version(
    agent_id: int,
    version_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rollback to a specific prompt version."""
    from voice_platform.rbac import get_team_membership as _get_team_membership

    agent_result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")
    if agent.user_id != user.id:
        if not agent.team_id or not await _get_team_membership(user.id, agent.team_id):
            raise HTTPException(404, "Agent not found")

    version_result = await db.execute(
        select(PromptVersion).where(
            PromptVersion.id == version_id,
            PromptVersion.agent_id == agent_id,
        )
    )
    version = version_result.scalar_one_or_none()
    if not version:
        raise HTTPException(404, "Version not found")

    # Deactivate all versions for this agent
    await db.execute(
        update(PromptVersion)
        .where(PromptVersion.agent_id == agent_id)
        .values(is_active=False, traffic_percentage=0)
    )

    # Activate rolled-back version
    version.is_active = True  # type: ignore[assignment]
    version.traffic_percentage = 100  # type: ignore[assignment]
    agent.prompt_preamble = version.prompt_preamble
    agent.current_prompt_version_id = version.id
    await db.commit()

    logger.info(f"Rolled back agent {agent_id} to version {version.version}")
    return {
        "message": f"Rolled back to version {version.version}",
        "version": version.to_dict(),
        "agent": agent.to_dict(),
    }


@router.post("/{agent_id}/ab-test")
async def start_ab_test(
    agent_id: int,
    request: ABTestRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start an A/B test between two prompt versions."""
    from voice_platform.rbac import get_team_membership as _get_team_membership

    agent_result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")
    if agent.user_id != user.id:
        if not agent.team_id or not await _get_team_membership(user.id, agent.team_id):
            raise HTTPException(404, "Agent not found")

    # Verify both versions exist and belong to this agent
    for vid in (request.version_a_id, request.version_b_id):
        v_result = await db.execute(
            select(PromptVersion).where(
                PromptVersion.id == vid,
                PromptVersion.agent_id == agent_id,
            )
        )
        if not v_result.scalar_one_or_none():
            raise HTTPException(404, f"Version {vid} not found")

    # Deactivate all versions first
    await db.execute(
        update(PromptVersion)
        .where(PromptVersion.agent_id == agent_id)
        .values(is_active=False, traffic_percentage=0)
    )

    # Set traffic split
    split_a = request.traffic_split
    split_b = 100 - split_a

    await db.execute(
        update(PromptVersion)
        .where(PromptVersion.id == request.version_a_id)
        .values(is_active=True, traffic_percentage=split_a)
    )
    await db.execute(
        update(PromptVersion)
        .where(PromptVersion.id == request.version_b_id)
        .values(is_active=True, traffic_percentage=split_b)
    )

    await db.commit()

    logger.info(
        f"A/B test started for agent {agent_id}: "
        f"v{request.version_a_id}({split_a}%) vs v{request.version_b_id}({split_b}%)"
    )
    return {
        "message": "A/B test started",
        "split": {"a": split_a, "b": split_b},
        "version_a_id": request.version_a_id,
        "version_b_id": request.version_b_id,
    }
