# SmileCare demo pack (optional)

These scripts and fixtures shaped a **dental clinic** demo used while hardening VOIA’s flow contracts (missing inputs, Sheets ranges, email capture).

They are **not required** to run VOIA. Tier 0 playground works without anything in this folder.

## What’s here

| Script | Purpose |
|--------|---------|
| `patch_smilecare_on_missing_edge.py` | Repair `on_missing` edges on a stored agent graph |
| `patch_smilecare_sheets_range.py` | Fix Google Sheets range wiring |
| `update_smilecare_workflow.py` / `update_smilecare_graph_db.py` | Apply graph repairs to DB |
| `dedup_smilecare.py` | Deduplicate demo graph artifacts |
| `sync_smilecare_prompt.py` | Sync demo prompt text |
| `probe_smilecare_*.py` | One-off integration probes |

## How to run

From the **repo root** (with app env / Compose as usual):

```bash
# Example: list agents / dry-run a patch
python examples/smilecare/patch_smilecare_on_missing_edge.py --list
docker compose exec -T app python examples/smilecare/dedup_smilecare.py
```

Generic industry templates live in the product UI / `agent_templates.py`. Prefer those for new installs; keep this pack for regression and demos.

## Related tests

SmileCare-named tests under `tests/voice_platform/` exercise routing contracts. Over time they should be renamed to domain scenarios (`dental_intake`, `missing_email_edge`) — see the open-source strategy doc.
