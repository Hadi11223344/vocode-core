"""
Voice Platform — Language & Voice Configuration Constants
=============================================================

GAP-07: Multi-Language Support

Maps agent language settings to the correct STT language code, TTS provider,
voice ID, and LLM prompt suffix for consistent cross-language configuration.

Usage:
    from voice_platform.constants import LANGUAGE_CONFIGS
    config = LANGUAGE_CONFIGS.get(agent.language, LANGUAGE_CONFIGS["en-US"])
"""

LANGUAGE_CONFIGS = {
    "en-US": {
        "stt_language": "en-US",
        "tts_provider": "elevenlabs",
        "tts_voice_id": "XB0fDUnXU5powFXDhCwa",  # Josh
        "prompt_suffix": (
            "You must respond ONLY in English. Never use Urdu, Hindi, Arabic, or any other language. "
            "Do not mix in Urdu phrases like 'salam', 'ji', 'acha', 'zaroor', 'theek hai', or 'bilkul'. "
            "If the caller speaks another language, politely ask them to speak in English."
        ),
    },
    "en-GB": {
        "stt_language": "en-GB",
        "tts_provider": "elevenlabs",
        "tts_voice_id": "N2lVS1w4ETc19Stfnl9O",  # Thomas
        "prompt_suffix": "Respond in British English.",
    },
    "ur-PK": {
        "stt_language": "ur",
        "tts_provider": "azure",
        "tts_voice_id": "ur-PK-AsadNeural",  # Azure Urdu voice
        "prompt_suffix": "اردو میں جواب دیں۔",
    },
    "hi-IN": {
        "stt_language": "hi",
        "tts_provider": "azure",
        "tts_voice_id": "hi-IN-MadhurNeural",
        "prompt_suffix": "हिंदी में जवाब दें।",
    },
    "ar-SA": {
        "stt_language": "ar",
        "tts_provider": "azure",
        "tts_voice_id": "ar-SA-HamedNeural",
        "prompt_suffix": "يرجى الرد باللغة العربية.",
    },
    "es-ES": {
        "stt_language": "es",
        "tts_provider": "elevenlabs",
        "tts_voice_id": "AZnzlk1XvdvUeBnXmlld",  # Spanish voice
        "prompt_suffix": "Responde en español.",
    },
    "fr-FR": {
        "stt_language": "fr",
        "tts_provider": "elevenlabs",
        "tts_voice_id": "TX3AE3VoIzMeqJ9j3K3z",  # French voice
        "prompt_suffix": "Réponds en français.",
    },
    "de-DE": {
        "stt_language": "de",
        "tts_provider": "elevenlabs",
        "tts_voice_id": "IKne3meq5aSn9VSyZbDR",  # German voice
        "prompt_suffix": "Antworte auf Deutsch.",
    },
    "auto": {
        "stt_language": "multi",
        "tts_provider": "elevenlabs",
        "tts_voice_id": "XB0fDUnXU5powFXDhCwa",
        "prompt_suffix": "Respond in the same language the user is speaking.",
    },
}
