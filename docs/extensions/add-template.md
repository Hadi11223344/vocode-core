# Extension guide: add an agent template

Templates help newcomers reach value in the playground without designing a graph from scratch.

## Where templates live

- **In-product templates:** `voice_platform/agent_templates.py` (`AGENT_TEMPLATES`, `get_template`, slug aliases)  
- **Demo / customer-shaped ops:** `examples/` (e.g. [`examples/smilecare/`](../../examples/smilecare/)) — not the default onboarding path  

Prefer **generic industry** templates in `AGENT_TEMPLATES` (support, restaurant, scheduling). Keep real clinic/university copy and patch scripts under `examples/`.

## Steps

1. **Define the template** in `AGENT_TEMPLATES`:  
   - Stable `id` / `slug`  
   - Mode: `single_prompt` or conversational flow graph JSON  
   - Sensible default LLM/STT/TTS labels (BYOK — don’t embed secrets)  
2. **Graph quality**  
   - Required conversation edges and `on_missing` where inputs can be missing  
   - Terminal `end` / `end_call` nodes  
   - Run through graph contracts / workflow validation  
3. **Optional KB sample** under `knowledge_base/` with non-PII content  
4. **Frontend**  
   - Confirm the templates UI lists your slug/category  
5. **Docs**  
   - One line in README or examples README if this is a showcase template  

## Test

```bash
make test-fast
# Plus a playground manual check: load template → mock context → one successful turn
```

## Checklist

- [ ] No real phone numbers, emails, or patient data  
- [ ] Works on Tier 0 (playground) without Twilio  
- [ ] Slug aliases updated if renaming  
- [ ] SmileCare-specific maintenance scripts stay in `examples/smilecare/`  

## References

- `voice_platform/agent_templates.py`  
- `voice_platform/graph_contracts.py`  
- [add-node.md](./add-node.md)
