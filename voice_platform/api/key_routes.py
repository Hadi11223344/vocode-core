"""
Voice Platform — API Key Management Routes
=============================================

CRUD endpoints for managing per-user API keys.

Users register their own API keys for services like OpenAI, Gemini,
Deepgram, ElevenLabs, Twilio, Google Calendar, and Google Sheets.
These keys are used at call-time to authenticate with the
respective service on behalf of the user.

Security:
    - Keys are never returned in full — only masked previews
    - All endpoints require authentication
    - Users can only access their own keys
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voice_platform.config import settings
from voice_platform.database import VALID_KEY_SERVICES, User, UserApiKey, get_db
from voice_platform.encryption import decrypt, encrypt
from voice_platform.middleware.auth_middleware import get_current_user

router = APIRouter(prefix="/api/keys", tags=["API Keys"])


# ── Request Schemas ────────────────────────────────────────────────────

class CreateApiKeyRequest(BaseModel):
    service: str = Field(..., description="Service name: openai, gemini, deepgram, elevenlabs, twilio, google_calendar, google_sheets")
    api_key: str = Field(..., min_length=1, max_length=500, description="The API key value")
    api_secret: Optional[str] = Field(None, max_length=500, description="Secondary secret (e.g. Twilio auth_token)")
    metadata_json: Optional[str] = Field(None, description="JSON metadata (e.g. Twilio phone_number, account_sid)")
    label: Optional[str] = Field(None, max_length=255, description="A display label for this key")


class UpdateApiKeyRequest(BaseModel):
    api_key: Optional[str] = Field(None, min_length=1, max_length=500)
    api_secret: Optional[str] = Field(None, max_length=500)
    metadata_json: Optional[str] = None
    label: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None


# ── Routes ─────────────────────────────────────────────────────────────

@router.get("/services")
async def list_available_services():
    """
    List all services that users can register API keys for.
    Returns service names grouped by category with descriptions.
    """
    return {
        "services": [
            {
                "id": "openrouter",
                "name": "OpenRouter",
                "category": "llm",
                "description": "Unified API for many models. Get your key at openrouter.ai",
                "required_fields": ["api_key"],
                "models": ["deepseek/deepseek-v4-flash"],
            },
            {
                "id": "openai",
                "name": "OpenAI",
                "category": "llm",
                "description": "GPT-4o, GPT-4o-mini, etc. Get your key at platform.openai.com",
                "required_fields": ["api_key"],
                "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
            },
            {
                "id": "gemini",
                "name": "Google Gemini",
                "category": "llm",
                "description": "Gemini 2.0 Flash, Pro, etc. Get your key at aistudio.google.com",
                "required_fields": ["api_key"],
                "models": ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-pro", "gemini-1.5-flash"],
            },
            {
                "id": "groq",
                "name": "Groq",
                "category": "llm",
                "description": "Ultra-fast inference. Free tier available at console.groq.com",
                "required_fields": ["api_key"],
                "models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3-32b"],
            },
            {
                "id": "anthropic",
                "name": "Anthropic",
                "category": "llm",
                "description": "Claude models. Get your key at console.anthropic.com",
                "required_fields": ["api_key"],
                "models": ["claude-3-haiku-20240307", "claude-3-sonnet-20240229", "claude-3-opus-20240229"],
            },
            {
                "id": "commandcode",
                "name": "CommandCode",
                "category": "llm",
                "description": "Discounted models (DeepSeek V4 Pro 4× usage). Get your key at commandcode.ai/studio/api-keys",
                "required_fields": ["api_key"],
                "models": ["deepseek/deepseek-v4-pro"],
            },
            {
                "id": "deepgram",
                "name": "Deepgram",
                "category": "stt/tts",
                "description": "Speech-to-text and text-to-speech. Get your key at deepgram.com",
                "required_fields": ["api_key"],
            },
            {
                "id": "elevenlabs",
                "name": "ElevenLabs",
                "category": "tts",
                "description": "Premium AI voices. Get your key at elevenlabs.io",
                "required_fields": ["api_key"],
            },
            {
                "id": "twilio",
                "name": "Twilio",
                "category": "telephony",
                "description": "Phone call infrastructure. Get credentials at twilio.com/console",
                "required_fields": ["api_key", "api_secret"],
                "metadata_fields": ["account_sid", "phone_number"],
            },
            {
                "id": "google_calendar",
                "name": "Google Calendar",
                "category": "integration",
                "description": "Create, read, update calendar events during calls",
                "required_fields": ["api_key"],
                "note": "Use a Google Cloud service account JSON key",
            },
            {
                "id": "google_sheets",
                "name": "Google Sheets",
                "category": "integration",
                "description": "Read and write spreadsheet data during calls",
                "required_fields": ["api_key"],
                "note": "Use a Google Cloud service account JSON key",
            },
            {
                "id": "mcp",
                "name": "MCP Server",
                "category": "integration",
                "description": (
                    "Model Context Protocol server. The agent can discover and call "
                    "tools from any MCP-compatible server dynamically."
                ),
                "required_fields": ["api_key", "server_url"],
                "note": "server_url is the MCP endpoint URL. api_key is the Bearer auth token (optional).",
            },
        ]
    }


@router.get("/platform-status")
async def get_platform_key_status():
    """
    Return which services have platform-level (.env) keys configured.
    Only returns booleans — never exposes actual key values.
    This lets the frontend show that the system is ready even without
    user-stored DB keys.
    """
    from voice_platform.config import settings

    return {
        "platform_keys": {
            "openrouter": bool(settings.openrouter_api_key),
            "openai": bool(settings.openai_api_key),
            "gemini": bool(settings.gemini_api_key),
            "groq": bool(settings.groq_api_key),
            "anthropic": False,  # no env var for this yet
            "commandcode": bool(settings.commandcode_api_key),
            "ollama": bool(settings.ollama_base_url),
            "deepgram": bool(settings.deepgram_api_key),
            "elevenlabs": bool(settings.elevenlabs_api_key),
            "azure": bool(settings.azure_speech_key),
            "cartesia": bool(settings.cartesia_api_key),
            "twilio": bool(settings.twilio_account_sid and settings.twilio_auth_token),
            "google_calendar": False,
            "google_sheets": False,
            "email": bool(settings.smtp_host and settings.smtp_password),
        },
        "twilio_phone_number": settings.twilio_phone_number or None,
        "default_llm_model": settings.default_llm_model,
    }


@router.get("")
async def list_user_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all API keys for the current user.
    Keys are always masked in responses.
    """
    result = await db.execute(
        select(UserApiKey)
        .where(UserApiKey.user_id == user.id)
        .order_by(UserApiKey.service)
    )
    keys = result.scalars().all()
    return {"keys": [k.to_dict() for k in keys]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_api_key(
    request: Request,
    body: CreateApiKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Register an API key for a specific service.
    Each user can have one key per service — updating replaces the old one.
    """
    if body.service not in VALID_KEY_SERVICES:
        raise HTTPException(400, f"Invalid service. Must be one of: {VALID_KEY_SERVICES}")
    
    # Validate Twilio requires api_secret
    if body.service == "twilio" and not body.api_secret:
        raise HTTPException(400, "Twilio requires both api_key (Account SID) and api_secret (Auth Token)")
    
    # Validate metadata_json if provided
    if body.metadata_json:
        try:
            json.loads(body.metadata_json)
        except json.JSONDecodeError:
            raise HTTPException(400, "metadata_json must be valid JSON")
    
    # Check if key already exists for this user+service
    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user.id,
            UserApiKey.service == body.service,
        )
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        # Update existing key
        existing.api_key = encrypt(body.api_key)  # type: ignore[assignment]
        existing.api_secret = encrypt(body.api_secret) if body.api_secret else None  # type: ignore[assignment]
        existing.metadata_json = body.metadata_json  # type: ignore[assignment]
        existing.label = body.label or existing.label  # type: ignore[assignment]
        existing.is_active = True  # type: ignore[assignment]
        await db.commit()
        await db.refresh(existing)
        return {"key": existing.to_dict(), "message": f"Updated {body.service} API key"}
    
    # Create new key
    key = UserApiKey(
        user_id=user.id,
        service=body.service,
        api_key=encrypt(body.api_key),
        api_secret=encrypt(body.api_secret) if body.api_secret else None,
        metadata_json=body.metadata_json,
        label=body.label,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return {"key": key.to_dict(), "message": f"Added {body.service} API key"}


@router.get("/{service}")
async def get_key_for_service(
    service: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the API key entry for a specific service (masked)."""
    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user.id,
            UserApiKey.service == service,
        )
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(404, f"No API key found for service '{service}'")
    return {"key": key.to_dict()}


@router.put("/{key_id}")
async def update_api_key(
    key_id: int,
    request: UpdateApiKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing API key."""
    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.id == key_id,
            UserApiKey.user_id == user.id,
        )
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(404, "API key not found")
    
    update_data = request.model_dump(exclude_unset=True)
    if "metadata_json" in update_data and update_data["metadata_json"]:
        try:
            json.loads(update_data["metadata_json"])
        except json.JSONDecodeError:
            raise HTTPException(400, "metadata_json must be valid JSON")
    
    # Encrypt sensitive fields before writing
    if "api_key" in update_data and update_data["api_key"]:
        update_data["api_key"] = encrypt(update_data["api_key"])
    if "api_secret" in update_data and update_data["api_secret"]:
        update_data["api_secret"] = encrypt(update_data["api_secret"])
    
    for field, value in update_data.items():
        setattr(key, field, value)
    
    await db.commit()
    await db.refresh(key)
    return {"key": key.to_dict(), "message": "API key updated"}


@router.delete("/{key_id}")
async def delete_api_key(
    key_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an API key."""
    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.id == key_id,
            UserApiKey.user_id == user.id,
        )
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(404, "API key not found")
    
    service = key.service
    await db.delete(key)
    await db.commit()
    return {"message": f"Deleted {service} API key"}


@router.get("/validate/{service}")
async def validate_key(
    service: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Quick validation check — does the user have an active key for this service?
    Does NOT verify the key against the external API (that happens at call time).
    """
    result = await db.execute(
        select(UserApiKey).where(
            UserApiKey.user_id == user.id,
            UserApiKey.service == service,
            UserApiKey.is_active == True,
        )
    )
    key = result.scalar_one_or_none()
    return {
        "service": service,
        "has_key": key is not None,
        "is_active": key.is_active if key else False,
    }
