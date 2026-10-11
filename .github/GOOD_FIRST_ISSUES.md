# Seeding good first issues

After enabling Issues on the public repo, open these as separate issues (copy each block). Label: `good first issue`, plus `docs` / `provider` / `flow-node` as noted.

---

### Docs: Tier 0 screenshot walkthrough
**Labels:** `good first issue`, `docs`  
Add 3–5 screenshots (or a short GIF) to the README Tier 0 section: Dev Login → template → playground turn. No secrets in images.

---

### Docs: Ollama Tier 0 recipe
**Labels:** `good first issue`, `docs`, `provider`  
Document exact `OPENAI_API_BASE` + model values for local Ollama in README and `.env.example` comments. Verify with `make setup-check`.

---

### Node: `log_event` utility node
**Labels:** `good first issue`, `flow-node`  
Follow [docs/extensions/add-node.md](../docs/extensions/add-node.md). Action-style node that writes `{ "logged": true, "message": "..." }` into `business_outcome` / `result` and shows in playground tracer. Include a unit test in `test-fast` surface if practical.

---

### DX: `check_setup.py` suggests compose profile
**Labels:** `good first issue`, `docs`  
When Redis is down, print the exact command `docker compose up -d db redis` vs full `--profile playground` based on what failed.

---

### Templates: generic “clinic intake” without SmileCare branding
**Labels:** `good first issue`, `docs`  
Add a non-branded dental/clinic intake template in `agent_templates.py` (or document how to derive one from examples). No real clinic names/phones.
