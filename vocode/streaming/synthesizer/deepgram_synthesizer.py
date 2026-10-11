"""
Deepgram Aura TTS Synthesizer
==============================

Uses Deepgram's Text-to-Speech API (Aura models).

For Twilio calls, requests **mulaw 8kHz** output directly from Deepgram
— zero conversion overhead. For other use cases, falls back to WAV
with automatic resampling.

Available voices (English):
- aura-asteria-en (Female, US)       - aura-luna-en (Female, US)
- aura-stella-en (Female, US)        - aura-athena-en (Female, UK)
- aura-hera-en (Female, US)          - aura-orion-en (Male, US)
- aura-arcas-en (Male, US)           - aura-perseus-en (Male, US)
- aura-angus-en (Male, Irish)        - aura-orpheus-en (Male, US)
- aura-helios-en (Male, UK)          - aura-zeus-en (Male, US)

Pricing: ~$0.0150 per 1,000 characters (covered by $200 free credits).
"""

import audioop
import io
from typing import AsyncGenerator, List, Optional

import aiohttp
from loguru import logger

from vocode.streaming.models.agent import FillerAudioConfig
from vocode.streaming.models.audio import AudioEncoding
from vocode.streaming.models.message import BaseMessage
from vocode.streaming.models.synthesizer import DeepgramSynthesizerConfig
from vocode.streaming.synthesizer.base_synthesizer import (
    BaseSynthesizer,
    FillerAudio,
    SynthesisResult,
)

DEEPGRAM_TTS_BASE_URL = "https://api.deepgram.com/v1/speak"

FILLER_PHRASES = [
    "One moment...",
    "Let me check...",
    "Just a second...",
    "Please stay on the line...",
    "I'm right here, just looking that up...",
    "Give me just a moment...",
    "Thanks for your patience...",
    "Let me find that for you...",
]

# Simple in-memory cache: text → raw audio bytes (mulaw or PCM)
_audio_cache: dict[str, bytes] = {}


class DeepgramSynthesizer(BaseSynthesizer[DeepgramSynthesizerConfig]):
    """
    Deepgram Aura TTS synthesizer.

    Requests audio in the exact format needed by the output pipeline:
    - Twilio (MULAW 8kHz): ``encoding=mulaw&sample_rate=8000``
    - Other (LINEAR16):    ``encoding=linear16&sample_rate=<rate>&container=wav``

    All HTTP calls use ``async with`` for proper connection lifecycle.
    """

    def __init__(self, synthesizer_config: DeepgramSynthesizerConfig):
        super().__init__(synthesizer_config)
        self.api_key = synthesizer_config.api_key
        if not self.api_key:
            raise ValueError(
                "Deepgram TTS requires an API key. "
                "Set DEEPGRAM_API_KEY in .env or add via /api/keys"
            )
        self.model = synthesizer_config.model
        self.voice = synthesizer_config.voice
        self._is_mulaw = (
            synthesizer_config.audio_encoding == AudioEncoding.MULAW
        )

    @classmethod
    def get_voice_identifier(cls, synthesizer_config: DeepgramSynthesizerConfig) -> str:
        return f"deepgram-{synthesizer_config.voice}"

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Core API call — returns raw audio bytes with proper cleanup
    # ------------------------------------------------------------------

    async def _synthesize(self, text: str) -> bytes:
        """
        Call Deepgram TTS and return raw audio bytes.

        For MULAW pipelines: returns raw mulaw 8kHz bytes (no container).
        For LINEAR16 pipelines: returns WAV bytes.

        Uses ``async with`` to guarantee the HTTP connection is released.
        """
        if self._is_mulaw:
            params = {
                "model": self.voice,
                "encoding": "mulaw",
                "sample_rate": "8000",
            }
        else:
            params = {
                "model": self.voice,
                "encoding": "linear16",
                "sample_rate": str(self.synthesizer_config.sampling_rate),
                "container": "wav",
            }

        async with self.async_requestor.get_session().post(
            DEEPGRAM_TTS_BASE_URL,
            headers=self._get_headers(),
            params=params,
            json={"text": text},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(
                    f"Deepgram TTS error ({response.status}): {error_text}"
                )
            return await response.read()

    # ------------------------------------------------------------------
    # Filler audio (pre-synthesized at startup)
    # ------------------------------------------------------------------

    async def get_phrase_filler_audios(self) -> List[FillerAudio]:
        """Pre-synthesize short filler phrases at startup."""
        filler_audios: List[FillerAudio] = []
        for phrase in FILLER_PHRASES:
            try:
                audio_data = await self._get_playable_audio(phrase)
                filler_audios.append(
                    FillerAudio(
                        message=BaseMessage(text=phrase),
                        audio_data=audio_data,
                        synthesizer_config=self.synthesizer_config,
                        is_interruptible=True,
                        seconds_per_chunk=1,
                    )
                )
            except Exception as e:
                logger.warning(f"Deepgram TTS: filler failed for '{phrase}': {e}")
        logger.info(f"Deepgram TTS: {len(filler_audios)} filler audios ready")
        return filler_audios

    # ------------------------------------------------------------------
    # Main synthesis entry point
    # ------------------------------------------------------------------

    async def create_speech(
        self,
        message: BaseMessage,
        chunk_size: int,
        is_first_text_chunk: bool = False,
        is_sole_text_chunk: bool = False,
    ) -> SynthesisResult:
        """
        Synthesize speech for *message* and return a SynthesisResult
        whose chunk_generator yields audio in the correct encoding.
        """
        text = message.text
        logger.debug(f"Deepgram TTS: synthesizing: {text[:60]}...")

        audio_bytes = await self._get_playable_audio(text)

        async def chunk_generator() -> AsyncGenerator[SynthesisResult.ChunkResult, None]:
            for i in range(0, len(audio_bytes), chunk_size):
                is_last = (i + chunk_size) >= len(audio_bytes)
                yield SynthesisResult.ChunkResult(
                    audio_bytes[i : i + chunk_size], is_last
                )

        return SynthesisResult(
            chunk_generator(),
            lambda seconds: self.get_message_cutoff_from_voice_speed(
                message, seconds, 150
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_playable_audio(self, text: str) -> bytes:
        """
        Return audio bytes ready to be chunked and sent to the output.

        - MULAW pipeline: raw mulaw bytes from Deepgram (no conversion).
        - LINEAR16 pipeline: WAV → resampled PCM via convert_wav.

        Results are cached in-memory to avoid re-synthesizing repeated
        phrases (greetings, fillers, etc.).
        """
        cache_key = f"{self.voice}:{self._is_mulaw}:{text}"
        if cache_key in _audio_cache:
            logger.debug(f"Deepgram TTS: cache hit for '{text[:30]}...'")
            return _audio_cache[cache_key]

        raw = await self._synthesize(text)

        if self._is_mulaw:
            # Raw mulaw 8kHz — ready to send to Twilio as-is
            audio_data: bytes = raw
        else:
            # WAV — resample + encode via base class helper
            from vocode.streaming.utils import convert_wav
            converted = convert_wav(
                io.BytesIO(raw),
                output_sample_rate=self.synthesizer_config.sampling_rate,
                output_encoding=self.synthesizer_config.audio_encoding,
            )
            if converted is None:
                raise Exception("Deepgram TTS: WAV conversion failed")
            audio_data = converted

        _audio_cache[cache_key] = audio_data
        return audio_data
