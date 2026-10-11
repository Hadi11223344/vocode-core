# VOIA Moat

**Pitch:** Design the call like a flowchart. Run the same graph in the playground and on the phone. Bring your own keys.

This doc is the public explanation of what is hard to copy quickly — and what we deliberately do *not* treat as a moat.

---

## The product claim

Closed voice platforms sell agents and APIs. VOIA is a **voice-agent operating system**:

1. Authors design conversations as **React Flow** graphs  
2. A **compiler** turns those graphs into **LangGraph** state machines  
3. The **playground** and **Twilio live path** execute with shared semantics  
4. Operators bring **their own** STT / LLM / TTS / telephony keys  

Open-sourcing the compiler is intentional: the moat is **parity + reliability + ops**, not secrecy.

---

## Moat assets

### 1. Dual-runtime parity

| Path | Entry | Engine |
|------|--------|--------|
| Design-time | Flow playground (WebSocket) | `LangGraphFlowExecutor` |
| Call-time | Twilio media stream | `FlowAgent` |

Both compile through `voice_platform/flow/compiler.py` and share node handlers from `voice_platform/flow/nodes.py`.

**Invariant:** for the same graph content hash, routing decisions (branches, `on_missing`, slot retries) must not diverge between playground and live.

### 2. Graph contracts

`voice_platform/graph_contracts.py` normalizes branch keys, required-input / `on_missing` edges, and content hashing. Invalid graphs fail loudly at save/compile time instead of mid-call.

### 3. Voice-native state (slots)

`voice_platform/flow/slots.py` plus validators (e.g. spoken email in `voice_platform/validation/email.py`) keep conversational state typed and aliased (`patient_name` ↔ `caller_name`), with anti-repeat / retry scope behavior for real phone speech.

### 4. BYOK provider adapters

LLM/STT/TTS/telephony are resolved through factories and encrypted user keys — not a single-vendor runtime. Self-hosters keep control; cloud VOIA sells convenience, not lock-in.

### 5. Ops surface

Campaigns, HITL review, memory, quality scoring, alerts, and RBAC make VOIA a platform, not a demo script.

---

## Not the moat

Do not lead marketing or README copy with:

- 3D dashboard chrome  
- Undifferentiated feature laundry lists  
- Customer-specific demos (SmileCare lives under `examples/`)  
- “We have more nodes in the palette” without runtime depth  

---

## Competitive frame (honest)

| Dimension | Closed platforms (Retell / Vapi-class) | VOIA |
|-----------|----------------------------------------|------|
| Self-host | Rare / limited | First-class |
| BYOK | Partial | Design center |
| Graph openness | Proprietary | Readable compiler + contracts |
| Playground ≡ live | Often approximated | Shared LangGraph handlers |
| Ops | Hosted bundle | Self-host + future cloud |

---

## For contributors

When you change flow behavior, ask:

1. Does playground still match live?  
2. Did graph contracts / validation need an update?  
3. Is there a `make test-fast` case for the branch?

See [extensions/add-node.md](./extensions/add-node.md) and [VOIA_OPEN_SOURCE_STRATEGY.md](./VOIA_OPEN_SOURCE_STRATEGY.md).
