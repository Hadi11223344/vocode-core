"""
Voice Platform — Database Layer
================================

This module defines all SQLAlchemy ORM models and the database engine
for the VOIA voice agent platform. It uses async SQLite for zero-setup
persistence (perfect for FYP / development).

Tables:
    - users:         Authenticated user accounts (Google OAuth)
    - user_api_keys: Per-user, per-service API keys (OpenAI, Gemini, Deepgram, etc.)
    - agents:        Voice agent configurations (LLM/STT/TTS providers)
    - call_logs:     Records of every phone call handled
    - transcripts:   Individual messages within a call
    - action_logs:   Actions executed during calls (e.g. schedule, transfer)
    - workflows:     Intent-based routing rules with integration steps
    - integrations:  User-connected third-party services (Google Calendar, Sheets)
    - settings:      Platform-wide key-value configuration
    - review_queue:  Human-in-the-loop approval queue

Usage:
    from voice_platform.database import async_session, init_db, User, Agent, ...
    
    # Initialize on startup:
    await init_db()
    
    # Use in routes:
    async with async_session() as session:
        user = await session.get(User, user_id)
"""

import json
import os  # For building database file path
from datetime import datetime, timezone  # For timestamp columns
from typing import Optional  # For type hints on computed properties

from loguru import logger  # Structured logging
from sqlalchemy import Boolean  # For is_active, end_on_goodbye, etc.
from sqlalchemy import Column  # Defines a table column
from sqlalchemy import DateTime  # Timestamp columns (timezone=True for PostgreSQL compat)
from sqlalchemy import Float  # For temperature, duration_secs
from sqlalchemy import ForeignKey  # Foreign key relationships between tables
from sqlalchemy import Index  # Database indexes for query performance
from sqlalchemy import Integer  # Integer primary keys, max_tokens, etc.
from sqlalchemy import String  # VARCHAR columns (name, email, etc.)
from sqlalchemy import Text  # Long text columns (prompt_preamble, messages)
from sqlalchemy import UniqueConstraint  # Unique constraints for data integrity
from sqlalchemy import text  # Raw SQL expressions

# (create_engine removed — unused; async engine is used exclusively)
from sqlalchemy.ext.asyncio import AsyncSession  # Async database session for queries
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,  # Factory for creating async database sessions
)
from sqlalchemy.ext.asyncio import create_async_engine  # Creates async-compatible SQLite engine
from sqlalchemy.orm import DeclarativeBase  # Base class for all ORM models
from sqlalchemy.orm import relationship  # Defines relationships between tables

# ── Database Engine Setup ──────────────────────────────────────────────
# Supports both SQLite (development) and PostgreSQL (production).
# Set DATABASE_URL env var for production, e.g.:
#   DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/voia
# Default: SQLite in the voice_platform directory.

def _build_database_url() -> str:
    """Resolve the database URL from config or use SQLite default."""
    from voice_platform.config import settings as _settings
    if _settings.database_url:
        return _settings.database_url
    db_dir = os.path.dirname(os.path.abspath(__file__))
    return f"sqlite+aiosqlite:///{os.path.join(db_dir, 'voia.db')}"

DATABASE_URL = _build_database_url()
_is_sqlite = DATABASE_URL.startswith("sqlite")

# Create the async engine:
# - echo=False: Don't log every SQL query (set True for debugging)
# - connect_args: SQLite-specific — allow multi-threaded access
# - pool_size/max_overflow: PostgreSQL connection pooling (TEL-15)
_engine_kwargs: dict = {"echo": False}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL / production pooling
    _engine_kwargs["pool_size"] = 20
    _engine_kwargs["max_overflow"] = 40
    _engine_kwargs["pool_recycle"] = 3600  # Recycle connections after 1 hour
    _engine_kwargs["pool_pre_ping"] = True  # Verify connection health before use

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

# DB-03: Enable foreign key enforcement in SQLite (disabled by default).
# Without this, CASCADE DELETE and FK constraints are silently ignored.
if _is_sqlite:
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# Session factory — creates new database sessions for each request.
# - expire_on_commit=False: Objects remain usable after commit
#   (important for returning data in API responses)
async_session = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


# ── Base Model ─────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """Base class for all ORM models. All tables inherit from this."""
    pass


# ── User Model ─────────────────────────────────────────────────────────
class User(Base):
    """
    Represents an authenticated user account.
    
    Users sign in via Google OAuth. On first sign-in, a row is created.
    On subsequent sign-ins, name/picture are updated.
    The very first user to register gets role='admin'.
    
    Relationships:
        - agents: One user can have many voice agents
        - call_logs: One user can have many call records
    """
    __tablename__ = "users"

    # Primary key — auto-incrementing integer
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Google's unique user identifier (the 'sub' claim from the ID token)
    # UNIQUE constraint ensures no duplicate accounts
    google_id = Column(String(255), unique=True, nullable=False)
    
    # User's email from Google — also unique
    email = Column(String(255), unique=True, nullable=False)
    
    # Display name from Google profile
    name = Column(String(255), nullable=False)
    
    # Profile picture URL from Google (can be null if no picture)
    picture_url = Column(Text, nullable=True)
    
    # Role-based access: 'admin' can manage system settings, 'user' is default
    role = Column(String(20), default="user", nullable=False)

    # Billing plan for quota enforcement (BIL-04)
    plan = Column(String(20), default="free", nullable=False)  # free, pro, enterprise

    # Timestamps for auditing
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # ── Relationships ──────────────────────────────────────────────
    # back_populates creates a bidirectional link:
    #   user.agents → list of Agent objects
    #   agent.user  → the User who owns it
    agents = relationship("Agent", back_populates="user", lazy="raise")
    call_logs = relationship("CallLog", back_populates="user", lazy="raise")
    api_keys = relationship("UserApiKey", back_populates="user", lazy="selectin", cascade="all, delete-orphan")
    integrations = relationship("Integration", back_populates="user", lazy="selectin", cascade="all, delete-orphan")
    team_memberships = relationship("TeamMember", back_populates="user", lazy="selectin")

    def to_dict(self):
        """Convert user to a dictionary for API responses."""
        return {
            "id": self.id,
            "google_id": self.google_id,
            "email": self.email,
            "name": self.name,
            "picture_url": self.picture_url,
            "role": self.role,
            "plan": self.plan,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── User API Key Model ────────────────────────────────────────────────
# FIX M-8: Expanded to include all integration service types so that
# any integration that stores credentials via /api/keys is allowed.
# Previously only 8 services were listed, silently rejecting hubspot,
# stripe, zendesk, etc.
VALID_KEY_SERVICES = [
    # LLM providers
    "openai", "gemini", "groq", "anthropic", "commandcode",
    # STT providers
    "deepgram",
    # TTS providers
    "elevenlabs",
    # Telephony
    "twilio",
    # Google integrations
    "google_calendar", "google_sheets",
    # Scheduling
    "cal_com", "calendly",
    # Communication
    "sms", "email", "slack", "discord", "microsoft_teams",
    "whatsapp", "sendgrid",
    # CRM
    "hubspot", "salesforce", "pipedrive", "gohighlevel",
    # Customer support
    "zendesk", "intercom", "freshdesk",
    # E-commerce & payments
    "shopify", "stripe",
    # Automation
    "webhook", "zapier", "make",
    # AI & Knowledge
    "knowledge_base",
    # Productivity
    "notion", "airtable",
    # Project management
    "jira", "linear",
    # MCP & Custom integrations (dynamic / user-defined)
    "mcp", "custom_api",
]


class UserApiKey(Base):
    """
    Per-user, per-service API key storage.
    
    Instead of embedding keys into each Agent, users register their keys
    once via /api/keys. Agents then reference a service name and the
    system resolves the key at call time from this table.
    
    Security:
        - Keys are encrypted at rest (future: use Fernet/AES)
        - API responses never return the full key, only masked version
        - Each user can have exactly one key per service
    """
    __tablename__ = "user_api_keys"

    __table_args__ = (
        UniqueConstraint("user_id", "service", name="uq_user_api_key_service"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Service identifier: 'openai', 'gemini', 'deepgram', 'elevenlabs', 'twilio', etc.
    service = Column(String(50), nullable=False)
    
    # The actual API key value
    api_key = Column(Text, nullable=False)
    
    # Optional: for Twilio, also stores account SID and phone number
    api_secret = Column(Text, nullable=True)  # e.g. Twilio auth_token
    metadata_json = Column(Text, nullable=True)  # e.g. {"phone_number": "+1...", "account_sid": "AC..."}
    
    # Display label set by the user
    label = Column(String(255), nullable=True)
    
    # Whether this key is currently active
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", back_populates="api_keys")

    def to_dict(self):
        """API-safe representation — key is ALWAYS masked."""
        from voice_platform.encryption import decrypt
        plain_key = decrypt(self.api_key) if self.api_key else ""
        key_preview = plain_key[:4] + "..." + plain_key[-4:] if plain_key and len(plain_key) > 8 else "***"
        return {
            "id": self.id,
            "service": self.service,
            "masked_key": key_preview,
            "has_secret": bool(self.api_secret),
            "label": self.label,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Team / Organization Model ───────────────────────────────────────
class Team(Base):
    """A team/organization that owns agents and campaigns."""
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    plan = Column(String(20), default="free")  # free, pro, enterprise
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    members = relationship("TeamMember", back_populates="team", lazy="raise")
    agents = relationship("Agent", back_populates="team", lazy="raise")


class TeamMember(Base):
    """Many-to-many: Users belong to Teams with a Role."""
    __tablename__ = "team_members"

    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_member"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), default="member")  # owner, admin, developer, member, analyst

    team = relationship("Team", back_populates="members")
    user = relationship("User", back_populates="team_memberships")


# ── Prompt Version Model ────────────────────────────────────────────────
class PromptVersion(Base):
    """
    History of prompt changes for an agent.
    GAP-08: Prompt Versioning & A/B Testing support.
    """
    __tablename__ = "prompt_versions"

    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_prompt_version"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)  # Sequential: 1, 2, 3...
    prompt_preamble = Column(Text, nullable=False)

    # A/B testing
    is_active = Column(Boolean, default=False)
    traffic_percentage = Column(Integer, default=100)  # 0-100

    # Performance metrics (computed post-call)
    call_count = Column(Integer, default=0)
    avg_sentiment_score = Column(Float, nullable=True)
    avg_duration_secs = Column(Float, nullable=True)
    resolution_rate = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    agent = relationship(
        "Agent",
        back_populates="prompt_versions",
        foreign_keys=[agent_id],
    )

    def to_dict(self):
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "version": self.version,
            "prompt_preamble": self.prompt_preamble,
            "is_active": self.is_active,
            "traffic_percentage": self.traffic_percentage,
            "call_count": self.call_count,
            "avg_sentiment_score": self.avg_sentiment_score,
            "avg_duration_secs": self.avg_duration_secs,
            "resolution_rate": self.resolution_rate,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "created_by": self.created_by,
        }


# ── Integration Model ─────────────────────────────────────────────────
VALID_INTEGRATION_TYPES = [
    # ── MCP & Custom (dynamic, user-defined integrations) ──
    "mcp",
    "custom_api",
    "webhook",
    # ── Google Workspace ──
    "google_calendar",
    "google_sheets",
    "google_drive_mcp",
    # ── Messaging ──
    "whatsapp_cloud",
    "telegram_bot",
    "sms",
    "email",
    "sendgrid",
    "slack",
    "discord",
    "microsoft_teams",
    # ── CRM & Sales ──
    "salesforce",
    "pipedrive",
    "gohighlevel",
    "hubspot",
    # ── Commerce ──
    "stripe",
    "shopify",
    # ── Support ──
    "zendesk",
    "freshdesk",
    "intercom",
    # ── Productivity ──
    "notion",
    "airtable",
    # ── Project Management ──
    "jira",
    "linear",
    # ── Scheduling ──
    "cal_com",
    "calendly",
    # ── Knowledge ──
    "knowledge_base",
    # ── Automation ──
    "zapier",
    "make",
]


class Integration(Base):
    """
    Represents a user-connected third-party service.
    
    Users connect their Google Calendar, Google Sheets, etc. from the
    frontend. Each integration stores the service type, credentials
    reference, and service-specific configuration.
    
    Integrations are used by Workflows: when a workflow step says
    "create a calendar event", the system looks up the user's
    Google Calendar integration to get the credentials and config.
    """
    __tablename__ = "integrations"

    __table_args__ = (
        UniqueConstraint("user_id", "service_type", name="uq_user_integration"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Type: 'google_calendar', 'google_sheets'
    service_type = Column(String(50), nullable=False)
    
    # Human-readable name (e.g. "My Work Calendar", "Sales Sheet")
    name = Column(String(255), nullable=False)
    
    # Reference to the UserApiKey used for authentication
    api_key_id = Column(Integer, ForeignKey("user_api_keys.id", ondelete="SET NULL"), nullable=True)
    
    # Service-specific config stored as JSON
    # e.g. {"calendar_id": "primary", "spreadsheet_id": "abc123", "sheet_name": "Sheet1"}
    config_json = Column(Text, nullable=True)
    
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User", back_populates="integrations")
    api_key = relationship("UserApiKey")

    def to_dict(self):
        import json as _json
        config = None
        if self.config_json:
            try:
                config = _json.loads(self.config_json)
            except Exception:
                config = self.config_json
        return {
            "id": self.id,
            "user_id": self.user_id,
            "service_type": self.service_type,
            "name": self.name,
            "api_key_id": self.api_key_id,
            "config": config,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Agent Model ────────────────────────────────────────────────────────
class Agent(Base):
    """
    Represents a configurable voice agent.
    
    Each agent has its own LLM, STT, and TTS provider settings.
    The frontend controls which provider/model to use — stored here.
    When a call arrives, the agent_factory reads this config and builds
    the correct vocode objects (ChatGPTAgent, DeepgramTranscriber, etc.)
    
    Provider fields follow the pattern:
        {component}_provider  → which service to use (e.g. 'openai')
        {component}_model     → which model/voice (e.g. 'gpt-4o-mini')
        {component}_api_key   → user's own API key (null = use platform default)
    """
    __tablename__ = "agents"

    __table_args__ = (
        Index("idx_agents_mode", "mode"),
        Index("idx_agents_user_active", "user_id", "is_active"),
    )

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign key linking this agent to its owner
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # GAP-06: Optional team ownership for RBAC
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)

    # Human-readable name (shown in frontend dashboard)
    name = Column(String(255), nullable=False)
    
    # ── LLM Configuration ──────────────────────────────────────────
    # The system prompt that defines the agent's personality and behavior
    prompt_preamble = Column(Text, nullable=False)
    
    # What the agent says when the call first connects
    initial_message = Column(
        Text,
        default="Hello! Thank you for calling. How can I help you today?"
    )
    
    # LLM provider: 'openrouter', 'openai', 'anthropic', 'groq', etc.
    llm_provider = Column(String(50), default="openrouter", nullable=False)
    
    # Model identifier (e.g. 'deepseek/deepseek-v4-flash', 'gpt-4o-mini')
    llm_model = Column(String(100), default="deepseek/deepseek-v4-flash", nullable=False)
    
    # User's own API key for this LLM. If NULL, we use the platform's
    # default key from .env (OPENAI_API_KEY, etc.)
    llm_api_key = Column(Text, nullable=True)
    
    # ── STT (Speech-to-Text) Configuration ─────────────────────────
    # STT provider: 'deepgram', 'google', 'azure', 'assemblyai'
    stt_provider = Column(String(50), default="deepgram", nullable=False)
    
    # Language for speech recognition (e.g. 'en-US', 'ur', 'multi')
    stt_language = Column(String(20), default="en-US", nullable=False)
    
    # User's own STT API key (null = use platform default)
    stt_api_key = Column(Text, nullable=True)
    
    # ── TTS (Text-to-Speech) Configuration ─────────────────────────
    # TTS provider: 'gtts', 'elevenlabs', 'azure', 'cartesia', 'polly'
    tts_provider = Column(String(50), default="gtts", nullable=False)
    
    # Voice ID for the TTS provider (e.g. ElevenLabs voice ID)
    tts_voice_id = Column(String(255), nullable=True)
    
    # User's own TTS API key (null = use platform default)
    tts_api_key = Column(Text, nullable=True)
    
    # ── LLM Parameters ─────────────────────────────────────────────
    # Controls randomness: 0.0 = deterministic, 2.0 = very creative
    temperature = Column(Float, default=0.7)
    
    # Maximum tokens the LLM can generate per response
    max_tokens = Column(Integer, default=2048)
    
    # ── Behavior Settings ──────────────────────────────────────────
    # Whether this agent is currently accepting calls
    is_active = Column(Boolean, default=True)
    
    # Automatically end the call when goodbye is detected
    end_on_goodbye = Column(Boolean, default=True)
    
    # How sensitive to interruptions: 'low' or 'high'
    interrupt_sensitivity = Column(String(10), default="low")
    
    # ── Call Stability Settings ─────────────────────────────────────
    # Seconds of silence before idle-check triggers (None → platform default 60s)
    allowed_idle_time_seconds = Column(Float, default=60.0)
    
    # Number of "are you there?" retries before auto-ending.
    # 0 = terminate immediately (bad!). 2 = ask twice before hanging up.
    num_check_human_present_times = Column(Integer, default=2)
    
    # Seconds to wait before sending initial_message (give Twilio WS time to connect)
    initial_message_delay = Column(Float, default=0.4)
    
    # Deepgram model variant (nova-3, nova-3-phonecall, nova-2-phonecall, etc.)
    stt_model = Column(String(50), default="nova-3")
    
    # Endpointing strategy: 'punctuation', 'time', 'auto' (DeepgramEndpointingConfig)
    endpointing_type = Column(String(20), default="auto")
    
    # Enable filler audio ("um", typing sounds) during LLM processing
    filler_audio_enabled = Column(Boolean, default=True)
    
    # Minimum confidence (0.0-1.0) for a transcription to trigger an interrupt
    # Higher = fewer false interrupts from noise. 0.0 = any sound interrupts.
    min_interrupt_confidence = Column(Float, default=0.6)

    # Deepgram STT enhancement features
    stt_smart_format = Column(Boolean, default=True)
    stt_diarize = Column(Boolean, default=True)
    stt_filter_filler_words = Column(Boolean, default=False)

    # Post-call analysis provider: "auto" (Deepgram if recording, else LLM), "deepgram", "llm"
    analysis_provider = Column(String(20), default="auto")
    
    # JSON array of enabled tool names for in-call function calling
    # e.g. '["check_calendar", "send_email", "lookup_contact"]'
    tools_config = Column(Text, nullable=True)

    # Per-agent instructions for how tools should behave during calls.
    # Injected into each enabled tool's description so the LLM sees them.
    tool_instructions = Column(Text, nullable=True)

    # Per-agent extraction prompts — JSON dict mapping variable names to human-readable descriptions.
    # Overrides the defaults in WorkflowExecutor._DEFAULT_EXTRACTION_PROMPTS.
    # e.g. '{"order_number": "the customer's order number", "refund_reason": "why the customer wants a refund"}'
    extraction_prompts = Column(Text, nullable=True)

    # Per-agent integration overrides — which specific integration instance
    # to use for each service type. Format: {"google_sheets": 123, "google_calendar": 456}
    integration_overrides_json = Column(Text, nullable=True)
    
    # GAP-01: Primary knowledge base for live RAG retrieval during calls
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True)

    # Optional Google Drive MCP integration attached directly to this agent
    google_drive_integration_id = Column(Integer, ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True)

    # MCP resource bindings — which files/folders this agent can access
    # Format: {"drive": {"file_ids": [...], "folder_ids": [...]}, "calendar": {"calendar_ids": [...]}}
    mcp_bindings_json = Column(Text, nullable=True)

    # GAP-03: Webhook URL for post-call event notifications (e.g. CRM, Slack)
    webhook_url = Column(String(500), nullable=True)

    # GAP-07: Agent language for STT/TTS auto-configuration
    language = Column(String(10), default="en-US", nullable=False)

    # GAP-08: Current active prompt version for A/B testing
    current_prompt_version_id = Column(
        Integer, ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True
    )

    # ── Agent Mode & Flow (Retell AI 2.0) ─────────────────────────
    # single_prompt or conversational_flow
    mode = Column(String(20), default="single_prompt", nullable=False)

    # For conversational flow agents — stores ReactFlow graph JSON
    # DEPRECATED: graph_json is kept for backward compat; new code should use
    # the .graph property which fetches from the linked Workflow.
    graph_json = Column(Text, nullable=True)

    # Link to the canonical workflow that owns this agent's conversational graph.
    # When set, agent.graph reads from workflow.graph_json instead of agent.graph_json.
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True)

    # Transition flexibility: 'strict' or 'flex'
    transition_flexibility = Column(String(10), default="flex", nullable=False)

    # Agent handbook toggle + content (RAG document attached to agent)
    handbook_enabled = Column(Boolean, default=False, nullable=False)
    handbook_content = Column(Text, nullable=True)

    # Template ID this agent was created from
    template_id = Column(String(50), nullable=True)

    # Voicemail drop: message to leave when AMD detects voicemail on outbound calls.
    # If NULL, the call simply hangs up on voicemail detection.
    voicemail_message = Column(Text, nullable=True)

    # Issue 14: Configurable timezone for calendar bookings (IANA string, e.g. "Asia/Karachi")
    timezone = Column(String(50), nullable=True)

    # B1: Whether this agent can make outbound calls (checked before placing calls)
    outbound_ready = Column(Boolean, default=False, nullable=False, server_default='0')
    # Whether this agent can receive inbound calls
    inbound_ready = Column(Boolean, default=True, nullable=False, server_default='1')

    # Ollama context window size (num_ctx). NULL = auto-detect from model.
    context_window = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # ── Relationships ──────────────────────────────────────────────
    user = relationship("User", back_populates="agents")
    team = relationship("Team", back_populates="agents")
    call_logs = relationship("CallLog", back_populates="agent", lazy="raise")
    workflows = relationship("Workflow", back_populates="agent", lazy="raise", foreign_keys="[Workflow.agent_id]")
    linked_workflow = relationship(
        "Workflow",
        foreign_keys=[workflow_id],
        lazy="selectin",
        post_update=True,
    )
    google_drive_integration = relationship(
        "Integration",
        foreign_keys=[google_drive_integration_id],
        lazy="selectin",
    )
    prompt_versions = relationship(
        "PromptVersion",
        back_populates="agent",
        lazy="selectin",
        foreign_keys=[PromptVersion.agent_id],
        cascade="all, delete-orphan",
        order_by="PromptVersion.version.desc()",
    )

    @property
    def graph(self) -> Optional[dict]:
        """Computed graph: fetches from linked workflow, falls back to graph_json.

        This is the canonical way to read an agent's conversational graph.
        New code should use agent.graph instead of agent.graph_json.
        """
        import json as _gjson

        # Prefer the linked workflow's graph (single source of truth)
        if self.workflow_id and self.linked_workflow and self.linked_workflow.graph_json:
            try:
                return _gjson.loads(self.linked_workflow.graph_json)
            except Exception:
                pass
        # Fall back to the deprecated agent.graph_json column
        if self.graph_json:
            try:
                return _gjson.loads(self.graph_json)
            except Exception:
                pass
        return None

    def to_dict(self):
        """Convert agent to a dictionary for API responses."""
        import json as _json
        from voice_platform.graph_contracts import canonical_content_hash

        tools = []
        if self.tools_config:
            try:
                tools = _json.loads(self.tools_config)
            except Exception:
                pass
        return {
            "id": self.id,
            "user_id": self.user_id,
            "team_id": self.team_id,
            "name": self.name,
            "prompt_preamble": self.prompt_preamble,
            "initial_message": self.initial_message,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_api_key": "***" if self.llm_api_key else None,
            "stt_provider": self.stt_provider,
            "stt_language": self.stt_language,
            "stt_model": self.stt_model,
            "stt_api_key": "***" if self.stt_api_key else None,
            "tts_provider": self.tts_provider,
            "tts_voice_id": self.tts_voice_id,
            "tts_api_key": "***" if self.tts_api_key else None,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "is_active": self.is_active,
            "end_on_goodbye": self.end_on_goodbye,
            "interrupt_sensitivity": self.interrupt_sensitivity,
            "allowed_idle_time_seconds": self.allowed_idle_time_seconds,
            "num_check_human_present_times": self.num_check_human_present_times,
            "initial_message_delay": self.initial_message_delay,
            "endpointing_type": self.endpointing_type,
            "filler_audio_enabled": self.filler_audio_enabled,
            "min_interrupt_confidence": self.min_interrupt_confidence,
            "stt_smart_format": self.stt_smart_format,
            "stt_diarize": self.stt_diarize,
            "stt_filter_filler_words": self.stt_filter_filler_words,
            "analysis_provider": self.analysis_provider,
            "knowledge_base_id": self.knowledge_base_id,
            "google_drive_integration_id": self.google_drive_integration_id,
            "mcp_bindings": (_json.loads(self.mcp_bindings_json) if self.mcp_bindings_json else {}),
            "webhook_url": self.webhook_url,
            "language": self.language,
            "tools_config": tools,
            "tool_instructions": self.tool_instructions,
            "extraction_prompts": (_json.loads(self.extraction_prompts) if self.extraction_prompts else None),
            "integration_overrides": (_json.loads(self.integration_overrides_json) if self.integration_overrides_json else {}),
            "mode": self.mode,
            "agent_type": "Single Prompt" if self.mode == "single_prompt" else "Conversation Flow",
            "transition_flexibility": self.transition_flexibility,
            "handbook_enabled": self.handbook_enabled,
            "handbook_content": self.handbook_content,
            "template_id": self.template_id,
            "graph_json": self.graph,
            "graph_hash": canonical_content_hash(self.graph),
            "workflow_id": self.workflow_id,
            "voicemail_message": self.voicemail_message,
            "context_window": self.context_window,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Call Log Model ─────────────────────────────────────────────────────
class CallLog(Base):
    """
    Records metadata for every phone call handled by the platform.
    
    Created when a Twilio inbound call arrives (status='active').
    Updated when the call ends (status='completed', duration filled).
    
    The conversation_id links to vocode's internal call tracking,
    which uses Redis to manage the active call's config.
    """
    __tablename__ = "call_logs"

    # Indexes for common dashboard + analytics query patterns
    __table_args__ = (
        Index("idx_calls_user_started", "user_id", "started_at"),
        Index("idx_calls_agent_status", "agent_id", "status"),
        Index("idx_calls_direction_started", "direction", "started_at"),
        Index("idx_calls_conversation", "conversation_id"),
        # DB-02: Index for active call lookups and status-based analytics
        Index("idx_calls_status_started", "status", "started_at"),
        # TEL-05: Index for user attribution via Twilio SID / phone number lookup
        Index("idx_calls_from_phone", "from_phone"),
        Index("idx_calls_twilio_sid", "twilio_call_sid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # vocode's internal conversation UUID — links to Redis config
    conversation_id = Column(String(255), unique=True, nullable=False)

    # Twilio Call SID — stored so Twilio status/recording callbacks can find
    # the CallLog even when conversation_id is a vocode UUID (inbound calls).
    twilio_call_sid = Column(String(50), nullable=True, index=True)

    # Which agent handled this call (nullable for system/unknown)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    
    # Which user owns the agent (denormalized for easy querying)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Phone numbers involved in the call
    from_phone = Column(String(20), nullable=False)  # Caller's number
    to_phone = Column(String(20), nullable=False)     # Our Twilio number
    
    # Call direction: 'inbound' (caller → us) or 'outbound' (us → caller)
    direction = Column(String(10), default="inbound")
    
    # Call lifecycle: 'active' → 'completed' / 'failed'
    status = Column(String(20), default="active")

    # AMD outcome: 'human', 'voicemail', 'fax', 'unknown' (for outbound calls with machine_detection)
    call_outcome = Column(String(20), nullable=True)
    
    # Timing
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime(timezone=True), nullable=True)          # Set when call ends
    duration_secs = Column(Float, nullable=True)         # Calculated on end
    
    # Twilio recording URL if call recording is enabled
    recording_url = Column(Text, nullable=True)

    # D-1: Cached LLM analysis result (JSON string) to avoid re-running on every view
    analysis_json = Column(Text, nullable=True)

    # GAP-08: Which prompt version was used for this call (A/B tracking)
    prompt_version_id = Column(Integer, ForeignKey("prompt_versions.id", ondelete="SET NULL"), nullable=True)

    # GAP-12: Latency tracking (all in milliseconds)
    first_response_ms = Column(Float, nullable=True)       # Time from call start to first bot audio
    avg_turn_latency_ms = Column(Float, nullable=True)    # Average latency per turn
    llm_latency_ms = Column(Float, nullable=True)         # Average LLM generation time
    stt_latency_ms = Column(Float, nullable=True)          # Average speech-to-text time
    tts_latency_ms = Column(Float, nullable=True)          # Average text-to-speech time

    # Phase 5: AI Quality Assurance
    quality_score = Column(Float, nullable=True)          # 0-100 composite quality score
    interruption_count = Column(Integer, default=0)        # How many times caller interrupted
    filler_count = Column(Integer, default=0)              # How many filler audio events played
    review_flag = Column(Boolean, default=False)         # Flagged for human review
    review_reason = Column(String(100), nullable=True)    # Why it was flagged

    # ── Relationships ──────────────────────────────────────────────
    agent = relationship("Agent", back_populates="call_logs", lazy="selectin")
    user = relationship("User", back_populates="call_logs", lazy="selectin")
    # cascade="all, delete-orphan": deleting a call_log deletes its transcripts
    transcripts = relationship(
        "Transcript", back_populates="call_log",
        cascade="all, delete-orphan", lazy="raise"
    )
    action_logs = relationship(
        "ActionLog", back_populates="call_log",
        cascade="all, delete-orphan", lazy="raise"
    )

    def to_dict(self, include_transcript=False):
        """Convert call log to a dictionary for API responses."""
        import json as _json

        result = {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "twilio_call_sid": self.twilio_call_sid,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "agent_name": self.agent.name if self.agent else None,
            "from_phone": self.from_phone,
            "to_phone": self.to_phone,
            "direction": self.direction,
            "status": self.status,
            "call_outcome": self.call_outcome,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_secs": self.duration_secs,
            "recording_url": self.recording_url,
            # GAP-08: Which prompt version was used (A/B tracking)
            "prompt_version_id": self.prompt_version_id,
            # GAP-12: Latency metrics (milliseconds)
            "first_response_ms": self.first_response_ms,
            "avg_turn_latency_ms": self.avg_turn_latency_ms,
            "llm_latency_ms": self.llm_latency_ms,
            "stt_latency_ms": self.stt_latency_ms,
            "tts_latency_ms": self.tts_latency_ms,
            "analysis_json": self.analysis_json,
            # Phase 5: Quality metrics
            "quality_score": self.quality_score,
            "interruption_count": self.interruption_count,
            "filler_count": self.filler_count,
            "review_flag": self.review_flag,
            "review_reason": self.review_reason,
        }
        # Optionally include full transcript (for detail view)
        if include_transcript:
            try:
                result["transcript"] = [t.to_dict() for t in self.transcripts]
            except Exception:
                result["transcript"] = []
            try:
                result["actions"] = [a.to_dict() for a in self.action_logs]
            except Exception:
                result["actions"] = []
            # Include cached analysis if available (avoids re-inference)
            if self.analysis_json:
                try:
                    result["analysis"] = _json.loads(self.analysis_json)
                except (_json.JSONDecodeError, TypeError):
                    result["analysis"] = None
        return result


# ── Do Not Call List Model ────────────────────────────────────────────
class DNCList(Base):
    """
    Do Not Call entries — global and per-user blocks.

    Twilio Voice Services Policy requires callers to honor opt-out
    requests and not call numbers on do-not-call registries.
    """
    __tablename__ = "dnc_list"

    __table_args__ = (
        Index("idx_dnc_phone", "phone_number"),
        Index("idx_dnc_user_phone", "user_id", "phone_number"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone_number = Column(String(20), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)  # NULL = global block
    source = Column(String(50), default="manual")  # manual, opt_out, import
    reason = Column(String(255), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self):
        return {
            "id": self.id,
            "phone_number": self.phone_number,
            "user_id": self.user_id,
            "source": self.source,
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── Transcript Model ───────────────────────────────────────────────────
class Transcript(Base):
    """
    Stores individual messages within a phone call.
    
    Each row is one utterance (human or bot). These are persisted
    by the PersistentEventsManager which subscribes to vocode's
    TRANSCRIPT events in real-time during calls.
    
    Used for:
        1. Call log detail view (full conversation replay)
        2. Cross-call memory (inject past conversations into prompts)
        3. Analytics and auditing
    """
    __tablename__ = "transcripts"

    __table_args__ = (
        Index("idx_transcripts_call", "call_log_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign key to the call this message belongs to
    call_log_id = Column(Integer, ForeignKey("call_logs.id", ondelete="CASCADE"), nullable=False)
    
    # Who said this: 'human', 'bot', 'action', 'system'
    sender = Column(String(20), nullable=False)
    
    # The actual text content of the message
    message = Column(Text, nullable=False)
    
    # Unix timestamp from vocode's Transcript system
    timestamp = Column(Float, nullable=False)

    # ── Relationships ──────────────────────────────────────────────
    call_log = relationship("CallLog", back_populates="transcripts")

    def to_dict(self):
        """Convert transcript entry to dictionary."""
        return {
            "id": self.id,
            "call_log_id": self.call_log_id,
            "sender": self.sender,
            "message": self.message,
            "timestamp": self.timestamp,
        }


# ── Action Log Model ──────────────────────────────────────────────────
class ActionLog(Base):
    """
    Records actions executed during a call (e.g. transfer, schedule).
    
    vocode's action system fires ActionEvents when actions start/finish.
    Our PersistentEventsManager captures these and writes them here.
    """
    __tablename__ = "action_logs"

    __table_args__ = (
        Index("idx_actions_call", "call_log_id"),
        Index("idx_actions_conversation", "conversation_id"),
        Index("idx_actions_tool", "tool_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Which call this action was part of
    call_log_id = Column(Integer, ForeignKey("call_logs.id", ondelete="CASCADE"), nullable=False)
    
    # Action type identifier (e.g. 'action_transfer_call', 'action_external')
    action_type = Column(String(100), nullable=False)
    
    # Specific tool name (e.g. 'read_drive_file', 'send_email')
    tool_name = Column(String(100), nullable=True)
    
    # Conversation ID for querying without joins
    conversation_id = Column(String(255), nullable=True)
    
    # JSON-encoded input parameters for the action
    params_json = Column(Text, nullable=True)
    
    # JSON-encoded result of the action
    result_json = Column(Text, nullable=True)
    
    # Unix timestamp when the action occurred
    timestamp = Column(Float, nullable=False)
    
    # Tool execution latency in milliseconds
    latency_ms = Column(Float, nullable=True)
    
    # Whether the tool call resulted in an error
    is_error = Column(Boolean, default=False)
    
    # Extracted error message if the tool failed
    error_message = Column(Text, nullable=True)

    # ── Relationships ──────────────────────────────────────────────
    call_log = relationship("CallLog", back_populates="action_logs")

    def to_dict(self):
        """Convert action log to dictionary."""
        return {
            "id": self.id,
            "call_log_id": self.call_log_id,
            "action_type": self.action_type,
            "tool_name": self.tool_name,
            "conversation_id": self.conversation_id,
            "params_json": self.params_json,
            "result_json": self.result_json,
            "timestamp": self.timestamp,
            "latency_ms": self.latency_ms,
            "is_error": self.is_error,
            "error_message": self.error_message,
        }


# ── Workflow Model ─────────────────────────────────────────────────────
class Workflow(Base):
    """
    Defines an intent-based workflow routing rule.
    
    When the AI agent detects that a user's intent matches one of the
    trigger_phrases, it executes the associated action. Workflows can
    chain multiple steps (stored as JSON in steps_json):
    
    trigger_phrases: JSON array string e.g. '["schedule", "appointment"]'
    steps_json: JSON array of step objects e.g.:
        [
            {"type": "google_calendar", "action": "create_event", "params": {...}},
            {"type": "google_sheets", "action": "append_row", "params": {...}},
            {"type": "webhook", "url": "https://...", "method": "POST"}
        ]
    """
    __tablename__ = "workflows"

    __table_args__ = (
        Index("idx_workflows_agent", "agent_id"),
        Index("idx_workflows_user", "user_id"),
        Index("idx_workflows_active", "is_active"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Owner of this workflow
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Human-readable name (e.g. "Schedule Appointment")
    name = Column(String(255), nullable=False)
    
    # Description of what this workflow does
    description = Column(Text, nullable=True)
    
    # JSON array of phrases that trigger this workflow
    trigger_phrases = Column(Text, nullable=False)
    
    # Optionally route to a different agent
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    
    # Legacy action config (kept for backward compat)
    action_type = Column(String(100), nullable=True)
    action_url = Column(Text, nullable=True)
    
    # Structured workflow steps as JSON array
    # Each step: {"type": "google_calendar|google_sheets|webhook", "action": "...", "params": {...}}
    steps_json = Column(Text, nullable=True)
    
    # Full ReactFlow graph state: {"nodes": [...], "edges": [...]}
    # Preserves node positions, types, edge labels, branching — ensures lossless round-trip
    graph_json = Column(Text, nullable=True)

    # Transition flexibility: 'strict' (follow edges exactly) or 'flex' (LLM can choose)
    transition_flexibility = Column(String(10), default="flex", nullable=False)
    
    # Whether this workflow requires human approval before executing
    requires_approval = Column(Boolean, default=False)
    
    # Whether this workflow is active
    is_active = Column(Boolean, default=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # ── Relationships ──────────────────────────────────────────────
    agent = relationship("Agent", back_populates="workflows", foreign_keys=[agent_id])

    def to_dict(self):
        """Convert workflow to dictionary."""
        import json as _json

        from loguru import logger
        from voice_platform.graph_contracts import canonical_content_hash
        steps = None
        if self.steps_json:
            try:
                steps = _json.loads(self.steps_json)
            except Exception:
                steps = self.steps_json
        graph = None
        graph_corrupted = False
        if self.graph_json:
            try:
                graph = _json.loads(self.graph_json)
            except Exception as e:
                graph = None
                graph_corrupted = True
                logger.warning(
                    f"Workflow #{self.id} graph_json is corrupted: {e}. "
                    f"Falling back to steps_json if available."
                )
        trigger_phrases = []
        if self.trigger_phrases:
            try:
                trigger_phrases = _json.loads(self.trigger_phrases)
            except Exception:
                trigger_phrases = [self.trigger_phrases]
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "description": self.description,
            "trigger_phrases": trigger_phrases,
            "agent_id": self.agent_id,
            "action_type": self.action_type,
            "action_url": self.action_url,
            "steps": steps,
            "graph": graph,
            "graph_hash": canonical_content_hash(graph),
            "graph_corrupted": graph_corrupted,
            "transition_flexibility": self.transition_flexibility,
            "requires_approval": self.requires_approval,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Settings Model ─────────────────────────────────────────────────────
class Setting(Base):
    """
    Platform-wide key-value configuration store.
    
    Stores settings like default LLM provider, default model, etc.
    Admin users can update these via the settings API.
    
    Initial settings are seeded on first startup.
    """
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Setting key (unique identifier)
    key = Column(String(255), unique=True, nullable=False)
    
    # Setting value (stored as string — JSON-encoded for complex values)
    value = Column(Text, nullable=False)
    
    # Last update timestamp
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# ── Review Queue Model ────────────────────────────────────────────────
class ReviewQueue(Base):
    """
    Human-in-the-loop review queue for sensitive actions (UC-07).
    
    When a workflow with requires_approval=True triggers an action,
    the action is queued here instead of executing immediately.
    An admin or authorized user must approve/reject before execution.
    
    Status lifecycle: 'pending' → 'approved' / 'rejected'
    """
    __tablename__ = "review_queue"

    __table_args__ = (
        Index("idx_review_user_status", "user_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Which call triggered this action
    call_log_id = Column(Integer, ForeignKey("call_logs.id", ondelete="CASCADE"), nullable=True)
    
    # Which workflow rule matched
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True)
    
    # Owner of the workflow (for access control)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    # Action details
    action_type = Column(String(100), nullable=False)
    action_url = Column(Text, nullable=True)
    action_params = Column(Text, nullable=True)  # JSON params
    
    # Context about why this was triggered
    trigger_context = Column(Text, nullable=True)  # What the user said
    
    # Review status
    status = Column(String(20), default="pending", nullable=False)  # pending/approved/rejected
    
    # Who reviewed it and when
    reviewed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # ── Relationships ──────────────────────────────────────────────
    call_log = relationship("CallLog")
    workflow = relationship("Workflow")

    def to_dict(self):
        """Convert review queue entry to dictionary."""
        return {
            "id": self.id,
            "call_log_id": self.call_log_id,
            "workflow_id": self.workflow_id,
            "user_id": self.user_id,
            "action_type": self.action_type,
            "action_url": self.action_url,
            "action_params": self.action_params,
            "trigger_context": self.trigger_context,
            "status": self.status,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "review_notes": self.review_notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── Google OAuth Token Model ───────────────────────────────────────────
class GoogleOAuthToken(Base):
    """
    Stores Google OAuth 2.0 tokens for a user.

    Used by GoogleCalendarClient and GoogleSheetsClient to access
    user data via OAuth instead of service account JSON keys.
    Tokens are encrypted at rest.
    """
    __tablename__ = "google_oauth_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    access_token = Column(String, nullable=False)  # Encrypted
    refresh_token = Column(String, nullable=False)  # Encrypted
    token_type = Column(String, default="Bearer")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    scopes = Column(String, nullable=False)  # JSON array
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# ── Phone Number Mapping Model ─────────────────────────────────────────
class PhoneNumberMapping(Base):
    """
    Maps inbound phone numbers to specific agents.
    
    When a call comes in on a Twilio number, the system looks up the
    mapping to route to the correct agent. This enables multi-agent
    routing: different phone numbers connect to different AI agents.
    
    If no mapping exists for a number, the system falls back to the
    most recently updated active agent (legacy behavior).
    """
    __tablename__ = "phone_number_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    phone_number = Column(String(20), unique=True, nullable=False)  # E.164 format
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    label = Column(String(255), nullable=True)  # e.g. "Sales Line", "Support Line"
    greeting_override = Column(Text, nullable=True)  # Override initial_message per number
    max_call_duration_secs = Column(Integer, default=600)  # Max 10min default
    voicemail_detection = Column(Boolean, default=False)  # Enable AMD
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User")
    agent = relationship("Agent")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "phone_number": self.phone_number,
            "agent_id": self.agent_id,
            "agent_name": self.agent.name if self.agent else None,
            "label": self.label,
            "greeting_override": self.greeting_override,
            "max_call_duration_secs": self.max_call_duration_secs,
            "voicemail_detection": self.voicemail_detection,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── Knowledge Base Model ──────────────────────────────────────────────
class KnowledgeBase(Base):
    """
    Knowledge base for RAG-powered agent context (inspired by Retell AI).
    
    Stores documents/text that the agent can retrieve during calls.
    Supports: plain text snippets, URLs (content fetched and stored),
    and file references.
    
    During calls, the system does keyword/semantic matching against
    the knowledge base to inject relevant context into the LLM prompt.
    """
    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Source type: 'text', 'url', 'file'
    source_type = Column(String(20), nullable=False, default="text")
    
    # The actual content (for text type) or URL/file path
    content = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    
    # Chunked content stored as JSON array for retrieval
    chunks_json = Column(Text, nullable=True)

    # Semantic search: embeddings stored as JSON array parallel to chunks
    embeddings_json = Column(Text, nullable=True)
    embedding_model = Column(String(50), nullable=True)
    embedding_provider = Column(String(20), default="openai")

    # Which agent(s) this KB is linked to (JSON array of agent IDs)
    agent_ids_json = Column(Text, nullable=True)

    # Retrieval settings
    chunk_size = Column(Integer, default=500)  # chars per chunk
    max_chunks_per_query = Column(Integer, default=3)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    user = relationship("User")

    def to_dict(self):
        import json as _json
        agent_ids = []
        if self.agent_ids_json:
            try:
                agent_ids = _json.loads(self.agent_ids_json)
            except Exception:
                pass
        chunk_count = 0
        if self.chunks_json:
            try:
                chunk_count = len(_json.loads(self.chunks_json))
            except Exception:
                pass
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "description": self.description,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "content_preview": (self.content[:200] + "...") if self.content and len(self.content) > 200 else self.content,
            "agent_ids": agent_ids,
            "chunk_size": self.chunk_size,
            "max_chunks_per_query": self.max_chunks_per_query,
            "chunk_count": chunk_count,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Alert Rule Model ──────────────────────────────────────────────────
class AlertRule(Base):
    """
    User-defined alert rules for real-time monitoring.

    Condition types:
      - call_failed_count:   N failed calls within window_minutes
      - avg_latency_spike:   avg latency exceeds threshold_ms
      - call_duration_short: calls shorter than threshold_secs
      - quality_score_drop:  avg quality below threshold
      - no_calls:            zero calls within window_minutes
    """
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)

    # Condition
    condition_type = Column(String(50), nullable=False)
    threshold = Column(Float, nullable=True)       # numeric threshold
    window_minutes = Column(Integer, default=10)     # lookback window
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)

    # Notification channels (JSON: ["email","slack","webhook"])
    channels_json = Column(Text, nullable=True)
    # Channel config JSON (webhook URL, Slack token, email address)
    channel_config_json = Column(Text, nullable=True)

    # Cooldown between firings (minutes)
    cooldown_minutes = Column(Integer, default=15)
    last_fired_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        import json as _json
        channels = []
        if self.channels_json:
            try:
                channels = _json.loads(self.channels_json)
            except Exception:
                pass
        config = {}
        if self.channel_config_json:
            try:
                config = _json.loads(self.channel_config_json)
            except Exception:
                pass
        return {
            "id": self.id,
            "name": self.name,
            "is_active": self.is_active,
            "condition_type": self.condition_type,
            "threshold": self.threshold,
            "window_minutes": self.window_minutes,
            "agent_id": self.agent_id,
            "channels": channels,
            "channel_config": config,
            "cooldown_minutes": self.cooldown_minutes,
            "last_fired_at": self.last_fired_at.isoformat() if self.last_fired_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AlertHistory(Base):
    """Log of fired alerts."""
    __tablename__ = "alert_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    alert_rule_id = Column(Integer, ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True)
    rule_name = Column(String(255), nullable=False)
    condition_type = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    channels = Column(Text, nullable=True)  # comma-separated
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "alert_rule_id": self.alert_rule_id,
            "rule_name": self.rule_name,
            "condition_type": self.condition_type,
            "message": self.message,
            "channels": self.channels,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
        }


class PricingRate(Base):
    """Configurable per-service pricing rates (BIL-01)."""
    __tablename__ = "pricing_rates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_type = Column(String(20), nullable=False)   # llm, stt, tts, telephony
    provider = Column(String(50), nullable=False)       # e.g. gpt-4o-mini, deepgram
    metric = Column(String(20), nullable=False)         # input, output, per_second, per_char
    rate_usd = Column(Float, nullable=False, default=0.0)
    pricing_updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_pricing_service_provider", "service_type", "provider"),
    )


class UsageLog(Base):
    """Per-call usage metrics for billing & cost estimation."""
    __tablename__ = "usage_logs"

    __table_args__ = (
        Index("idx_usage_user_recorded", "user_id", "recorded_at"),
        Index("idx_usage_call", "call_id"),
        # DB-02: Index for time-based usage aggregation queries
        Index("idx_usage_recorded", "recorded_at"),
        # BIL-05: Prevent duplicate usage logs for the same call
        UniqueConstraint("call_id", name="uq_usage_log_call_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    call_id = Column(Integer, ForeignKey("call_logs.id", ondelete="SET NULL"), nullable=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)

    # Providers used
    llm_provider = Column(String(50), nullable=True)
    llm_model = Column(String(50), nullable=True)
    stt_provider = Column(String(50), nullable=True)
    tts_provider = Column(String(50), nullable=True)

    # Quantities
    duration_seconds = Column(Float, default=0)          # call duration
    input_tokens = Column(Integer, default=0)             # LLM prompt tokens
    output_tokens = Column(Integer, default=0)            # LLM completion tokens
    stt_seconds = Column(Float, default=0)                # STT audio seconds
    tts_characters = Column(Integer, default=0)           # TTS chars generated

    # Cost
    estimated_cost_usd = Column(Float, default=0)

    recorded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "call_id": self.call_id,
            "agent_id": self.agent_id,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "stt_provider": self.stt_provider,
            "tts_provider": self.tts_provider,
            "duration_seconds": round(self.duration_seconds, 1) if self.duration_seconds else 0,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "stt_seconds": round(self.stt_seconds, 1) if self.stt_seconds else 0,
            "tts_characters": self.tts_characters,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4) if self.estimated_cost_usd else 0,
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
        }


# ── Database Initialization ───────────────────────────────────────────
async def init_db():
    """
    Create all database tables if they don't exist.
    
    Called once on application startup. For new installations, this creates
    all tables. For existing installations, use Alembic migrations:
    
        cd voice_platform
        alembic upgrade head
    
    Also seeds initial settings if the settings table is empty.
    """
    # Import campaign models so they register with Base.metadata before create_all
    from voice_platform.api.campaign_routes import Campaign, CampaignContact  # noqa: F401

    # Create all tables defined by our models (safe for first run;
    # subsequent schema changes should use Alembic migrations)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # ── Auto-migrate: add missing columns to existing tables ───────────
    _migrations = [
        ("agents", "tools_config", "TEXT"),
        # Retell AI 2.0: agent mode & flow columns
        ("agents", "mode", "VARCHAR(20) DEFAULT 'single_prompt'"),
        ("agents", "graph_json", "TEXT"),
        ("agents", "transition_flexibility", "VARCHAR(10) DEFAULT 'flex'"),
        ("agents", "handbook_enabled", "BOOLEAN DEFAULT 0"),
        ("agents", "handbook_content", "TEXT"),
        ("agents", "template_id", "VARCHAR(50)"),
        ("agents", "google_drive_integration_id", "INTEGER"),
        # Retell AI 2.0: workflow transition flexibility
        ("workflows", "transition_flexibility", "VARCHAR(10) DEFAULT 'flex'"),
        # Phase 5: AI Quality Assurance
        ("call_logs", "quality_score", "FLOAT"),
        ("call_logs", "interruption_count", "INTEGER DEFAULT 0"),
        ("call_logs", "filler_count", "INTEGER DEFAULT 0"),
        ("call_logs", "review_flag", "BOOLEAN DEFAULT 0"),
        ("call_logs", "review_reason", "VARCHAR(100)"),
        # Phase 6: Alerting System (new tables handled by create_all, columns for existing tables)
        ("alert_rules", "cooldown_minutes", "INTEGER DEFAULT 15"),
        ("alert_rules", "last_fired_at", "DATETIME"),
        # D-1: Cached LLM analysis (GAP-04)
        ("call_logs", "analysis_json", "TEXT"),
        # GAP-08: Prompt version tracking
        ("call_logs", "prompt_version_id", "INTEGER"),
        # GAP-12: Latency tracking
        ("call_logs", "first_response_ms", "FLOAT"),
        ("call_logs", "avg_turn_latency_ms", "FLOAT"),
        ("call_logs", "llm_latency_ms", "FLOAT"),
        ("call_logs", "stt_latency_ms", "FLOAT"),
        ("call_logs", "tts_latency_ms", "FLOAT"),
        # Phase 1: Twilio compliance — DNC + consent tracking
        ("campaign_contacts", "consent_status", "VARCHAR(20) DEFAULT 'unknown'"),
        ("campaign_contacts", "consent_date", "DATETIME"),
        ("campaign_contacts", "consent_source", "VARCHAR(50)"),
        ("campaign_contacts", "opted_out_at", "DATETIME"),
        ("campaign_contacts", "timezone", "VARCHAR(50)"),
        # Phase 2: Outbound CPS rate limiter
        ("campaigns", "max_cps", "INTEGER DEFAULT 1"),
        # BIL-04: Billing plan on users table
        ("users", "plan", "VARCHAR(20) DEFAULT 'free'"),
        # Phase 4: Semantic search in Knowledge Base
        ("knowledge_bases", "embeddings_json", "TEXT"),
        ("knowledge_bases", "embedding_model", "VARCHAR(50)"),
        ("knowledge_bases", "embedding_provider", "VARCHAR(20) DEFAULT 'openai'"),
        # MCP resource bindings for agents
        ("agents", "mcp_bindings_json", "TEXT"),
        # Phase A: Per-agent tool usage instructions
        ("agents", "tool_instructions", "TEXT"),
        # NEW-3: Per-agent extraction prompts
        ("agents", "extraction_prompts", "TEXT"),
        # Phase A: Per-agent integration overrides
        ("agents", "integration_overrides_json", "TEXT"),
        # ActionLog enhanced tool call tracing
        ("action_logs", "tool_name", "VARCHAR(100)"),
        ("action_logs", "conversation_id", "VARCHAR(255)"),
        ("action_logs", "latency_ms", "FLOAT"),
        ("action_logs", "is_error", "BOOLEAN DEFAULT 0"),
        ("action_logs", "error_message", "TEXT"),
        # Twilio Call SID on call_logs for status callback matching
        ("call_logs", "twilio_call_sid", "VARCHAR(50)"),
        # AMD outcome for outbound calls (human, voicemail, fax, unknown)
        ("call_logs", "call_outcome", "VARCHAR(20)"),
        # Voicemail drop: message to leave when AMD detects voicemail on outbound calls
        ("agents", "voicemail_message", "TEXT"),
        # Deepgram STT enhancement features
        ("agents", "stt_smart_format", "BOOLEAN DEFAULT 1"),
        ("agents", "stt_diarize", "BOOLEAN DEFAULT 1"),
        ("agents", "stt_filter_filler_words", "BOOLEAN DEFAULT 0"),
        ("agents", "analysis_provider", "VARCHAR(20) DEFAULT 'auto'"),
        # Phase 7: Configurable Ollama context window
        ("agents", "context_window", "INTEGER"),
        # Link agent to canonical workflow for conversational flow graph
        ("agents", "workflow_id", "INTEGER"),
    ]

    async def _column_exists(conn, table: str, column: str) -> bool:
        """Check if a column exists — SQLite uses PRAGMA, PostgreSQL uses information_schema."""
        if _is_sqlite:
            result = await conn.execute(
                text("SELECT 1 FROM pragma_table_info(:table) WHERE name = :column"),
                {"table": table, "column": column},
            )
        else:
            result = await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = :table AND column_name = :column"
                ),
                {"table": table, "column": column},
            )
        return result.scalar() is not None

    for table, column, col_type in _migrations:
        async with engine.begin() as conn:
            if not await _column_exists(conn, table, column):
                try:
                    await conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                    )
                    logger.info(f"DB MIGRATION: Added {table}.{column}")
                except Exception as exc:
                    logger.error(
                        f"DB MIGRATION: Failed to add {table}.{column}: {exc}"
                    )
            else:
                logger.debug(f"DB MIGRATION: {table}.{column} already exists — skipping")

    # ── Partial unique indexes for dedup enforcement ───────────────────
    # Ensures only one active agent per template per user, and one active
    # workflow per agent per user. SQLite doesn't support partial indexes
    # with WHERE clauses the same way, so only apply on PostgreSQL.
    if not _is_sqlite:
        _unique_indexes = [
            (
                "uq_active_agent_template",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_active_agent_template "
                "ON agents (user_id, template_id) WHERE is_active = true AND template_id IS NOT NULL",
            ),
            (
                "uq_active_workflow_agent",
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_active_workflow_agent "
                "ON workflows (user_id, agent_id) WHERE is_active = true AND agent_id IS NOT NULL",
            ),
        ]
        for idx_name, idx_sql in _unique_indexes:
            try:
                async with engine.begin() as conn:
                    await conn.execute(text(idx_sql))
                logger.info(f"DB INDEX: Ensured {idx_name}")
            except Exception as exc:
                logger.warning(f"DB INDEX: Failed to create {idx_name}: {exc}")

    # ── Performance indexes for existing databases ─────────────────────
    _perf_indexes = [
        ("idx_agents_mode", "CREATE INDEX IF NOT EXISTS idx_agents_mode ON agents (mode)"),
        ("idx_agents_user_active", "CREATE INDEX IF NOT EXISTS idx_agents_user_active ON agents (user_id, is_active)"),
        ("idx_workflows_agent", "CREATE INDEX IF NOT EXISTS idx_workflows_agent ON workflows (agent_id)"),
        ("idx_workflows_user", "CREATE INDEX IF NOT EXISTS idx_workflows_user ON workflows (user_id)"),
        ("idx_workflows_active", "CREATE INDEX IF NOT EXISTS idx_workflows_active ON workflows (is_active)"),
        ("idx_playground_session_type", "CREATE INDEX IF NOT EXISTS idx_playground_session_type ON playground_sessions (session_type)"),
    ]
    for idx_name, idx_sql in _perf_indexes:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(idx_sql))
            logger.debug(f"DB INDEX: Ensured {idx_name}")
        except Exception as exc:
            logger.warning(f"DB INDEX: Failed to create {idx_name}: {exc}")

    # ── Stale-call cleanup ─────────────────────────────────────────────
    # Mark calls stuck in 'active'/'ringing'/'initiated' for more than 4 hours
    # as 'completed' — they are almost certainly disconnected but the status
    # callback was missed (e.g. conversation_id ≠ CallSid for inbound calls).
    try:
        from datetime import timedelta as _td

        from sqlalchemy import func as _stale_func
        from sqlalchemy import select as _stale_select
        stale_cutoff = datetime.now(timezone.utc) - _td(hours=4)
        async with async_session() as session:
            stale_result = await session.execute(
                _stale_select(CallLog).where(
                    CallLog.status.in_(["active", "ringing", "initiated"]),
                    CallLog.started_at < stale_cutoff,
                )
            )
            stale_calls = stale_result.scalars().all()
            for sc in stale_calls:
                sc.status = "completed"
                sc.ended_at = sc.ended_at or datetime.now(timezone.utc)
                if sc.duration_secs is None and sc.started_at:
                    started = sc.started_at.replace(tzinfo=timezone.utc) if sc.started_at.tzinfo is None else sc.started_at
                    sc.duration_secs = (datetime.now(timezone.utc) - started).total_seconds()
            if stale_calls:
                await session.commit()
                logger.warning(f"DB STARTUP: Cleaned up {len(stale_calls)} stale active call(s)")
    except Exception as stale_err:
        logger.error(f"DB STARTUP: Stale-call cleanup failed: {stale_err}")

    # Seed default settings if this is a fresh database
    async with async_session() as session:
        from sqlalchemy import func, select

        # Count existing settings to detect fresh database
        result = await session.execute(select(func.count(Setting.id)))
        count = result.scalar()
        
        if count == 0:
            # First startup — seed default settings
            default_settings = [
                Setting(key="default_llm_provider", value="openai"),
                Setting(key="default_llm_model", value="openai/gpt-oss-120b"),
                Setting(key="default_stt_provider", value="deepgram"),
                Setting(key="default_tts_provider", value="gtts"),
                Setting(key="platform_name", value="VOIA"),
            ]
            session.add_all(default_settings)
            await session.commit()

        # Seed default pricing rates if table is empty (BIL-01)
        from sqlalchemy import func as _func
        pricing_count = (await session.execute(select(_func.count(PricingRate.id)))).scalar()
        if pricing_count == 0:
            default_rates = [
                PricingRate(service_type="llm", provider="gpt-4o-mini", metric="input", rate_usd=0.15/1_000_000),
                PricingRate(service_type="llm", provider="gpt-4o-mini", metric="output", rate_usd=0.60/1_000_000),
                PricingRate(service_type="llm", provider="gpt-4o", metric="input", rate_usd=2.50/1_000_000),
                PricingRate(service_type="llm", provider="gpt-4o", metric="output", rate_usd=10.00/1_000_000),
                PricingRate(service_type="llm", provider="default", metric="input", rate_usd=0.50/1_000_000),
                PricingRate(service_type="llm", provider="default", metric="output", rate_usd=1.50/1_000_000),
                PricingRate(service_type="stt", provider="deepgram", metric="per_second", rate_usd=0.0043/60),
                PricingRate(service_type="stt", provider="default", metric="per_second", rate_usd=0.005/60),
                PricingRate(service_type="tts", provider="elevenlabs", metric="per_char", rate_usd=0.30/1_000),
                PricingRate(service_type="tts", provider="default", metric="per_char", rate_usd=0.0),
                PricingRate(service_type="telephony", provider="inbound", metric="per_second", rate_usd=0.0085/60),
                PricingRate(service_type="telephony", provider="outbound", metric="per_second", rate_usd=0.013/60),
            ]
            session.add_all(default_rates)
            await session.commit()


# ── Scheduled Call Model ───────────────────────────────────────────────
class ScheduledCall(Base):
    """
    Represents an individually scheduled outbound phone call.

    Users can schedule one-off or recurring calls to specific contacts.
    A background scheduler picks up pending calls when their scheduled_at
    time arrives and initiates them via Twilio.
    """
    __tablename__ = "scheduled_calls"

    __table_args__ = (
        Index("idx_scheduled_at_status", "scheduled_at", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)

    # Contact info
    contact_name = Column(String(255), nullable=True)
    phone_number = Column(String(20), nullable=False)

    # Scheduling
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    timezone = Column(String(50), default="UTC")
    recurrence = Column(String(20), default="none")  # none, daily, weekly, monthly

    # Twilio config
    from_phone = Column(String(20), nullable=True)

    # Status: pending, executing, completed, failed, cancelled
    status = Column(String(20), default="pending", nullable=False)

    # Link to actual call after execution
    call_log_id = Column(Integer, ForeignKey("call_logs.id", ondelete="SET NULL"), nullable=True)

    # Error tracking
    last_error = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    agent = relationship("Agent", lazy="selectin")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent.name if self.agent else None,
            "contact_name": self.contact_name,
            "phone_number": self.phone_number,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "timezone": self.timezone,
            "recurrence": self.recurrence,
            "from_phone": self.from_phone,
            "status": self.status,
            "call_log_id": self.call_log_id,
            "last_error": self.last_error,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Playground Session Model ──────────────────────────────────────────
class PlaygroundSession(Base):
    """
    Records a playground testing session for later replay and analysis.

    Stores the full message history, execution trace events (for flow
    playground), mock context, and metadata about the agent and voice
    settings used during the session.
    """
    __tablename__ = "playground_sessions"

    __table_args__ = (
        Index("idx_playground_user_agent", "user_id", "agent_id"),
        Index("idx_playground_created", "created_at"),
        Index("idx_playground_session_type", "session_type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)

    # Session type: "chat" or "flow"
    session_type = Column(String(20), default="chat", nullable=False)

    # Full message history as JSON
    messages_json = Column(Text, nullable=True)

    # Execution trace events (for flow playground) as JSON
    trace_events_json = Column(Text, nullable=True)

    # Mock context used during the session
    context_json = Column(Text, nullable=True)

    # Voice settings
    voice_mode = Column(String(20), default="text")  # text, browser, production
    tts_provider = Column(String(50), nullable=True)

    # Metrics
    turn_count = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    total_latency_ms = Column(Float, default=0.0)

    # Status
    status = Column(String(20), default="active")  # active, ended, archived

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    agent = relationship("Agent", lazy="selectin")

    def to_dict(self):
        def _safe_json(value, default):
            if not value:
                return default
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return default

        return {
            "id": self.id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent.name if self.agent else None,
            "session_type": self.session_type,
            "messages": _safe_json(self.messages_json, []),
            "trace_events": _safe_json(self.trace_events_json, []),
            "context": _safe_json(self.context_json, {}),
            "voice_mode": self.voice_mode,
            "tts_provider": self.tts_provider,
            "turn_count": self.turn_count,
            "total_tokens": self.total_tokens,
            "total_latency_ms": self.total_latency_ms,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }


# ── Test Case Model ───────────────────────────────────────────────────
class TestCase(Base):
    """
    User-defined test cases for agent simulation/testing.

    Each test case specifies a user prompt and success criteria
    to evaluate the agent's response automatically.
    """
    __tablename__ = "test_cases"
    __test__ = False  # prevent pytest from collecting this as a test class

    __table_args__ = (
        Index("idx_testcase_agent", "agent_id"),
        Index("idx_testcase_user", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    label = Column(String(100), nullable=False)
    user_prompt = Column(Text, nullable=False)
    success_criteria = Column(Text, nullable=False)
    criteria_type = Column(String(20), default="keyword", nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "label": self.label,
            "user_prompt": self.user_prompt,
            "success_criteria": self.success_criteria,
            "criteria_type": self.criteria_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ── Test Run Model ────────────────────────────────────────────────────
class TestRun(Base):
    """
    Records a single simulation run — the result of sending a test
    case's user_prompt to the agent and evaluating the response.
    """
    __tablename__ = "test_runs"
    __test__ = False  # prevent pytest from collecting this as a test class

    __table_args__ = (
        Index("idx_testrun_agent", "agent_id"),
        Index("idx_testrun_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    test_case_id = Column(Integer, ForeignKey("test_cases.id", ondelete="SET NULL"), nullable=True)

    user_prompt = Column(Text, nullable=False)
    agent_response = Column(Text, nullable=True)
    passed = Column(Boolean, default=False, nullable=False)
    criteria_type = Column(String(20), nullable=True)
    success_criteria = Column(Text, nullable=True)

    latency_ms = Column(Integer, default=0)
    tokens_used = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "test_case_id": self.test_case_id,
            "user_prompt": self.user_prompt,
            "agent_response": self.agent_response,
            "passed": self.passed,
            "criteria_type": self.criteria_type,
            "success_criteria": self.success_criteria,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── Campaign Models ───────────────────────────────────────────────────
# Moved from api/campaign_routes.py to fix upward dependency (compliance → api).

class Campaign(Base):
    """Outbound calling campaign."""
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)

    status = Column(String(20), default="draft", nullable=False)

    from_phone = Column(String(20), nullable=True)
    max_concurrent_calls = Column(Integer, default=1)
    call_interval_secs = Column(Integer, default=30)
    max_cps = Column(Integer, default=1)
    max_retries = Column(Integer, default=2)
    max_call_duration_secs = Column(Integer, default=300)

    scheduled_start = Column(DateTime, nullable=True)

    total_contacts = Column(Integer, default=0)
    completed_contacts = Column(Integer, default=0)
    failed_contacts = Column(Integer, default=0)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    contacts = relationship("CampaignContact", back_populates="campaign", cascade="all, delete-orphan", lazy="selectin")
    agent = relationship("Agent", lazy="selectin")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "team_id": self.team_id,
            "name": self.name,
            "description": self.description,
            "agent_id": self.agent_id,
            "agent_name": self.agent.name if self.agent else None,
            "status": self.status,
            "from_phone": self.from_phone,
            "max_concurrent_calls": self.max_concurrent_calls,
            "call_interval_secs": self.call_interval_secs,
            "max_cps": self.max_cps,
            "max_retries": self.max_retries,
            "max_call_duration_secs": self.max_call_duration_secs,
            "scheduled_start": self.scheduled_start.isoformat() if self.scheduled_start else None,
            "total_contacts": self.total_contacts,
            "completed_contacts": self.completed_contacts,
            "failed_contacts": self.failed_contacts,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "progress_pct": round(
                (self.completed_contacts + self.failed_contacts) / self.total_contacts * 100, 1
            ) if self.total_contacts > 0 else 0,
        }


class CampaignContact(Base):
    """Individual contact in a campaign."""
    __tablename__ = "campaign_contacts"

    __table_args__ = (
        UniqueConstraint("campaign_id", "phone_number", name="uq_campaign_contact_phone"),
        Index("idx_campaign_contact_campaign_status", "campaign_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)

    phone_number = Column(String(20), nullable=False)
    name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    custom_data = Column(Text, nullable=True)

    consent_status = Column(String(20), default="unknown")
    consent_date = Column(DateTime, nullable=True)
    consent_source = Column(String(50), nullable=True)
    opted_out_at = Column(DateTime, nullable=True)
    timezone = Column(String(50), nullable=True)

    status = Column(String(20), default="pending", nullable=False)

    call_log_id = Column(Integer, ForeignKey("call_logs.id", ondelete="SET NULL"), nullable=True)
    call_duration_secs = Column(Float, nullable=True)
    call_outcome = Column(String(50), nullable=True)
    retries = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)

    called_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    campaign = relationship("Campaign", back_populates="contacts")

    def to_dict(self):
        custom = None
        if self.custom_data:
            try:
                custom = json.loads(self.custom_data)
            except Exception:
                custom = self.custom_data
        return {
            "id": self.id,
            "campaign_id": self.campaign_id,
            "phone_number": self.phone_number,
            "name": self.name,
            "email": self.email,
            "custom_data": custom,
            "status": self.status,
            "call_log_id": self.call_log_id,
            "call_duration_secs": self.call_duration_secs,
            "call_outcome": self.call_outcome,
            "retries": self.retries,
            "last_error": self.last_error,
            "consent_status": self.consent_status,
            "consent_date": self.consent_date.isoformat() if self.consent_date else None,
            "consent_source": self.consent_source,
            "opted_out_at": self.opted_out_at.isoformat() if self.opted_out_at else None,
            "timezone": self.timezone,
            "called_at": self.called_at.isoformat() if self.called_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# ── Database Session Dependency ────────────────────────────────────────
async def get_db():
    """
    FastAPI dependency that provides a database session.
    
    Usage in route handlers:
        @router.get("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(User))
            ...
    
    The session is automatically closed after the request completes,
    even if an exception occurs (guaranteed by the finally block).
    """
    async with async_session() as session:
        try:
            yield session  # Provide session to the route handler
        finally:
            await session.close()  # Always close when done
