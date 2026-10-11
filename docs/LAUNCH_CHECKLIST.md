# VOIA public open-source launch checklist

Do **not** announce “we're open source” until Tier 0 is verified by someone outside the core team.

## Gate 0 — Cold-clone proof (hard gate)

Have a friend or colleague with **no prior VOIA setup** run:

```bash
git clone <this-repo>
cd vocode-core
cp voice_platform/.env.example voice_platform/.env
# Add ALLOW_DEV_LOGIN=true (already default in example) + one LLM key
docker compose --profile playground up -d
# Open http://localhost:3001 → Dev Login → load a flow → playground reply
python3 scripts/check_setup.py
make test-fast
```

**Pass criteria**

- [ ] First playground agent reply in **≤ 15 minutes**  
- [ ] No Google OAuth required  
- [ ] No Twilio required for that path  
- [ ] `make test-fast` green on their machine (or documented skip if deps missing)

## Gate 1 — Narrative & repo hygiene

- [ ] README hero = pitch + moat + Tier 0 (done)  
- [ ] [OPEN_CORE.md](./OPEN_CORE.md) + [MOAT.md](./MOAT.md) + [COMPARE.md](./COMPARE.md) linked  
- [ ] [CONTRIBUTING.md](../CONTRIBUTING.md) + issue/PR templates present  
- [ ] SmileCare ops under `examples/` — not default path  
- [ ] No FYP / “demo only” language on primary surfaces  
- [ ] LICENSE + NOTICE accurate  
- [ ] Secrets scrubbed (no real `.env` in git)

## Gate 2 — Launch assets

### Short demo video (3–5 min) — script

1. **0:00** — Problem: closed voice platforms lock graphs and keys  
2. **0:30** — Clone + `docker compose --profile playground up`  
3. **1:00** — Dev Login → open workflow editor  
4. **1:30** — Load template / simple graph (ask name → action → end)  
5. **2:00** — Flow playground + mock caller context → successful turn + node trace  
6. **2:45** — (Optional) flip to Tier 1: Twilio inbound, same graph  
7. **3:30** — Moat line: playground ≡ live, BYOK, open compiler  
8. **4:00** — CTA: star/fork, good first issues, Cloud waitlist  

### Launch post (skeleton)

```text
Title: VOIA — open-source voice agent OS (BYOK, playground ≡ live)

Body:
- One-liner pitch
- Why open-core (link OPEN_CORE + COMPARE)
- Tier 0 quickstart (link README)
- What we want contributors to build (nodes, providers, templates)
- Cloud waitlist for people who hate ops (link VOIA_CLOUD)
```

Channels (pick 2–3): GitHub repo release notes, LinkedIn/X, Discord (Vocode or own), relevant HN/Reddit only if Tier 0 is solid.

## Gate 3 — Community surface

- [ ] Enable GitHub Discussions (Q&A + Ideas + Cloud) **or** link a Discord  
- [ ] Pin issue: “Good first issues for VOIA”  
- [ ] Label set: `good first issue`, `provider`, `flow-node`, `docs`, `bug`, `cloud-waitlist`  
- [ ] Public [ROADMAP.md](./ROADMAP.md) visible from README  

## Gate 4 — After launch (48 hours)

- [ ] Triage issues daily  
- [ ] Thank first external PR publicly  
- [ ] Note setup friction → fix README / `check_setup.py`  
- [ ] Start Cloud waitlist responses  

## Related docs

- [VOIA_CLOUD.md](./VOIA_CLOUD.md)  
- [COMPARE.md](./COMPARE.md)  
- [DEMO_SCRIPT.md](./DEMO_SCRIPT.md) — longer product demo (not the OSS launch video)  
