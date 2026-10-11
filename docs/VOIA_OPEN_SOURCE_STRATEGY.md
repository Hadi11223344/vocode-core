# VOIA Open-Source Strategy & Sequenced Project Plan

**Status:** Draft for execution  
**Product:** VOIA — self-hosted AI voice agent platform  
**One-line pitch:** Design the call like a flowchart. Run the same graph in the playground and on the phone. Bring your own keys.

---

## 0. Refined product thesis

VOIA is not “another Retell clone with a UI.” It is a **BYOK voice-agent operating system** whose hard-to-copy core is:

1. **React Flow → LangGraph compiler** with interrupts, branch routing, and terminal guards  
2. **Dual-runtime parity** — playground WebSocket executor ≡ telephony `FlowAgent`  
3. **Graph contracts + slots** — `on_missing`, required inputs, typed slots, voice-native validation  
4. **Ops surface** — campaigns, HITL, memory, quality scoring, alerts, encrypted key vault  
5. **Provider freedom** — STT / TTS / LLM / telephony as swappable adapters

Open source is the **distribution and trust engine**. Hosted VOIA is the **convenience and revenue engine**.

---

## 1. Open-core boundary (exact list)

### 1.1 Open forever (Apache-2.0 preferred for platform layer; preserve Vocode MIT)

| Module | Path / surface | Why open |
|--------|----------------|----------|
| Streaming SDK heritage | `vocode/` | Already MIT; keep compatible |
| Platform API + auth basics | `voice_platform/api/`, JWT + local/dev login | Self-host foundation |
| Flow compiler / executor / slots | `voice_platform/flow/`, `graph_contracts.py` | **Show the moat** |
| Live flow agent | `voice_platform/agents/flow_agent.py` | Parity is the product |
| Playground backend | `voice_platform/api/playground_routes.py` | Time-to-value |
| Provider adapters | STT/TTS/LLM/telephony clients | BYOK promise |
| Dashboard builder + playground UI | `frontend/` (workflow editor, playground) | Contributors need UI seams |
| Generic templates | support, ecommerce, restaurant, dental-*generic* | Onboarding + forks |
| Docker Compose + setup scripts | `docker-compose.yml`, setup CLI | Forkability |
| Docs: architecture, contributing, extension guides | `docs/` | Community growth |
| Diagnostics / tracers (PII-safe) | `diagnostics.py`, flow tracer | Reliability culture |

### 1.2 Hosted / paid (keep closed or cloud-only)

| Capability | Rationale |
|------------|-----------|
| Managed cloud VOIA (multi-tenant SaaS) | Ops, SSO, billing, SLA |
| Managed number provisioning + telephony proxy | Removes Twilio/ngrok pain |
| Enterprise SSO / SCIM / audit export packs | Buyer requirement |
| Advanced compliance packs (recording retention policies, region pinning) | Enterprise wedge |
| Private template marketplace (rev-share) | Ecosystem monetization later |
| Priority support / onboarding SLAs | Services revenue |

### 1.3 Explicitly not a secret moat

Do **not** try to protect: feature checklist length, 3D dashboard chrome, SmileCare-specific fixtures, FYP branding. Those confuse strangers and dilute the story.

### 1.4 Customer / demo gravity quarantine

| Keep in core | Move to `examples/` or `templates/community/` |
|--------------|-----------------------------------------------|
| Generic dental / admissions *patterns* | SmileCare Lahore-specific copy, numbers, KB dumps |
| Contract + slot regression tests (anonymized) | `scripts/patch_smilecare_*.py`, UMT-specific ops scripts |
| Architecture fitness tests | Seed IDs tied to a single tenant |

---

## 2. Success metrics

| Metric | Target |
|--------|--------|
| Cold clone → first playground agent reply | **≤ 15 minutes** |
| Playground → first real inbound call (with keys) | **≤ 60 minutes** |
| First external PR after public launch | **≤ 30 days** |
| Primary community signal | Template reuse + new node/provider PRs (not stars alone) |
| Commercial signal | Self-hosters join hosted waitlist after Twilio/ops friction |

---

## 3. Sequenced roadmap

### Phase 0 — Positioning & legal clarity (Week 1)

**Goal:** One identity, one license story, one open-core line.

| ID | Work item | Acceptance criteria |
|----|-----------|---------------------|
| P0.1 | VOIA vs Vocode narrative | README opens as VOIA; Vocode credited as streaming foundation; contributing links to VOIA, not upstream Discord-only |
| P0.2 | License decision | Platform layer: Apache-2.0 **or** MIT with clear VOIA copyright notice; Vocode MIT preserved; `NOTICE` file if Apache |
| P0.3 | Publish open-core boundary | This section (or shortened) lives in `docs/OPEN_CORE.md` |
| P0.4 | Repo / org plan | Target public name e.g. `voia-ai/voia` (or keep current remote with rename); remove “FYP” from user-facing surfaces |
| P0.5 | Moat statement freeze | Locked one-liner + 5-bullet differentiator list used in README, site, launch post |

**Deliverables:** `LICENSE` / `NOTICE`, `docs/OPEN_CORE.md`, README hero rewrite (draft), brand scrub checklist.

---

### Phase 1 — Forkable in an afternoon (Weeks 2–4)

**Goal:** Tier-0 magic without Twilio or Google OAuth.

#### 1A. Auth & local access

| ID | Work item | Acceptance criteria |
|----|-----------|---------------------|
| P1.1 | Dev / password login on by default in local profile | Dashboard usable with no Google Cloud project |
| P1.2 | Google OAuth remains optional | Documented as “production recommended” |
| P1.3 | First-run creates admin user | One command or compose healthcheck path |

#### 1B. Playground-only mode (no telephony)

| ID | Work item | Acceptance criteria |
|----|-----------|---------------------|
| P1.4 | `VOIA_MODE=playground` (or compose profile) | Backend + frontend start; flow playground works |
| P1.5 | LLM path: OpenRouter **or** OpenAI **or** Ollama | At least one local-friendly path documented |
| P1.6 | Mock caller context UX | Existing `MockContextEditor` documented as the zero-Twilio path |

#### 1C. BYOK plug-and-play

| ID | Work item | Acceptance criteria |
|----|-----------|---------------------|
| P1.7 | Key matrix in README | Required vs optional per tier (playground / live call / campaigns) |
| P1.8 | Setup script or `/setup` health endpoint | Validates Redis, DB, JWT, and present keys; prints next missing step |
| P1.9 | In-dashboard “Test connection” for providers | Deepgram / LLM / Twilio ping without leaving UI |
| P1.10 | Secrets hygiene | No tracked salt surprises; generate `ENCRYPTION_KEY` on first boot; kill FYP JWT default in prod profile |

#### 1D. Compose & docs truth

| ID | Work item | Acceptance criteria |
|----|-----------|---------------------|
| P1.11 | Compose ports match `.env.example` | Postgres/Redis URLs copy-paste correct |
| P1.12 | README drift fix | Remove “deterministic graph planned”; document LangGraph + playground parity |
| P1.13 | Quarantine demo scripts | SmileCare/UMT patches under `examples/` with README; default path is generic |

**Tier definitions (product contract):**

```
Tier 0 — Playground:  Postgres/SQLite + Redis + 1 LLM key (+ optional STT for voice sim)
Tier 1 — Live call:   Tier 0 + Twilio + Deepgram (or alt STT) + public BASE_URL/ngrok
Tier 2 — Full ops:    Tier 1 + KB/RAG + campaigns + integrations OAuth
```

---

### Phase 2 — Contributor-ready (Weeks 4–7)

**Goal:** A stranger can add a node or provider without reverse-engineering.

#### 2A. Docs & process

| ID | Work item | Acceptance criteria |
|----|-----------|---------------------|
| P2.1 | `CONTRIBUTING.md` for VOIA | Setup, lint, test subset, PR rules |
| P2.2 | Issue / PR templates | Bug, feature, new-provider, new-node |
| P2.3 | `ARCHITECTURE.md` | Layers matching import-linter; call lifecycle; playground vs live |
| P2.4 | Good-first-issues | ≥10 labeled issues from real gaps |

#### 2B. Extension seams (make them boring)

| Extension | Seam to stabilize | Guide |
|-----------|-------------------|-------|
| LLM / STT / TTS provider | Adapter registry + env/key schema | `docs/extensions/add-provider.md` |
| Flow node type | Handler in `flow/nodes.py` (or package) + UI palette + contract keys | `docs/extensions/add-node.md` — **30-minute tutorial** |
| Integration action | Client + `WorkflowExecutor` registration + auth pattern | `docs/extensions/add-integration.md` |
| Template | Graph JSON + metadata + sample KB | `docs/extensions/add-template.md` |

| ID | Work item | Acceptance criteria |
|----|-----------|---------------------|
| P2.5 | Provider registry doc + example PR | One “hello provider” stub merged as reference |
| P2.6 | Node extension tutorial | Contributor adds a noop/log node end-to-end |
| P2.7 | Lite CI extras | `poetry install` path that runs unit tests without torch-heavy extras |
| P2.8 | Frontend `private: true` decision | Keep private for app; document it is still OSS source |

#### 2C. Test strategy for strangers

| ID | Work item | Acceptance criteria |
|----|-----------|---------------------|
| P2.9 | `make test-fast` (or equiv) | Graph contracts, slots, compiler unit tests in &lt;2 min |
| P2.10 | Anonymize SmileCare-named tests over time | Rename to domain scenarios (`dental_intake`, `missing_email_edge`) |

---

### Phase 3 — Moat-visible launch & distribution (Weeks 7–10)

**Goal:** Public story matches the real product.

#### 3A. Narrative assets

| Asset | Content rule |
|-------|--------------|
| README hero | Pitch + moat + Tier-0 quickstart only |
| `docs/MOAT.md` | Compiler, dual runtime, contracts, slots — with diagrams |
| Compare page (docs) | VOIA vs Retell / Vapi / Bland: self-host, BYOK, open graphs, playground≡live |
| Demo video script | Design flow → playground mock context → live call (3–5 min) |
| Launch post | Problem (closed voice platforms) → VOIA OS → how to contribute |

#### 3B. Community

| ID | Work item | Acceptance criteria |
|----|-----------|---------------------|
| P3.1 | GitHub Discussions or Discord | Linked from README |
| P3.2 | Template gallery | ≥5 generic industry templates, screenshots |
| P3.3 | Public roadmap board | Phases visible; “what’s paid cloud” labeled |

---

### Phase 4 — Monetize without betrayal (Weeks 10–16+)

**Goal:** Hosted VOIA converts self-hosters who hit ops pain — same graphs, zero ops.

| ID | Work item | Acceptance criteria |
|----|-----------|---------------------|
| P4.1 | Hosted waitlist + “same graph export/import” promise | Graphs portable OSS ↔ cloud |
| P4.2 | Managed Twilio / numbers (or partner) | One-click dial-in for cloud tenants |
| P4.3 | Team seats + usage metering | Align with existing usage/billing estimates |
| P4.4 | Pricing page honesty | What’s free OSS vs what’s cloud |

**Conversion narrative (do not fight self-host):**  
> Run VOIA on your laptop with your keys. When you want production telephony, SSO, and SLA — import the same graph into VOIA Cloud.

---

## 4. Moat narrative (canonical copy)

### Elevator

> VOIA is an open-source voice-agent OS. You design conversations as visual flows, test them in a playground that uses the same runtime as live phone calls, and plug in your own STT, LLM, TTS, and Twilio keys — no vendor lock-in.

### Differentiator bullets (use everywhere)

1. **One graph, two runtimes** — playground and telephony share LangGraph semantics  
2. **Compiler you can read** — React Flow → deterministic graph contracts, not a black box  
3. **Voice-native state** — slots, aliases, spoken email/phone validation, anti-repeat  
4. **BYOK by design** — encrypted key vault; providers are adapters  
5. **Ops included** — campaigns, HITL, memory, quality, alerts — self-hosted

### Anti-positioning (do not lead with)

- “3D dashboard”  
- Long undifferentiated feature laundry list  
- Customer-specific dental clinic demo as the brand  

---

## 5. 15-minute onboarding redesign (target UX)

```
0:00  git clone && docker compose --profile playground up
0:03  open localhost:3001 → create local admin
0:05  paste OpenRouter or start Ollama; click Test connection
0:08  Load “Support Triage” template
0:10  Set mock caller context → Run playground
0:12  See node trace + agent reply
0:15  Optional: CTA “Add Twilio to go live” → Tier 1 docs
```

**Hard blockers to remove (current state):** Google OAuth required, Twilio required for any value, Redis/Postgres port mismatch, README claiming flows aren’t ready, demo-script pollution in default paths.

---

## 6. Contributor architecture (target seams)

```
frontend/src/components/workflow/   → node palette + inspectors
voice_platform/flow/compiler.py     → graph → LangGraph
voice_platform/flow/nodes.py        → node handlers
voice_platform/flow/slots.py        → typed state
voice_platform/graph_contracts.py   → edge/input contracts
voice_platform/agents/flow_agent.py → live calls
voice_platform/api/playground_routes.py → design-time runs
voice_platform/integrations/        → tools & SaaS clients
vocode/                             → streaming STT/TTS/telephony adapters
```

**Invariant to protect in CI:** playground routing decisions and live `FlowAgent` decisions must not diverge for the same graph hash (add a parity test suite over time).

---

## 7. Risks & decisions log

| Risk | Decision / mitigation |
|------|------------------------|
| Looks like confused Vocode fork | Brand VOIA hard; credit Vocode once; own docs |
| Opening compiler “gives away moat” | Moat is parity + reliability + cloud ops; open code is marketing |
| SmileCare gravity | Examples pack; rename tests to domain language |
| Heavy Poetry/torch install | Lite extras + `test-fast` |
| Upstream Vocode drift | Pin/vendoring policy documented; don’t promise drop-in Vocode PyPI compatibility for VOIA platform |
| License dual MIT/Apache | Prefer single story: MIT everywhere if simpler; else Apache for `voice_platform/` + `frontend/` with NOTICE |

**Defaults locked for execution (2026-10-11):**

1. Public repo: keep `Hadi11223344/vocode-core` (brand as VOIA in docs); rename/org later optional  
2. **MIT** for Vocode + VOIA layer (see `LICENSE` + `NOTICE`)  
3. Hosted cloud **after** public Tier-0 path is solid  
4. SmileCare/UMT ops scripts → **`examples/`** (community/demo); core templates stay generic  

---

## 8. Execution checklist (compressed)

- [x] Freeze pitch + moat copy  
- [x] Write `docs/OPEN_CORE.md`  
- [x] License / NOTICE / copyright pass  
- [x] Dev login + playground compose profile  
- [x] Setup validator + key matrix  
- [x] Quarantine SmileCare scripts to `examples/smilecare/`  
- [x] Fix README drift (LangGraph dual-runtime)  
- [x] `CONTRIBUTING.md` + VOIA issue/PR templates  
- [x] Extension guides (provider, node, template)  
- [x] `make test-fast` / `make setup-check`  
- [x] `docs/MOAT.md` + `docs/COMPARE.md`  
- [x] Launch assets (`LAUNCH_CHECKLIST.md`, `LAUNCH_VIDEO_SCRIPT.md`, `ROADMAP.md`)  
- [x] Hosted wedge doc (`VOIA_CLOUD.md` — waitlist form + portability checklist)  
- [ ] External cold-clone verification (Gate 0)  
- [ ] Enable Discussions / record demo / public announcement  

---

## 9. Suggested near-term sprint order

**Sprint A (this week):** Phase 0 + README/moat draft + open-core doc  
**Sprint B:** Dev login + playground profile + setup validator  
**Sprint C:** Examples quarantine + CONTRIBUTING + add-node tutorial  
**Sprint D:** Moat docs + demo video + public launch prep  
**Sprint E:** Hosted waitlist / cloud wedge design  

---

## 10. How to use this plan

1. Resolve the four open decisions in §7.  
2. Execute Phase 0 → 1 before any “we’re open source” announcement.  
3. Do not announce until Tier-0 path is cold-clone verified by someone outside the core team.  
4. Treat every README feature bullet as a promise — demote unfinished connectors.

---

*This plan is the execution source of truth for open-sourcing VOIA. Update acceptance criteria as work lands; do not expand scope before Tier-0 is real.*
