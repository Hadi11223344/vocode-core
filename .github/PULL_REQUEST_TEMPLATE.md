## Summary

<!-- 1–3 bullets: what changed and why -->

## Tier impact

- [ ] None (docs/tests only)
- [ ] Tier 0 — playground / local setup
- [ ] Tier 1 — live Twilio calls
- [ ] Tier 2 — campaigns / integrations / ops

## Extension type (if any)

- [ ] Provider (LLM / STT / TTS / telephony)
- [ ] Flow node
- [ ] Integration action
- [ ] Template / example
- [ ] N/A

## Test plan

- [ ] `make test-fast` (or relevant unit tests)
- [ ] Manual: playground path checked if flow semantics changed
- [ ] Manual: live call path checked if telephony/agent factory changed
- [ ] `.env.example` / README updated if new config is required

## Checklist

- [ ] No secrets or customer PII
- [ ] SmileCare/demo ops stay under `examples/` unless anonymized
- [ ] Playground ↔ live parity considered for flow changes
