"""
Voice Platform — Configuration
=================================

Central configuration for the VOIA voice agent platform.
All settings are loaded from the .env file via pydantic-settings.

Settings categories:
    - Server: Host, port, base URL
    - ngrok: Auto-tunnel for development
    - Twilio: Phone call infrastructure
    - Deepgram: Speech-to-text API
    - OpenAI: LLM API
    - Azure: TTS + STT services
    - ElevenLabs: High-quality TTS
    - Redis: Call config storage (vocode uses Redis to store active call configs)
    - Google OAuth: Authentication
    - JWT: Token signing
    - Platform: Default values
"""

from typing import Optional  # For optional config fields

from pydantic_settings import BaseSettings  # Settings with .env loading


class PlatformSettings(BaseSettings):
    """
    Central configuration loaded from .env file.
    
    Field names are case-insensitive and match .env variable names.
    Example: `openai_api_key` matches `OPENAI_API_KEY` in .env.
    
    Optional fields have defaults — only required fields must be in .env.
    """

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    # ── Server ──────────────────────────────────────────────────────
    # base_url: Public URL for Twilio webhooks. If not set, ngrok is used.
    base_url: Optional[str] = None
    # host: What network interface to bind to (0.0.0.0 = all interfaces)
    host: str = "0.0.0.0"
    # port: Server port number
    port: int = 3000

    # ── ngrok (auto-tunnel if no BASE_URL) ──────────────────────────
    # When developing locally, ngrok creates a public URL that Twilio
    # can reach. Set NGROK_AUTH_TOKEN to enable this.
    ngrok_auth_token: Optional[str] = None

    # ── Twilio ──────────────────────────────────────────────────────
    # Required for handling phone calls (optional if not using telephony)
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None  # Your Twilio phone number

    # ── STT: Deepgram ───────────────────────────────────────────────
    # Default speech-to-text provider API key (optional if users provide their own)
    deepgram_api_key: Optional[str] = None

    # ── LLM: OpenAI ─────────────────────────────────────────────
    # Default LLM provider API key (optional if users provide their own)
    openai_api_key: Optional[str] = None
    openai_api_base: Optional[str] = None

    # ── LLM: Gemini (Optional) ──────────────────────────────────────
    # Google Gemini via OpenAI-compatible API — only needed if users select Gemini
    gemini_api_key: Optional[str] = None

    # ── LLM: Groq (Optional) ────────────────────────────────────────
    # Fast inference via Groq — only needed if users select Groq provider
    groq_api_key: Optional[str] = None

    # ── LLM: Anthropic (via OpenRouter proxy) ───────────────────────
    # NOTE: This requires an OpenRouter API key, NOT a native Anthropic key.
    # Get your key at https://openrouter.ai and set ANTHROPIC_API_KEY in .env.
    # Anthropic is excluded from the in-browser Playground (see playground_routes.py).
    anthropic_api_key: Optional[str] = None

    # ── LLM: OpenRouter ─────────────────────────────────────────────
    # OpenRouter provides unified access to many models via an OpenAI-compatible API.
    # Get your key at https://openrouter.ai and set OPENROUTER_API_KEY in .env.
    openrouter_api_key: Optional[str] = None

    # ── LLM: CommandCode (Optional) ─────────────────────────────────
    # CommandCode Provider API — OpenAI-compatible endpoint with discounted models
    # Get your key at commandcode.ai/studio/api-keys
    commandcode_api_key: Optional[str] = None

    # ── LLM: Ollama (Local) ─────────────────────────────────────────
    # Local LLM via Ollama's OpenAI-compatible endpoint
    # host.docker.internal is used so the Docker container can reach the host's Ollama
    ollama_base_url: str = "http://host.docker.internal:11434/v1"
    ollama_api_key: str = "ollama"  # Dummy key — Ollama doesn't auth, but OpenAI SDK requires non-empty

    # ── TTS: Azure ──────────────────────────────────────────────────
    # Azure Speech Services for high-quality TTS and STT
    # Note: Azure STT/TTS read AZURE_SPEECH_KEY and AZURE_SPEECH_REGION
    # from env vars directly at runtime (vocode handles this internally)
    azure_speech_key: Optional[str] = None
    azure_speech_region: Optional[str] = "eastus"

    # ── TTS: ElevenLabs ─────────────────────────────────────────────
    # Premium voice cloning and neural TTS
    # Field name must match env var: ELEVENLABS_API_KEY → elevenlabs_api_key
    elevenlabs_api_key: Optional[str] = None

    # ── TTS: Cartesia ───────────────────────────────────────────────
    # Ultra-low latency TTS
    cartesia_api_key: Optional[str] = None

    # ── STT: AssemblyAI ─────────────────────────────────────────────
    assemblyai_api_key: Optional[str] = None

    # ── Email: SMTP ─────────────────────────────────────────────────
    # Default SMTP credentials for sending emails (appointment confirmations, etc.)
    # Users can override by connecting their own email integration.
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from_email: Optional[str] = None
    smtp_from_name: str = "VOIA Platform"
    smtp_use_tls: bool = True

    # ── Redis ───────────────────────────────────────────────────────

    # vocode uses Redis to store active call configurations.
    # When a call comes in, the call config is saved to Redis.
    # When the WebSocket connects, it retrieves the config from Redis.
    redis_url: str = "redis://localhost:6379"

    # ── Google OAuth ────────────────────────────────────────────────
    # Required for user authentication (Google Sign-In)
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    # Canonical Google OAuth callback URL used by the frontend and backend.
    google_oauth_redirect_uri: Optional[str] = None

    # ── JWT ──────────────────────────────────────────────────────────
    # No forgeable default ships in code. For local Tier 0, either set
    # JWT_SECRET in .env (≥32 chars) or enable ALLOW_DEV_LOGIN (server
    # generates an ephemeral secret for the process lifetime).
    jwt_secret: str = ""

    # ── Encryption ───────────────────────────────────────────────────
    # Fernet key for encrypting API keys at rest.
    # If not set, derived automatically from jwt_secret via PBKDF2.
    # Generate one: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: Optional[str] = None

    # ── Webhooks ─────────────────────────────────────────────────────
    # GAP-03: Secret for signing webhook payloads (HMAC-SHA256).
    # Falls back to jwt_secret if not set. Used by WebhookDispatcher.
    webhook_signing_secret: Optional[str] = None

    # ── Platform Defaults ───────────────────────────────────────────
    # These are used when no agent-specific settings are provided
    default_llm_model: str = "deepseek/deepseek-v4-flash"
    default_stt_model: str = "nova-3"
    default_tts_voice: str = "aura-asteria-en"
    log_level: str = "DEBUG"
    # Development auth bypass (POST /api/auth/dev-login).
    # Keep disabled by default and explicitly enable only for local development.
    allow_dev_login: bool = False
    # Legacy websocket token auth via ?token=. Keep disabled by default to
    # avoid token leakage through URL logs.
    allow_ws_query_token_auth: bool = False
    # Phase 3: Sandboxed code nodes (user-submitted Python execution).
    # Disabled by default because the current sandbox is bypassable. Only
    # enable after replacing exec() with a real sandbox (subprocess/WASM).
    enable_sandboxed_code_nodes: bool = False
    # Allow falling back to platform Twilio credentials for read-only routes.
    # Mutating Twilio routes should require per-user credentials.
    allow_platform_twilio_fallback: bool = True
    # Campaign execution fallback to platform Twilio credentials.
    # Keep disabled by default to avoid cross-tenant resource usage.
    allow_platform_twilio_fallback_for_campaigns: bool = False
    # Twilio webhook request signature handling.
    # - require_twilio_webhook_signature=False keeps local/dev callbacks working
    #   when no signature header is present.
    # - validate_twilio_webhook_if_present=True still rejects spoofed requests
    #   whenever a signature header is provided.
    require_twilio_webhook_signature: bool = False
    validate_twilio_webhook_if_present: bool = True

    # ── Compliance ─────────────────────────────────────────────────
    # Phase 3: TSR/TCPA calling hours enforcement (8AM-9PM local).
    # Disable only for dev/test environments.
    enforce_calling_hours: bool = True

    # ── Database ─────────────────────────────────────────────────
    # Default: SQLite for local development
    # Production: Set DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/voia
    database_url: Optional[str] = None

    # ── Manual Test Mode ─────────────────────────────────────────
    # When true, exposes sanitized debug events through the developer console,
    # WebSocket event stream, or test response payload. Must NOT alter routing,
    # prompts, tool success, or validation. Must NOT be enabled by default.
    manual_test_mode: bool = False

    # ── CORS ─────────────────────────────────────────────────────
    # Comma-separated list of allowed origins.
    # PRODUCTION: Set to your frontend URL(s), e.g. "https://app.voia.com"
    # DEVELOPMENT: Use "*" (default) for open access
    cors_allowed_origins: str = "*"


# ── Singleton Instance ──────────────────────────────────────────────
# Created once at import time. All modules import this single instance.
# This avoids loading .env multiple times.
settings = PlatformSettings()
