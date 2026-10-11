# VOIA vs closed voice platforms

Honest comparison for builders choosing between **self-hosted open-core** and hosted SaaS (Retell / Vapi / Bland-class products). Feature sets move quickly — judge on *architecture*, not a checklist race.

## One-line difference

| | Closed platforms | VOIA |
|--|------------------|------|
| Model | Hosted API + studio | **Voice-agent OS you can fork** |
| Graphs | Proprietary runtime | React Flow → LangGraph you can read |
| Keys | Often platform-mediated | **BYOK** (bring your own STT/LLM/TTS/Twilio) |
| Parity | Playground ≈ production (sometimes) | **Same handlers** for playground and live calls |

Pitch: *Design the call like a flowchart. Run the same graph in the playground and on the phone. Bring your own keys.*

---

## Dimension-by-dimension

| Dimension | Typical closed platform | VOIA (open-core) |
|-----------|-------------------------|------------------|
| **Self-host** | Rare or limited | First-class (`docker compose --profile playground`) |
| **Source access** | Closed | MIT — compiler, slots, contracts, dashboard |
| **BYOK** | Partial / add-on | Design center — encrypted key vault |
| **Flow authoring** | Visual builder | React Flow + graph contracts (`on_missing`, branches) |
| **Playground ≡ live** | Best-effort | Shared `flow/nodes.py` + LangGraph compile path |
| **Local LLM** | Uncommon | Ollama / OpenAI-compatible base URL (Tier 0) |
| **Ops** | Hosted campaigns, analytics | Self-host campaigns, HITL, memory, alerts |
| **Time-to-first-value** | Fast (no infra) | Fast Tier 0 if keys ready; Twilio adds Tier 1 setup |
| **Compliance / data residency** | Vendor regions | You choose where it runs |
| **SLA / managed numbers** | Product strength | **VOIA Cloud** (commercial) — see [VOIA_CLOUD.md](./VOIA_CLOUD.md) |
| **Community extensibility** | Plugins if offered | [Add node / provider / template](./extensions/add-node.md) |

---

## When to pick VOIA

- You need **self-host** or air-gapped / regulated environments  
- You want **open graphs** and to debug the compiler, not a black box  
- You already pay Deepgram / OpenRouter / Twilio and refuse double markup  
- You want contributors to add nodes without waiting on a vendor roadmap  

## When to pick a closed hosted platform

- You want **zero telephony ops** tomorrow (numbers, webhooks, scaling)  
- You have no one to run Postgres/Redis/Docker  
- You need vendor SLA and support contracts immediately  

**Both can be true:** prototype on VOIA OSS → import the same graph into VOIA Cloud when ops hurt. That is the open-core conversion path.

---

## What we do not claim

- “More integrations in the palette” ≠ deeper runtime support — check implementation depth  
- We are not “Vocode with a skin”; we are a platform on the Vocode streaming SDK  
- SmileCare / demo packs are examples, not the product brand — see `examples/`

---

## Dig deeper

- [MOAT.md](./MOAT.md) — dual-runtime and contracts  
- [OPEN_CORE.md](./OPEN_CORE.md) — what stays free vs cloud  
- [VOIA_CLOUD.md](./VOIA_CLOUD.md) — managed offering  
- [LAUNCH_CHECKLIST.md](./LAUNCH_CHECKLIST.md) — public launch readiness  
