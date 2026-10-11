"""
Voice Platform — Agent Factory (Retell-Grade Provider System)
===============================================================

Creates vocode agent instances from database agent configurations.
This is the heart of the modular provider system. When a call arrives,
the factory reads the agent's settings from the DB and builds the
correct vocode objects — plug-and-play, zero config.

Provider Support Matrix (English-first focus):
─────────────────────────────────────────────────────────────
COMPONENT     PROVIDER        STATUS    NOTES
─────────────────────────────────────────────────────────────
LLM           openrouter      ✅        DeepSeek V4 Flash (default)
              groq            ✅        Llama 3.3 70B, Llama 4
              openai          ✅        GPT-4o, GPT-4o-mini
              gemini          ✅        Gemini 2.0 Flash via OpenAI-compat
              anthropic       ✅        Via OpenAI-compatible endpoint (proxy)


STT           deepgram        ✅        Best accuracy, primary provider
              google          ✅        Google Cloud Speech
              azure           ✅        Azure Speech Services
              assemblyai      ✅        AssemblyAI

TTS           deepgram        ✅        Aura neural voices (same key as STT)
              gtts            ✅        Free, no API key needed
              elevenlabs      ✅        Premium neural voices
              azure           ✅        Azure Neural TTS
              cartesia        ✅        Ultra-low latency
              polly           ✅        AWS Polly
              streamelements  ✅        Free, no API key needed
─────────────────────────────────────────────────────────────

API Key Resolution Chain (per provider):
    1. User's key from `user_api_keys` table (highest priority)
    2. Agent-level API key (legacy field in Agent)
    3. Platform .env default key
    4. Clear error message if none exists
"""

import json
import os
from typing import Any, List, Optional, Tuple, cast

from loguru import logger
from sqlalchemy import select

# ── vocode Agent Classes ───────────────────────────────────────────────
from vocode.streaming.agent.abstract_factory import AbstractAgentFactory
from vocode.streaming.agent.base_agent import BaseAgent
from vocode.streaming.agent.chat_gpt_agent import ChatGPTAgent

# ── vocode Config Models ──────────────────────────────────────────────
from vocode.streaming.models.agent import (
    LLM_AGENT_DEFAULT_MAX_TOKENS,
    AgentConfig,
    ChatGPTAgentConfig,
    FillerAudioConfig,
)
from vocode.streaming.models.message import BaseMessage
from vocode.streaming.models.synthesizer import (
    AzureSynthesizerConfig,
    CartesiaSynthesizerConfig,
    DeepgramSynthesizerConfig,
    ElevenLabsSynthesizerConfig,
    GTTSSynthesizerConfig,
    PollySynthesizerConfig,
    StreamElementsSynthesizerConfig,
    SynthesizerConfig,
)
from vocode.streaming.models.transcriber import (
    AssemblyAITranscriberConfig,
    AzureTranscriberConfig,
    DeepgramTranscriberConfig,
    GoogleTranscriberConfig,
    PunctuationEndpointingConfig,
    TimeEndpointingConfig,
    TranscriberConfig,
)
from vocode.streaming.telephony.constants import (
    DEFAULT_AUDIO_ENCODING,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_SAMPLING_RATE,
)
from vocode.streaming.transcriber.deepgram_transcriber import (
    DeepgramEndpointingConfig,  # VAD-based endpointing — best for telephony
)
from voice_platform.config import settings
from voice_platform.database import Integration, UserApiKey, async_session
from voice_platform.encryption import decrypt
from voice_platform.runtime.prompt_renderer import (
    _DRIVE_APPENDIX,
    _EMAIL_APPENDIX,
    _SECURITY_GUARD,
    _VOICE_CONDUCT,
    PromptRenderer,
    RenderContext,
    RenderResult,
    _build_tool_availability_guard,
    _select_prompt_version,
)

# ═══════════════════════════════════════════════════════════════════════
# Prompt rendering — extracted to voice_platform.runtime.prompt_renderer
# Guards, _build_tool_availability_guard, _select_prompt_version, and
# PromptRenderer.render() now live in prompt_renderer.py.
# Symbols are re-exported here for backward compatibility.
# ═══════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════
# Agent Factory — Creates vocode agents from AgentConfig instances
# ═══════════════════════════════════════════════════════════════════════

class PlatformAgentFactory(AbstractAgentFactory):
    """
    Factory that creates vocode agents from database configurations.
    
    Currently all LLM providers route through ChatGPTAgent because:
    - OpenAI, Gemini, Groq, and Anthropic all support OpenAI-compatible APIs
    - vocode's ChatGPTAgent uses the openai Python SDK which supports base_url
    - This gives us plug-and-play provider switching with zero custom agent code
    """
    
    def create_agent(
        self,
        agent_config: AgentConfig,
        **kwargs: Any,
    ) -> BaseAgent:
        if isinstance(agent_config, ChatGPTAgentConfig):
            # Check if this is a conversational_flow agent
            graph_json = getattr(agent_config, 'graph_json', None)
            if graph_json and agent_config.flow_agent_id:
                logger.info(
                    f"Creating FlowAgent: model={agent_config.model_name}, "
                    f"agent_id={agent_config.flow_agent_id}"
                )
                from voice_platform.actions.platform_tools import PlatformActionFactory
                from voice_platform.agents.flow_agent import FlowAgent
                from voice_platform.runtime.session.state_manager import LangGraphStateManager
                action_factory = PlatformActionFactory(actions=agent_config.actions)
                flow_agent = FlowAgent(
                    agent_config=agent_config,
                    graph_json=graph_json,
                    agent_id=agent_config.flow_agent_id,
                    user_id=agent_config.flow_user_id or 0,
                    action_factory=action_factory,
                    state_manager=LangGraphStateManager(),
                )
                # Wrap in ConversationSession for lifecycle coordination
                from voice_platform.integrations.plugins.registry import EmptyPluginRegistry
                from voice_platform.runtime.events.event_bus import NoOpEventBus
                from voice_platform.runtime.session.adapters.telephony import TelephonyRuntime
                from voice_platform.runtime.session.context import ExecutionContext
                from voice_platform.runtime.session.conversation_context import (
                    ConversationChannel,
                    ConversationContext,
                )
                from voice_platform.runtime.session.infrastructure_context import (
                    InfrastructureContext,
                )
                from voice_platform.runtime.session.runtime_config import (
                    AgentConfig as RuntimeAgentConfig,
                )
                from voice_platform.runtime.session.runtime_config import (
                    EnrichmentContext,
                    ModelReference,
                    PromptContext,
                    RuntimeConfig,
                    ToolContext,
                )
                from voice_platform.runtime.session.session import ConversationSession
                from voice_platform.runtime.session.session import (
                    create_conversation_id as _session_uuid,
                )
                from voice_platform.runtime.tracing.tracer import NoOpTracer

                class _NoOpDB:
                    async def execute(self, stmt): raise RuntimeError("No DB in agent factory")
                    async def commit(self): pass
                    async def rollback(self): pass
                    async def close(self): pass

                class _NoOpCache:
                    async def get(self, key): return None
                    async def set(self, key, value, ttl=None): pass
                    async def delete(self, key): pass

                telephony_runtime = TelephonyRuntime(agent=flow_agent)
                flow_agent._conversation_session = ConversationSession(
                    runtime=telephony_runtime,
                    context=ExecutionContext(
                        conversation=ConversationContext(
                            conversation_id=_session_uuid(),
                            agent_id=agent_config.flow_agent_id,
                            user_id=agent_config.flow_user_id,
                            channel=ConversationChannel.TELEPHONY,
                        ),
                        runtime=RuntimeConfig(
                            agent=RuntimeAgentConfig(
                                model_ref=ModelReference(
                                    provider=getattr(agent_config, "llm_provider", "openai"),
                                    model=agent_config.model_name,
                                ),
                                temperature=agent_config.temperature,
                                max_tokens=getattr(agent_config, "max_tokens", 2048),
                            ),
                            prompt=PromptContext(
                                system_prompt=getattr(agent_config, "prompt_preamble", "") or "",
                            ),
                            tools=ToolContext(),
                            enrichment=EnrichmentContext(),
                        ),
                        infrastructure=InfrastructureContext(
                            db=_NoOpDB(),
                            cache=_NoOpCache(),
                            event_bus=NoOpEventBus(),
                            tracer=NoOpTracer(),
                            plugin_registry=EmptyPluginRegistry(),
                        ),
                    ),
                )
                return flow_agent

            logger.info(
                f"Creating ChatGPT agent: model={agent_config.model_name}, "
                f"temp={agent_config.temperature}, "
                f"tools={len(agent_config.actions) if agent_config.actions else 0}"
            )
            from voice_platform.actions.platform_tools import PlatformActionFactory
            action_factory = PlatformActionFactory(actions=agent_config.actions)
            return ChatGPTAgent(agent_config=agent_config, action_factory=action_factory)
        
        raise ValueError(f"Unsupported agent config type: {type(agent_config)}")


# ═══════════════════════════════════════════════════════════════════════
# LLM Config Builder
# ═══════════════════════════════════════════════════════════════════════

# OpenAI-compatible base URLs for each provider
LLM_BASE_URLS = {
    "openai": None,  # Uses default https://api.openai.com/v1
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "groq": "https://api.groq.com/openai/v1",
    "anthropic": "https://openrouter.ai/api/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "commandcode": "https://api.commandcode.ai/provider/v1",
    "ollama": None,  # Set dynamically in _resolve_base_url from settings
}

# Default model names per provider
LLM_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "groq": "openai/gpt-oss-120b",
    "anthropic": "claude-sonnet-4-20250514",
    "openrouter": "deepseek/deepseek-v4-flash",
    "commandcode": "deepseek/deepseek-v4-pro",
    "ollama": "granite4.1:8b",
}

# Known valid models per provider — used to detect stale configs after provider switches
_PROVIDER_MODELS = {
    "openai": {
        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4",
        "gpt-4o-2024-08-06", "gpt-4o-mini-2024-07-18",
        "gpt-3.5-turbo", "gpt-3.5-turbo-1106",
    },
    "gemini": {
        "gemini-2.0-flash", "gemini-2.0-flash-exp", "gemini-2.0-flash-lite",
        "gemini-1.5-pro", "gemini-1.5-flash",
    },
    "groq": {
        "openai/gpt-oss-120b", "openai/gpt-oss-20b",
        "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
        "qwen/qwen3-32b",
    },
    "anthropic": {
        "claude-sonnet-4-20250514", "claude-opus-4-20250514",
        "claude-3-5-sonnet-20241022", "claude-3-haiku-20240307",
        "claude-3-sonnet-20240229", "claude-3-opus-20240229",
    },
    "openrouter": {
        "deepseek/deepseek-v4-flash",
    },
    "commandcode": {
        "deepseek/deepseek-v4-pro",
    },
    "ollama": {
        "granite4.1:8b", "qwen3:8b", "qwen3", "qwen3:32b", "qwen3:4b",
        "qwen3.5:9b", "qwen3-nothink", "phi4-mini",
        "gemma4:e4b", "llama3.3", "llama3.3:70b", "gemma3:4b",
    },
}


def _decrypt_agent_key(raw_key: str, service: str = "") -> str:
    """Decrypt an agent-level API key with fallback to raw (legacy plaintext)."""
    try:
        return decrypt(raw_key)
    except Exception:
        logger.warning(f"Agent-level {service} API key could not be decrypted — using raw value (may be legacy plaintext)")
        return raw_key


def _resolve_llm_api_key(provider: str, db_agent, user_api_keys: list = None) -> str:
    """
    Resolve the LLM API key with proper fallback chain:
    
    Priority:
        1. User's key from UserApiKey table (if user_api_keys provided)
        2. Agent-level key (legacy per-agent key)
        3. Platform default from .env
    
    Args:
        provider: LLM provider name (openai, gemini, groq, anthropic)
        db_agent: Agent DB row with optional llm_api_key
        user_api_keys: List of UserApiKey rows for the agent's owner
    """
    # 1. UserApiKey table — highest priority
    if user_api_keys:
        # Map provider name to service name in user_api_keys
        service_name = provider  # openai → openai, gemini → gemini
        for key_row in user_api_keys:
            if key_row.service == service_name and key_row.is_active:
                logger.debug(f"Using user API key for {provider} (from user_api_keys table)")
                return decrypt(key_row.api_key)
    
    # 2. Agent-level key (legacy)
    if db_agent.llm_api_key:
        logger.debug(f"Using agent-level API key for {provider}")
        return _decrypt_agent_key(db_agent.llm_api_key, "LLM")
    
    # 3. Platform defaults from .env
    if provider == "openai":
        if settings.openai_api_key:
            return settings.openai_api_key
    elif provider == "gemini":
        if settings.gemini_api_key:
            return settings.gemini_api_key
        # Gemini uses its own OpenAI-compatible endpoint — needs real Gemini key
        logger.warning("No Gemini API key found. Get one at aistudio.google.com")
    elif provider == "groq":
        if settings.groq_api_key:
            return settings.groq_api_key
        logger.warning("No Groq API key found — add one at /api/keys or set GROQ_API_KEY in .env")
    elif provider == "anthropic":
        if settings.anthropic_api_key:
            return settings.anthropic_api_key
        logger.warning("No Anthropic API key found — add one at /api/keys or set ANTHROPIC_API_KEY in .env")
    elif provider == "openrouter":
        if settings.openrouter_api_key:
            return settings.openrouter_api_key
        logger.warning("No OpenRouter API key found — add one at /api/keys or set OPENROUTER_API_KEY in .env")
    elif provider == "commandcode":
        if settings.commandcode_api_key:
            return settings.commandcode_api_key
        logger.warning("No CommandCode API key found — add one at /api/keys or set COMMANDCODE_API_KEY in .env")
    elif provider == "ollama":
        return settings.ollama_api_key
    
    raise ValueError(
        f"No API key available for LLM provider '{provider}'. "
        f"Add your key at /api/keys or set it in platform .env"
    )


def _resolve_base_url(provider: str) -> Optional[str]:
    """
    Get the OpenAI-compatible base URL for the LLM provider.
    For OpenAI direct, returns the configured base (which may route to Gemini).
    """
    if provider == "openai":
        # If OPENAI_API_BASE is set, use it (e.g., Gemini endpoint)
        return settings.openai_api_base
    if provider == "ollama":
        return settings.ollama_base_url
    return LLM_BASE_URLS.get(provider)



async def build_agent_config(db_agent, user_api_keys: list = None) -> AgentConfig:
    """
    Build a vocode AgentConfig from a database Agent row.

    All providers route through ChatGPTAgentConfig because they all
    support OpenAI-compatible APIs via base_url_override.

    Uses Redis caching to skip expensive LLM param resolution on
    repeated calls. Cache is keyed by agent_id + updated_at, so any
    agent edit automatically invalidates the cached config.

    Args:
        db_agent: Agent DB row with LLM/STT/TTS config
        user_api_keys: Optional list of UserApiKey rows for key resolution
    """
    from voice_platform.cache import RedisCache

    agent_id = getattr(db_agent, "id", 0)
    updated_at = getattr(db_agent, "updated_at", None)
    cache_version = updated_at.isoformat() if updated_at else "0"
    cache_key = f"agent_config:{agent_id}:{cache_version}"

    # Try cache hit first
    cached = await RedisCache.get(cache_key)
    if cached:
        logger.debug(f"Agent config cache hit for agent #{agent_id}")
        # Rebuild from cached serializable params
        return await _rebuild_config_from_cache(cached, db_agent)

    provider = db_agent.llm_provider.lower()

    # Resolve API key and base URL
    api_key = _resolve_llm_api_key(provider, db_agent, user_api_keys)
    base_url = _resolve_base_url(provider)
    model = db_agent.llm_model or LLM_DEFAULT_MODELS.get(provider, settings.default_llm_model or "llama-3.3-70b-versatile")

    # Validate model belongs to provider (e.g. prevent gpt-4o-mini on Gemini)
    valid_models = _PROVIDER_MODELS.get(provider)
    if valid_models and model not in valid_models:
        fallback = LLM_DEFAULT_MODELS.get(provider, settings.default_llm_model or "llama-3.3-70b-versatile")
        logger.warning(
            f"Agent #{db_agent.id} has model '{model}' which is not valid for provider '{provider}'. "
            f"Falling back to '{fallback}'. Update the agent settings to fix this."
        )
        model = fallback

    # Build in-call tool actions from tools_config
    tool_actions = []
    skipped_tools: list = []
    if hasattr(db_agent, 'tools_config') and db_agent.tools_config:
        try:
            import json as _json
            tools_list = _json.loads(db_agent.tools_config) if isinstance(db_agent.tools_config, str) else db_agent.tools_config
            if tools_list:
                from voice_platform.actions.platform_tools import build_tool_actions
                bindings = {}
                if hasattr(db_agent, 'mcp_bindings_json') and db_agent.mcp_bindings_json:
                    try:
                        bindings = json.loads(db_agent.mcp_bindings_json)
                    except Exception:
                        pass
                instructions = getattr(db_agent, 'tool_instructions', None)
                overrides = {}
                if hasattr(db_agent, 'integration_overrides_json') and db_agent.integration_overrides_json:
                    try:
                        overrides = json.loads(db_agent.integration_overrides_json)
                    except Exception:
                        pass
                tool_actions, skipped_tools = await build_tool_actions(tools_list, db_agent.user_id, bindings, instructions, overrides, agent_timezone=getattr(db_agent, 'timezone', None))
                logger.info(f"Loaded {len(tool_actions)} in-call tools for agent {db_agent.name}")
        except Exception as e:
            logger.warning(f"Failed to load tools_config: {e}")
            skipped_tools = []

    # Optional Google Drive MCP integration attached directly to the agent.
    drive_tool_actions = await _build_google_drive_tool_actions(db_agent)
    if drive_tool_actions:
        # Issue 07: Deduplicate by tool_name — MCP discovery may return tools
        # that already exist in tool_actions from PLATFORM_TOOLS (e.g. read_drive_file)
        existing_names = {
            getattr(a, "tool_name", "")
            for a in tool_actions
        }
        for dt in drive_tool_actions:
            if getattr(dt, "tool_name", "") not in existing_names:
                tool_actions.append(dt)

    # I-4: Disable filler audio for gTTS (high latency causes overlap).
    # Only enable for low-latency providers: Deepgram, ElevenLabs, Cartesia.
    _tts_provider = getattr(db_agent, 'tts_provider', 'gtts').lower()
    _filler_supported = _tts_provider in ('deepgram', 'elevenlabs', 'cartesia')
    _filler_enabled = (
        not hasattr(db_agent, 'filler_audio_enabled')
        or db_agent.filler_audio_enabled is not False
    )
    _filler_config = (
        FillerAudioConfig(
            silence_threshold_seconds=0.3,
            use_phrases=True,
            use_typing_noise=False,
        )
        if (_filler_enabled and _filler_supported)
        else False
    )

    # ── Prompt Assembly (delegated to PromptRenderer) ───────────────────
    render_result = PromptRenderer.render(RenderContext(
        db_agent=db_agent,
        tool_actions=tool_actions,
        skipped_tools=skipped_tools,
        drive_tool_actions=drive_tool_actions,
        tools_config=getattr(db_agent, 'tools_config', None),
    ))
    selected_prompt = render_result.prompt
    selected_version_id = render_result.version_id

    config = ChatGPTAgentConfig(
        # Auth
        openai_api_key=api_key,
        base_url_override=base_url,
        # Model
        model_name=model,
        # Prompt
        prompt_preamble=selected_prompt,
        initial_message=_make_initial_message(db_agent.initial_message),
        # Generation
        temperature=db_agent.temperature or 0.7,
        max_tokens=db_agent.max_tokens or LLM_AGENT_DEFAULT_MAX_TOKENS,
        generate_responses=True,
        # GAP-01: Live KB retrieval
        knowledge_base_id=getattr(db_agent, 'knowledge_base_id', None),
        # Behavior
        end_conversation_on_goodbye=db_agent.end_on_goodbye if db_agent.end_on_goodbye is not None else False,
        goodbye_phrases=["goodbye", "talk to you later", "have a good day", "end the call"],
        interrupt_sensitivity=db_agent.interrupt_sensitivity or "low",
        # ── Call Stability Settings (prevent call drops!) ──────────
        # How long to wait (seconds) before checking if caller is still there.
        # Default 60s. Lower values catch disconnects faster.
        allowed_idle_time_seconds=(
            db_agent.allowed_idle_time_seconds
            if hasattr(db_agent, 'allowed_idle_time_seconds') and db_agent.allowed_idle_time_seconds is not None
            else 60.0
        ),
        # How many "are you still there?" attempts before auto-disconnect.
        # CRITICAL: vocode default is 0 (instant drop!). We default to 2.
        num_check_human_present_times=(
            db_agent.num_check_human_present_times
            if hasattr(db_agent, 'num_check_human_present_times') and db_agent.num_check_human_present_times is not None
            else 2
        ),
        # Delay before first message — gives Twilio WebSocket time to fully connect.
        # Without this, the first few words may be clipped.
        initial_message_delay=(
            db_agent.initial_message_delay
            if hasattr(db_agent, 'initial_message_delay') and db_agent.initial_message_delay is not None
            else 0.2
        ),
        # Filler audio — play "um", "let me check" or typing sounds while
        # the LLM is generating. Prevents awkward silence that makes callers
        # think the call dropped.
        send_filler_audio=_filler_config,
        # In-call tool actions (function calling)
        actions=tool_actions if tool_actions else [],
        # Phase 7: Configurable Ollama context window
        context_window=getattr(db_agent, 'context_window', None),
    )

    # GAP-08: Attach selected prompt version ID for call tracking
    object.__setattr__(config, '_selected_prompt_version_id', selected_version_id)

    # Flow agent support: set graph_json and flow metadata for conversational_flow agents
    agent_mode = getattr(db_agent, 'mode', 'single_prompt')
    if agent_mode == 'conversational_flow':
        graph_data = getattr(db_agent, 'graph', None)
        if graph_data:
            try:
                config.graph_json = graph_data
                config.flow_agent_id = db_agent.id
                config.flow_user_id = db_agent.user_id
                # Keep DB initial_message so FlowAgent can speak a cached static
                # greeting immediately (nodes.py static path). StreamingConversation
                # must NOT also send it — FlowAgent owns greeting for flow mode.
                object.__setattr__(config, "_flow_owns_greeting", True)
                # Flow manages actions via action nodes — disable in-call tool calling
                config.actions = []
                logger.info(f"Agent {db_agent.id} configured as conversational_flow with graph from workflow")
            except Exception as e:
                logger.warning(f"Failed to set flow config for agent {db_agent.id}: {e}. Falling back to single_prompt.")
                config.graph_json = None

    logger.info(
        f"Built LLM config: provider={provider}, model={model}, "
        f"base_url={'custom' if base_url else 'default'}"
    )

    # Cache serializable parameters for future calls
    # NOTE: api_key is NOT cached to prevent plaintext key leakage.
    # It is re-resolved from DB on every cache hit via _resolve_llm_api_key.
    # NOTE: prompt_preamble is NOT cached to prevent leakage of
    # tool instructions, security guards, and Drive appendices.
    # It is rebuilt from db_agent on every cache hit.
    cache_dict = {
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "initial_message": db_agent.initial_message,
        "temperature": db_agent.temperature or 0.7,
        "max_tokens": db_agent.max_tokens or LLM_AGENT_DEFAULT_MAX_TOKENS,
        "knowledge_base_id": getattr(db_agent, 'knowledge_base_id', None),
        "end_on_goodbye": db_agent.end_on_goodbye if db_agent.end_on_goodbye is not None else False,
        "interrupt_sensitivity": db_agent.interrupt_sensitivity or "low",
        "allowed_idle_time_seconds": (
            db_agent.allowed_idle_time_seconds
            if hasattr(db_agent, 'allowed_idle_time_seconds') and db_agent.allowed_idle_time_seconds is not None
            else 60.0
        ),
        "num_check_human_present_times": (
            db_agent.num_check_human_present_times
            if hasattr(db_agent, 'num_check_human_present_times') and db_agent.num_check_human_present_times is not None
            else 2
        ),
        "initial_message_delay": (
            db_agent.initial_message_delay
            if hasattr(db_agent, 'initial_message_delay') and db_agent.initial_message_delay is not None
            else 0.2
        ),
        "filler_enabled": _filler_enabled,
        "filler_supported": _filler_supported,
        "selected_version_id": selected_version_id,
        "drive_integration_id": getattr(db_agent, "google_drive_integration_id", None),
    }
    await RedisCache.set(cache_key, cache_dict, ttl_seconds=300)

    return config


async def _rebuild_config_from_cache(cached: dict, db_agent) -> AgentConfig:
    """Rebuild a ChatGPTAgentConfig from cached serializable parameters."""
    from voice_platform.actions.platform_tools import build_tool_actions

    # Rebuild actions from DB (never cached — may change between calls)
    tool_actions: List[Any] = []
    skipped_tools: list = []
    if hasattr(db_agent, 'tools_config') and db_agent.tools_config:
        try:
            import json as _json
            tools_list = _json.loads(db_agent.tools_config) if isinstance(db_agent.tools_config, str) else db_agent.tools_config
            if tools_list:
                bindings = {}
                if hasattr(db_agent, 'mcp_bindings_json') and db_agent.mcp_bindings_json:
                    try:
                        bindings = json.loads(db_agent.mcp_bindings_json)
                    except Exception:
                        pass
                instructions = getattr(db_agent, 'tool_instructions', None)
                overrides = {}
                if hasattr(db_agent, 'integration_overrides_json') and db_agent.integration_overrides_json:
                    try:
                        overrides = json.loads(db_agent.integration_overrides_json)
                    except Exception:
                        pass
                tool_actions, skipped_tools = await build_tool_actions(tools_list, db_agent.user_id, bindings, instructions, overrides, agent_timezone=getattr(db_agent, 'timezone', None))
                logger.info(f"Rebuilt {len(tool_actions)} in-call tools from cache for agent {db_agent.name}")
        except Exception as e:
            logger.warning(f"Failed to rebuild tools_config from cache: {e}")

    _filler_config = (
        FillerAudioConfig(
            silence_threshold_seconds=0.3,
            use_phrases=True,
            use_typing_noise=False,
        )
        if (cached.get("filler_enabled") and cached.get("filler_supported"))
        else False
    )

    # Optional Google Drive MCP integration attached directly to the agent.
    drive_tool_actions = await _build_google_drive_tool_actions(db_agent)
    if drive_tool_actions:
        # Issue 07: Deduplicate by tool_name — MCP discovery may return tools
        # that already exist in tool_actions from PLATFORM_TOOLS (e.g. read_drive_file)
        existing_names = {
            getattr(a, "tool_name", "")
            for a in tool_actions
        }
        for dt in drive_tool_actions:
            if getattr(dt, "tool_name", "") not in existing_names:
                tool_actions.append(dt)

    # Re-resolve API key from DB (never cached for security)
    _provider = cached.get("provider", db_agent.llm_provider.lower())
    _user_api_keys = []
    if db_agent.user_id:
        from voice_platform.database import UserApiKey
        async with async_session() as session:
            key_result = await session.execute(
                select(UserApiKey).where(
                    UserApiKey.user_id == db_agent.user_id,
                    UserApiKey.is_active == True,
                )
            )
            _user_api_keys = key_result.scalars().all()
    _api_key = _resolve_llm_api_key(_provider, db_agent, _user_api_keys)

    # ── Prompt Assembly (delegated to PromptRenderer) ───────────────────
    render_result = PromptRenderer.render(RenderContext(
        db_agent=db_agent,
        tool_actions=tool_actions,
        skipped_tools=skipped_tools,
        drive_tool_actions=drive_tool_actions,
        tools_config=getattr(db_agent, 'tools_config', None),
    ))
    _selected_prompt = render_result.prompt
    _selected_version_id = render_result.version_id

    config = ChatGPTAgentConfig(
        openai_api_key=_api_key,
        base_url_override=cached.get("base_url"),
        model_name=cached["model"],
        prompt_preamble=_selected_prompt,
        initial_message=_make_initial_message(cached.get("initial_message")),
        temperature=cached.get("temperature", 0.7),
        max_tokens=cached.get("max_tokens", LLM_AGENT_DEFAULT_MAX_TOKENS),
        generate_responses=True,
        knowledge_base_id=cached.get("knowledge_base_id"),
        end_conversation_on_goodbye=cached.get("end_on_goodbye", False),
        goodbye_phrases=["goodbye", "talk to you later", "have a good day", "end the call"],
        interrupt_sensitivity=cached.get("interrupt_sensitivity", "low"),
        allowed_idle_time_seconds=cached.get("allowed_idle_time_seconds", 60.0),
        num_check_human_present_times=cached.get("num_check_human_present_times", 2),
        initial_message_delay=cached.get("initial_message_delay", 0.2),
        send_filler_audio=_filler_config,
        actions=tool_actions,  # Rebuilt from fresh DB state
    )

    object.__setattr__(config, '_selected_prompt_version_id', _selected_version_id)

    # Flow agent support: set graph_json and flow metadata for conversational_flow agents (cache hit path)
    agent_mode = getattr(db_agent, 'mode', 'single_prompt')
    if agent_mode == 'conversational_flow':
        graph_data = getattr(db_agent, 'graph', None)
        if graph_data:
            try:
                config.graph_json = graph_data
                config.flow_agent_id = db_agent.id
                config.flow_user_id = db_agent.user_id
                # Keep DB initial_message; FlowAgent owns greeting for flow mode.
                object.__setattr__(config, "_flow_owns_greeting", True)
                config.actions = []
                logger.info(f"Agent {db_agent.id} configured as conversational_flow (cache hit)")
            except Exception as e:
                logger.warning(f"Failed to set flow config for agent {db_agent.id} (cache hit): {e}. Falling back to single_prompt.")
                config.graph_json = None

    return config



async def _build_google_drive_tool_actions(db_agent) -> list[Any]:
    """
    Build tool actions for a Google Drive integration.

    Uses GoogleDriveClient (REST API v3) via the workflow executor for reliable
    file access. The external MCP server (drivemcp.googleapis.com) is skipped
    because its availability is unreliable — the direct REST client handles
    OAuth resolution and token refresh internally.
    """
    integration_id = getattr(db_agent, "google_drive_integration_id", None)
    if not integration_id:
        return []

    from voice_platform.actions.platform_tools import PlatformToolActionConfig

    # Verify the integration exists and is active
    async with async_session() as session:
        result = await session.execute(
            select(Integration).where(
                Integration.id == integration_id,
                Integration.user_id == db_agent.user_id,
                Integration.service_type == "google_drive_mcp",
                Integration.is_active == True,
            )
        )
        integration = result.scalar_one_or_none()
        if not integration:
            logger.warning(
                f"Agent {getattr(db_agent, 'id', '?')} references missing Google Drive integration {integration_id}"
            )
            return []

    # Always use direct REST API via GoogleDriveClient — skip unreliable MCP discovery.
    # The executor's _execute_drive_action handles OAuth resolution and token refresh.
    action = PlatformToolActionConfig(
        tool_name="read_drive_file",
        tool_description=(
            "Read content from a specific file that this agent has been given access to. "
            "Use this when the caller asks about data stored in a specific document. "
            "After reading, summarize the key information and remember it for the rest of the call."
        ),
        tool_parameters_schema=json.dumps({
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "File ID"},
                "file_name": {"type": "string", "description": "Human-readable file name for reference"},
            },
            "required": ["file_id"],
        }),
        integration_type="google_drive_mcp",
        integration_action="read_file_content",
        user_id=db_agent.user_id,
    )
    logger.info(f"Added Google Drive read_file action (direct REST API) for agent {getattr(db_agent, 'name', '?')}")
    return [action]


# ═══════════════════════════════════════════════════════════════════════
# STT (Speech-to-Text) Config Builder
# ═══════════════════════════════════════════════════════════════════════

def build_transcriber_config(db_agent, user_api_keys: list = None) -> TranscriberConfig:
    """
    Build a vocode TranscriberConfig from a database Agent row.
    
    All configs use Twilio telephone defaults (8kHz mulaw).
    API key resolution:
        1. User's key from UserApiKey table
        2. Agent-level stt_api_key
        3. Platform .env default
    """
    provider = db_agent.stt_provider.lower()
    language = db_agent.stt_language or "en-US"
    
    # Resolve endpointing strategy from DB agent config
    endpointing_type = getattr(db_agent, 'endpointing_type', 'auto') or 'auto'
    
    if endpointing_type == 'auto':
        # DeepgramEndpointingConfig uses Deepgram's built-in VAD.
        # Best for telephony — handles background noise, non-punctuated speech,
        # and partial utterances much better than punctuation-based.
        endpointing = DeepgramEndpointingConfig(
            vad_threshold_ms=300,       # 300ms silence = end of utterance (low-latency)
            utterance_cutoff_ms=1000,   # Hard cutoff at 1s silence (Deepgram minimum)
        )
    elif endpointing_type == 'time':
        endpointing = TimeEndpointingConfig(time_cutoff_seconds=1.0)
    else:
        endpointing = PunctuationEndpointingConfig()
    
    # Minimum confidence to allow an interrupt (prevents background noise triggers)
    interrupt_confidence = (
        getattr(db_agent, 'min_interrupt_confidence', 0.6) or 0.6
    )
    
    # Common params for all telephone transcribers
    base_params = dict(
        sampling_rate=DEFAULT_SAMPLING_RATE,
        audio_encoding=DEFAULT_AUDIO_ENCODING,
        chunk_size=DEFAULT_CHUNK_SIZE,
        endpointing_config=endpointing,
        min_interrupt_confidence=interrupt_confidence,
    )
    
    if provider == "deepgram":
        # Resolve Deepgram key: UserApiKey → agent key → platform .env
        api_key = None
        if user_api_keys:
            for key_row in user_api_keys:
                if key_row.service == "deepgram" and key_row.is_active:
                    api_key = decrypt(key_row.api_key)
                    logger.debug("Using user API key for Deepgram (from user_api_keys table)")
                    break
        if not api_key:
            api_key = (_decrypt_agent_key(db_agent.stt_api_key, "STT") if db_agent.stt_api_key else None) or settings.deepgram_api_key
        if not api_key:
            raise ValueError(
                "No Deepgram API key. Set in agent settings or DEEPGRAM_API_KEY env var."
            )
        
        # Nova-3 is Deepgram's flagship model with best accuracy across
        # noisy environments, accents, and low-quality audio.
        stt_model = getattr(db_agent, 'stt_model', 'nova-3') or 'nova-3'
        
        config = DeepgramTranscriberConfig(
            **base_params,
            model=stt_model,
            language=language,
            api_key=api_key,
            smart_format=getattr(db_agent, 'stt_smart_format', True),
            diarize=getattr(db_agent, 'stt_diarize', True),
            filter_filler_words=getattr(db_agent, 'stt_filter_filler_words', False),
        )
        logger.info(f"Built Deepgram STT: language={language}, model={stt_model}, endpointing={endpointing_type}")
        return config
    
    elif provider == "google":
        config = GoogleTranscriberConfig(
            **base_params,
            language_code=language,
        )
        logger.info(f"Built Google STT: language={language}")
        return config
    
    elif provider == "azure":
        # Azure STT reads AZURE_SPEECH_KEY and AZURE_SPEECH_REGION from env vars
        # These are set via .env → dotenv at startup
        if not os.environ.get("AZURE_SPEECH_KEY"):
            logger.warning(
                "AZURE_SPEECH_KEY not set in env. Azure STT will fail. "
                "Set it in .env or use a different STT provider."
            )
        config = AzureTranscriberConfig(
            **base_params,
            language=language,
        )
        logger.info(f"Built Azure STT: language={language}")
        return config
    
    elif provider == "assemblyai":
        config = AssemblyAITranscriberConfig(
            **base_params,
        )
        logger.info("Built AssemblyAI STT")
        return config
    
    else:
        logger.warning(f"Unknown STT provider '{provider}', falling back to Deepgram")
        return DeepgramTranscriberConfig(
            **base_params,
            model=db_agent.stt_model or settings.default_stt_model or "nova-3",
            language="en-US",
            api_key=settings.deepgram_api_key,
        )


# ═══════════════════════════════════════════════════════════════════════
# TTS (Text-to-Speech) Config Builder
# ═══════════════════════════════════════════════════════════════════════

def build_synthesizer_config(db_agent, user_api_keys: list = None) -> SynthesizerConfig:
    """
    Build a vocode SynthesizerConfig from a database Agent row.
    
    All configs use telephone output defaults (8kHz for Twilio).
    API key resolution:
        1. User's key from UserApiKey table
        2. Agent-level tts_api_key
        3. Platform .env default
    """
    provider = (db_agent.tts_provider or "gtts").lower()
    
    # Helper to resolve TTS API key
    def _resolve_tts_key(service_name: str):
        if user_api_keys:
            for key_row in user_api_keys:
                if key_row.service == service_name and key_row.is_active:
                    logger.debug(f"Using user API key for {service_name} (from user_api_keys table)")
                    return decrypt(key_row.api_key)
        return None
    
    if provider == "deepgram":
        api_key = _resolve_tts_key("deepgram") or (_decrypt_agent_key(db_agent.tts_api_key, "TTS") if db_agent.tts_api_key else None) or settings.deepgram_api_key
        if not api_key:
            logger.warning(
                "No Deepgram API key for TTS — falling back to gTTS. "
                "Set DEEPGRAM_API_KEY in .env or agent settings."
            )
            return GTTSSynthesizerConfig.from_telephone_output_device()

        voice = db_agent.tts_voice_id or settings.default_tts_voice or "aura-asteria-en"
        config = DeepgramSynthesizerConfig.from_telephone_output_device(
            api_key=api_key,
            voice=voice,
        )
        logger.info(f"Built Deepgram TTS: voice={voice}")
        return config
    
    elif provider == "gtts":
        config = GTTSSynthesizerConfig.from_telephone_output_device()
        logger.info("Built gTTS synthesizer (free)")
        return config
    
    elif provider == "elevenlabs":
        api_key = _resolve_tts_key("elevenlabs") or (_decrypt_agent_key(db_agent.tts_api_key, "TTS") if db_agent.tts_api_key else None) or settings.elevenlabs_api_key
        if not api_key:
            logger.warning(
                "No ElevenLabs API key — falling back to gTTS. "
                "Set ELEVENLABS_API_KEY in .env or agent settings."
            )
            return GTTSSynthesizerConfig.from_telephone_output_device()
        
        config = ElevenLabsSynthesizerConfig.from_telephone_output_device(
            api_key=api_key,
            voice_id=db_agent.tts_voice_id or "pNInz6obpgDQGcFmaJgB",  # Adam
            model_id="eleven_turbo_v2",  # Low-latency model for telephony
            optimize_streaming_latency=3,  # 3 = aggressive latency optimization
            stability=0.5,
            similarity_boost=0.5,
        )
        logger.info(f"Built ElevenLabs TTS: voice={db_agent.tts_voice_id or 'Adam'}")
        return config
    
    elif provider == "azure":
        # Azure TTS reads AZURE_SPEECH_KEY and AZURE_SPEECH_REGION from env vars
        if not os.environ.get("AZURE_SPEECH_KEY"):
            logger.warning(
                "AZURE_SPEECH_KEY not set — falling back to gTTS. "
                "Set it in .env or use a different TTS provider."
            )
            return GTTSSynthesizerConfig.from_telephone_output_device()
        
        config = AzureSynthesizerConfig.from_telephone_output_device(
            voice_name=db_agent.tts_voice_id or "en-US-SteffanNeural",
        )
        logger.info(f"Built Azure TTS: voice={db_agent.tts_voice_id or 'en-US-SteffanNeural'}")
        return config
    
    elif provider == "cartesia":
        api_key = _resolve_tts_key("cartesia") or (_decrypt_agent_key(db_agent.tts_api_key, "TTS") if db_agent.tts_api_key else None) or settings.cartesia_api_key
        if not api_key:
            logger.warning("No Cartesia API key — falling back to gTTS.")
            return GTTSSynthesizerConfig.from_telephone_output_device()
        
        config = CartesiaSynthesizerConfig.from_telephone_output_device(
            api_key=api_key,
            voice_id=db_agent.tts_voice_id or "f9836c6e-a0bd-460e-9d3c-f7299fa60f94",
        )
        logger.info("Built Cartesia TTS")
        return config
    
    elif provider == "polly":
        config = PollySynthesizerConfig.from_telephone_output_device(
            voice_id=db_agent.tts_voice_id or "Matthew",
        )
        logger.info(f"Built Polly TTS: voice={db_agent.tts_voice_id or 'Matthew'}")
        return config
    
    elif provider == "streamelements":
        config = StreamElementsSynthesizerConfig.from_telephone_output_device(
            voice=db_agent.tts_voice_id or "Brian",
        )
        logger.info(f"Built StreamElements TTS: voice={db_agent.tts_voice_id or 'Brian'}")
        return config
    
    else:
        logger.warning(f"Unknown TTS provider '{provider}', falling back to gTTS")
        return GTTSSynthesizerConfig.from_telephone_output_device()


# ═══════════════════════════════════════════════════════════════════════
# Language Override Helper (GAP-07)
# ═══════════════════════════════════════════════════════════════════════

def _apply_language_overrides(db_agent, agent_config, transcriber_config, synthesizer_config):
    """
    Auto-configure STT/TTS/prompt based on agent's language setting.

    Called after all three configs are built to apply language-aware overrides
    from voice_platform/constants.py.

    Skips en-US (the platform default) because English doesn't need
    STT/TTS overrides or a "Respond in English" prompt suffix.
    """
    from voice_platform.constants import LANGUAGE_CONFIGS

    lang = getattr(db_agent, "language", None) or "en-US"

    # For en-US, skip STT/TTS overrides but still append the language suffix
    # to prevent the LLM from switching languages mid-call (e.g. Urdu examples
    # in the prompt causing the LLM to respond in Urdu).
    if lang not in LANGUAGE_CONFIGS:
        return

    if lang == "en-US":
        if hasattr(agent_config, "prompt_preamble"):
            agent_config.prompt_preamble = (
                agent_config.prompt_preamble + "\n\n" + LANGUAGE_CONFIGS["en-US"]["prompt_suffix"]
            )
        logger.info("Applied en-US language suffix to prevent language drift")
        return

    cfg = LANGUAGE_CONFIGS[lang]

    # Override STT language
    if hasattr(transcriber_config, "language"):
        transcriber_config.language = cfg["stt_language"]
    elif hasattr(transcriber_config, "language_code"):
        transcriber_config.language_code = cfg["stt_language"]

    # Override TTS voice if provider matches
    synth_provider = getattr(synthesizer_config, "__class__", type(synthesizer_config)).__name__.lower()
    if cfg["tts_provider"] in synth_provider:
        if hasattr(synthesizer_config, "voice_id"):
            synthesizer_config.voice_id = cfg["tts_voice_id"]
        elif hasattr(synthesizer_config, "voice"):
            synthesizer_config.voice = cfg["tts_voice_id"]
        elif hasattr(synthesizer_config, "voice_name"):
            synthesizer_config.voice_name = cfg["tts_voice_id"]

    # Append language instruction to prompt
    if cfg.get("prompt_suffix") and hasattr(agent_config, "prompt_preamble"):
        agent_config.prompt_preamble = (
            agent_config.prompt_preamble + "\n\n" + cfg["prompt_suffix"]
        )

    logger.info(f"Applied language overrides for '{lang}': stt={cfg['stt_language']}, tts_voice={cfg['tts_voice_id']}")


# ═══════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════

def _make_initial_message(text: Optional[str]):
    """
    Convert an initial message string to a BaseMessage object.
    vocode expects BaseMessage, not a plain string.
    Returns None if no initial message (agent stays silent until caller speaks).
    """
    if text:
        return BaseMessage(text=text)
    return None


async def _get_configs_for_agent(agent_id: int):
    """
    Load configuration for a specific agent by ID.

    Used for phone-number → agent routing: when a PhoneNumberMapping
    matches the dialed number, we load the exact agent assigned to it.

    Args:
        agent_id: Primary key of the Agent row to load.

    Returns:
        Tuple of (AgentConfig, TranscriberConfig, SynthesizerConfig)

    Raises:
        ValueError: If agent_id does not exist or is inactive.
    """
    from sqlalchemy import select

    from voice_platform.database import Agent, UserApiKey, async_session

    from sqlalchemy.orm import selectinload

    async with async_session() as session:
        result = await session.execute(
            select(Agent)
            .options(selectinload(Agent.linked_workflow))
            .where(Agent.id == agent_id, Agent.is_active == True)
        )
        db_agent = result.scalar_one_or_none()

    if not db_agent:
        raise ValueError(f"Agent #{agent_id} not found or inactive")

    user_api_keys = []
    if db_agent.user_id:
        async with async_session() as session:
            key_result = await session.execute(
                select(UserApiKey).where(
                    UserApiKey.user_id == db_agent.user_id,
                    UserApiKey.is_active == True,
                )
            )
            user_api_keys = key_result.scalars().all()

    logger.info(f"Using mapped agent: '{db_agent.name}' #{db_agent.id} ({db_agent.llm_provider}/{db_agent.llm_model})")
    agent_config = await build_agent_config(db_agent, user_api_keys)
    transcriber_config = build_transcriber_config(db_agent, user_api_keys)
    synthesizer_config = build_synthesizer_config(db_agent, user_api_keys)
    _apply_language_overrides(db_agent, agent_config, transcriber_config, synthesizer_config)
    return (agent_config, transcriber_config, synthesizer_config)


async def _get_default_configs():
    """
    Load the default agent configuration from the database.

    Looks for the first active agent in the DB. If none exists,
    creates a fallback config using platform defaults.

    Returns:
        Tuple of (AgentConfig, TranscriberConfig, SynthesizerConfig)
    """
    from voice_platform.database import Agent, UserApiKey, async_session

    try:
        async with async_session() as session:
            result = await session.execute(
                select(Agent).where(Agent.is_active == True).limit(1)
            )
            db_agent = result.scalar_one_or_none()

        if db_agent:
            user_api_keys = []
            if db_agent.user_id:
                async with async_session() as session:
                    key_result = await session.execute(
                        select(UserApiKey).where(
                            UserApiKey.user_id == db_agent.user_id,
                            UserApiKey.is_active == True,
                        )
                    )
                    user_api_keys = key_result.scalars().all()

            logger.info(f"Using DB agent: '{db_agent.name}' ({db_agent.llm_provider}/{db_agent.llm_model})")
            agent_config = await build_agent_config(db_agent, user_api_keys)
            transcriber_config = build_transcriber_config(db_agent, user_api_keys)
            synthesizer_config = build_synthesizer_config(db_agent, user_api_keys)
            _apply_language_overrides(db_agent, agent_config, transcriber_config, synthesizer_config)
            return (agent_config, transcriber_config, synthesizer_config)
    except Exception as e:
        logger.warning(f"Could not load agent from DB: {e}")

    # Fallback: Create default configs from .env settings
    logger.info("No DB agent found — using default configuration")

    agent_config = ChatGPTAgentConfig(
        openai_api_key=settings.openrouter_api_key or settings.groq_api_key,
        base_url_override="https://openrouter.ai/api/v1" if settings.openrouter_api_key else "https://api.groq.com/openai/v1",
        model_name=settings.default_llm_model,
        prompt_preamble=(
            "You are a helpful AI voice assistant for VOIA platform. "
            "Be concise, friendly, and professional. "
            "Respond naturally as if speaking to someone on the phone."
        ),
        initial_message=BaseMessage(
            text="Hello! Thank you for calling VOIA. How can I help you today?"
        ),
        temperature=0.7,
        max_tokens=LLM_AGENT_DEFAULT_MAX_TOKENS,
        generate_responses=True,
        allowed_idle_time_seconds=60.0,
        num_check_human_present_times=2,
        initial_message_delay=0.4,
        send_filler_audio=True,
    )

    deepgram_key = settings.deepgram_api_key or ""
    if not deepgram_key:
        logger.error(
            "⚠️ DEEPGRAM_API_KEY not set! STT will fail on inbound calls. "
            "Set it in .env or add a user API key via /api/keys"
        )

    transcriber_config = DeepgramTranscriberConfig(
        sampling_rate=DEFAULT_SAMPLING_RATE,
        audio_encoding=DEFAULT_AUDIO_ENCODING,
        chunk_size=DEFAULT_CHUNK_SIZE,
        model="nova-3",
        language="en-US",
        api_key=deepgram_key,
        endpointing_config=DeepgramEndpointingConfig(
            vad_threshold_ms=300,
            utterance_cutoff_ms=1000,
        ),
        min_interrupt_confidence=0.6,
        smart_format=True,
        diarize=True,
        filter_filler_words=False,
    )

    if deepgram_key:
        synthesizer_config = DeepgramSynthesizerConfig.from_telephone_output_device(
            api_key=deepgram_key,
            voice="aura-asteria-en",
        )
    else:
        synthesizer_config = GTTSSynthesizerConfig.from_telephone_output_device()

    return agent_config, transcriber_config, synthesizer_config
