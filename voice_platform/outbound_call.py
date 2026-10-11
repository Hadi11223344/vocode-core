"""
Voice Agent Platform — Make an Outbound Call
=============================================

This script makes the AI call YOU. The AI will greet you and have a conversation.

Usage:
    # Make sure the server is running first, then:
    cd /home/hammad/PycharmProjects/vocode-core
    LD_LIBRARY_PATH=$HOME/anaconda3/lib:$LD_LIBRARY_PATH \
    poetry run python voice_platform/outbound_call.py

Prerequisites:
    - Server must be running (voice_platform/run.sh)
    - Your phone number must be verified in Twilio (trial account)
    - Redis must be running
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

# Load .env from the platform directory
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from loguru import logger

from vocode.streaming.models.agent import LLM_AGENT_DEFAULT_MAX_TOKENS, ChatGPTAgentConfig
from vocode.streaming.models.message import BaseMessage
from vocode.streaming.models.synthesizer import StreamElementsSynthesizerConfig
from vocode.streaming.models.telephony import TwilioConfig
from vocode.streaming.models.transcriber import (
    DeepgramTranscriberConfig,
    PunctuationEndpointingConfig,
)
from vocode.streaming.telephony.config_manager.redis_config_manager import RedisConfigManager
from vocode.streaming.telephony.conversation.outbound_call import OutboundCall


# ── Configuration ────────────────────────────────────────────────────
def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        logger.error(f"Missing required environment variable: {name}")
        sys.exit(1)
    return val

TWILIO_ACCOUNT_SID = _require_env("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = _require_env("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = _require_env("TWILIO_PHONE_NUMBER")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY") or _require_env("OPENROUTER_API_KEY")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")

# ── Who to call ──────────────────────────────────────────────────────
# Pass the target phone number as a CLI argument:
#   python voice_platform/outbound_call.py +1234567890
if len(sys.argv) < 2:
    logger.error("Usage: python outbound_call.py <TO_PHONE_NUMBER>")
    sys.exit(1)
TO_PHONE_NUMBER = sys.argv[1]

# ── Get the ngrok base URL from the running server ───────────────────
def get_base_url():
    """Get the current ngrok base URL."""
    try:
        import requests

        # Try to get from ngrok API
        resp = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=3)
        tunnels = resp.json()["tunnels"]
        for tunnel in tunnels:
            if tunnel["proto"] == "https":
                return tunnel["public_url"].replace("https://", "")
    except Exception:
        pass

    # Fallback: get from server root endpoint
    try:
        import requests
        resp = requests.get("http://localhost:3000/", timeout=3)
        return resp.json()["base_url"]
    except Exception:
        pass

    logger.error("Could not determine base URL. Is the server running?")
    sys.exit(1)


async def main():
    base_url = get_base_url()
    logger.info(f"Using base URL: {base_url}")

    config_manager = RedisConfigManager()

    outbound_call = OutboundCall(
        base_url=base_url,
        to_phone=TO_PHONE_NUMBER,
        from_phone=TWILIO_PHONE_NUMBER,
        config_manager=config_manager,
        agent_config=ChatGPTAgentConfig(
            openai_api_key=OPENROUTER_API_KEY,
            base_url_override="https://openrouter.ai/api/v1",
            initial_message=BaseMessage(
                text="Hi! This is an AI voice assistant calling from Vocode. How are you doing today?"
            ),
            prompt_preamble="""You are a friendly AI voice assistant making an outbound call.
You called this person to demonstrate voice AI technology.
Be warm, conversational, and brief. Keep responses to 1-2 sentences.
If they ask who you are, explain you're an AI voice agent built with Vocode.
After a brief conversation, thank them and say goodbye.""",
            model_name="deepseek/deepseek-v4-flash",
            generate_responses=True,
            temperature=0.7,
            max_tokens=LLM_AGENT_DEFAULT_MAX_TOKENS,
            end_conversation_on_goodbye=True,
            send_filler_audio=True,
        ),
        transcriber_config=DeepgramTranscriberConfig(
            sampling_rate=8000,
            audio_encoding="mulaw",
            chunk_size=20 * 160,
            model="nova-3",
            api_key=DEEPGRAM_API_KEY,
            endpointing_config=PunctuationEndpointingConfig(),
        ),
        synthesizer_config=StreamElementsSynthesizerConfig.from_telephone_output_device(
            voice="Brian",
        ),
        telephony_config=TwilioConfig(
            account_sid=TWILIO_ACCOUNT_SID,
            auth_token=TWILIO_AUTH_TOKEN,
        ),
    )

    logger.info(f"📞 Calling {TO_PHONE_NUMBER} from {TWILIO_PHONE_NUMBER}...")
    logger.info(f"🌐 Base URL: {base_url}")
    logger.info("")

    await outbound_call.start()
    logger.info("📞 Call initiated! The AI is now calling your phone...")
    logger.info("   Pick up when your phone rings!")

    # Keep the script alive while the call is happening
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    print("=" * 50)
    print("🤖 Voice Agent — Outbound Call")
    print("=" * 50)
    print(f"Calling: {TO_PHONE_NUMBER if len(sys.argv) > 1 else '+923390044169'}")
    print(f"From:    {os.environ.get('TWILIO_PHONE_NUMBER', '+18313188656')}")
    print("")
    print("⚠️  Make sure:")
    print("  1. The server is running (voice_platform/run.sh)")
    print("  2. Your number is verified in Twilio (trial account)")
    print("  3. Redis is running")
    print("")
    input("Press ENTER to call... ")

    asyncio.run(main())
