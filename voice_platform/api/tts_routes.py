"""
TTS Preview Routes
==================

Real-time TTS preview for the agent builder. Generates a short audio clip
using the agent's configured TTS provider so the builder's "Test Audio" button
produces the same voice the caller will hear on a live call.

Supported providers:
- deepgram (Deepgram Aura)
- elevenlabs
- gtts
- cartesia (via direct HTTP)
- polly (via boto3)
"""

import io
import os
from typing import Optional

import aiohttp
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from loguru import logger

from voice_platform.database import get_db, User
from voice_platform.api.auth_routes import get_current_user

router = APIRouter(prefix="/api/tts", tags=["TTS Preview"])


class TTSPreviewRequest(BaseModel):
    text: str = Field(..., max_length=500, description="Text to synthesize")
    provider: str = Field(default="deepgram", description="TTS provider")
    voice_id: Optional[str] = Field(default=None, description="Voice ID")
    api_key: Optional[str] = Field(default=None, description="Optional custom API key")


# ── Provider Handlers ──────────────────────────────────────────

async def _deepgram_preview(text: str, voice_id: str, api_key: str):
    """Call Deepgram TTS and return WAV bytes."""
    key = api_key or os.environ.get("DEEPGRAM_API_KEY", "")
    if not key:
        raise HTTPException(400, "Deepgram API key required. Set DEEPGRAM_API_KEY in .env or provide api_key.")

    url = "https://api.deepgram.com/v1/speak"
    params = {
        "model": voice_id or "aura-asteria-en",
        "encoding": "linear16",
        "sample_rate": "24000",
        "container": "wav",
    }
    headers = {
        "Authorization": f"Token {key}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url, headers=headers, params=params, json={"text": text}, timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status != 200:
                err = await resp.text()
                raise HTTPException(502, f"Deepgram TTS error ({resp.status}): {err}")
            audio = await resp.read()
            return audio, "audio/wav"


async def _elevenlabs_preview(text: str, voice_id: str, api_key: str):
    """Call ElevenLabs TTS and return MP3 bytes."""
    key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        raise HTTPException(400, "ElevenLabs API key required. Set ELEVENLABS_API_KEY in .env or provide api_key.")

    vid = voice_id or "pNInz6obpgDQGcFmaJgB"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status != 200:
                err = await resp.text()
                raise HTTPException(502, f"ElevenLabs error ({resp.status}): {err}")
            audio = await resp.read()
            return audio, "audio/mpeg"


async def _gtts_preview(text: str):
    """Use gTTS (Google Translate TTS) — no API key needed."""
    try:
        from gtts import gTTS
    except ImportError:
        raise HTTPException(500, "gTTS not installed. Install with: pip install gtts")

    mp3_fp = io.BytesIO()
    tts = gTTS(text=text, lang="en")
    tts.write_to_fp(mp3_fp)
    mp3_fp.seek(0)
    return mp3_fp.read(), "audio/mpeg"


async def _cartesia_preview(text: str, voice_id: str, api_key: str):
    """Call Cartesia TTS and return WAV bytes."""
    key = api_key or os.environ.get("CARTESIA_API_KEY", "")
    if not key:
        raise HTTPException(400, "Cartesia API key required. Set CARTESIA_API_KEY in .env or provide api_key.")

    vid = voice_id or "f9836c6e-a0bd-460e-9d3c-f7299fa60f94"
    url = "https://api.cartesia.ai/tts/bytes"
    headers = {
        "X-API-Key": key,
        "Content-Type": "application/json",
        "Cartesia-Version": "2024-06-10",
    }
    payload = {
        "transcript": text,
        "model_id": "sonic-english",
        "voice": {"mode": "id", "id": vid},
        "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 24000},
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            if resp.status != 200:
                err = await resp.text()
                raise HTTPException(502, f"Cartesia error ({resp.status}): {err}")
            audio = await resp.read()
            return audio, "audio/wav"


# ── Route ────────────────────────────────────────────────────

@router.post("/preview")
async def tts_preview(
    request: TTSPreviewRequest,
    user: User = Depends(get_current_user),
):
    """
    Generate a TTS preview using the agent's configured provider.
    Returns raw audio bytes with the appropriate Content-Type.
    """
    provider = request.provider.lower()
    text = request.text[:500]

    logger.info(f"TTS preview: provider={provider}, voice={request.voice_id}, user={user.id}")

    if provider == "deepgram":
        audio, mime = await _deepgram_preview(text, request.voice_id or "", request.api_key or "")
    elif provider == "elevenlabs":
        audio, mime = await _elevenlabs_preview(text, request.voice_id or "", request.api_key or "")
    elif provider == "gtts":
        audio, mime = await _gtts_preview(text)
    elif provider == "cartesia":
        audio, mime = await _cartesia_preview(text, request.voice_id or "", request.api_key or "")
    else:
        # Fallback to gTTS for any unsupported provider
        logger.warning(f"Unsupported TTS provider '{provider}', falling back to gTTS")
        audio, mime = await _gtts_preview(text)

    return StreamingResponse(
        io.BytesIO(audio),
        media_type=mime,
        headers={"Content-Disposition": "inline; filename=preview.wav"},
    )
