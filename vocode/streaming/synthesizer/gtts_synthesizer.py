import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import List

from gtts import gTTS
from loguru import logger
from pydub import AudioSegment

from vocode.streaming.models.agent import FillerAudioConfig
from vocode.streaming.models.message import BaseMessage
from vocode.streaming.models.synthesizer import GTTSSynthesizerConfig
from vocode.streaming.synthesizer.base_synthesizer import (
    BaseSynthesizer,
    FillerAudio,
    SynthesisResult,
)

FILLER_PHRASES = [
    "Um, let me think...",
    "One moment...",
    "Let me check...",
]


class GTTSSynthesizer(BaseSynthesizer):
    def __init__(
        self,
        synthesizer_config: GTTSSynthesizerConfig,
    ):
        super().__init__(synthesizer_config)

        self.thread_pool_executor = ThreadPoolExecutor(max_workers=1)

    async def get_phrase_filler_audios(self) -> List[FillerAudio]:
        """Synthesize short filler phrases so the caller hears something
        while the LLM + gTTS are generating the real response."""
        filler_audios: List[FillerAudio] = []
        for phrase in FILLER_PHRASES:
            try:
                audio_data = await self._synthesize_to_wav_bytes(phrase)
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
                logger.warning(f"gTTS: Failed to create filler audio for '{phrase}': {e}")
        logger.info(f"gTTS: Created {len(filler_audios)} filler audios")
        return filler_audios

    async def _synthesize_to_wav_bytes(self, text: str) -> bytes:
        """Synthesize text to raw WAV bytes (used for filler audio)."""
        audio_file = BytesIO()

        def _run():
            tts = gTTS(text)
            tts.write_to_fp(audio_file)
            audio_file.seek(0)
            audio_segment = AudioSegment.from_mp3(audio_file)
            output = BytesIO()
            audio_segment.export(output, format="wav")
            return output.getvalue()

        return await asyncio.get_event_loop().run_in_executor(
            self.thread_pool_executor, _run
        )

    async def create_speech(
        self,
        message: BaseMessage,
        chunk_size: int,
        is_first_text_chunk: bool = False,
        is_sole_text_chunk: bool = False,
    ) -> SynthesisResult:
        import time

        audio_file = BytesIO()

        def thread():
            start = time.time()
            logger.debug(f"gTTS: Starting synthesis for: {message.text[:50]}...")
            tts = gTTS(message.text)
            tts.write_to_fp(audio_file)
            logger.debug(f"gTTS: API call/write took {time.time() - start:.2f}s")

            pydub_start = time.time()
            audio_file.seek(0)
            audio_segment: AudioSegment = AudioSegment.from_mp3(audio_file)
            output_bytes_io = BytesIO()
            audio_segment.export(output_bytes_io, format="wav")
            logger.debug(f"gTTS: pydub conversion took {time.time() - pydub_start:.2f}s")
            return output_bytes_io

        try:
            output_bytes_io = await asyncio.get_event_loop().run_in_executor(
                self.thread_pool_executor, thread
            )
        except Exception as e:
            logger.error(f"gTTS: Synthesis failed for '{message.text[:50]}': {e}", exc_info=True)
            raise

        result = self.create_synthesis_result_from_wav(
            synthesizer_config=self.synthesizer_config,
            file=output_bytes_io,
            message=message,
            chunk_size=chunk_size,
        )
        return result
