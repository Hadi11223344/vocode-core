"""
Voice Platform — Playground Production Voice Session
=====================================================

Provides server-side STT/TTS for the playground using the agent's
configured providers (Deepgram, ElevenLabs, etc.).

Used by the playground voice WebSocket to:
1. Synthesize TTS audio from text responses
2. Transcribe STT audio from the browser microphone
"""

from typing import Any, Optional

import aiohttp
from loguru import logger

from vocode.streaming.models.audio import AudioEncoding
from vocode.streaming.models.message import BaseMessage
from vocode.streaming.models.synthesizer import GTTSSynthesizerConfig
from vocode.streaming.synthesizer.base_synthesizer import SynthesisResult
from vocode.streaming.synthesizer.default_factory import DefaultSynthesizerFactory
from vocode.streaming.synthesizer.gtts_synthesizer import GTTSSynthesizer
from voice_platform.agents.agent_factory import build_synthesizer_config
from voice_platform.config import settings
from voice_platform.encryption import decrypt


class PlaygroundVoiceSession:
    """
    Manages a production voice session for the playground.

    Uses the agent's configured TTS provider to synthesize speech
    and Deepgram for STT (browser microphone audio).
    """

    def __init__(self, agent, user_id: int, user_api_keys: list):
        self.agent = agent
        self.user_id = user_id
        self.user_api_keys = user_api_keys
        self._synthesizer = None
        self._synthesizer_config = None
        self._tts_provider = getattr(agent, "tts_provider", "gtts") or "gtts"
        self._stt_provider = getattr(agent, "stt_provider", "deepgram") or "deepgram"
        self._tts_voice = getattr(agent, "tts_voice_id", None)

    async def _init_synthesizer(self):
        """Initialize the TTS synthesizer using the agent's config."""
        if self._synthesizer is not None:
            return

        try:
            synth_config = build_synthesizer_config(self.agent, self.user_api_keys)
            self._synthesizer_config = synth_config

            factory = DefaultSynthesizerFactory()
            self._synthesizer = factory.create_synthesizer(synth_config)
            logger.info(
                f"Playground voice: initialized {self._tts_provider} TTS "
                f"with voice={self._tts_voice or 'default'}"
            )
        except Exception as e:
            logger.warning(f"Playground voice: TTS init failed ({e}), falling back to gTTS")
            # Fallback to gTTS
            try:
                synth_config = GTTSSynthesizerConfig.from_telephone_output_device()
                self._synthesizer_config = synth_config
                self._synthesizer = GTTSSynthesizer(synth_config)
            except Exception as e2:
                logger.error(f"Playground voice: gTTS fallback also failed: {e2}")
                raise

    async def synthesize_text(self, text: str) -> Optional[bytes]:
        """
        Synthesize text to audio bytes using the configured TTS provider.

        Returns raw audio bytes in the synthesizer's output format
        (typically LINEAR16 PCM at the configured sampling rate).
        """
        await self._init_synthesizer()

        try:
            message = BaseMessage(text=text)
            chunk_size = 1024

            synth_result: SynthesisResult = await self._synthesizer.create_speech(
                message,
                chunk_size=chunk_size,
                is_sole_text_chunk=True,
            )

            # Collect all audio chunks
            audio_data = b""
            async for chunk in synth_result.chunk_generator:
                audio_data += chunk.chunk

            logger.debug(
                f"Playground voice: synthesized {len(audio_data)} bytes "
                f"for text '{text[:50]}...'"
            )
            return audio_data

        except Exception as e:
            logger.error(f"Playground voice: TTS synthesis failed: {e}")
            return None

    def get_audio_format(self) -> dict:
        """Return the audio format info for the client."""
        if not self._synthesizer_config:
            return {
                "encoding": "linear16",
                "sample_rate": 16000,
            }

        encoding = self._synthesizer_config.audio_encoding
        sample_rate = self._synthesizer_config.sampling_rate

        encoding_str = "linear16"
        if encoding == AudioEncoding.MULAW:
            encoding_str = "mulaw"
        elif encoding == AudioEncoding.LINEAR16:
            encoding_str = "linear16"

        return {
            "encoding": encoding_str,
            "sample_rate": sample_rate,
        }

    async def transcribe_audio(
        self,
        audio_chunks: list[bytes],
        sample_rate: int = 16000,
        encoding: str = "linear16",
    ) -> Optional[str]:
        """
        Transcribe audio chunks using Deepgram STT.

        This is a simplified implementation that sends the collected
        audio to Deepgram's streaming endpoint.
        """
        if not audio_chunks:
            return None

        # Resolve Deepgram API key
        api_key = None
        for key_row in self.user_api_keys:
            if key_row.service == "deepgram" and key_row.is_active:
                api_key = decrypt(key_row.api_key)
                break

        if not api_key:
            api_key = getattr(self.agent, "stt_api_key", None) or settings.deepgram_api_key

        if not api_key:
            logger.warning("Playground voice: No Deepgram API key for STT")
            return None

        try:
            # Combine audio chunks
            all_audio = b"".join(audio_chunks)

            # Use Deepgram's streaming API
            url = "https://api.deepgram.com/v1/listen"
            params = {
                "model": "nova-3",
                "language": getattr(self.agent, "stt_language", None) or "en-US",
                "encoding": encoding,
                "sample_rate": str(sample_rate),
                "interim_results": "false",
                "punctuate": "true",
            }

            headers = {
                "Authorization": f"Token {api_key}",
                "Content-Type": "audio/raw",
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    params=params,
                    headers=headers,
                    data=all_audio,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Deepgram STT error ({response.status}): {error_text}")
                        return None

                    result = await response.json()
                    # Extract transcript from the response
                    channel = result.get("channel", {})
                    alternatives = channel.get("alternatives", [])
                    if alternatives:
                        transcript = alternatives[0].get("transcript", "").strip()
                        if transcript:
                            logger.debug(f"Playground voice: STT result: '{transcript[:60]}'")
                            return transcript

            return None

        except Exception as e:
            logger.error(f"Playground voice: STT failed: {e}")
            return None

    async def close(self) -> None:
        """Clean up synthesizer and any underlying resources."""
        if self._synthesizer is not None:
            cleanup = getattr(self._synthesizer, "close", None) or getattr(self._synthesizer, "aclose", None)
            if cleanup is not None:
                try:
                    result = cleanup()
                    if hasattr(result, "__await__"):
                        await result
                except Exception as e:
                    logger.debug(f"Playground voice: synthesizer cleanup error: {e}")
            self._synthesizer = None
