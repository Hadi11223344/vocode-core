# Extension guide: add a flow node (~30 minutes)

Goal: add a new `nodeType` that appears in the workflow palette and runs in **both** the playground and live calls.

## Mental model

```
Frontend palette  →  graph JSON (nodeType + config)
        ↓
compiler.py       →  picks a handler kind
        ↓
nodes.py handlers →  conversation | condition | action | control
        ↓
playground executor  ≡  FlowAgent (live)
```

Most integration-style types already fall through to the shared **`action`** handler. Prefer that path unless you need new interrupt/branch semantics.

## Step 1 — Pick a handler kind

| Kind | When | Handler key in `nodes.py` |
|------|------|---------------------------|
| `conversation` | Agent speaks / waits for user | `conversation` |
| `condition` | Yes/no (or branch) routing | `condition` |
| `action` | Side effects (HTTP, Sheets, SMS, …) | `action` (default for unknown types) |
| `control` | `trigger` / `end` / `delay` / `note` | `control_handler` |

For a first contribution, implement an **action-style** node (e.g. `log_event`) that writes to `business_outcome` or emits a structured `node_result`.

## Step 2 — Frontend palette

Edit `frontend/src/components/workflow/WorkflowNodes.tsx`:

1. Add an entry to `NODE_TYPES_CONFIG` with `label`, `icon`, `category`, `description`.  
2. If the node needs a custom inspector, register it in `frontend/src/components/workflow/node-configs/registry.ts`.  
3. For SaaS connectors, also wire `NODE_TYPE_TO_INTEGRATION` / parameter templates in `node-configs/types.ts` when applicable.

`nodeType` string must match what the backend reads (`data.nodeType`).

## Step 3 — Backend behavior

### Option A — Action / integration (usual)

1. Ensure the executor can run your action (often via `voice_platform/integrations/` + `WorkflowExecutor`).  
2. Unknown types already map to `action` in `compiler.py` — confirm config keys (`action`, `integration_type`, parameters) match what `action_handler` expects.  
3. Emit clear `node_result` / errors so the playground tracer stays useful.

### Option B — New control or conversation semantics

1. Add a dedicated handler in `create_node_handlers()` inside `voice_platform/flow/nodes.py`.  
2. Register it in the returned handler map.  
3. Teach `compiler.py` to select that handler (see the `node_type == "conversation"` / `"condition"` branches).  
4. Add contract rules in `voice_platform/graph_contracts.py` if the node has required outgoing edges or `on_missing` behavior.

## Step 4 — Validation & contracts

- Frontend: `frontend/src/lib/workflowValidation.ts` if the editor should block incomplete configs.  
- Backend: graph contracts for required edges / branch keys.  
- Keep playground and live on the same validation story.

## Step 5 — Tests

```bash
make test-fast
# and/or a focused test:
poetry run pytest tests/voice_platform/test_langgraph_flow_executor.py -q -k your_case
```

Minimum: a unit test that compiles a tiny graph containing your node and asserts the next edge / `business_outcome` key.

## Step 6 — Docs

- One paragraph in your PR describing playground vs live behavior.  
- If new env vars are required, update `voice_platform/.env.example`.

## Parity checklist

- [ ] Same `nodeType` string in UI and backend  
- [ ] Playground mock context can exercise the node  
- [ ] Live path does not special-case the node in a second codepath  
- [ ] Failures surface as `node_result` errors, not silent fallthrough  

## References

- [MOAT.md](../MOAT.md) — why parity matters  
- `voice_platform/flow/compiler.py`  
- `voice_platform/flow/nodes.py`  
- `voice_platform/agents/flow_agent.py`  
- `voice_platform/api/playground_routes.py`
