# OSS launch video script (3–5 minutes)

**On-screen title:** VOIA — Voice agent OS you can fork  
**Closing CTA:** Star · Fork · Contribute a node · Cloud waitlist  

---

### [0:00–0:30] Hook

> Closed voice platforms own your graphs and sit between you and your API keys.  
> VOIA is open-source: design the call like a flowchart, test it in a playground that uses the **same runtime** as the phone, and bring your own keys.

Show: README hero + [COMPARE](./COMPARE.md) table flash.

### [0:30–1:10] Install

Terminal:

```bash
cp voice_platform/.env.example voice_platform/.env
# paste OPENROUTER_API_KEY or GROQ_API_KEY
docker compose --profile playground up -d
```

Browser: `http://localhost:3001` → **Dev Login**.

### [1:10–2:20] Build

- Open workflow / conversational flow editor  
- Simple path: trigger → conversation (“ask name”) → end  
- Or load a generic template  

Call out: nodes are real graph contracts, not a slideshow.

### [2:20–3:20] Playground ≡ product

- Open Flow Playground  
- Set mock caller context  
- Run a turn — show node trace / agent reply  
- Line: *This is the same LangGraph path live Twilio calls use.*

### [3:20–4:00] Optional Tier 1 tease

- “Add Twilio + Deepgram when you want a real number”  
- Do **not** derail the video if the tunnel fails — cut back to playground  

### [4:00–4:40] Moat + contribute

- Moat bullets: dual runtime, contracts, BYOK  
- “Add a node in ~30 minutes” → `docs/extensions/add-node.md`  
- `make test-fast`  

### [4:40–5:00] CTA

> Fork it. Run Tier 0 today. If you want the same graphs without ops — join the VOIA Cloud waitlist.

End card: repo URL · docs/OPEN_CORE.md · docs/VOIA_CLOUD.md  
