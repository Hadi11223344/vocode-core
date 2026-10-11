# Flow Playground Reference Guide

A guide to the React Flow graph model used in our Flow Playground and how it maps to `voice_platform.FlowPlaygroundConversation` and `WorkflowExecutor` execution.

---

## 1. React Flow Primer

React Flow is a React library for building interactive node-based diagrams. The data model is intentionally simple: a graph is two arrays — `nodes` and `edges`.

### 1.1 Nodes

A node is an object with at minimum:

```ts
interface Node {
  id: string;              // unique identifier
  position: { x: number; y: number };
  type?: string;           // built-in or custom node type
  data?: Record<string, unknown>; // arbitrary application data
  className?: string;
  style?: CSSProperties;
}
```

React Flow ships with a few built-in types (`default`, `input`, `output`, `group`), but most real-world use cases register **custom node components** via the `nodeTypes` prop.

### 1.2 Handles

A `Handle` is the connection point on a node where an edge attaches. Each handle has:

- `type`: `"source"` (outgoing) or `"target"` (incoming)
- `position`: `"top"`, `"bottom"`, `"left"`, `"right"`
- `id` (optional, **required** when a node has multiple handles on the same side)

Example custom node with two output handles:

```tsx
import { Handle, Position } from 'reactflow';

function ConditionNode() {
  return (
    <div className="condition-node">
      <Handle type="target" position={Position.Top} />
      <div>Condition</div>
      <Handle type="source" id="yes" position={Position.Bottom} style={{ left: '30%' }} />
      <Handle type="source" id="no"  position={Position.Bottom} style={{ left: '70%' }} />
    </div>
  );
}
```

> **Key rule**: when a node has more than one source or target handle, each handle must have a unique `id`. Edges then reference that id in `sourceHandle` / `targetHandle`.

### 1.3 Edges

An edge connects a `source` node to a `target` node:

```ts
interface Edge {
  id: string;
  source: string;          // source node id
  target: string;          // target node id
  sourceHandle?: string;   // required when source has multiple handles
  targetHandle?: string;   // required when target has multiple handles
  type?: 'default' | 'smoothstep' | 'step' | 'straight' | string;
  label?: string | ReactNode;
  animated?: boolean;
}
```

If you omit `sourceHandle` / `targetHandle`, React Flow connects to the first matching handle. That works for single-port nodes, but **condition nodes with dual outputs rely on `sourceHandle` ids** to distinguish yes/no branches.

### 1.4 Built-in edge types

React Flow provides four built-in edge renderers:

- `default` — bezier curve
- `smoothstep` — rounded orthogonal line
- `step` — right-angle stepped line
- `straight` — straight line

These are useful for call-flow graphs where readability matters; `smoothstep` is commonly used for vertical top-to-bottom flows.

### 1.5 Layout

React Flow itself does **not** auto-layout graphs. Common layout choices:

- **dagre** — simple directed-graph layout, good for trees
- **elkjs** — highly configurable layered layout, supports multiple handles/ports
- **d3-hierarchy** / **d3-force** — alternative for strict trees or physics-based layouts

Our backend executor uses node `position.y` to decide execution order (top-to-bottom), so a stable layout is also important for deterministic behavior.

### 1.6 Events

Controlled React Flow components use these handlers:

- `onNodesChange` — drag, select, remove
- `onEdgesChange` — select, remove
- `onConnect` — fired when a user drags from one handle to another
- `onConnectStart` / `onConnectEnd` — for custom connection UX

The playground canvas is read-only during execution (`nodesDraggable={false}`, `nodesConnectable={false}`), so these events are used during editing only.

---

## 2. Our `graph_json` Format

The agent `graph_json` column stores a plain JSON object with the same `nodes` and `edges` arrays React Flow uses. Our backend does not require the full React Flow object; it reads a subset of fields.

### 2.1 Node schema

```json
{
  "id": "conversation_3",
  "type": "workflowNode",
  "position": { "x": 400, "y": 300 },
  "data": {
    "nodeType": "conversation",
    "label": "Scheduling Preferences",
    "description": "Ask the caller for a preferred date/time",
    "config": {
      "prompt": "Ask the caller what date and time they prefer.",
      "variables_to_extract": ["preferred_date", "preferred_time"]
    },
    "isConfigured": true
  }
}
```

Backend extraction (`_node_type`) uses `data.nodeType` (fallback to `type`) to determine the execution type. The `config` object is what `WorkflowExecutor` and `FlowPlaygroundConversation` actually read.

### 2.2 Edge schema

```json
{
  "id": "e-cond-no",
  "source": "condition_2",
  "target": "conversation_4",
  "sourceHandle": "no",
  "label": "no"
}
```

Important fields:

- `sourceHandle`: `"yes"` or `"no"` for condition nodes (set by the frontend dual-handle component)
- `label`: optional text; the executor also checks `label` if `sourceHandle` is missing

### 2.3 Node categories used by our frontend

Our `WorkflowNodes.tsx` defines the visual node palette:

| Category | Examples |
|----------|----------|
| flow | `trigger`, `conversation`, `condition`, `end`, `end_call`, `extract_variable` |
| telephony | `transfer_call`, `voicemail_detect` |
| communication | `send_sms`, `send_email`, `notification`, `whatsapp_cloud`, `discord`, `microsoft_teams` |
| integration | `google_calendar`, `google_sheets`, `cal_com`, `calendly`, `salesforce`, `pipedrive`, `gohighlevel`, `zendesk`, `freshdesk`, `intercom`, `stripe`, `shopify`, `webhook`, `zapier`, `make`, `notion`, `airtable`, `jira`, `linear`, `action`, `api_request`, `mcp_tool`, `custom_api` |
| ai | `knowledge_base`, `llm_process`, `subagent` |
| utility | `delay`, `note`, `code` |

Only the `nodeType` matters for execution; styling lives in the frontend config.

---

## 3. Node Deep Dives

### 3.1 Trigger

- **Visual**: green node with a single target handle (no source)
- **Execution**: entry point; the executor starts from trigger nodes or from any node with zero incoming edges
- **Config fields**: `trigger_phrases` (list of strings) is also stored on the agent, but the trigger node itself is mostly a marker

### 3.2 Conversation

- **Visual**: violet node, single input, single output
- **Behavior**: pauses execution, asks the LLM to generate a response, waits for the next user message
- **Config fields**:
  - `prompt`: instruction appended to the system prompt for this turn
  - `variables_to_extract`: list of variable names to extract from the caller's next message
- **Execution details**:
  - `process_user_message` appends the user message to `context["transcript"]`
  - `_extract_conversation_variables` calls `WorkflowExecutor._llm_extract` for each variable
  - Extracted values are stored in `self.context[variable_name]`
  - Look-ahead extraction also scans queued action nodes for `{{variable}}` references and auto-adds them

Example:

```json
{
  "nodeType": "conversation",
  "label": "Scheduling Preferences",
  "config": {
    "prompt": "Ask the caller which day and time they prefer for the appointment.",
    "variables_to_extract": ["preferred_date", "preferred_time"]
  }
}
```

### 3.3 Action / Integration

- **Visual**: varies by integration (calendar, sheets, etc.)
- **Behavior**: executes an integration action immediately, no pause
- **Config fields** depend on the service type. For Google Calendar actions:
  - `action`: `"check_availability"`, `"create_event"`, `"list_events"`, etc.
  - `params`: the action payload; values may use `{{variable}}` templates

Example:

```json
{
  "nodeType": "google_calendar",
  "label": "Check Availability",
  "config": {
    "action": "check_availability",
    "params": {
      "date": "{{preferred_date}}",
      "duration_minutes": 60
    }
  }
}
```

The executor resolves `{{preferred_date}}` to the current context value. If the value is missing, the action may fail or return a structured error.

### 3.4 Condition

- **Visual**: amber node with **two output handles** (`yes` / `no`)
- **Behavior**: evaluates an expression against `context`, then routes to the matching branch
- **Config fields**:
  - `expression`: condition string, e.g. `result.available_slots not_empty`

The condition node result is **not** stored in `context["result"]`; only action results are. This prevents a condition from overwriting the upstream action output when a loop re-enters the condition.

### 3.5 End / End_call / Voicemail_detect

These are control-flow terminal nodes:

- `end` — graph complete
- `end_call` — terminate the call
- `voicemail_detect` — branch based on whether voicemail was reached

`end` and `end_call` stop execution. `voicemail_detect` is a branching node with output edges.

### 3.6 Note

Invisible to the caller; stores text in `context["_last_note"]` for the LLM or downstream nodes.

### 3.7 Code

Runs sandboxed Python code. The sandbox allows basic math, list/dict operations, `datetime`, and `random`, but blocks imports, `open`, `exec`, `eval`, classes, and attribute access.

### 3.8 Extract Variable

A dedicated node to run LLM extraction from the transcript. Use it when a conversation node alone is not enough, or when extraction must happen at a specific point.

---

## 4. Condition Node Branching

### 4.1 Expression syntax

The backend `_evaluate_condition` supports:

| Syntax | Meaning | Example |
|--------|---------|---------|
| `X not_empty` | X is truthy (non-empty string / non-empty collection) | `preferred_date not_empty` |
| `X == value` | equality; unquoted strings become literals | `caller_type == new_patient` |
| `X != value` | inequality | `is_emergency != true` |
| `X contains Y` | substring or list membership | `tags contains vip` |
| `X > Y`, `X < Y`, `X >= Y`, `X <= Y` | numeric comparison | `confidence >= 0.8` |
| `X == not_empty` | same as `X not_empty`, kept for legacy flows | `result.available_slots == not_empty` |

### 4.2 Context resolution

Expressions can reference:

- Top-level context variables: `preferred_date`, `is_emergency`
- Dotted paths into dict results: `result.available_slots`, `node_action_1_result.matches`

Example context after a Google Calendar check:

```json
{
  "result": {
    "success": true,
    "available_slots": ["10:00", "11:00"]
  },
  "node_node-20_result": {
    "success": true,
    "available_slots": ["10:00", "11:00"]
  }
}
```

Expression: `result.available_slots not_empty` → `True`.

### 4.3 Edge selection

The executor determines the branch by checking each outgoing edge:

```python
branch_aliases = {"yes", "true"} if condition_met else {"no", "false"}
for edge in edges:
    source_handle = str(edge.get("sourceHandle") or "").strip().lower()
    label = str(edge.get("label") or "").strip().lower()
    if source_handle in branch_aliases or label in branch_aliases:
        preferred.append(edge)
```

This means:

- The frontend should create edges with `sourceHandle: "yes"` or `"no"`
- The optional `label` can also be `"yes"` / `"no"`
- If neither matches, the executor returns an empty list and halts that branch

### 4.4 Common condition mistake

A common bug is connecting both outgoing edges of a condition node without labels. Because the executor now returns an empty list on no-match, that branch simply stops instead of executing both paths.

> **Best practice**: always label condition edges yes/no, either via `sourceHandle` or `label`.

---

## 5. Variable Extraction and Templates

### 5.1 Template syntax

Action/condition parameters use double-curly variable references:

```json
{
  "date": "{{preferred_date}}",
  "summary": "Appointment for {{caller_name}}"
}
```

These are resolved by `WorkflowExecutor._resolve_templates` before the integration handler runs.

### 5.2 Extraction methods

Our system has three ways variables get into `context`:

1. **Pre-populated context**
   - `caller_name`, `caller_phone`, `transcript`, `user_id`

2. **Conversation-node extraction**
   - `variables_to_extract` on the conversation node config
   - Runs on the next user message via `_extract_conversation_variables`

3. **Just-in-time extraction**
   - Before an action/condition node runs, the executor scans the node's `config` and `params` for `{{var}}` patterns
   - Missing variables are extracted from the full transcript immediately before execution

4. **Look-ahead extraction**
   - When a conversation node pauses, queued action nodes are scanned for `{{var}}`
   - Those variables are added to `_pending_variables_to_extract` so they are captured from the next user message

### 5.3 Extraction prompt

The LLM is asked:

```
You are a precise extraction assistant.
Extract ONLY the requested value from the text.
Return ONLY the value — no explanation, no quotes, no markdown.
If the value is not present, respond with exactly: NOT_FOUND
```

If the value is `NOT_FOUND`, the variable is left out of context. Actions that need it may fail gracefully (e.g., Google Calendar returns `available_slots: []`).

### 5.4 Fallback regex extraction

If the LLM is unavailable, `email` fields use a regex fallback. Other variables return `None`.

---

## 6. Execution Model

### 6.1 Playground vs backend

Two execution paths share the same node handler (`WorkflowExecutor._execute_graph_node`):

| Aspect | Flow Playground | Backend graph executor |
|--------|-----------------|------------------------|
| Entry | WebSocket `/ws/{agent_id}/flow` | `workflow_routes.execute_workflow` / `call_events` |
| Pause at conversation | Yes | Yes, returns `status: "blocking"` |
| Resume | Next user message sends `process_user_message` | Not supported for live calls |
| Cycle handling | Warns, continues with visit limits | Blocks on pre-execution cycle detection |
| Max steps | 50 per `_run_until_conversation` call | 50 total |
| Max visits per node | 3 | 3 (configurable) |

### 6.2 Flow Playground lifecycle

```
start_flow()
  ├─ _detect_cycles()          # warn only
  ├─ queue start nodes
  └─ _run_until_conversation()
        ├─ pop node from queue
        ├─ increment visit count, skip if > 3
        ├─ if conversation node:
        │     ├─ build system prompt + context summary + instruction
        │     ├─ stream LLM response
        │     ├─ queue outgoing nodes
        │     └─ RETURN (pause)
        ├─ if end/end_call: emit flow_end, RETURN
        ├─ if trigger/voicemail_detect: queue outgoing, continue
        └─ else (action/condition/integration):
              ├─ JIT variable extraction
              ├─ _execute_graph_node()
              ├─ store result in context (skip for conditions)
              ├─ if condition: _select_condition_edges()
              └─ queue outgoing nodes

process_user_message(user_text)
  ├─ append to transcript + history
  ├─ extract pending variables
  └─ _run_until_conversation()
```

### 6.3 Context summary injected into the LLM

For each conversation turn, the system prompt includes:

```
[FLOW CONTEXT — Use this information to respond naturally]
Last action result (❌ FAILED): {"success":false,"error":"...","available_slots":[],...}
Conversation so far: Caller: I'd like to book... Agent: Sure...
Step 'node-20' result: {...}
preferred_date: 2025-08-15
[END FLOW CONTEXT]

[INSTRUCTION — You are now at the "Suggest Alternatives" step. Suggest alternative times if the preferred slot is unavailable. ...]
```

This is why the conversation node's `prompt` and the previous action's result shape are critical: they determine what the agent says next.

---

## 7. WebSocket Events

Events emitted to the frontend (`use-flow-playground.ts`):

| Event | Payload | Meaning |
|-------|---------|---------|
| `flow_start` | `{ graph }` | Execution began |
| `node_start` | `{ node_id, node_type, label }` | A node is about to run |
| `agent_token` | `{ node_id, text }` | Streaming token from the LLM |
| `agent_response` | `{ node_id, text }` | Final assembled response |
| `node_result` | `{ node_id, node_type, label, status, result, duration_ms, error }` | Node completed, skipped, or failed |
| `condition_branch` | `{ node_id, condition_met }` | Condition chose yes/no |
| `edge_traversed` | `{ source, target, label }` | An edge was followed |
| `variables_extracted` | `{ variables: { preferred_date: "..." } }` | Variables extracted from the last message |
| `error` | `{ text, node_id?, fatal? }` | Non-fatal warning or fatal error |
| `flow_end` | `{ total_nodes }` | No more nodes to execute |
| `context_updated` | — | Reserved |

The `FlowGraphCanvas` uses `completedNodeIds`, `failedNodeIds`, `activeNodeId`, and `traversedEdgeKeys` to color nodes/edges during execution.

---

## 8. Common Errors and Fixes

### 8.1 "Condition evaluated to NO" loop

**Symptom**: condition node keeps evaluating to NO even though the upstream action returned a matching result.

**Cause**: older code stored the condition node's own output in `context["result"]`, so subsequent evaluations looked at `{condition_met: false}` instead of the action output.

**Fix**: condition node results are no longer written to `context["result"]`. Ensure your branch labels are yes/no.

### 8.2 "Condition node has no 'yes' branch edge"

**Symptom**: flow stops after a condition with a warning.

**Cause**: the outgoing edge has no `sourceHandle` or `label` matching yes/no.

**Fix**: label condition edges. In the frontend, condition nodes render two handles (`id: "yes"` and `id: "no"`).

### 8.3 "Google Calendar check_availability requires a non-empty 'date'"

**Symptom**: `date` is null.

**Cause**: `preferred_date` was never extracted or not in context.

**Fix**:

- Set `variables_to_extract: ["preferred_date"]` on the conversation node that asks for the date
- Make sure that conversation node's `prompt` actually asks for a date
- Just-in-time extraction will catch `{{preferred_date}}` references, but the user still has to mention a date in their response

### 8.4 "Flow halted because a node exceeded the visit limit"

**Symptom**: execution stops with a visit-limit error.

**Cause**: a cycle that does not update the condition variable. Example: condition → conversation → same condition with no action in between that changes the result.

**Fix**: ensure retry loops pass through an action that can change the data the condition evaluates (e.g., check a different date).

### 8.5 Conversation node ignores its prompt

**Symptom**: the agent's reply does not follow the node's instruction.

**Cause**: the system prompt/context is too long, conflicting, or the model is ignoring the bracketed instruction.

**Fix**:

- Keep node prompts short and directive
- Avoid stacking too many failed action results without clear guidance
- Make sure the previous action result includes the fields the prompt expects

---

## 9. Best Practices

### 9.1 Graph design

- **Start with a trigger node** so execution has one clear entry point
- **Top-to-bottom layout** — the executor sorts start nodes by `y` then `x`
- **Avoid unconditional cycles**; every loop should be gated by a condition that can become false
- **End every branch** with an `end`, `end_call`, or conversation node

### 9.2 Condition nodes

- Always use `sourceHandle` yes/no
- Use `result.<field> not_empty` for list checks
- Place the action whose result the condition reads immediately before the condition node

### 9.3 Conversation nodes

- Match the `prompt` to the downstream action's needs
- Set `variables_to_extract` for every variable the next action uses
- Ask for one thing at a time to improve extraction accuracy

### 9.4 Action nodes

- Prefer explicit `params` over relying on config fallbacks
- Use `{{variable}}` references consistently
- Handle missing-variable errors by returning structured data (e.g., `available_slots: []`)

### 9.5 Frontend canvas

- Keep `FlowGraphCanvas` read-only during execution (`nodesDraggable={false}`, `nodesConnectable={false}`)
- Use `nodeTypes={{ workflowNode: WorkflowNode }}` to render all nodes through one custom component
- Style active/failed/completed nodes with CSS classes `flow-node-active`, `flow-node-failed`, `flow-node-completed`

---

## 10. Code Reference

### 10.1 Key files

| File | Responsibility |
|------|----------------|
| `voice_platform/api/playground_routes.py` | `FlowPlaygroundConversation`, WebSocket endpoint, conversation streaming |
| `voice_platform/integrations/executor.py` | `WorkflowExecutor`, `_execute_graph_node`, `_evaluate_condition`, `_resolve_templates`, `_llm_extract` |
| `frontend/src/components/workflow/WorkflowNodes.tsx` | Custom node component, node type config, handles |
| `frontend/src/components/playground/FlowGraphCanvas.tsx` | Read-only React Flow canvas for the playground |
| `frontend/src/hooks/use-flow-playground.ts` | WebSocket client, event aggregation, trace state |

### 10.2 Important method signatures

```python
# playground_routes.py
class FlowPlaygroundConversation:
    async def start_flow(self, event_callback=None) -> None
    async def process_user_message(self, user_text: str, event_callback=None) -> None
    async def _run_until_conversation(self, event_callback=None) -> None
    async def _extract_conversation_variables(self, event_callback=None) -> None
    def _build_context_summary(self) -> str
    def _select_condition_edges(self, edges, condition_met, event_callback=None, node_id="") -> list

# executor.py
class WorkflowExecutor:
    async def execute_graph(self, graph, context=None, *, max_steps=50, max_visits_per_node=3, transition_flexibility="strict", event_callback=None) -> list
    async def _execute_graph_node(self, node, context, *, event_callback=None) -> dict
    @staticmethod
    def _evaluate_condition(expression: str, context: dict) -> bool
    @staticmethod
    def _select_condition_edges(edges: list[dict], condition_met: bool) -> list[dict]
    def _resolve_templates(self, obj, context: dict)
    async def _llm_extract(self, transcript: str, prompt: str, variable_name: str) -> str | None
```

---

## 11. Quick Checklist for Building a Flow

- [ ] One trigger node at the top
- [ ] Conversation nodes ask for the variables the next action needs
- [ ] Conversation nodes set `variables_to_extract` for those variables
- [ ] Condition nodes have two outgoing edges labeled yes/no
- [ ] Retry loops eventually update the condition input
- [ ] Every path ends at `end`, `end_call`, or a conversation node
- [ ] Action params use `{{variable}}` names that match extracted variables
- [ ] Integration is active and has an API key configured
