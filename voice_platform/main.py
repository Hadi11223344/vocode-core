"""
VOIA Voice Platform — Main Server
====================================

This is the entry point for the VOIA voice agent backend.
It sets up the FastAPI application with:

1. Database initialization (SQLite via SQLAlchemy)
2. CORS middleware (for frontend at any origin)
3. Google OAuth + JWT authentication
4. REST API endpoints (agents, calls, keys, integrations, twilio, workflows, dashboard, settings)
5. Twilio telephony integration (via vocode's TelephonyServer)
6. Persistent event logging (transcripts, call lifecycle → database)
7. Modular provider system (user-selectable LLM, STT, TTS)
8. Cross-call memory (inject past conversation history into prompts)
9. User API key management (per-service keys: OpenAI, Gemini, Deepgram, etc.)
10. Integration system (Google Calendar, Google Sheets with workflow execution)

Architecture:
    Frontend (React) → REST API → Database
                     ↘ Twilio → vocode Pipeline → LLM/STT/TTS
                     
Run with:
    cd voice_platform && python main.py
    # Or:
    poetry run uvicorn voice_platform.main:app --host 0.0.0.0 --port 3000
"""

import asyncio  # For async startup tasks and background event loop
import os  # For environment variable access
import sys  # For sys.exit on critical errors
from contextlib import asynccontextmanager

from dotenv import load_dotenv  # Load .env file into os.environ
from fastapi import FastAPI, HTTPException, Request, Response, status  # The web framework
from fastapi.exceptions import RequestValidationError  # Pydantic validation errors
from fastapi.middleware.cors import CORSMiddleware  # Cross-origin requests
from fastapi.responses import JSONResponse  # For structured error responses
from loguru import logger  # Structured, human-readable logging
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware

from voice_platform.errors import AppError
from voice_platform.middleware.body_size_limit import BodySizeLimitMiddleware
from voice_platform.middleware.request_logging import RequestLoggingMiddleware
from voice_platform.middleware.security_headers import SecurityHeadersMiddleware
from voice_platform.middleware.ws_tracker import ws_tracker
from voice_platform.rate_limit import limiter

# ── Load .env BEFORE any other imports that need env vars ──────────────
# This ensures all os.environ lookups find the values from .env
# In Docker, let environment variables take precedence over .env file.
env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path, override=not os.getenv("DOCKER_ENV"))

# ── vocode imports ─────────────────────────────────────────────────────
from vocode.streaming.models.telephony import TwilioConfig  # Twilio credentials config
from vocode.streaming.telephony.config_manager.redis_config_manager import (
    RedisConfigManager,  # Stores active call configs in Redis
)
from vocode.streaming.telephony.server.base import (
    TelephonyServer,  # Handles Twilio webhooks and WebSocket calls
)
from voice_platform.agents.agent_factory import (
    PlatformAgentFactory,  # Creates vocode agents from DB config
)
from voice_platform.agents.agent_factory import _get_default_configs
from voice_platform.api.agent_routes import router as agent_router
from voice_platform.api.alert_routes import router as alert_router
from voice_platform.api.analytics_routes import router as analytics_router

# ── API route imports ──────────────────────────────────────────────────
from voice_platform.api.auth_routes import router as auth_router
from voice_platform.api.call_routes import router as call_router
from voice_platform.api.campaign_routes import router as campaign_router
from voice_platform.api.compliance_routes import router as compliance_router
from voice_platform.api.dashboard_routes import router as dashboard_router
from voice_platform.api.integration_routes import router as integration_router
from voice_platform.api.key_routes import router as key_router
from voice_platform.api.knowledge_base_routes import router as kb_router
from voice_platform.api.live_routes import router as live_router
from voice_platform.api.playground_routes import router as playground_router
from voice_platform.api.review_routes import router as review_router
from voice_platform.api.schedule_routes import router as schedule_router
from voice_platform.api.settings_routes import router as settings_router
from voice_platform.api.test_routes import router as test_router
from voice_platform.api.tools_routes import router as tools_router
from voice_platform.api.tts_routes import router as tts_router
from voice_platform.api.twilio_routes import router as twilio_router
from voice_platform.api.usage_routes import router as usage_router
from voice_platform.api.workflow_routes import router as workflow_router

# ── Platform imports ───────────────────────────────────────────────────
from voice_platform.config import settings  # Platform configuration (from .env)
from voice_platform.database import async_session  # Database session factory
from voice_platform.database import init_db  # Create database tables
from voice_platform.events.call_events import PersistentEventsManager  # DB-backed events
from voice_platform.telephony.inbound_handler import router as telephony_router

# ═══════════════════════════════════════════════════════════════════════
# Lifespan — Initialize & Tear Down Server Resources
# ═══════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(application: FastAPI):
    """
    Modern lifespan handler (replaces deprecated @app.on_event).

    Everything before ``yield`` runs at startup.
    Everything after ``yield`` runs at shutdown.
    """
    logger.info("🚀 Starting VOIA Voice Platform...")

    # ── Step 1: Database ──────────────────────────────────────────
    logger.info("📦 Initializing database...")
    await init_db()
    logger.info("✅ Database initialized")

    # ── Step 1c: ServiceContainer (application-scoped infrastructure) ─
    from voice_platform.runtime.session.service_container import ServiceContainer

    services = ServiceContainer()
    application.state.services = services
    logger.info(
        f"✅ ServiceContainer initialized "
        f"({len(services.plugin_registry.aliases())} plugin aliases registered)"
    )

    # ── Step 1d: ConversationSessionFactory (session construction) ───
    from voice_platform.runtime.session.factory import ConversationSessionFactory

    session_factory = ConversationSessionFactory(service_container=services)
    application.state.session_factory = session_factory
    logger.info("✅ ConversationSessionFactory initialized")

    # ── Step 1e: StateManager (LangGraph checkpointer lifecycle) ─────
    from voice_platform.runtime.session.state_manager import LangGraphStateManager

    state_manager = LangGraphStateManager()
    application.state.state_manager = state_manager
    logger.info("✅ StateManager initialized")

    # ── Step 1b: LangGraph checkpointer ───────────────────────────
    # Postgres checkpointer tables must exist before any playground flow starts.
    # For SQLite / development this is a no-op (MemorySaver fallback).
    try:
        await state_manager.setup()
    except Exception as e:
        logger.warning(f"⚠️  Could not initialize LangGraph checkpointer: {e}")

    # ── Step 1a: NLTK Setup ───────────────────────────────────────
    # Vocode uses NLTK to split LLM output into sentences for TTS streaming.
    # In Docker, these resources aren't downloaded by default, causing a LookupError
    # which crashes the call loop silently after the greeting.
    logger.info("📚 Checking NLTK resources...")
    import nltk
    try:
        nltk.data.find('tokenizers/punkt_tab')
    except LookupError:
        logger.info("⬇️  Downloading NLTK punkt tokenizer...")
        nltk.download('punkt', quiet=True)
        nltk.download('punkt_tab', quiet=True)
        logger.info("✅ NLTK setup complete")

    # ── Step 1b: Startup security + architecture checks ───────────
    # These don't block startup but surface misconfigurations early.

    # M-5: CORS wildcard warning
    if settings.cors_allowed_origins.strip() in ("*", ""):
        logger.warning(
            "⚠️  CORS is set to wildcard '*' — any origin can call the API. "
            "Set CORS_ALLOWED_ORIGINS=https://yourdomain.com in .env for production."
        )

    # M-10 / JWT weak default check — block startup in production
    _weak_jwt_defaults = {
        "voia-fyp-secret-change-in-production",
        "voia-fyp-secret-2026-change-in-production",
        "secret",
        "changeme",
    }
    if settings.jwt_secret in _weak_jwt_defaults or len(settings.jwt_secret) < 32:
        if not settings.allow_dev_login:
            logger.error(
                "❌ JWT_SECRET is too weak or too short (must be at least 32 bytes). "
                "Refusing to start. Set a strong random secret in .env: "
                "python -c \"import secrets; print(secrets.token_hex(32))\""
            )
            sys.exit(1)
        else:
            logger.warning(
                "⚠️  JWT_SECRET is too weak or too short. "
                "Tokens can be forged. Set a strong random secret in .env: "
                "python -c \"import secrets; print(secrets.token_hex(32))\""
            )

    # C-2/C-3: Google integration architecture note
    logger.info(
        "ℹ️  Google Calendar/Sheets integrations prefer OAuth tokens when connected. "
        "Service account JSON remains an optional fallback for advanced setups."
    )


    # ── Step 2: Base URL (ngrok or configured) ────────────────────
    base_url = settings.base_url
    if not base_url:
        if settings.ngrok_auth_token:
            base_url = await _setup_ngrok()
        else:
            base_url = f"http://{settings.host}:{settings.port}"
            logger.warning(
                f"⚠️ No BASE_URL or NGROK_AUTH_TOKEN set. "
                f"Using {base_url} — Twilio webhooks will NOT work."
            )

    # Strip protocol — vocode's TwiML template adds wss:// itself
    base_url = (base_url or f"http://{settings.host}:{settings.port}").replace(
        "https://", ""
    ).replace("http://", "")
    logger.info(f"🌐 Base URL: {base_url}")

    # ── Step 3: Events Manager ────────────────────────────────────
    events_manager = PersistentEventsManager()
    application.state.events_manager = events_manager

    # ── Step 4: Telephony Server ──────────────────────────────────
    tts_task = None
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        logger.warning(
            "⚠️ TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set. "
            "Telephony disabled — API-only mode."
        )
        application.state.config_manager = None
        application.state.twilio_config = None
        application.state.base_url = base_url
        events_task = asyncio.create_task(events_manager.start())
        logger.info("📊 Events manager started (persisting to database)")
        logger.info("✅ VOIA Voice Platform started (API-only, no telephony)")
    else:
        twilio_config = TwilioConfig(
            account_sid=settings.twilio_account_sid,
            auth_token=settings.twilio_auth_token,
            record=True,
        )

        default_agent_config, default_transcriber, default_synthesizer = await _get_default_configs()

        application.state.default_agent_config = default_agent_config
        application.state.default_transcriber = default_transcriber
        application.state.default_synthesizer = default_synthesizer
        application.state.twilio_config = twilio_config
        application.state.base_url = base_url

        telephony_server = TelephonyServer(
            base_url=base_url,
            config_manager=RedisConfigManager(),
            inbound_call_configs=[],
            agent_factory=PlatformAgentFactory(),
            events_manager=events_manager,
        )
        application.state.telephony_server = telephony_server
        application.state.config_manager = telephony_server.config_manager

        for route in telephony_server.router.routes:
            application.routes.append(route)

        logger.info("📞 Telephony server configured")

        # ── Step 5: Pre-cache TTS for initial greeting ────────────
        tts_task = asyncio.create_task(_safe_background_task("TTS warm-up", _warm_up_tts_cache(default_agent_config)))

        events_task = asyncio.create_task(events_manager.start())
        logger.info("📊 Events manager started (persisting to database)")
        logger.info("✅ VOIA Voice Platform started successfully!")
        logger.info(f"📖 API docs: {base_url}/docs")

    settings.base_url = base_url

    # ── Step 6: Scheduled Call Background Scheduler ─────────────
    from voice_platform.api.schedule_routes import execute_pending_scheduled_calls

    async def _scheduler_loop():
        while True:
            try:
                await execute_pending_scheduled_calls()
            except Exception as e:
                logger.error(f"Scheduled call scheduler error: {e}")
            await asyncio.sleep(30)

    scheduler_task = asyncio.create_task(_scheduler_loop())
    logger.info("⏰ Scheduled call background scheduler started (30s interval)")

    # ── Yield control to the running application ──────────────────
    yield

    # ── Shutdown scheduler ─────────────────────────────────────
    scheduler_task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(scheduler_task), timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    # ── Cancel TTS warm-up if still running ───────────────────
    if tts_task is not None and not tts_task.done():
        tts_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(tts_task), timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    # ── Graceful WebSocket call shutdown ──────────────────────────
    # Give active calls 10s to finish before we cancel the events manager.
    # This prevents mid-sentence drops during rolling deployments.
    telephony = getattr(application.state, "telephony_server", None)
    if telephony is not None:
        logger.info("📞 Grace period for active calls (10s)...")
        await asyncio.sleep(10)

    # ── Graceful WebSocket shutdown ──────────────────────────
    # Close all playground/live WebSocket connections before tearing down.
    await ws_tracker.close_all()

    # ── Shutdown ──────────────────────────────────────────────────
    logger.info("🛑 Shutting down VOIA Voice Platform...")    

    # Close the shared LangGraph checkpointer pool (Postgres only).
    try:
        await state_manager.close()
    except Exception as e:
        logger.warning(f"Error closing LangGraph checkpointer: {e}")

    events_task.cancel()
    # FIX M-1: Await the task so pending transcript writes finish cleanly
    # before the DB session closes. Without this, asyncio may emit
    # 'Task was destroyed but it is pending!' and in-flight writes are lost.
    try:
        await asyncio.wait_for(asyncio.shield(events_task), timeout=5.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass  # Expected — the task was cancelled or timed out cleanly
    logger.info("✅ Shutdown complete")


# ═══════════════════════════════════════════════════════════════════════
# FastAPI Application Setup
# ═══════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="VOIA Voice Platform",
    description=(
        "Backend API for the VOIA voice agent platform. "
        "Handles user authentication, agent management, real-time voice calls, "
        "and call logging. Built on vocode-core."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ── Rate Limiting ──────────────────────────────────────────────────────
# Protect endpoints from abuse. Limits are per-IP by default.
# Override per-route with @limiter.limit("X/minute") decorator.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)

# ── Request Body Size Limit ────────────────────────────────────────────
# M10: Reject request bodies larger than 10 MB to prevent memory exhaustion.
app.add_middleware(BodySizeLimitMiddleware, max_body_size=10 * 1024 * 1024)


# ── Global Exception Handlers ─────────────────────────────────────────
# Catch unhandled exceptions and return consistent, user-friendly errors
# instead of bare 500s with no context.

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    """Return structured AppError responses with code, message, suggestion."""
    logger.warning(f"AppError {exc.code.value} on {request.url.path}: {exc.message}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.to_dict()},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return human-readable validation errors instead of raw Pydantic dumps."""
    errors = exc.errors()
    messages = []
    for err in errors:
        field = " → ".join(str(loc) for loc in err.get("loc", []) if loc != "body")
        messages.append(f"{field}: {err.get('msg', 'invalid value')}")
    detail = "; ".join(messages) if messages else "Invalid request data."
    logger.warning(f"Validation error on {request.url.path}: {detail}")
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request data.",
                "detail": {"fields": detail},
                "suggestion": "Check the highlighted fields and try again.",
            }
        },
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all for unhandled exceptions.

    Returns a structured error response instead of a bare
    {"detail": "Internal Server Error"} with no context.
    Strips internal details (stack traces, secrets) from the message.
    """
    # Don't intercept HTTPExceptions or AppErrors — handled above
    from fastapi import HTTPException
    if isinstance(exc, (HTTPException, AppError)):
        raise exc

    error_type = type(exc).__name__
    safe_message = _get_safe_error_message(exc)

    logger.error(f"Unhandled {error_type} on {request.method} {request.url.path}: {exc}")

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": safe_message,
                "suggestion": "Please try again in a moment. If the problem persists, contact support.",
            }
        },
    )

def _get_safe_error_message(exc: Exception) -> str:
    """Convert an exception into a user-safe message without leaking internals."""
    import re

    msg = str(exc)
    error_type = type(exc).__name__
    msg_lower = msg.lower()

    # Database errors
    if "sqlalchemy" in error_type.lower() or "database" in msg_lower or "sqlite" in msg_lower:
        return "A database error occurred. Please try again."

    # Connection errors
    if any(kw in msg_lower for kw in ["connection refused", "timeout", "connection reset", "network"]):
        return "A network connection error occurred. Please try again."

    # Redis errors
    if "redis" in msg_lower:
        return "A cache service error occurred. Please try again."

    # Twilio errors — remove account SIDs and auth tokens
    if "twilio" in msg_lower:
        safe = re.sub(r'AC[a-f0-9]{32}', '[ACCOUNT]', msg)
        safe = re.sub(r'SK[a-f0-9]{32}', '[KEY]', safe)
        safe = re.sub(r'[a-f0-9]{32}', '[REDACTED]', safe)
        return f"Twilio error: {safe[:200]}"

    # Redact common API key patterns (sk-..., Bearer ..., long hex strings)
    safe = re.sub(r'sk-[a-zA-Z0-9]{20,}', '[API_KEY]', msg)
    safe = re.sub(r'Bearer\s+[a-zA-Z0-9._-]+', 'Bearer [REDACTED]', safe)
    safe = re.sub(r'[a-f0-9]{32,}', '[REDACTED]', safe)

    # Redact email addresses
    safe = re.sub(r'[\w.+-]+@[\w-]+\.[\w.-]+', '[EMAIL]', safe)

    # Redact phone numbers (E.164 or common formats)
    safe = re.sub(r'\+1?\d{10,15}', '[PHONE]', safe)

    # Generic — don't leak the full message if it's long (could contain stack traces)
    if len(safe) > 200:
        return "An unexpected error occurred. Please try again or contact support."

    return safe or "An unexpected error occurred."


# ── Security Headers Middleware ────────────────────────────────────────
# C1: Add browser security headers to every response.
app.add_middleware(SecurityHeadersMiddleware)


# ── Request Logging & Correlation Middleware ───────────────────────────
# M2/m10: Log every request with method, path, status, duration, and request ID.
app.add_middleware(RequestLoggingMiddleware)


# ── CORS Middleware ────────────────────────────────────────────────────
# SEC-03: Block wildcard in production (allow_dev_login=False means production)
_cors_origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
if "*" in _cors_origins and not settings.allow_dev_login:
    logger.critical(
        "SEC-03: CORS wildcard '*' is forbidden in production. "
        "Set CORS_ALLOWED_ORIGINS=https://yourdomain.com in .env"
    )
    _cors_origins = []  # Block all cross-origin requests

# C4: When wildcard is used (dev mode), disable credentials to comply with CORS spec.
_cors_allow_credentials = "*" not in _cors_origins
if not _cors_allow_credentials:
    logger.warning(
        "⚠️  CORS wildcard detected — allow_credentials set to False per CORS spec."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Request-ID",
        "X-Twilio-Signature",
    ],
)


# ── Mount API Routers ─────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(agent_router)
app.include_router(call_router)
app.include_router(key_router)
app.include_router(integration_router)
app.include_router(twilio_router)
app.include_router(dashboard_router)
app.include_router(settings_router)
app.include_router(workflow_router)
app.include_router(review_router)
app.include_router(live_router)
app.include_router(analytics_router)
app.include_router(alert_router)
app.include_router(usage_router)
app.include_router(tools_router)
app.include_router(tts_router)
app.include_router(playground_router)
app.include_router(kb_router)
app.include_router(schedule_router)
app.include_router(campaign_router)
app.include_router(compliance_router)
app.include_router(test_router)
app.include_router(telephony_router)


# ═══════════════════════════════════════════════════════════════════════
# Health Check
# ═══════════════════════════════════════════════════════════════════════

@app.get("/", tags=["Health"])
async def health_check():
    """
    Health check endpoint.
    
    Returns basic server status. Used by monitoring tools and the
    frontend to check if the backend is running.
    """
    return {
        "status": "ok",
        "service": "VOIA Voice Platform",
        "version": "1.0.0",
    }


@app.get("/health", tags=["Health"])
async def health():
    """Comprehensive health check with DB and Redis connectivity."""
    from sqlalchemy import text

    checks = {
        "status": "ok",
        "service": "VOIA Voice Platform",
        "version": "1.0.0",
        "checks": {},
    }
    healthy = True

    # Database check
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        checks["checks"]["database"] = "ok"
    except Exception:
        checks["checks"]["database"] = "error"
        healthy = False

    # Redis check
    try:
        config_manager = getattr(app.state, "config_manager", None)
        if config_manager is not None:
            redis_client = getattr(config_manager, "redis", None)
            if redis_client is not None:
                await redis_client.ping()
                checks["checks"]["redis"] = "ok"
            else:
                checks["checks"]["redis"] = "not configured"
        else:
            checks["checks"]["redis"] = "not configured"
    except Exception:
        checks["checks"]["redis"] = "error"
        healthy = False

    if not healthy:
        checks["status"] = "degraded"
        return JSONResponse(content=checks, status_code=503)

    return checks


async def _warm_up_tts_cache(agent_config):
    """
    Pre-synthesize greetings + fillers via Deepgram TTS so the first
    call plays them from cache instead of waiting several seconds.

    Loads each agent's (voice, initial_message) from the DB so SmileCare
    (aura-stella-en) and others get their exact opener warmed — not just
    the default agent greeting on asteria.
    """
    try:
        import aiohttp
        from sqlalchemy import select

        from vocode.streaming.synthesizer.deepgram_synthesizer import FILLER_PHRASES, _audio_cache
        from voice_platform.database import Agent, async_session

        dg_key = os.environ.get("DEEPGRAM_API_KEY", "")
        if not dg_key:
            logger.warning("No DEEPGRAM_API_KEY — skipping TTS warm-up")
            return

        # voice → set of phrases to warm
        warm_map: dict[str, set[str]] = {
            "aura-asteria-en": set(FILLER_PHRASES),
            "aura-stella-en": set(FILLER_PHRASES),
            "aura-luna-en": set(FILLER_PHRASES),
            "aura-athena-en": set(FILLER_PHRASES),
            "aura-orpheus-en": set(FILLER_PHRASES),
        }

        default_greeting = None
        if hasattr(agent_config, "initial_message") and agent_config.initial_message:
            default_greeting = (agent_config.initial_message.text or "").strip() or None
        if default_greeting:
            warm_map["aura-asteria-en"].add(default_greeting)

        try:
            async with async_session() as session:
                rows = (
                    await session.execute(
                        select(Agent.initial_message, Agent.tts_voice_id).where(
                            Agent.initial_message.isnot(None)
                        )
                    )
                ).all()
            for greeting, voice_id in rows:
                text = (greeting or "").strip()
                if not text:
                    continue
                voice = voice_id if (
                    isinstance(voice_id, str) and voice_id.startswith("aura-")
                ) else "aura-asteria-en"
                warm_map.setdefault(voice, set(FILLER_PHRASES)).add(text)
        except Exception as db_err:
            logger.warning(f"TTS warm-up: could not load agent greetings from DB: {db_err}")

        headers = {
            "Authorization": f"Token {dg_key}",
            "Content-Type": "application/json",
        }

        cached_count = 0
        async with aiohttp.ClientSession() as session:
            for voice, phrases in warm_map.items():
                params = {"model": voice, "encoding": "mulaw", "sample_rate": "8000"}
                for phrase in phrases:
                    cache_key = f"{voice}:True:{phrase}"
                    if cache_key in _audio_cache:
                        continue
                    for attempt in range(2):
                        try:
                            async with session.post(
                                "https://api.deepgram.com/v1/speak",
                                headers=headers,
                                params=params,
                                json={"text": phrase},
                                timeout=aiohttp.ClientTimeout(total=30),
                            ) as resp:
                                if resp.status == 200:
                                    audio = await resp.read()
                                    _audio_cache[cache_key] = audio
                                    cached_count += 1
                                    logger.info(
                                        f"🔊 TTS cached [{voice}]: '{phrase[:40]}...' ({len(audio)} bytes)"
                                    )
                                    break
                                else:
                                    err = await resp.text()
                                    logger.warning(
                                        f"TTS warm-up failed for '{phrase[:30]}' [{voice}]: {err}"
                                    )
                        except Exception as e:
                            if attempt == 0:
                                logger.debug(
                                    f"TTS warm-up retry for '{phrase[:30]}' [{voice}]: {e}"
                                )
                            else:
                                logger.warning(
                                    f"TTS warm-up error for '{phrase[:30]}' [{voice}]: {e}"
                                )

        logger.info(
            f"✅ TTS warm-up done — {cached_count} new phrases cached "
            f"({len(_audio_cache)} total in cache)"
        )
    except Exception as e:
        logger.warning(f"TTS warm-up failed: {e}")


async def _safe_background_task(name: str, coro):
    """Wrap a background task so exceptions are logged instead of silently lost.

    Usage:
        asyncio.create_task(_safe_background_task("My task", my_coro()))
    """
    try:
        await coro
    except asyncio.CancelledError:
        pass  # Expected during shutdown
    except Exception as e:
        logger.error(f"Background task '{name}' failed: {type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════

async def _setup_ngrok():
    """
    Set up an ngrok tunnel for development.
    
    ngrok creates a public URL (e.g. https://abc123.ngrok.io) that
    forwards traffic to our local server. This is needed for Twilio
    to send webhooks to our local machine.
    
    Returns:
        The public ngrok URL (e.g. "https://abc123.ngrok-free.app")
    """
    try:
        from pyngrok import ngrok  # Import only when needed

        # Set the auth token for ngrok
        ngrok.set_auth_token(settings.ngrok_auth_token)
        
        # Kill any existing tunnels first (prevents ERR_NGROK_334 on hot-reload)
        try:
            for tunnel in ngrok.get_tunnels():
                logger.info(f"🔗 Closing existing ngrok tunnel: {tunnel.public_url}")
                ngrok.disconnect(tunnel.public_url)
        except Exception:
            pass  # No tunnels open or ngrok not running yet
        
        # Open a tunnel to our server port
        tunnel = ngrok.connect(settings.port, bind_tls=True)
        
        # Get the public URL
        public_url = tunnel.public_url
        logger.info(f"🔗 ngrok tunnel established: {public_url}")
        
        return public_url
    
    except Exception as e:
        logger.error(f"Failed to set up ngrok: {e}")
        return f"http://{settings.host}:{settings.port}"


def _can_bind_port(host: str, port: int) -> bool:
    """Return True when the configured host/port can be bound."""
    import socket

    bind_host = host if host not in ("0.0.0.0", "::") else "127.0.0.1"
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((bind_host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


# ═══════════════════════════════════════════════════════════════════════
# Direct Execution
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn  # ASGI server

    # Disable reload when using ngrok — hot-reload causes duplicate tunnel errors
    use_reload = not settings.ngrok_auth_token
    if not use_reload:
        logger.info("🔄 Hot-reload disabled (ngrok mode — restart manually for code changes)")

    if not _can_bind_port(settings.host, settings.port):
        logger.error(
            f"❌ Cannot start server on {settings.host}:{settings.port} — port already in use. "
            "Stop the existing process or choose a different PORT."
        )
        sys.exit(1)

    uvicorn.run(
        "voice_platform.main:app",
        host=settings.host,
        port=settings.port,
        reload=use_reload,
    )
