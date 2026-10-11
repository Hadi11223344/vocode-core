# VOIA Voice Platform — Complete Developer Documentation

> **Target audience:** Beginner developers — both the backend developer who maintains this and the frontend developer who connects a React/Next.js app to it.

---

## Table of Contents

1. [What is VOIA?](#1-what-is-voia)
2. [Architecture Overview](#2-architecture-overview)
3. [Project File Structure](#3-project-file-structure)
4. [How to Set Up & Run](#4-how-to-set-up--run)
5. [Environment Variables (.env)](#5-environment-variables-env)
6. [Database — How Data is Stored](#6-database--how-data-is-stored)
7. [Authentication — How Login Works](#7-authentication--how-login-works)
8. [API Endpoints — Complete Reference](#8-api-endpoints--complete-reference)
9. [The Modular Provider System](#9-the-modular-provider-system)
10. [How Phone Calls Work (End-to-End)](#10-how-phone-calls-work-end-to-end)
11. [Frontend Integration Guide (React/Next.js)](#11-frontend-integration-guide-reactnextjs)
12. [How to Extend the Platform](#12-how-to-extend-the-platform)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. What is VOIA?

VOIA is a **voice AI platform** that lets users create custom AI phone agents. Think of it like building a receptionist that answers your business phone calls automatically.

**What it does:**
- A real phone number (via Twilio) rings → our server picks up
- AI listens to the caller using Speech-to-Text (Deepgram)
- AI thinks of a response using a Large Language Model (OpenAI GPT-4)
- AI speaks the response using Text-to-Speech (gTTS/ElevenLabs)
- All of this happens in real-time, like a normal phone conversation
- Every call is logged with full transcripts in the database

**What makes it special:**
- Users can pick WHICH AI provider to use (OpenAI vs Groq vs Anthropic)
- Users can bring their OWN API keys
- Everything is controlled via REST API (the frontend is a separate app)

---

## 2. Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│                        VOIA SYSTEM                             │
│                                                                │
│  ┌──────────┐     REST API (JSON)     ┌─────────────────────┐ │
│  │          │ ◄──────────────────────► │                     │ │
│  │ Frontend │                         │   FastAPI Server     │ │
│  │ (React)  │   Auth: JWT Bearer      │   (main.py)         │ │
│  │          │                         │                     │ │
│  └──────────┘                         │  ┌───────────────┐  │ │
│                                       │  │ API Routes    │  │ │
│                                       │  │ • auth        │  │ │
│                                       │  │ • agents      │  │ │
│                                       │  │ • calls       │  │ │
│                                       │  │ • dashboard   │  │ │
│                                       │  │ • settings    │  │ │
│                                       │  │ • workflows   │  │ │
│                                       │  └───────────────┘  │ │
│                                       │                     │ │
│                                       │  ┌───────────────┐  │ │
│  ┌──────────┐   Twilio Webhooks       │  │ Telephony     │  │ │
│  │          │ ────────────────────────►│  │ Server        │  │ │
│  │  Twilio  │                         │  │ (vocode-core) │  │ │
│  │  (Phone) │ ◄──── WebSocket ───────►│  │               │  │ │
│  │          │   (audio streaming)     │  └───────┬───────┘  │ │
│  └──────────┘                         │          │          │ │
│                                       │          ▼          │ │
│                                       │  ┌───────────────┐  │ │
│                                       │  │ Voice Pipeline│  │ │
│                                       │  │ STT→LLM→TTS  │  │ │
│                                       │  └───────────────┘  │ │
│                                       │                     │ │
│  ┌──────────┐     ┌──────────┐        │  ┌───────────────┐  │ │
│  │  SQLite  │◄───►│  Redis   │◄──────►│  │ Events Manager│  │ │
│  │ (voia.db)│     │ (6379)   │        │  │ (DB logging)  │  │ │
│  └──────────┘     └──────────┘        │  └───────────────┘  │ │
│                                       └─────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

**Data flow during a phone call:**

```
Phone → Twilio → POST /inbound_call → WebSocket → vocode pipeline
                                                        │
                   Audio in ───────► [Deepgram STT] ────┤
                                                        │
                                     [OpenAI GPT-4] ◄───┤
                                                        │
                   Audio out ◄────── [gTTS/11Labs] ◄────┘
                                                        │
              (Events Manager saves transcript to SQLite DB)
```

---

## 3. Project File Structure

```
vocode-core/                          ← Root of the entire project
│
├── vocode/                           ← vocode-core library (DON'T EDIT these)
│   └── streaming/
│       ├── agent/                    ← AI agent implementations
│       │   ├── base_agent.py         ← Abstract base class
│       │   ├── chat_gpt_agent.py     ← OpenAI GPT agent
│       │   └── openai_utils.py       ← Formats conversation for OpenAI
│       │
│       ├── models/                   ← Pydantic data models
│       │   ├── agent.py              ← AgentConfig (ChatGPTAgentConfig, etc.)
│       │   ├── synthesizer.py        ← SynthesizerConfig (gTTS, ElevenLabs, etc.)
│       │   ├── transcriber.py        ← TranscriberConfig (Deepgram, Google, etc.)
│       │   ├── events.py             ← Event types (call connected, ended, etc.)
│       │   └── transcript.py         ← Transcript model (messages in a call)
│       │
│       ├── telephony/
│       │   ├── server/base.py        ← TelephonyServer (Twilio webhook handling)
│       │   ├── server/router/calls.py ← WebSocket call handler
│       │   └── config_manager/       ← Redis config storage
│       │
│       ├── synthesizer/              ← TTS implementations
│       ├── transcriber/              ← STT implementations
│       └── utils/
│           └── events_manager.py     ← Base EventsManager class
│
├── voice_platform/                   ← OUR CODE (VOIA backend)
│   ├── .env                          ← API keys & secrets (NEVER commit this)
│   ├── main.py                       ← 🏠 Entry point — starts the server
│   ├── config.py                     ← Loads .env into Python objects
│   ├── database.py                   ← 📦 All database tables & models
│   ├── auth.py                       ← 🔐 Google OAuth + JWT token logic
│   │
│   ├── middleware/
│   │   └── auth_middleware.py        ← 🛡️ Protects API routes with JWT
│   │
│   ├── api/                          ← 🌐 REST API endpoints
│   │   ├── auth_routes.py            ← POST /api/auth/google, GET /me
│   │   ├── agent_routes.py           ← CRUD for voice agents
│   │   ├── call_routes.py            ← View call history & transcripts
│   │   ├── dashboard_routes.py       ← Analytics & statistics
│   │   ├── settings_routes.py        ← Platform-wide config
│   │   └── workflow_routes.py        ← Intent-based automation rules
│   │
│   ├── agents/
│   │   └── agent_factory.py          ← 🏭 Builds vocode agents from DB config
│   │
│   ├── events/
│   │   └── call_events.py            ← 💾 Saves call events to database
│   │
│   └── voia.db                       ← SQLite database file (auto-created)
│
└── .venv/                            ← Python virtual environment
```

### What Each File Does (Plain English)

| File | Purpose | When is it used? |
|------|---------|-----------------|
| `main.py` | Starts the web server, connects everything together | Every time you run the app |
| `config.py` | Reads your `.env` file and makes values available as `settings.xxx` | At import time |
| `database.py` | Defines all 7 database tables and how to connect to SQLite | At startup + every API request |
| `auth.py` | Verifies Google login tokens, creates/reads our JWT tokens | When users log in/make requests |
| `auth_middleware.py` | Checks if API requests have a valid login token | Every protected API request |
| `agent_routes.py` | Let users create, view, edit, delete voice agents | When frontend manages agents |
| `call_routes.py` | Let users view call history and transcripts | When frontend shows call logs |
| `dashboard_routes.py` | Calculates stats (total calls, average duration, etc.) | When frontend loads dashboard |
| `settings_routes.py` | Platform-wide settings (admin-only for writes) | When admin configures platform |
| `workflow_routes.py` | Automation rules (e.g., "if user says X, do Y") | When frontend manages workflows |
| `agent_factory.py` | Translates DB agent config → vocode objects for calls | When a phone call arrives |
| `call_events.py` | Listens to vocode call events and saves them to DB | During every active phone call |

---

## 4. How to Set Up & Run

### Prerequisites

- **macOS** (or Linux)
- **Python 3.10–3.13** (we use 3.13 via homebrew)
- **Redis** server (for vocode's call config storage)
- **Twilio account** with a phone number
- **Deepgram account** (free tier: 200 hours/year)
- **OpenAI account** with API key

### Step-by-Step Setup

```bash
# 1. Navigate to the project
cd /path/to/vocode-core

# 2. Create virtual environment (if not already done)
/opt/homebrew/bin/python3.13 -m venv .venv

# 3. Activate the virtual environment
source .venv/bin/activate

# 4. Install dependencies
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
pip install -e ".[twilio]" aiosqlite "python-jose[cryptography]" \
    google-auth google-auth-oauthlib pyngrok audioop-lts "sqlalchemy[asyncio]"

# 5. Start Redis (in a separate terminal or background)
redis-server &

# 6. Start the VOIA server
cd /path/to/vocode-core
.venv/bin/python -m uvicorn voice_platform.main:app --host 0.0.0.0 --port 3000
```

### What You'll See

```
🚀 Starting VOIA Voice Platform...
📦 Initializing database... ✅ Database initialized
🔗 ngrok tunnel established: https://xxxx.ngrok-free.dev
PersistentEventsManager initialized with DB persistence
📞 Telephony server configured
📊 Events manager started (persisting to database)
✅ VOIA Voice Platform started successfully!
📖 API docs: https://xxxx.ngrok-free.dev/docs
Uvicorn running on http://0.0.0.0:3000
```

### Quick Verification

```bash
# Health check
curl http://localhost:3000/health
# → {"status":"ok","service":"VOIA Voice Platform","version":"1.0.0"}

# See available AI providers
curl http://localhost:3000/api/agents/providers
# → Returns list of LLM, STT, TTS providers with models

# Open interactive API docs in browser
open http://localhost:3000/docs
```

---

## 5. Environment Variables (.env)

The `.env` file lives at `voice_platform/.env`. It contains all API keys and secrets.

> ⚠️ **NEVER commit this file to git.** It's already in `.gitignore`.

| Variable | What It Does | Where to Get It |
|----------|-------------|-----------------|
| `BASE_URL` | Public URL for Twilio webhooks. Leave empty to use ngrok. | Set manually or leave blank |
| `NGROK_AUTH_TOKEN` | Creates a public tunnel to your local server | [ngrok.com dashboard](https://dashboard.ngrok.com) |
| `DEEPGRAM_API_KEY` | Speech-to-text service | [console.deepgram.com](https://console.deepgram.com) |
| `OPENAI_API_KEY` | AI language model | [platform.openai.com](https://platform.openai.com) |
| `TWILIO_ACCOUNT_SID` | Twilio account identifier | [twilio.com/console](https://www.twilio.com/console) |
| `TWILIO_AUTH_TOKEN` | Twilio API secret | Same as above |
| `TWILIO_PHONE_NUMBER` | Your Twilio phone number (e.g., `+18313188656`) | Twilio console → Phone Numbers |
| `REDIS_URL` | Redis connection string | Default: `redis://localhost:6379` |
| `GOOGLE_CLIENT_ID` | Google OAuth app ID | [console.cloud.google.com](https://console.cloud.google.com) |
| `GOOGLE_CLIENT_SECRET` | Google OAuth secret | Same as above |
| `JWT_SECRET` | Secret for signing login tokens | Any random string (change in production!) |
| `DEFAULT_LLM_MODEL` | Fallback model when no agent is configured | Default: `gpt-4o-mini` |

---

## 6. Database — How Data is Stored

We use **SQLite** (file: `voice_platform/voia.db`). It's automatically created on first startup. No setup needed.

### Tables

#### `users` — Who uses the platform
```
┌────┬────────────┬──────────────────────┬──────────┬────────┐
│ id │ google_id  │ email                │ name     │ role   │
├────┼────────────┼──────────────────────┼──────────┼────────┤
│ 1  │ 123456...  │ alex@example.com     │ Alex   │ admin  │
│ 2  │ 789012...  │ friend@gmail.com     │ Friend   │ user   │
└────┴────────────┴──────────────────────┴──────────┴────────┘
```
- First user to ever sign up automatically becomes `admin`
- `google_id` comes from Google OAuth (unique per Google account)

#### `agents` — The AI voice agents
```
┌────┬─────────┬───────────┬──────────────┬──────────┬──────────────┬──────────┐
│ id │ user_id │ name      │ llm_provider │ llm_model│ stt_provider │ tts_prov │
├────┼─────────┼───────────┼──────────────┼──────────┼──────────────┼──────────┤
│ 1  │ 1       │ Reception │ openai       │ gpt-4o   │ deepgram     │ gtts     │
│ 2  │ 1       │ Support   │ groq         │ llama3.. │ deepgram     │ 11labs   │
└────┴─────────┴───────────┴──────────────┴──────────┴──────────────┴──────────┘
```
- Each agent belongs to ONE user
- `prompt_preamble` = the system prompt (personality of the agent)
- `llm_api_key` / `stt_api_key` / `tts_api_key` = user's OWN key (null = use platform default)

#### `call_logs` — Record of every phone call
```
┌────┬─────────────────┬──────────┬─────────────┬───────────┬──────────┐
│ id │ conversation_id │ agent_id │ from_phone  │ status    │ duration │
├────┼─────────────────┼──────────┼─────────────┼───────────┼──────────┤
│ 1  │ abc-123-def     │ 1        │ +1234567890 │ completed │ 125.4    │
│ 2  │ ghi-456-jkl     │ 1        │ +0987654321 │ active    │ NULL     │
└────┴─────────────────┴──────────┴─────────────┴───────────┴──────────┘
```
- `conversation_id` = vocode's internal UUID for the call
- `status`: `active` → `completed` or `failed`
- `duration_secs` is set when the call ends

#### `transcripts` — Every message in every call
```
┌────┬─────────────┬────────┬─────────────────────────────────┬────────────┐
│ id │ call_log_id │ sender │ message                         │ timestamp  │
├────┼─────────────┼────────┼─────────────────────────────────┼────────────┤
│ 1  │ 1           │ bot    │ Hello! How can I help you today? │ 1709500000 │
│ 2  │ 1           │ human  │ I'd like to book an appointment │ 1709500005 │
│ 3  │ 1           │ bot    │ Sure! What date works for you?  │ 1709500008 │
└────┴─────────────┴────────┴─────────────────────────────────┴────────────┘
```
- `sender`: `human`, `bot`, `action`, or `system`
- Saved in real-time during the call by `PersistentEventsManager`

#### `action_logs` — Actions executed during calls
- Records when the AI does something (transfers a call, calls an API, etc.)

#### `workflows` — Automation rules
- `trigger_phrases`: JSON array like `["schedule", "appointment", "book"]`
- When AI detects these phrases, it triggers the associated action

#### `settings` — Platform-wide config
- Key-value store for admin settings
- Seeded with defaults on first startup

### How to Inspect the Database

```bash
# Open SQLite directly
sqlite3 voice_platform/voia.db

# See all tables
.tables

# See users
SELECT * FROM users;

# See agents with their providers
SELECT id, name, llm_provider, llm_model, stt_provider, tts_provider FROM agents;

# See call transcripts
SELECT t.sender, t.message FROM transcripts t
JOIN call_logs c ON t.call_log_id = c.id
ORDER BY t.timestamp;

# Exit
.quit
```

---

## 7. Authentication — How Login Works

### The Flow (Step by Step)

```
┌──────────┐                    ┌──────────┐                    ┌────────────┐
│ Frontend │                    │ Backend  │                    │  Google    │
│ (React)  │                    │ (FastAPI)│                    │  OAuth     │
└─────┬────┘                    └─────┬────┘                    └─────┬──────┘
      │                              │                              │
      │  1. User clicks              │                              │
      │     "Sign in with Google"    │                              │
      │──────────────────────────────────────────────────────────►│
      │                              │                              │
      │  2. Google shows login page  │                              │
      │◄──────────────────────────────────────────────────────────│
      │                              │                              │
      │  3. User logs in with Gmail  │                              │
      │──────────────────────────────────────────────────────────►│
      │                              │                              │
      │  4. Google returns id_token  │                              │
      │◄──────────────────────────────────────────────────────────│
      │                              │                              │
      │  5. Frontend sends id_token  │                              │
      │  POST /api/auth/google       │                              │
      │  { "id_token": "eyJ..." }    │                              │
      │─────────────────────────────►│                              │
      │                              │  6. Backend verifies token   │
      │                              │     with Google's servers    │
      │                              │─────────────────────────────►│
      │                              │                              │
      │                              │  7. Google confirms: valid!  │
      │                              │◄─────────────────────────────│
      │                              │                              │
      │                              │  8. Backend creates/updates  │
      │                              │     user in database         │
      │                              │                              │
      │                              │  9. Backend creates OUR JWT  │
      │                              │                              │
      │  10. Returns our JWT + user  │                              │
      │  { "access_token": "eyJ..",  │                              │
      │    "user": { "name": ... } } │                              │
      │◄─────────────────────────────│                              │
      │                              │                              │
      │  11. Frontend stores JWT     │                              │
      │      in localStorage/cookie  │                              │
      │                              │                              │
      │  12. All future API calls    │                              │
      │  include the JWT:            │                              │
      │  Authorization: Bearer eyJ.. │                              │
      │─────────────────────────────►│                              │
      │                              │  13. Backend decodes JWT     │
      │                              │      and finds the user      │
```

### Two Types of Tokens

| Token | Who Creates It | What It Contains | Lifetime |
|-------|---------------|------------------|----------|
| Google ID Token | Google | User's email, name, picture, Google ID | ~1 hour |
| Our JWT | Our backend (`auth.py`) | User's DB id, email, role | 7 days |

The frontend only deals with **our JWT** after the initial login. Google's token is used once and discarded.

### Protected vs Public Endpoints

| Endpoint | Auth Required? | Who Can Access? |
|----------|---------------|-----------------|
| `GET /` | ❌ No | Anyone |
| `GET /api/agents/providers` | ❌ No | Anyone |
| `POST /api/auth/google` | ❌ No | Anyone (this IS the login) |
| `GET /api/auth/me` | ✅ Yes | Logged-in users |
| `GET /api/agents` | ✅ Yes | Logged-in users (sees only their own) |
| `PUT /api/settings` | ✅ Yes + Admin | Only admin users |

---

## 8. API Endpoints — Complete Reference

### 🔐 Authentication

#### `POST /api/auth/google` — Sign In
```bash
curl -X POST http://localhost:3000/api/auth/google \
  -H "Content-Type: application/json" \
  -d '{"id_token": "eyJhbGciOiJSUzI1NiIs..."}'
```
**Response:**
```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "email": "user@gmail.com",
    "name": "User Name",
    "picture_url": "https://...",
    "role": "admin",
    "created_at": "2026-03-03T00:30:00"
  }
}
```

#### `GET /api/auth/me` — Get Current User
```bash
curl http://localhost:3000/api/auth/me \
  -H "Authorization: Bearer eyJhbGciOi..."
```

#### `PUT /api/auth/profile` — Update Profile
```bash
curl -X PUT http://localhost:3000/api/auth/profile \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "New Name"}'
```

---

### 🤖 Agents

#### `GET /api/agents/providers` — What AI Services Are Available
```bash
curl http://localhost:3000/api/agents/providers
```
**Response:** Lists all LLM providers (OpenAI, Anthropic, Groq) with their models, all STT providers with supported languages, and all TTS providers with available voices.

#### `POST /api/agents` — Create a New Agent
```bash
curl -X POST http://localhost:3000/api/agents \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Customer Support Agent",
    "prompt_preamble": "You are a friendly customer support agent for ACME Corp. Help customers with their orders, returns, and general questions. Be polite and concise.",
    "initial_message": "Hello! Welcome to ACME Corp support. How can I help you today?",
    "llm_provider": "openai",
    "llm_model": "gpt-4o-mini",
    "stt_provider": "deepgram",
    "stt_language": "en-US",
    "tts_provider": "gtts",
    "temperature": 0.7,
    "max_tokens": 256
  }'
```

#### `GET /api/agents` — List Your Agents
```bash
curl http://localhost:3000/api/agents \
  -H "Authorization: Bearer TOKEN"
```

#### `GET /api/agents/{id}` — Get Agent Details
```bash
curl http://localhost:3000/api/agents/1 \
  -H "Authorization: Bearer TOKEN"
```

#### `PUT /api/agents/{id}` — Update Agent
```bash
# Change only the model (all other fields stay the same)
curl -X PUT http://localhost:3000/api/agents/1 \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"llm_model": "gpt-4o", "temperature": 0.5}'
```

#### `DELETE /api/agents/{id}` — Deactivate Agent
```bash
curl -X DELETE http://localhost:3000/api/agents/1 \
  -H "Authorization: Bearer TOKEN"
```
> This is a **soft delete** — marks the agent as inactive but keeps the data.

---

### 📞 Call Logs

#### `GET /api/calls` — List Call History
```bash
# Basic usage
curl http://localhost:3000/api/calls \
  -H "Authorization: Bearer TOKEN"

# With pagination and filtering
curl "http://localhost:3000/api/calls?page=1&per_page=10&status=completed&agent_id=1" \
  -H "Authorization: Bearer TOKEN"
```
**Response:**
```json
{
  "calls": [
    {
      "id": 1,
      "conversation_id": "abc-123",
      "agent_name": "Customer Support",
      "from_phone": "+1234567890",
      "to_phone": "+18313188656",
      "status": "completed",
      "started_at": "2026-03-03T00:30:00",
      "ended_at": "2026-03-03T00:32:05",
      "duration_secs": 125.4
    }
  ],
  "total": 1,
  "page": 1,
  "per_page": 10,
  "pages": 1
}
```

#### `GET /api/calls/{id}` — Full Call Detail with Transcript
```bash
curl http://localhost:3000/api/calls/1 \
  -H "Authorization: Bearer TOKEN"
```
**Response includes the entire conversation:**
```json
{
  "call": { ... },
  "transcript": [
    {"sender": "bot", "message": "Hello! How can I help?", "timestamp": 1709500000},
    {"sender": "human", "message": "I want to return my order", "timestamp": 1709500005},
    {"sender": "bot", "message": "I can help with that! What's your order number?", "timestamp": 1709500008}
  ],
  "actions": []
}
```

#### `GET /api/calls/active` — Currently Active Calls
```bash
curl http://localhost:3000/api/calls/active \
  -H "Authorization: Bearer TOKEN"
```

#### `POST /api/calls/{id}/end` — Force End a Call
```bash
curl -X POST http://localhost:3000/api/calls/1/end \
  -H "Authorization: Bearer TOKEN"
```

---

### 📊 Dashboard

#### `GET /api/dashboard/stats` — Call Analytics
```bash
curl http://localhost:3000/api/dashboard/stats \
  -H "Authorization: Bearer TOKEN"
```
**Response:**
```json
{
  "total_calls": 42,
  "total_duration_mins": 156.7,
  "avg_duration_secs": 223.8,
  "active_calls": 1,
  "calls_today": 5,
  "calls_this_week": 18,
  "agents_count": 3
}
```

#### `GET /api/dashboard/recent` — 10 Most Recent Calls
```bash
curl http://localhost:3000/api/dashboard/recent \
  -H "Authorization: Bearer TOKEN"
```

---

### ⚙️ Settings

#### `GET /api/settings` — Get Platform Settings
```bash
curl http://localhost:3000/api/settings \
  -H "Authorization: Bearer TOKEN"
```
**Response:**
```json
{
  "settings": {
    "default_llm_provider": "openai",
    "default_llm_model": "gpt-4o-mini",
    "default_stt_provider": "deepgram",
    "default_tts_provider": "gtts",
    "platform_name": "VOIA"
  }
}
```

#### `PUT /api/settings` — Update a Setting (Admin Only)
```bash
curl -X PUT http://localhost:3000/api/settings \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"key": "default_llm_model", "value": "gpt-4o"}'
```

---

### 🔄 Workflows

#### `POST /api/workflows` — Create Workflow
```bash
curl -X POST http://localhost:3000/api/workflows \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Schedule Appointment",
    "description": "Routes to scheduling when user wants to book",
    "trigger_phrases": ["schedule", "appointment", "book a meeting", "reserve a slot"],
    "action_type": "action_external",
    "action_url": "https://your-calendar-api.com/schedule",
    "requires_approval": true
  }'
```

#### `GET /api/workflows` — List Workflows
```bash
curl http://localhost:3000/api/workflows \
  -H "Authorization: Bearer TOKEN"
```

---

## 9. The Modular Provider System

This is the key differentiator of VOIA. Users control which AI services power their voice agent.

### How It Works

```
Frontend dropdown selections          Database (agents table)
──────────────────────────            ────────────────────────
LLM Provider: [OpenAI ▼]     →      llm_provider = "openai"
LLM Model:    [gpt-4o-mini ▼] →     llm_model = "gpt-4o-mini"
LLM API Key:  [optional]      →     llm_api_key = "sk-..."

STT Provider: [Deepgram ▼]    →     stt_provider = "deepgram"
STT Language: [en-US ▼]       →     stt_language = "en-US"

TTS Provider: [ElevenLabs ▼]  →     tts_provider = "elevenlabs"
TTS Voice:    [Rachel ▼]      →     tts_voice_id = "21m00Tcm..."
```

### When a Call Arrives

The `agent_factory.py` reads the agent's DB config and builds the correct vocode objects:

```python
# This happens automatically inside agent_factory.py

if agent.llm_provider == "openai":
    config = ChatGPTAgentConfig(
        openai_api_key=agent.llm_api_key or os.environ["OPENAI_API_KEY"],
        model_name=agent.llm_model,
        ...
    )

elif agent.llm_provider == "groq":
    config = ChatGPTAgentConfig(
        openai_api_key=agent.llm_api_key or os.environ["GROQ_API_KEY"],
        base_url_override="https://api.groq.com/openai/v1",
        model_name=agent.llm_model,
        ...
    )
```

### API Key Fallback Chain

```
Priority 1: Agent-level key  (user typed their own key in the frontend)
     ↓ (if null)
Priority 2: Platform .env key  (your shared key in the .env file)
```

### Available Providers

| Component | Provider | Models/Voices | API Key Needed? |
|-----------|----------|--------------|-----------------|
| **LLM** | OpenAI | gpt-4o-mini, gpt-4o, gpt-4-turbo, gpt-3.5-turbo | Yes (OPENAI_API_KEY) |
| **LLM** | Groq | llama3-70b, llama3-8b, mixtral-8x7b, gemma-7b | Yes (GROQ_API_KEY) |
| **LLM** | Anthropic | claude-3-haiku, claude-3-sonnet, claude-3-opus | Yes (future) |
| **STT** | Deepgram | nova-2 model, languages: en-US, ur, hi, multi | Yes (DEEPGRAM_API_KEY) |
| **STT** | Google | Cloud Speech, languages: en-US, ur-PK, hi-IN | Yes (GCP credentials) |
| **STT** | Azure | Speech Services, languages: en-US, ur-PK | Yes (AZURE_SPEECH_KEY) |
| **TTS** | gTTS | Google Translate TTS (basic, free) | No |
| **TTS** | ElevenLabs | Adam, Rachel, plus custom voices | Yes (ELEVEN_LABS_API_KEY) |
| **TTS** | Azure | Neural voices: Aria, Steffan, Asad (Urdu) | Yes (AZURE_SPEECH_KEY) |
| **TTS** | Cartesia | Ultra-low latency voices | Yes (CARTESIA_API_KEY) |
| **TTS** | Polly | AWS voices: Matthew, Joanna | Yes (AWS credentials) |

---

## 10. How Phone Calls Work (End-to-End)

This is the most complex part of the system. Here's exactly what happens when someone dials your Twilio number:

### Phase 1: Call Setup (< 1 second)

```
1. Caller dials +18313188656 (your Twilio number)

2. Twilio receives the call and checks:
   "What should I do with calls to this number?"
   Answer: "Send a webhook to https://xxxx.ngrok-free.dev/inbound_call"

3. Twilio sends HTTP POST to our /inbound_call endpoint with:
   - From: +1234567890 (caller's number)
   - To: +18313188656 (your number)
   - CallSid: CA123456... (Twilio's call ID)

4. Our TelephonyServer handles this:
   a. Generates a unique conversation_id (UUID)
   b. Creates the voice pipeline config (agent + STT + TTS)
   c. Saves the config to Redis (key = conversation_id)
   d. Returns TwiML (XML) telling Twilio:
      "Connect this call via WebSocket to wss://xxxx.ngrok-free.dev/connect_call/{conversation_id}"

5. Twilio opens a WebSocket connection to our server
```

### Phase 2: Real-Time Conversation (entire call duration)

```
6. vocode's StreamingConversation starts:
   - Creates a Deepgram STT WebSocket (for speech recognition)
   - Creates the ChatGPT agent (for responses)
   - Creates gTTS synthesizer (for speech generation)

7. Audio flows in real-time:
   
   Caller speaks → Twilio streams audio → our WebSocket
                                            ↓
                              [Deepgram] converts speech to text
                                            ↓
                              "I'd like to book an appointment"
                                            ↓
                              [ChatGPT] generates response text
                                            ↓
                              "Sure! What date works for you?"
                                            ↓
                              [gTTS] converts text to speech audio
                                            ↓
                              our WebSocket → Twilio → Caller hears response

8. Meanwhile, PersistentEventsManager captures everything:
   - TranscriptEvent → saves each message to 'transcripts' table
   - ActionEvent → saves any actions executed to 'action_logs' table
```

### Phase 3: Call Ends

```
9. Call ends (caller hangs up, or agent detects "goodbye")

10. vocode fires PhoneCallEndedEvent:
    - PersistentEventsManager updates call_logs:
      status = "completed"
      ended_at = now
      duration_secs = calculated

11. Redis config is cleaned up
12. WebSocket closes
```

### Twilio Configuration

For this to work, you need to configure your Twilio phone number:

1. Go to [twilio.com/console/phone-numbers](https://www.twilio.com/console/phone-numbers)
2. Click on your phone number
3. Under "Voice & Fax" → "A CALL COMES IN":
   - Select "Webhook"
   - URL: `https://YOUR-NGROK-URL.ngrok-free.dev/inbound_call`
   - HTTP Method: POST

> **Important:** The ngrok URL changes every time you restart the server. You'll need to update Twilio each time (unless you pay for a fixed ngrok URL or deploy to a server with a static IP).

---

## 11. Frontend Integration Guide (React/Next.js)

### Setting Up the API Client

Create a file `src/lib/api.js` in your frontend project:

```javascript
// src/lib/api.js — API client for VOIA backend

const API_BASE = "http://localhost:3000";  // Backend URL

// Helper function for making API calls
async function apiCall(endpoint, options = {}) {
  const token = localStorage.getItem("voia_token");  // Get stored JWT
  
  const headers = {
    "Content-Type": "application/json",
    ...options.headers,
  };
  
  // Add auth header if we have a token
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });
  
  // Handle auth errors
  if (response.status === 401) {
    localStorage.removeItem("voia_token");
    window.location.href = "/login";  // Redirect to login
    return null;
  }
  
  return response.json();
}

// ── Auth API ───────────────────────────────────────────────
export async function loginWithGoogle(idToken) {
  const data = await apiCall("/api/auth/google", {
    method: "POST",
    body: JSON.stringify({ id_token: idToken }),
  });
  
  if (data?.access_token) {
    localStorage.setItem("voia_token", data.access_token);
  }
  
  return data;
}

export async function getCurrentUser() {
  return apiCall("/api/auth/me");
}

// ── Agents API ─────────────────────────────────────────────
export async function getProviders() {
  return apiCall("/api/agents/providers");
}

export async function listAgents() {
  return apiCall("/api/agents");
}

export async function createAgent(agentData) {
  return apiCall("/api/agents", {
    method: "POST",
    body: JSON.stringify(agentData),
  });
}

export async function updateAgent(agentId, updates) {
  return apiCall(`/api/agents/${agentId}`, {
    method: "PUT",
    body: JSON.stringify(updates),
  });
}

export async function deleteAgent(agentId) {
  return apiCall(`/api/agents/${agentId}`, { method: "DELETE" });
}

// ── Calls API ──────────────────────────────────────────────
export async function listCalls(page = 1, perPage = 20) {
  return apiCall(`/api/calls?page=${page}&per_page=${perPage}`);
}

export async function getCallDetail(callId) {
  return apiCall(`/api/calls/${callId}`);
}

export async function getActiveCalls() {
  return apiCall("/api/calls/active");
}

// ── Dashboard API ──────────────────────────────────────────
export async function getDashboardStats() {
  return apiCall("/api/dashboard/stats");
}

export async function getRecentCalls() {
  return apiCall("/api/dashboard/recent");
}

// ── Settings API ───────────────────────────────────────────
export async function getSettings() {
  return apiCall("/api/settings");
}
```

### Google Sign-In Component (React)

```jsx
// src/components/GoogleLogin.jsx
import { useEffect } from "react";
import { loginWithGoogle } from "../lib/api";

export default function GoogleLogin({ onSuccess }) {
  useEffect(() => {
    // Load the Google Sign-In SDK
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    document.body.appendChild(script);

    script.onload = () => {
      window.google.accounts.id.initialize({
        // This is YOUR Google Client ID from .env
        client_id: "398913280055-r4q53cgkbms9dll8bssrcop7k89ja7fb.apps.googleusercontent.com",
        callback: handleCredentialResponse,
      });

      // Render the Google Sign-In button
      window.google.accounts.id.renderButton(
        document.getElementById("google-signin-btn"),
        { theme: "outline", size: "large", text: "continue_with" }
      );
    };
  }, []);

  async function handleCredentialResponse(response) {
    // response.credential is the Google ID token
    const data = await loginWithGoogle(response.credential);
    if (data?.user) {
      onSuccess(data.user);  // Redirect to dashboard
    }
  }

  return <div id="google-signin-btn" />;
}
```

### Agent Creator Component (React)

```jsx
// src/components/AgentCreator.jsx
import { useState, useEffect } from "react";
import { getProviders, createAgent } from "../lib/api";

export default function AgentCreator() {
  const [providers, setProviders] = useState(null);
  const [formData, setFormData] = useState({
    name: "",
    prompt_preamble: "",
    llm_provider: "openai",
    llm_model: "gpt-4o-mini",
    stt_provider: "deepgram",
    stt_language: "en-US",
    tts_provider: "gtts",
    temperature: 0.7,
  });

  useEffect(() => {
    // Load available providers on mount
    getProviders().then(setProviders);
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    const result = await createAgent(formData);
    if (result?.agent) {
      alert(`Agent "${result.agent.name}" created!`);
    }
  }

  if (!providers) return <p>Loading providers...</p>;

  return (
    <form onSubmit={handleSubmit}>
      <input
        placeholder="Agent Name"
        value={formData.name}
        onChange={e => setFormData({ ...formData, name: e.target.value })}
      />

      <textarea
        placeholder="System prompt (personality)"
        value={formData.prompt_preamble}
        onChange={e => setFormData({ ...formData, prompt_preamble: e.target.value })}
      />

      {/* LLM Provider Dropdown */}
      <select
        value={formData.llm_provider}
        onChange={e => setFormData({ ...formData, llm_provider: e.target.value })}
      >
        {providers.llm_providers.map(p => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </select>

      {/* LLM Model Dropdown (filtered by selected provider) */}
      <select
        value={formData.llm_model}
        onChange={e => setFormData({ ...formData, llm_model: e.target.value })}
      >
        {providers.llm_providers
          .find(p => p.id === formData.llm_provider)
          ?.models.map(m => (
            <option key={m} value={m}>{m}</option>
          ))
        }
      </select>

      {/* Similar dropdowns for STT and TTS... */}

      <button type="submit">Create Agent</button>
    </form>
  );
}
```

### Dashboard Component (React)

```jsx
// src/components/Dashboard.jsx
import { useState, useEffect } from "react";
import { getDashboardStats, getRecentCalls } from "../lib/api";

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [recent, setRecent] = useState([]);

  useEffect(() => {
    getDashboardStats().then(r => setStats(r));
    getRecentCalls().then(r => setRecent(r?.recent_calls || []));
  }, []);

  if (!stats) return <p>Loading...</p>;

  return (
    <div>
      <div className="stats-grid">
        <div className="stat-card">
          <h3>{stats.total_calls}</h3>
          <p>Total Calls</p>
        </div>
        <div className="stat-card">
          <h3>{stats.total_duration_mins} min</h3>
          <p>Total Talk Time</p>
        </div>
        <div className="stat-card">
          <h3>{stats.active_calls}</h3>
          <p>Active Now</p>
        </div>
        <div className="stat-card">
          <h3>{stats.agents_count}</h3>
          <p>Agents</p>
        </div>
      </div>

      <h2>Recent Calls</h2>
      <table>
        <thead>
          <tr>
            <th>From</th>
            <th>Agent</th>
            <th>Status</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>
          {recent.map(call => (
            <tr key={call.id}>
              <td>{call.from_phone}</td>
              <td>{call.agent_name}</td>
              <td>{call.status}</td>
              <td>{call.duration_secs ? `${Math.round(call.duration_secs)}s` : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

---

## 12. How to Extend the Platform

### Adding a New LLM Provider

1. **Update `agent_routes.py`** — Add to `VALID_LLM_PROVIDERS` list
2. **Update the providers endpoint** in `agent_routes.py` — Add the new provider with its models
3. **Update `agent_factory.py`** — Add a new `elif` block in `build_agent_config()`:
   ```python
   elif provider == "my_new_llm":
       config = ChatGPTAgentConfig(
           openai_api_key=db_agent.llm_api_key or os.environ.get("MY_LLM_API_KEY"),
           base_url_override="https://api.my-llm.com/v1",
           model_name=db_agent.llm_model,
           ...
       )
   ```
4. **Add the API key to `.env`** — `MY_LLM_API_KEY=xxx`
5. **Add to `config.py`** — `my_llm_api_key: Optional[str] = None`

### Adding a New TTS Voice

1. **Update the providers endpoint** in `agent_routes.py` — Add voice entry
2. **Update `agent_factory.py`** — Add handling in `build_synthesizer_config()`

### Adding a New Action

vocode has an action framework. To add a custom action (e.g., "Send Email"):

1. Create `voice_platform/actions/send_email.py`:
   ```python
   from vocode.streaming.action.base_action import BaseAction
   
   class SendEmailAction(BaseAction):
       action_type = "action_send_email"
       
       async def run(self, action_input):
           # Your email sending logic here
           email = action_input.params["email"]
           message = action_input.params["message"]
           # ... send the email ...
           return {"status": "sent", "email": email}
   ```

2. Register it in the agent config's `actions` list

### Adding a New API Endpoint

1. Create or edit a file in `voice_platform/api/`
2. Follow the pattern:
   ```python
   from fastapi import APIRouter, Depends
   from voice_platform.middleware.auth_middleware import get_current_user
   
   router = APIRouter(prefix="/api/my-feature", tags=["My Feature"])
   
   @router.get("")
   async def my_endpoint(user: User = Depends(get_current_user)):
       return {"message": "Hello from my new endpoint!"}
   ```
3. Register the router in `main.py`:
   ```python
   from voice_platform.api.my_feature_routes import router as my_feature_router
   app.include_router(my_feature_router)
   ```

### Testing API Calls Without a Phone

You can test the agent's LLM response by:

```bash
# 1. Create an agent via API
# 2. Use the OpenAI API directly with the agent's prompt:

curl https://api.openai.com/v1/chat/completions \
  -H "Authorization: Bearer YOUR_OPENAI_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [
      {"role": "system", "content": "Your agent prompt_preamble here"},
      {"role": "user", "content": "Hello, I want to book an appointment"}
    ]
  }'
```

### Useful Commands for Playing Around

```bash
# View server logs in real-time
# (logs show every event: calls, transcripts, actions, errors)

# Inspect the database
sqlite3 voice_platform/voia.db "SELECT * FROM settings;"

# Check Redis for active call configs
redis-cli KEYS "*"

# Test a specific endpoint
curl -s http://localhost:3000/api/dashboard/stats \
  -H "Authorization: Bearer YOUR_JWT" | python3 -m json.tool

# Watch the ngrok traffic inspector (shows all HTTP requests)
open http://localhost:4040

# Check git history
git log --oneline
```

---

## 13. Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'xxx'` | Missing Python package | `pip install xxx` in the `.venv` |
| `No module named 'audioop'` | Python 3.13+ removed this | `pip install audioop-lts` |
| Server starts but Twilio calls fail | ngrok URL changed | Update Twilio webhook URL |
| `Redis connection refused` | Redis not running | `redis-server &` |
| `Invalid Google token` | Wrong client ID or expired token | Check `GOOGLE_CLIENT_ID` in `.env` |
| `401 Unauthorized` on API calls | JWT expired or invalid | Re-login to get a new token |
| Database locked | Multiple writers at once | Restart server (SQLite limitation) |
| `Cannot find Rust compiler` | tiktoken needs Rust | `brew install rust` then reinstall |
| Agent not picking up calls | No active agents in DB | Create an agent via POST /api/agents |

---

## Quick Reference Card

```
Start server:    .venv/bin/python -m uvicorn voice_platform.main:app --host 0.0.0.0 --port 3000
API docs:        http://localhost:3000/docs
Health check:    curl http://localhost:3000/health
Start Redis:     redis-server &
View database:   sqlite3 voice_platform/voia.db
Git commit:      git add -A && git commit -m "message"
```
