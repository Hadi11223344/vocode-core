"""
Tests for the agent factory — LLM key resolution and config building.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

# Set required env vars before importing settings
os.environ.setdefault("TWILIO_ACCOUNT_SID", "ACtest")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test_token")
os.environ.setdefault("DEEPGRAM_API_KEY", "dg-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")

from voice_platform.agents.agent_factory import (
    LLM_BASE_URLS,
    LLM_DEFAULT_MODELS,
    _resolve_base_url,
    _resolve_llm_api_key,
    build_agent_config,
)
from voice_platform.database import Integration


class FakeAgent:
    """Minimal fake of the Agent DB row for testing."""
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", 0)
        self.user_id = kwargs.get("user_id", 0)
        self.updated_at = kwargs.get("updated_at", None)
        self.llm_provider = kwargs.get("llm_provider", "openai")
        self.llm_model = kwargs.get("llm_model", "gpt-4o-mini")
        self.llm_api_key = kwargs.get("llm_api_key", None)
        self.stt_provider = kwargs.get("stt_provider", "deepgram")
        self.stt_language = kwargs.get("stt_language", "en-US")
        self.stt_api_key = kwargs.get("stt_api_key", None)
        self.tts_provider = kwargs.get("tts_provider", "gtts")
        self.tts_voice_id = kwargs.get("tts_voice_id", None)
        self.tts_api_key = kwargs.get("tts_api_key", None)
        self.prompt_preamble = kwargs.get("prompt_preamble", "You are a test agent.")
        self.initial_message = kwargs.get("initial_message", "Hello!")
        self.temperature = kwargs.get("temperature", 0.7)
        self.max_tokens = kwargs.get("max_tokens", 2048)
        self.end_on_goodbye = kwargs.get("end_on_goodbye", True)
        self.interrupt_sensitivity = kwargs.get("interrupt_sensitivity", "low")
        self.google_drive_integration_id = kwargs.get("google_drive_integration_id", None)
        self.tools_config = kwargs.get("tools_config", None)
        self.tool_instructions = kwargs.get("tool_instructions", None)
        self.handbook_enabled = kwargs.get("handbook_enabled", False)
        self.handbook_content = kwargs.get("handbook_content", None)


class FakeUserApiKey:
    """Minimal fake of a UserApiKey row."""
    def __init__(self, service, api_key, is_active=True):
        self.service = service
        self.api_key = api_key
        self.is_active = is_active


# ── LLM Key Resolution ────────────────────────────────────────────────

class TestResolveLlmApiKey:
    @patch("voice_platform.agents.agent_factory.settings")
    def test_user_api_key_highest_priority(self, mock_settings):
        """UserApiKey table should be checked first."""
        mock_settings.openai_api_key = "sk-platform-default"
        agent = FakeAgent(llm_api_key="sk-agent-level")
        user_keys = [FakeUserApiKey("openai", "sk-user-table-key")]

        result = _resolve_llm_api_key("openai", agent, user_keys)
        assert result == "sk-user-table-key"

    @patch("voice_platform.agents.agent_factory.settings")
    def test_agent_level_key_second(self, mock_settings):
        """If no UserApiKey, agent-level key should work."""
        mock_settings.openai_api_key = "sk-platform-default"
        agent = FakeAgent(llm_api_key="sk-agent-level")

        result = _resolve_llm_api_key("openai", agent)
        assert result == "sk-agent-level"

    @patch("voice_platform.agents.agent_factory.settings")
    def test_platform_default_fallback(self, mock_settings):
        """If no user or agent key, platform .env key should be used."""
        mock_settings.openai_api_key = "sk-platform-default"
        agent = FakeAgent()

        result = _resolve_llm_api_key("openai", agent)
        assert result == "sk-platform-default"

    @patch("voice_platform.agents.agent_factory.settings")
    def test_gemini_key_dedicated(self, mock_settings):
        """Gemini should use its own key, not OpenAI's."""
        mock_settings.gemini_api_key = "AIzaSy-gemini-key"
        mock_settings.openai_api_key = "sk-openai-key"
        agent = FakeAgent(llm_provider="gemini")

        result = _resolve_llm_api_key("gemini", agent)
        assert result == "AIzaSy-gemini-key"

    @patch("voice_platform.agents.agent_factory.settings")
    def test_gemini_no_fallback_to_openai(self, mock_settings):
        """Gemini should NOT fall back to OpenAI key (different APIs)."""
        mock_settings.gemini_api_key = None
        mock_settings.openai_api_key = "sk-openai-key"
        agent = FakeAgent(llm_provider="gemini")

        with pytest.raises(ValueError, match="No API key available for LLM provider 'gemini'"):
            _resolve_llm_api_key("gemini", agent)

    @patch("voice_platform.agents.agent_factory.settings")
    def test_gemini_user_key_works(self, mock_settings):
        """UserApiKey for Gemini should work."""
        mock_settings.gemini_api_key = None
        mock_settings.openai_api_key = None
        agent = FakeAgent(llm_provider="gemini")
        user_keys = [FakeUserApiKey("gemini", "AIzaSy-user-gemini")]

        result = _resolve_llm_api_key("gemini", agent, user_keys)
        assert result == "AIzaSy-user-gemini"

    @patch("voice_platform.agents.agent_factory.settings")
    def test_groq_with_fallback(self, mock_settings):
        """Groq requires its own key — no cross-provider fallback."""
        mock_settings.groq_api_key = None
        mock_settings.openai_api_key = "sk-openai-fallback"
        agent = FakeAgent(llm_provider="groq")

        with pytest.raises(ValueError, match="No API key available for LLM provider 'groq'"):
            _resolve_llm_api_key("groq", agent)

    @patch("voice_platform.agents.agent_factory.settings")
    def test_inactive_user_key_skipped(self, mock_settings):
        """Inactive UserApiKey entries should be skipped."""
        mock_settings.openai_api_key = "sk-platform"
        agent = FakeAgent()
        user_keys = [FakeUserApiKey("openai", "sk-inactive", is_active=False)]

        result = _resolve_llm_api_key("openai", agent, user_keys)
        assert result == "sk-platform"

    @patch("voice_platform.agents.agent_factory.settings")
    def test_no_key_raises_error(self, mock_settings):
        """If no key at any level, should raise ValueError."""
        mock_settings.openai_api_key = None
        mock_settings.gemini_api_key = None
        mock_settings.groq_api_key = None
        agent = FakeAgent()

        with pytest.raises(ValueError):
            _resolve_llm_api_key("openai", agent)


# ── Base URL Resolution ───────────────────────────────────────────────

class TestResolveBaseUrl:
    @patch("voice_platform.agents.agent_factory.settings")
    def test_openai_default(self, mock_settings):
        mock_settings.openai_api_base = None
        result = _resolve_base_url("openai")
        assert result is None

    @patch("voice_platform.agents.agent_factory.settings")
    def test_openai_custom_base(self, mock_settings):
        mock_settings.openai_api_base = "https://custom.openai.com"
        result = _resolve_base_url("openai")
        assert result == "https://custom.openai.com"

    def test_gemini_base_url(self):
        result = _resolve_base_url("gemini")
        assert "generativelanguage.googleapis.com" in result

    def test_groq_base_url(self):
        result = _resolve_base_url("groq")
        assert "groq.com" in result


# ── LLM Provider Constants ────────────────────────────────────────────

class TestProviderConstants:
    def test_gemini_in_base_urls(self):
        assert "gemini" in LLM_BASE_URLS

    def test_gemini_in_default_models(self):
        assert "gemini" in LLM_DEFAULT_MODELS
        assert "gemini-2.0-flash" == LLM_DEFAULT_MODELS["gemini"]

    def test_all_providers_have_defaults(self):
        for provider in LLM_BASE_URLS:
            assert provider in LLM_DEFAULT_MODELS


# ── Agent Config Building ────────────────────────────────────────────

class TestBuildAgentConfig:
    @pytest.mark.asyncio
    @patch("voice_platform.agents.agent_factory.settings")
    async def test_builds_openai_config(self, mock_settings):
        mock_settings.openai_api_key = "sk-test"
        mock_settings.openai_api_base = None
        mock_settings.default_llm_model = "gpt-4o-mini"
        agent = FakeAgent()
        config = await build_agent_config(agent)
        assert config.model_name == "gpt-4o-mini"
        assert config.openai_api_key == "sk-test"

    @pytest.mark.asyncio
    @patch("voice_platform.agents.agent_factory.settings")
    async def test_builds_gemini_config(self, mock_settings):
        mock_settings.gemini_api_key = "AIzaSy-gemini"
        mock_settings.openai_api_base = None
        mock_settings.default_llm_model = "gpt-4o-mini"
        agent = FakeAgent(llm_provider="gemini", llm_model="gemini-2.0-flash")
        config = await build_agent_config(agent)
        assert config.model_name == "gemini-2.0-flash"
        assert config.openai_api_key == "AIzaSy-gemini"
        assert "generativelanguage.googleapis.com" in config.base_url_override

    @pytest.mark.asyncio
    @patch("voice_platform.agents.agent_factory.settings")
    async def test_builds_config_with_user_keys(self, mock_settings):
        mock_settings.openai_api_key = "sk-platform"
        mock_settings.openai_api_base = None
        mock_settings.default_llm_model = "gpt-4o-mini"
        agent = FakeAgent()
        user_keys = [FakeUserApiKey("openai", "sk-user-key-123")]
        config = await build_agent_config(agent, user_keys)
        assert config.openai_api_key == "sk-user-key-123"

    @pytest.mark.asyncio
    @patch("voice_platform.agents.agent_factory.settings")
    async def test_attaches_google_drive_tools(self, mock_settings, db_session, test_user, test_agent, monkeypatch):
        mock_settings.openai_api_key = "sk-test"
        mock_settings.openai_api_base = None
        mock_settings.default_llm_model = "gpt-4o-mini"

        integration = Integration(
            user_id=test_user.id,
            service_type="google_drive_mcp",
            name="Docs Drive",
            config_json=json.dumps({"server_url": "https://drivemcp.googleapis.com/mcp/v1"}),
        )
        db_session.add(integration)
        await db_session.commit()
        await db_session.refresh(integration)

        test_agent.google_drive_integration_id = integration.id

        class _SessionShim:
            def __init__(self, session):
                self._session = session

            async def __aenter__(self):
                return self._session

            async def __aexit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("voice_platform.agents.agent_factory.async_session", lambda: _SessionShim(db_session))

        config = await build_agent_config(test_agent)
        assert config.actions is not None
        drive_tools = [action for action in config.actions if getattr(action, "tool_name", "") == "read_drive_file"]
        assert drive_tools, "Expected Google Drive read_drive_file tool to be attached"
        assert getattr(drive_tools[0], "integration_type") == "google_drive_mcp"
        assert getattr(drive_tools[0], "integration_action") == "read_file_content"


def test_platform_action_factory_registration():
    from vocode.streaming.models.agent import ChatGPTAgentConfig
    from vocode.streaming.models.message import BaseMessage
    from voice_platform.actions.platform_tools import (
        PlatformActionFactory,
        PlatformToolAction,
        PlatformToolActionConfig,
    )
    from voice_platform.agents.agent_factory import PlatformAgentFactory

    action_config = PlatformToolActionConfig(
        tool_name="test_tool",
        tool_description="A test tool",
        tool_parameters_schema='{"type": "object", "properties": {}}',
        integration_type="test",
        integration_action="run",
        user_id=1,
    )
    
    # Verify PlatformActionFactory registration
    factory = PlatformActionFactory(actions=[action_config])
    assert "action_platform_tool" in factory.actions
    assert factory.actions["action_platform_tool"] == PlatformToolAction
    
    # Verify create_action
    action = factory.create_action(action_config)
    assert isinstance(action, PlatformToolAction)
    
    # Verify PlatformAgentFactory.create_agent integrates PlatformActionFactory
    agent_config = ChatGPTAgentConfig(
        openai_api_key="test-key",
        model_name="gpt-4o-mini",
        prompt_preamble="System prompt",
        initial_message=BaseMessage(text="Hello"),
        actions=[action_config],
    )
    
    agent = PlatformAgentFactory().create_agent(agent_config)
    assert agent.action_factory is not None
    assert isinstance(agent.action_factory, PlatformActionFactory)

