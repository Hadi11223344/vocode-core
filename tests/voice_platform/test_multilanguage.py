"""
GAP-07: Multi-Language Support Tests
"""

import types
from unittest.mock import MagicMock, patch

import pytest

from voice_platform.agents.agent_factory import _apply_language_overrides
from voice_platform.constants import LANGUAGE_CONFIGS


def test_language_configs_loaded():
    """Verify all expected languages are in the config map."""
    expected = {"en-US", "en-GB", "ur-PK", "hi-IN", "ar-SA", "es-ES", "fr-FR", "de-DE", "auto"}
    assert set(LANGUAGE_CONFIGS.keys()) == expected


class FakeAzureSynth:
    voice_name = "en-US-SteffanNeural"


def test_apply_language_override_urdu():
    """Verify Urdu overrides STT language, TTS voice, and prompt."""
    db_agent = MagicMock()
    db_agent.language = "ur-PK"

    agent_config = types.SimpleNamespace(prompt_preamble="You are a helpful assistant.")
    transcriber_config = types.SimpleNamespace(language="en-US")
    synthesizer_config = FakeAzureSynth()

    _apply_language_overrides(db_agent, agent_config, transcriber_config, synthesizer_config)

    assert transcriber_config.language == "ur"
    assert synthesizer_config.voice_name == "ur-PK-AsadNeural"
    assert "اردو میں" in agent_config.prompt_preamble


class FakeAzureSynth2:
    voice_name = "default"


def test_apply_language_override_hindi():
    """Verify Hindi overrides set correctly."""
    db_agent = MagicMock()
    db_agent.language = "hi-IN"

    agent_config = types.SimpleNamespace(prompt_preamble="You are a helpful assistant.")
    transcriber_config = types.SimpleNamespace(language="en-US")
    synthesizer_config = FakeAzureSynth2()

    _apply_language_overrides(db_agent, agent_config, transcriber_config, synthesizer_config)

    assert transcriber_config.language == "hi"
    assert synthesizer_config.voice_name == "hi-IN-MadhurNeural"
    assert "हिंदी में" in agent_config.prompt_preamble


def test_apply_language_override_auto():
    """Verify auto-detect sets Deepgram multi-language mode."""
    db_agent = MagicMock()
    db_agent.language = "auto"

    agent_config = MagicMock()
    agent_config.prompt_preamble = "You are a helpful assistant."

    transcriber_config = MagicMock()
    transcriber_config.language = "en-US"

    synthesizer_config = MagicMock()
    synthesizer_config.__class__.__name__ = "ElevenLabsSynthesizerConfig"
    synthesizer_config.voice_id = "default"

    _apply_language_overrides(db_agent, agent_config, transcriber_config, synthesizer_config)

    assert transcriber_config.language == "multi"
    assert synthesizer_config.voice_id == "XB0fDUnXU5powFXDhCwa"
    assert "same language" in agent_config.prompt_preamble


class FakeElevenSynth:
    voice_id = "old-voice"


def test_apply_language_override_english_no_change():
    """English (en-US) should skip overrides to avoid wasting tokens."""
    db_agent = MagicMock()
    db_agent.language = "en-US"

    agent_config = types.SimpleNamespace(prompt_preamble="You are a helpful assistant.")
    transcriber_config = types.SimpleNamespace(language="en-US")
    synthesizer_config = FakeElevenSynth()

    _apply_language_overrides(db_agent, agent_config, transcriber_config, synthesizer_config)

    # en-US skips STT/TTS overrides but appends anti-drift prompt suffix
    assert transcriber_config.language == "en-US"
    assert synthesizer_config.voice_id == "old-voice"
    expected_suffix = LANGUAGE_CONFIGS["en-US"]["prompt_suffix"]
    assert agent_config.prompt_preamble == "You are a helpful assistant.\n\n" + expected_suffix


def test_apply_language_override_unknown_language():
    """Unknown language should not crash — just skip."""
    db_agent = MagicMock()
    db_agent.language = "klingon"

    agent_config = MagicMock()
    agent_config.prompt_preamble = "You are a helpful assistant."

    transcriber_config = MagicMock()
    transcriber_config.language = "en-US"

    synthesizer_config = MagicMock()
    synthesizer_config.__class__.__name__ = "DeepgramSynthesizerConfig"
    synthesizer_config.voice = "aura-asteria-en"

    _apply_language_overrides(db_agent, agent_config, transcriber_config, synthesizer_config)

    # Should be unchanged
    assert transcriber_config.language == "en-US"
    assert synthesizer_config.voice == "aura-asteria-en"
    assert agent_config.prompt_preamble == "You are a helpful assistant."


def test_apply_language_override_mismatched_tts_provider():
    """If TTS provider doesn't match, voice should not be overridden."""
    db_agent = MagicMock()
    db_agent.language = "ur-PK"  # expects azure

    agent_config = MagicMock()
    agent_config.prompt_preamble = "You are a helpful assistant."

    transcriber_config = MagicMock()
    transcriber_config.language = "en-US"

    # ElevenLabs config for Urdu — provider mismatch
    synthesizer_config = MagicMock()
    synthesizer_config.__class__.__name__ = "ElevenLabsSynthesizerConfig"
    synthesizer_config.voice_id = "old-id"

    _apply_language_overrides(db_agent, agent_config, transcriber_config, synthesizer_config)

    assert transcriber_config.language == "ur"
    # voice_id should NOT change because provider doesn't match
    assert synthesizer_config.voice_id == "old-id"
