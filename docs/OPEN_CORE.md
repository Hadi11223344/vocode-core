# VOIA Open-Core Boundary

VOIA is **open-core**: the voice-agent OS is open source; managed cloud convenience is commercial.

Full strategy: [VOIA_OPEN_SOURCE_STRATEGY.md](./VOIA_OPEN_SOURCE_STRATEGY.md) · Moat: [MOAT.md](./MOAT.md) · Compare: [COMPARE.md](./COMPARE.md) · Cloud: [VOIA_CLOUD.md](./VOIA_CLOUD.md) · Extensions: [extensions/](./extensions/)

## Open (self-host, fork, contribute)

- Flow compiler, executor, slots, graph contracts  
- Playground + live `FlowAgent` (dual-runtime)  
- Dashboard workflow builder  
- Provider adapters (STT / TTS / LLM / telephony) — BYOK  
- Generic templates, Docker Compose, docs  
- Campaigns, HITL, memory, alerts (self-hosted)

## Cloud / paid

- Managed multi-tenant hosting, SSO, SLA  
- Managed numbers / telephony proxy  
- Enterprise compliance packs  
- Priority support  
- (Later) private template marketplace

## Pitch

> Design the call like a flowchart. Run the same graph in the playground and on the phone. Bring your own keys.

## Production security defaults

- No forgeable `JWT_SECRET` ships in code; production refuses weak/empty secrets  
- `docker compose --profile production` forces `ALLOW_DEV_LOGIN=false` and Twilio signature checks  
- `POSTGRES_PASSWORD` must be set for the production profile  
- Encryption salt / `.env` are gitignored — set `ENCRYPTION_KEY` for durable key vaults
