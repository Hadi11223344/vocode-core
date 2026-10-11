<div align="center">

# VOIA — Open-Source Voice Agent OS

**Design the call like a flowchart. Run the same graph in the playground and on the phone. Bring your own keys.**

Self-hosted Retell-class voice agents — visual flows, dual-runtime playground, multi-provider STT/LLM/TTS, campaigns, and ops — without vendor lock-in.

[Open-core model](docs/OPEN_CORE.md) · [Strategy](docs/VOIA_OPEN_SOURCE_STRATEGY.md) · [Contributing](CONTRIBUTING.md) · [Architecture](docs/VOIA_ARCHITECTURE_AND_QUICKSTART.md)

</div>

---

## Why VOIA

| Moat | What it means |
|------|----------------|
| **One graph, two runtimes** | Flow playground and live telephony share LangGraph semantics |
| **Compiler you can read** | React Flow → graph contracts, branches, `on_missing` — not a black box |
| **Voice-native state** | Typed slots, aliases, spoken email/phone validation |
| **BYOK by design** | Encrypted key vault; swap Deepgram, OpenRouter, Groq, Ollama, Twilio, … |
| **Ops included** | Campaigns, HITL review, memory, quality scoring, alerts — self-hosted |

Built on the MIT [Vocode](https://github.com/vocodedev/vocode-core) streaming SDK, with a full platform layer (`voice_platform/` + `frontend/`).

---

## Tiered quickstart

| Tier | What you get | Keys needed |
|------|----------------|-------------|
| **0 — Playground** | Dashboard + flow editor + mock-context playground | 1 LLM key (OpenRouter / OpenAI / Groq / Ollama) |
| **1 — Live call** | Real inbound/outbound Twilio calls | Tier 0 + Twilio + Deepgram (+ public `BASE_URL` / ngrok) |
| **2 — Full ops** | KB/RAG, campaigns, Calendar/Sheets, … | Tier 1 + integration OAuth as needed |

### Tier 0 (recommended first run)

```bash
# 1. Env — enable local login; add one LLM key
cp voice_platform/.env.example voice_platform/.env
# Set at least:
#   ALLOW_DEV_LOGIN=true
#   OPENROUTER_API_KEY=...   # or GROQ_API_KEY / OPENAI_API_KEY / run Ollama

# 2. Start Postgres + Redis + API + dashboard
docker compose --profile playground up -d

# 3. Open the app
# Dashboard: http://localhost:3001  →  "Dev Login"
# API docs:  http://localhost:3000/docs

# 4. Create a conversational-flow agent → Flow Playground → mock caller context → Run
```

Validate your machine config anytime:

```bash
python3 scripts/check_setup.py
```

### Tier 1 (live phone)

Add to `voice_platform/.env`:

```bash
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=...
DEEPGRAM_API_KEY=...
# BASE_URL=https://your-tunnel.example   # or leave empty + NGROK_AUTH_TOKEN for auto-tunnel
```

Then use `docker compose --profile development up -d` (same stack; Twilio webhooks enabled).

### Manual setup (no Docker for the app)

```bash
poetry install
cp voice_platform/.env.example voice_platform/.env
# ALLOW_DEV_LOGIN=true + LLM key; for host-side Compose DB/Redis use ports below

# If using compose only for infra:
#   REDIS_URL=redis://localhost:6380
#   DATABASE_URL=postgresql+asyncpg://voia:voia_password@localhost:5433/voia

docker compose up -d db redis   # optional infra
cd voice_platform && python main.py   # :3000

cd frontend && npm install && npm run dev   # :3001
```

### Production

```bash
docker compose --profile production up -d
# See docs/DEPLOYMENT_GUIDE.md — set a strong JWT_SECRET, never ALLOW_DEV_LOGIN
```

---

## Architecture

| Component | Technology |
|-----------|------------|
| Backend | FastAPI + Vocode streaming SDK + LangGraph flow runtime |
| Frontend | Next.js 14, React Flow, Tailwind |
| Database | PostgreSQL (Compose) / SQLite (lightweight local) |
| Cache | Redis |
| Telephony | Twilio media streams |
| Auth | Dev login (local) · Google OAuth (optional / prod) |

```
vocode-core/
├── vocode/              # Streaming SDK (STT / TTS / telephony adapters)
├── voice_platform/      # API, flow compiler/executor, agents, integrations
├── frontend/            # Dashboard + workflow builder + playground
├── examples/            # Demo / customer-shaped packs (not required to run)
├── scripts/             # Setup checks + maintenance utilities
├── docker-compose.yml   # playground | development | production profiles
└── docs/                # Guides, open-core boundary, strategy
```

---

## Features (platform)

- Multi-LLM (OpenRouter, OpenAI, Groq, Gemini, Anthropic-via-OpenRouter, Ollama)
- Visual conversational flows with LangGraph execution (playground ≡ live)
- Knowledge base / RAG, campaigns, HITL review, cross-call memory
- Warm transfer, multilingual agents, prompt versioning, quality scoring
- Alerts, usage estimates, RBAC, Google Calendar & Sheets

---

## Environment cheat sheet

| Variable | Tier | Description |
|----------|------|-------------|
| `ALLOW_DEV_LOGIN` | 0 | `true` for local Dev Login (never in prod) |
| `OPENROUTER_API_KEY` / `GROQ_API_KEY` / `OPENAI_API_KEY` | 0 | At least one LLM path |
| `JWT_SECRET` | 0 | Change in production (≥32 chars) |
| `REDIS_URL` | 0 | Compose host: `redis://localhost:6380` |
| `DATABASE_URL` | 0/prod | Compose host: `postgresql+asyncpg://voia:voia_password@localhost:5433/voia` |
| `DEEPGRAM_API_KEY` | 1 | Speech-to-text |
| `TWILIO_*` | 1 | Telephony |
| `GOOGLE_CLIENT_ID` | optional | Google Sign-In (not required when Dev Login is on) |
| `BASE_URL` / `NGROK_AUTH_TOKEN` | 1 | Public webhook URL for Twilio |

Full template: [`voice_platform/.env.example`](voice_platform/.env.example).

**Compose host ports:** API `3000` · Dashboard `3001` · Postgres `5433` · Redis `6380`.

### Conversational flow mode

- **Single Prompt** — one system prompt for free-form agents  
- **Conversational Flow** — React Flow graph compiled to LangGraph; the **same** runtime powers the in-browser playground and Twilio calls (branch contracts, slots, interrupts)

### Anthropic via OpenRouter

Set an OpenRouter key as `ANTHROPIC_API_KEY=sk-or-v1-...` and select Anthropic on the agent. See `.env.example`.

---

## Documentation

- [Open-core boundary](docs/OPEN_CORE.md) — what is OSS vs cloud  
- [Moat](docs/MOAT.md) — dual-runtime, contracts, BYOK  
- [Compare](docs/COMPARE.md) — VOIA vs closed voice platforms  
- [Public roadmap](docs/ROADMAP.md) · [Launch checklist](docs/LAUNCH_CHECKLIST.md)  
- [VOIA Cloud](docs/VOIA_CLOUD.md) — managed “same graphs, zero ops”  
- [Contributing](CONTRIBUTING.md) — setup, tests, extension points  
- [Add a flow node](docs/extensions/add-node.md) · [Add a provider](docs/extensions/add-provider.md) · [Add a template](docs/extensions/add-template.md)  
- [Deployment Guide](docs/DEPLOYMENT_GUIDE.md) — production hardening  
- [Architecture & quickstart](docs/VOIA_ARCHITECTURE_AND_QUICKSTART.md)  
- [Demo pack (SmileCare)](examples/smilecare/README.md) — optional examples, not required for core

## VOIA Cloud

Self-host with your own keys. When you want managed telephony, SSO, and SLA without rewriting flows:

- Docs: **[VOIA Cloud](docs/VOIA_CLOUD.md)**
- Waitlist UI: `http://localhost:3001/cloud` (or set `NEXT_PUBLIC_CLOUD_WAITLIST_URL`)

Graphs stay portable between OSS and Cloud.

## Testing

```bash
make test-fast          # graph contracts, slots, routing (contributor default)
make setup-check        # Tier 0/1 env validation
poetry run pytest       # full suite
cd frontend && npx tsc --noEmit
```

## License

MIT — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Vocode streaming SDK © original authors; VOIA platform layer © VOIA contributors.

## Tech stack

**Backend:** Python 3.10+, FastAPI, SQLAlchemy async, Alembic, Redis, LangGraph, Vocode  
**Frontend:** Next.js 14, React 18, TypeScript, Tailwind, React Flow  
**Infra:** Docker, PostgreSQL, Redis, Twilio
