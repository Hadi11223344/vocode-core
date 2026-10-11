# Deployment Guide — VOIA Voice Platform

> **Audience**: Developers deploying the vocode-core platform + voice_platform to staging or production.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Environment Variables](#environment-variables)
3. [Security Hardening](#security-hardening)
4. [Database Setup](#database-setup)
5. [Redis Setup](#redis-setup)
6. [Running the Application](#running-the-application)
7. [Docker Deployment](#docker-deployment)
8. [Twilio Webhook Configuration](#twilio-webhook-configuration)
9. [CORS Configuration](#cors-configuration)
10. [Monitoring & Logging](#monitoring--logging)
11. [Production Checklist](#production-checklist)

---

## Prerequisites

| Tool | Minimum Version | Purpose |
|------|----------------|---------|
| Python | 3.10+ | Runtime |
| Poetry | 1.7+ | Dependency management |
| Redis | 6+ | Active call config storage |
| ngrok (dev only) | — | Tunnel for local Twilio webhooks |

Install project dependencies:

```bash
poetry install
```

---

## Environment Variables

Copy the template and fill in real values:

```bash
cp voice_platform/.env.example voice_platform/.env
```

### Required Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `TWILIO_ACCOUNT_SID` | Twilio Account SID | `AC...` |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token | `abc123...` |
| `DEEPGRAM_API_KEY` | Deepgram STT API key | `dg_...` |
| `OPENAI_API_KEY` | OpenAI API key (or Gemini-compatible endpoint) | `sk-...` |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BASE_URL` | — | Public URL for Twilio webhooks (e.g. `https://your-domain.com`) |
| `NGROK_AUTH_TOKEN` | — | Auto-start ngrok tunnel in development |
| `GOOGLE_CLIENT_ID` | — | Google OAuth client ID for frontend auth |
| `JWT_SECRET` | _(empty)_ | **Required ≥32 chars in production** (app refuses weak/empty when `ALLOW_DEV_LOGIN=false`) |
| `CORS_ALLOWED_ORIGINS` | `*` | Comma-separated list of allowed origins |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection string |
| `GROQ_API_KEY` | — | Groq LLM API key (primary LLM provider) |
| `OPENAI_API_KEY` | — | OpenAI API key (fallback LLM) |
| `GEMINI_API_KEY` | — | Google Gemini API key |
| `COMMANDCODE_API_KEY` | — | CommandCode provider API key |
| `OPENAI_API_BASE` | — | OpenAI-compatible endpoint URL (e.g. Ollama) |
| `ELEVENLABS_API_KEY` | — | ElevenLabs TTS (if using this provider) |
| `AZURE_SPEECH_KEY` | — | Azure Speech TTS/STT |
| `AZURE_SPEECH_REGION` | `eastus` | Azure Speech region |
| `CARTESIA_API_KEY` | — | Cartesia TTS |
| `ENCRYPTION_KEY` | derived | Fernet key for encrypting API keys at rest (auto-derived from JWT_SECRET if not set) |
| `ALLOW_PLATFORM_TWILIO_FALLBACK` | `true` | Allow platform Twilio creds for read-only routes (keep false for multi-tenant) |
| `ALLOW_PLATFORM_TWILIO_FALLBACK_FOR_CAMPAIGNS` | `false` | Campaign execution on shared Twilio creds (keep false) |
| `DATABASE_URL` | SQLite | PostgreSQL connection string for production |

> **Security**: Never commit `.env` files. The `.gitignore` already excludes `voice_platform/.env` and `voice_platform/voia.db`.

---

## Security Hardening

### JWT Secret

Generate a strong random secret:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Set it in your environment:

```bash
JWT_SECRET=<generated-secret>
```

### CORS

In production, **never** use `*` as the allowed origin. Set it to your frontend domain:

```bash
CORS_ALLOWED_ORIGINS=https://app.yourdomain.com,https://admin.yourdomain.com
```

### API Keys

- Use user-level API keys when possible (agents store their own `llm_api_key`, `stt_api_key`, `tts_api_key`)
- Platform-level keys from `.env` are used as fallback when user keys are null
- Rotate keys regularly and use a secrets manager in production

### Twilio Webhook and Campaign Hardening

Use these environment flags to enforce request authenticity and tenant boundaries:

| Variable | Dev | Staging | Production | Notes |
|----------|-----|---------|------------|-------|
| `REQUIRE_TWILIO_WEBHOOK_SIGNATURE` | `false` | `true` | `true` | Enforces signed Twilio webhooks on `/inbound_call` and `/call_status`. |
| `VALIDATE_TWILIO_WEBHOOK_IF_PRESENT` | `true` | `true` | `true` | Rejects spoofed requests when a signature header is present. |
| `ALLOW_PLATFORM_TWILIO_FALLBACK_FOR_CAMPAIGNS` | `false` | `false` | `false` | Keep disabled to prevent cross-tenant campaign execution on shared credentials. |

Example production snippet:

```bash
REQUIRE_TWILIO_WEBHOOK_SIGNATURE=true
VALIDATE_TWILIO_WEBHOOK_IF_PRESENT=true
ALLOW_PLATFORM_TWILIO_FALLBACK_FOR_CAMPAIGNS=false
```

### Database

- The default SQLite database is suitable for development and small deployments
- For production at scale, consider migrating to PostgreSQL (change `DATABASE_URL` and engine configuration)
- Ensure `voia.db` file has restricted permissions: `chmod 600 voice_platform/voia.db`

---

## Database Setup

### Initialize

On first run, the application auto-creates all tables and seeds default settings:

```bash
cd voice_platform && python main.py
```

### Migrations (Alembic)

The project uses Alembic for schema migrations:

```bash
cd voice_platform

# Check current migration status
alembic current

# Apply all pending migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "description of change"

# Rollback one migration
alembic downgrade -1
```

### Backup

```bash
# SQLite backup
cp voice_platform/voia.db voice_platform/voia.db.backup.$(date +%Y%m%d)
```

---

## Redis Setup

Redis is required for storing active call configurations (managed by vocode's `RedisConfigManager`).

### Local Development

```bash
# macOS
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt install redis-server
sudo systemctl enable redis-server
```

### Docker

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

### Production

Set the Redis URL in your environment:

```bash
REDIS_URL=redis://username:password@redis-host:6379/0
```

---

## Running the Application

### Development

```bash
cd voice_platform
python main.py
# Server starts on http://localhost:3000
```

### Production (uvicorn)

```bash
poetry run uvicorn voice_platform.main:app \
  --host 0.0.0.0 \
  --port 3000 \
  --workers 4 \
  --log-level info
```

### With systemd

Create `/etc/systemd/system/voia.service`:

```ini
[Unit]
Description=VOIA Voice Platform
After=network.target redis.service

[Service]
Type=exec
User=voia
Group=voia
WorkingDirectory=/opt/voia/vocode-core
ExecStart=/opt/voia/vocode-core/.venv/bin/uvicorn voice_platform.main:app --host 0.0.0.0 --port 3000 --workers 4
Restart=always
RestartSec=5
EnvironmentFile=/opt/voia/vocode-core/voice_platform/.env

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable voia
sudo systemctl start voia
```

---

## Docker Deployment

### Development (Docker Compose)

The `docker-compose.yml` includes 4 services: `db` (PostgreSQL), `redis`, `app` (backend), and `frontend` (Next.js).

```bash
# Start all services
docker compose --profile development up -d

# View logs
docker compose --profile development logs -f app

# Stop all services
docker compose --profile development down
```

Access:
- Frontend: `http://localhost:3001`
- Backend API: `http://localhost:3000`
- API docs: `http://localhost:3000/docs`

### Production (Docker Compose)

Use the production profile which builds with `Dockerfile.production` (multi-stage, optimized layers):

```bash
# Build and start production services
docker compose --profile production up -d

# View logs
docker compose --profile production logs -f app-prod

# Stop production services
docker compose --profile production down
```

Before starting, set these in your `voice_platform/.env`:
```bash
BASE_URL=https://voice.yourdomain.com
JWT_SECRET=<strong-random-secret>
CORS_ALLOWED_ORIGINS=https://app.yourdomain.com
REQUIRE_TWILIO_WEBHOOK_SIGNATURE=true
```

### Manual Docker Build

```bash
# Build the production image
docker build -f docker/Dockerfile.production -t voia-platform .

# Run with external Redis
 docker run -d \
  --name voia \
  -p 3000:3000 \
  --env-file voice_platform/.env \
  -e REDIS_URL=redis://host.docker.internal:6379 \
  voia-platform
```

### Docker Compose (full stack)

The project's `docker-compose.yml` already defines all services. The key services are:

| Service | Port | Description |
|---------|------|-------------|
| `db` | 5433→5432 | PostgreSQL 16 |
| `redis` | 6380→6379 | Redis 7 |
| `app` | 3000 | Backend (dev Dockerfile) |
| `frontend` | 3001 | Next.js frontend |
| `app-prod` | 3000 | Backend (production Dockerfile, profile: production) |
| `frontend-prod` | 3001 | Next.js frontend (profile: production) |

---

## Twilio Webhook Configuration

### 1. Get Your Public URL

**Development** (with ngrok):
```bash
ngrok http 3000
# Copy the https:// URL
```

**Production**: Use your domain (e.g. `https://voice.yourdomain.com`)

Set it in `.env`:
```bash
BASE_URL=https://your-public-url.com
```

### 2. Configure Twilio Phone Number

In [Twilio Console](https://console.twilio.com/) → Phone Numbers → Your Number:

| Setting | Value |
|---------|-------|
| **Voice & Fax → A Call Comes In** | Webhook: `https://your-url/inbound_call` |
| **HTTP Method** | `POST` |

The platform handles:
- `POST /inbound_call` — Twilio webhook for incoming calls
- WebSocket connections for real-time audio streaming

### 3. Outbound Calls

Outbound calls are initiated via the API:
```bash
POST /api/calls/outbound
{
  "agent_id": 1,
  "to_phone": "+15551234567"
}
```

---

## CORS Configuration

The `CORS_ALLOWED_ORIGINS` environment variable controls which frontend domains can call the API.

```bash
# Development (allow all — NOT for production)
CORS_ALLOWED_ORIGINS=*

# Production (specific origins)
CORS_ALLOWED_ORIGINS=https://app.yourdomain.com,https://admin.yourdomain.com

# Multiple origins
CORS_ALLOWED_ORIGINS=https://app.example.com,https://staging.example.com,http://localhost:5173
```

---

## Monitoring & Logging

### Loguru

The platform uses `loguru` for structured logging. Logs are written to stdout by default.

### Sentry (Optional)

The vocode streaming SDK includes optional Sentry tracing. To enable:

```bash
pip install sentry-sdk
```

```python
import sentry_sdk
sentry_sdk.init(dsn="your-sentry-dsn", traces_sample_rate=0.1)
```

### Health Check

```bash
curl http://localhost:3000/docs  # Swagger UI — confirms server is running
```

---

## Troubleshooting

### Port already in use

```bash
# Check what's using port 3000 or 3001
lsof -i :3000
lsof -i :3001

# Kill the process or change the port in docker-compose.yml
```

### Redis connection refused

```bash
# Check if Redis is running
docker compose ps redis

# Test connection
docker compose exec redis redis-cli ping
# Should return: PONG
```

### Database migration errors

```bash
# Check current migration status
docker compose exec app alembic current

# Apply pending migrations
docker compose exec app alembic upgrade head

# If tables are out of sync, recreate (WARNING: data loss)
docker compose exec app python -c "from voice_platform.database import Base, engine; Base.metadata.drop_all(engine); Base.metadata.create_all(engine)"
```

### Twilio webhook not receiving calls

1. Verify `BASE_URL` is set to your public URL (not localhost)
2. Check Twilio Console → Phone Numbers → Voice webhook points to `https://your-url/inbound_call`
3. Ensure `REQUIRE_TWILIO_WEBHOOK_SIGNATURE=true` in production
4. Test webhook: `curl -X POST https://your-url/inbound_call`

### Frontend can't reach backend

1. Check `NEXT_PUBLIC_API_URL` is set correctly in docker-compose
2. In Docker, frontend uses `http://app:3000` internally (via `DOCKER_ENV=1`)
3. Externally, frontend calls `http://localhost:3000`
4. Verify CORS: `CORS_ALLOWED_ORIGINS` must include the frontend URL

### ngrok tunnel issues

```bash
# If BASE_URL is empty, the app auto-starts ngrok
# Ensure NGROK_AUTH_TOKEN is set in .env
# Check logs for tunnel URL:
docker compose logs app | grep ngrok
```

---

## Production Checklist

- [ ] **JWT_SECRET** — set to a strong random value (not the default)
- [ ] **CORS_ALLOWED_ORIGINS** — set to specific frontend domains, not `*`
- [ ] **`.env` file** — verify it's not committed to git
- [ ] **Database** — using PostgreSQL (set `DATABASE_URL`)
- [ ] **Alembic** — run `alembic upgrade head` after deployment
- [ ] **Redis** — running and accessible at `REDIS_URL`
- [ ] **Twilio** — webhook URL points to your public domain
- [ ] **Twilio signatures** — `REQUIRE_TWILIO_WEBHOOK_SIGNATURE=true`
- [ ] **Twilio validation** — `VALIDATE_TWILIO_WEBHOOK_IF_PRESENT=true`
- [ ] **Campaign fallback** — `ALLOW_PLATFORM_TWILIO_FALLBACK_FOR_CAMPAIGNS=false`
- [ ] **SSL/TLS** — use HTTPS in production (required for Twilio webhooks)
- [ ] **API keys** — all required provider keys configured (Twilio, Deepgram, LLM)
- [ ] **Google OAuth** — `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` configured
- [ ] **Firewall** — only expose ports 3000 and 3001 (or behind reverse proxy)
- [ ] **Reverse proxy** — Nginx/Caddy in front of uvicorn for TLS termination
- [ ] **Process manager** — systemd, Docker, or supervisor for auto-restart
- [ ] **Backups** — regular database backups scheduled
- [ ] **Monitoring** — log aggregation and error tracking configured
- [ ] **Health check** — `curl http://localhost:3000/health` returns 200
