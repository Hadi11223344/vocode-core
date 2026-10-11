"""
Voice Agent — Browser-Based Test Server (FINAL FINAL FIX)
==========================================================

Fixed: Missing chunk_size in input_audio_config (solved Pydantic validation error).
"""

import asyncio
import io
import os
import tempfile
from typing import Any, AsyncGenerator, Optional

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../voice_platform/.env"))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from gtts import gTTS
from loguru import logger
from pydub import AudioSegment

from vocode.logging import configure_pretty_logging
from vocode.streaming.agent.base_agent import (
    AgentResponse,
    AgentResponseMessage,
    BaseAgent,
    TranscriptionAgentInput,
)
from vocode.streaming.client_backend.conversation import ConversationRouter
from vocode.streaming.models.agent import AgentConfig
from vocode.streaming.models.message import BaseMessage
from vocode.streaming.models.synthesizer import GTTSSynthesizerConfig
from vocode.streaming.synthesizer.base_synthesizer import BaseSynthesizer, SynthesisResult

configure_pretty_logging()

# ── Mock Agent (Always use for this test to ensure success) ──────────
class ForcedMockAgent(BaseAgent[AgentConfig]):
    def __init__(self, agent_config: AgentConfig):
        super().__init__(agent_config)

    async def generate_response(
        self,
        transcription: TranscriptionAgentInput,
        is_interrupt: bool = False,
        conversation_id: Optional[str] = None,
    ) -> AsyncGenerator[AgentResponse, None]:
        logger.info(f"Mock Agent reacting to: {transcription.transcription.message}")
        yield AgentResponseMessage(message=BaseMessage(text="I can hear you clearly now! The voice connection is stable and working perfectly."))

# ── Custom Raw PCM Synthesizer ──────────────────────────────────────
class RawPCMSynthesizer(BaseSynthesizer[GTTSSynthesizerConfig]):
    def __init__(self, synthesizer_config: GTTSSynthesizerConfig):
        synthesizer_config.should_encode_as_wav = False
        super().__init__(synthesizer_config)

    async def create_speech_uncached(
        self,
        message: BaseMessage,
        chunk_size: int,
        is_first_text_chunk: bool = False,
        is_sole_text_chunk: bool = False,
    ) -> SynthesisResult:
        logger.info(f"Synthesizing: {message.text}")
        try:
            def get_audio():
                tts = gTTS(text=message.text, lang='en')
                f = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                tts.save(f.name)
                f.close()
                return f.name

            temp_mp3 = await asyncio.to_thread(get_audio)
            try:
                audio = AudioSegment.from_mp3(temp_mp3)
                audio = audio.set_frame_rate(48000).set_channels(1).set_sample_width(2)
                raw_data = audio.raw_data
                
                async def chunk_generator():
                    for i in range(0, len(raw_data), chunk_size):
                        yield SynthesisResult.ChunkResult(raw_data[i:i + chunk_size], i + chunk_size >= len(raw_data))

                return SynthesisResult(chunk_generator(), lambda _: message.text)
            finally:
                if os.path.exists(temp_mp3): os.remove(temp_mp3)
        except Exception as e:
            logger.error(f"Synthesizer Error: {e}")
            async def empty_gen(): yield SynthesisResult.ChunkResult(b"", True)
            return SynthesisResult(empty_gen(), lambda _: "")

app = FastAPI()

conversation_router = ConversationRouter(
    agent_thunk=lambda: ForcedMockAgent(AgentConfig(initial_message=BaseMessage(text="Hello! The new audio engine is initialized. Can you hear me?"))),
    synthesizer_thunk=lambda config: RawPCMSynthesizer(GTTSSynthesizerConfig.from_output_audio_config(config)),
)
app.include_router(conversation_router.get_router())

@app.get("/")
async def index(): return HTMLResponse(BROWSER_CLIENT_HTML)

BROWSER_CLIENT_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Voice Agent — FINAL REPAIR</title>
    <style>
        body { font-family: sans-serif; background: #1a1a1a; color: white; text-align: center; padding-top: 50px; }
        #status { font-weight: bold; margin: 20px; color: #aaa; }
        .btn { padding: 15px 30px; font-size: 18px; cursor: pointer; border-radius: 5px; border: none; background: #4a90e2; color: white; }
        #transcript { margin-top: 30px; background: #222; padding: 20px; border-radius: 10px; max-width: 600px; margin-left: auto; margin-right: auto; text-align: left; }
    </style>
</head>
<body>
    <h1>Voice Agent — Final Test</h1>
    <div id="status">Ready</div>
    <button class="btn" id="startBtn" onclick="start()">START TALKING</button>
    <div id="transcript"></div>

    <script>
        let ws, audioContext, mediaStream;
        let queue = [];
        let playing = false;
        const SAMPLE_RATE = 48000;

        function log(msg, role) {
            const div = document.createElement('div');
            div.style.margin = '5px 0';
            div.style.color = role === 'agent' ? '#a5d6a7' : role === 'user' ? '#90caf9' : '#888';
            div.textContent = (role ? role.toUpperCase() + ": " : "") + msg;
            document.getElementById('transcript').appendChild(div);
        }

        async function playNext() {
            if (queue.length === 0) { playing = false; return; }
            playing = true;
            const data = queue.shift();
            try {
                const raw = atob(data);
                const bytes = new Uint8Array(raw.length);
                for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
                const pcm16 = new Int16Array(bytes.buffer);
                const f32 = new Float32Array(pcm16.length);
                for (let i = 0; i < pcm16.length; i++) f32[i] = pcm16[i] / 32768.0;
                const buffer = audioContext.createBuffer(1, f32.length, SAMPLE_RATE);
                buffer.getChannelData(0).set(f32);
                const source = audioContext.createBufferSource();
                source.buffer = buffer;
                source.connect(audioContext.destination);
                source.onended = playNext;
                source.start();
            } catch (e) { console.error("PCM Error:", e); playNext(); }
        }

        async function start() {
            document.getElementById('status').textContent = "Connecting...";
            try {
                audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
                mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                ws = new WebSocket((window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/conversation');
                ws.onopen = () => {
                    ws.send(JSON.stringify({
                        type: 'websocket_audio_config_start',
                        input_audio_config: { 
                            sampling_rate: SAMPLE_RATE, 
                            audio_encoding: 'linear16',
                            chunk_size: 4800 // CRITICAL: REQUIRED BY SERVER
                        },
                        output_audio_config: { sampling_rate: SAMPLE_RATE, audio_encoding: 'linear16' },
                        subscribe_transcript: true
                    }));
                };
                ws.onmessage = async (e) => {
                    const m = JSON.parse(e.data);
                    if (m.type === 'websocket_ready') {
                        document.getElementById('status').textContent = "CONNECTED - Speak Now";
                        const source = audioContext.createMediaStreamSource(mediaStream);
                        const proc = audioContext.createScriptProcessor(4096, 1, 1);
                        proc.onaudioprocess = (ev) => {
                            const input = ev.inputBuffer.getChannelData(0);
                            const p16 = new Int16Array(input.length);
                            for (let i = 0; i < input.length; i++) {
                                const s = Math.max(-1, Math.min(1, input[i]));
                                p16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                            }
                            if (ws.readyState === WebSocket.OPEN) {
                                ws.send(JSON.stringify({ type: 'websocket_audio', data: btoa(String.fromCharCode(...new Uint8Array(p16.buffer))) }));
                            }
                        };
                        source.connect(proc);
                        proc.connect(audioContext.destination);
                    } else if (m.type === 'websocket_audio') {
                        queue.push(m.data);
                        if (!playing) playNext();
                    } else if (m.type === 'websocket_transcript') {
                        log(m.text, m.sender);
                    }
                };
            } catch (err) {
                document.getElementById('status').textContent = "Error: " + err.message;
            }
        }
    </script>
</body>
</html>"""
