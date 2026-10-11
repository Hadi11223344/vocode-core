# Backend Workflow Executor Engine — Reference Guide

Deep-dive into `voice_platform.integrations.executor.WorkflowExecutor`: how it runs graphs, resolves templates, dispatches actions, handles errors, and is invoked from live calls.

---

## 1. WorkflowExecutor Overview

`WorkflowExecutor` is the core runtime for all workflow execution in the platform. It is used by:

- `voice_platform/api/workflow_routes.py` — manual `/api/workflows/{id}/execute`
- `voice_platform/api/review_routes.py` — approved review-queue execution
- `voice_platform/events/call_events.py` — auto-execution during live calls
- `voice_platform/api/playground_routes.py` — Flow Playground

### 1.1 Initialization

```python
from voice_platform.integrations.executor import WorkflowExecutor

executor = WorkflowExecutor(
    session: AsyncSession,
    user_id: int,
    agent_id: Optional[int] = None,
    agent_timezone: Optional[str] = None,
)
```

- `session` — async SQLAlchemy DB session for loading integrations, API keys, subagents
- `user_id` — tenant boundary for all DB lookups
- `agent_id` — passed through to OAuth credential resolution and subagent lookups
- `agent_timezone` — injected into Google Calendar and other time-aware integrations

### 1.2 Main entry points

| Method | Use case |
|--------|----------|
| `execute_workflow(steps=..., graph=..., context=...)` | Router: graph-first, falls back to legacy step list |
| `execute_graph(graph, context, *, max_steps=50, max_visits_per_node=3, transition_flexibility="strict", event_callback=None)` | Run a React Flow graph deterministically |
| `execute_steps(steps, context)` | Run legacy linear step list |
| `execute_single_step(step, context)` | In-call function calling / tool use (raises on failure) |

---

## 2. Graph Execution (`execute_graph`)

### 2.1 Expected graph format

```json
{
  "nodes": [...],
  "edges": [...]
}
```

Each node must have `id` and `data`. Edges must have `id`, `source`, `target`.

### 2.2 Start-node discovery

1. If any node has `data.nodeType == "trigger"`, those are the start nodes
2. Otherwise, nodes with zero incoming edges are starts
3. If neither exists, the graph errors with `"Graph has no start node"`

Start nodes are sorted top-to-bottom, then left-to-right (`y`, `x`, `id`), which mirrors how the frontend typically lays out flows.

### 2.3 Pre-execution cycle detection

```python
cycle = self._detect_cycles(nodes_by_id, outgoing)
if cycle:
    return [{
        "status": "error",
        "error": "Graph contains a cycle: ...",
        "suggestion": "Remove the loop or add a condition node to break the cycle.",
    }]
```

Unlike the Flow Playground, the backend **blocks** cycles before running. This protects live calls from accidental infinite loops.

### 2.4 Run loop

- Pop node from queue
- Increment per-node visit count; skip if `> max_visits_per_node` (default 3)
- Execute via `_execute_graph_node`
- If result is `blocking` (conversation node), break and return
- Store `node_{id}_result` in context
- For non-condition nodes, update `context["last_result"]` and `context["result"]`
- For condition nodes, select matching edges via `_select_condition_edges`
- If `transition_flexibility="flex"` and multiple edges exist, ask the LLM to pick one
- Append targets to queue
- Stop if `max_steps` (50) is exceeded

### 2.5 Execution results

Returns a list of node result dicts:

```python
[
  {
    "node_id": "node-1",
    "node_type": "google_calendar",
    "status": "success",
    "result": {...},
    "duration_ms": 123.4,
  },
  ...
]
```

---

## 3. Node Dispatch (`_execute_graph_node`)

This method is the single dispatcher for every node in a graph. It resolves params, identifies the service type/integration, and executes the correct handler.

### 3.1 Parameter resolution

```python
config = data.get("config") or {}
params_from_data = data.get("params") or {}
params = {**config, **params_from_data}   # explicit params win
action = data.get("action") or config.get("action") or node_type
```

- `config` holds the node-specific configuration (prompt, expression, API params)
- `params` can override config; also used for template-imported nodes
- `action` defaults to the node type if not specified

### 3.2 Integration identification

The executor tries to find an integration in this order:

1. `integrationId` / `integration_id` on node data or config
2. `node_type` matching a known service type (e.g., `google_calendar`)
3. `node_type == "action"` with `config.integration_type` set
4. Direct execution fallback (no integration DB row needed)

### 3.3 Handler dispatch

```python
if node_type == "mcp_tool":       → _execute_mcp_tool_node
if node_type == "custom_api":     → _execute_custom_api_node
if node_type == "note":           → context["_last_note"] = resolved content
if node_type == "code":           → _execute_sandboxed_code
if node_type == "subagent":       → lookup subagent, return delegation stub
if node_type == "extract_variable": → _llm_extract
if integration_id:                 → execute_single_step
if service_type:                    → load integration by service type → _execute_action
otherwise:                          → execute_direct_action
```

### 3.4 Status values

| Status | Meaning |
|--------|---------|
| `success` | Node executed; result stored in context |
| `error` | Node failed; message in `error` field; path continues in graph mode unless caller stops |
| `blocking` | Conversation node reached; graph should pause |
| `skipped` | Visit limit exceeded or node missing |

---

## 4. Legacy Step Execution (`execute_steps`)

Used by old-style workflows stored as `steps_json` and by `execute_single_step`.

### 4.1 Step schema

```python
{
    "step_number": 1,
    "integration_id": 42,
    "action": "create_event",
    "params": {"summary": "{{caller_name}}", "date": "{{preferred_date}}"},
    "type": "google_calendar",
}
```

### 4.2 Steps vs graphs

- Steps are sequential
- No branching, conditions, or cycles
- Results stored as `step_{N}_result`
- Graphs are preferred for new flows

---

## 5. Template Resolution (`_resolve_templates`)

### 5.1 Default template variables

| Variable | Value |
|----------|-------|
| `{{now}}` | Current UTC ISO datetime |
| `{{call_date}}` | Today's date `YYYY-MM-DD` |
| `{{call_time}}` | Current time `HH:MM` |
| `{{next_business_day}}` | Next weekday date |

### 5.2 Context variables

Any key in `context` is resolvable, including dotted paths:

```json
{
  "date": "{{preferred_date}}",
  "start": "{{result.available_slots.0}}",
  "summary": "{{caller_name}} - appointment"
}
```

### 5.3 Whole-value vs inline templates

If a value is exactly `{{var}}`, the resolved value keeps its original type (int, list, dict). If the template appears inline inside a string, it is stringified.

### 5.4 Nested resolution

The resolver does up to 5 passes, so a context value that itself contains `{{...}}` will be recursively resolved.

### 5.5 Missing variables

If a template cannot be resolved, the literal `{{var}}` remains in the value. This is a common source of downstream integration errors (e.g., Google Calendar receives `"{{preferred_date}}"` instead of a real date).

---

## 6. Condition Evaluation (`_evaluate_condition`)

### 6.1 Supported expressions

| Expression | Evaluates |
|------------|-----------|
| `result.available_slots not_empty` | truthy / non-empty list |
| `preferred_date not_empty` | truthy / non-empty string |
| `result.success == true` | boolean equality |
| `caller_type == new_patient` | string equality (unquoted right side becomes literal) |
| `score >= 0.8` | numeric comparison |
| `tags contains vip` | substring or list membership |
| `result.error != null` | inequality |

### 6.2 Dotted path resolution

```python
"result.available_slots" → context["result"]["available_slots"]
"node_node-1_result.success" → context["node_node-1_result"]["success"]
```

If a path segment is missing, the left operand becomes `None` and the condition returns `False`.

### 6.3 Edge selection

After evaluation, `_select_condition_edges` checks each outgoing edge:

- `sourceHandle` or `label` in `{"yes","true"}` if condition met
- `sourceHandle` or `label` in `{"no","false"}` otherwise
- If no match, returns `[]` and the branch halts

---

## 7. Action Dispatch (`_execute_action`)

### 7.1 Service routing

```python
if service_type == "google_calendar":    → _execute_calendar_action
elif service_type == "google_sheets":      → _execute_sheets_action
elif service_type == "sms":                → _execute_sms_action
elif service_type == "email":              → _execute_email_action
elif service_type == "knowledge_base":     → _execute_kb_action
elif service_type == "cal_com":            → _execute_calcom_action
elif service_type == "calendly":           → _execute_calendly_action
elif service_type in crm_set:              → _execute_crm_action
elif service_type == "stripe":             → _execute_stripe_action
elif service_type == "shopify":            → _execute_shopify_action
elif service_type in support_set:          → _execute_support_action
elif service_type in productivity_set:       → _execute_productivity_action
elif service_type in project_set:          → _execute_project_action
elif service_type == "google_drive_mcp":   → _execute_drive_action
elif service_type == "whatsapp_cloud":     → _execute_whatsapp_action
elif service_type == "telegram_bot":       → _execute_telegram_action
elif service_type in webhook_set:          → _execute_webhook_action
```

### 7.2 Credential loading

For each integration:

1. Load `Integration` row by ID or service type, verifying `user_id` and `is_active`
2. Load decrypted `api_key` and `api_secret` from `user_api_keys`
3. Fall back to integration `config_json` for legacy keys
4. Inject `webhook_url` from secret for webhook-style integrations

### 7.3 Parameter unwrapping

Graph nodes often wrap action params inside `config.params`. The executor unwraps them:

```python
action_params = resolved_params.get("params")
if not isinstance(action_params, dict):
    action_params = resolved_params
```

---

## 8. Direct Actions (`execute_direct_action`)

No integration DB row is required for these node types:

| Node type | Behavior |
|-----------|----------|
| `trigger` / `end` / `end_call` / `voicemail_detect` | No-op control node |
| `conversation` | Returns `status: "blocking"`, prompt from config |
| `webhook` / `api_request` | Calls `WebhookClient.request` |
| `delay` | `asyncio.sleep(min(delay_seconds, 300))` |
| `condition` | Evaluates `expression` via `_evaluate_condition` |
| `llm_process` | Returns note; handled by conversation pipeline |
| `notification` | Logs message |
| `transfer_call` | Returns `transfer_to`, `transfer_type`, `summary` |
| `send_sms` | Uses platform Twilio credentials if configured |
| `send_email` | Uses platform SMTP settings if configured |

---

## 9. Phase 3 Node Types

### 9.1 `note`

Resolves templates in `config.content` and stores it in `context["_last_note"]`. Useful for injecting static instructions into the LLM context without calling an integration.

### 9.2 `code`

Runs Python in a restricted sandbox.

Allowed globals: `abs`, `all`, `any`, `bool`, `dict`, `float`, `int`, `len`, `list`, `max`, `min`, `range`, `round`, `set`, `str`, `sum`, `tuple`, `type`, `zip`, plus `math`, `re`, `json`, `datetime`, `random`.

Blocked AST nodes: `Import`, `ImportFrom`, `With`, `AsyncWith`, `Try`, `ExceptHandler`, `Raise`, `Delete`, `Global`, `Nonlocal`, `ClassDef`, `Attribute`.

Blocked calls: `open`, `exec`, `eval`, `compile`, `__import__`, `input`, `print`, `exit`, `quit`.

If the code defines a `main(context)` function, it is called with the execution context; otherwise the value of the `result` local is returned.

### 9.3 `extract_variable`

Runs `_llm_extract(transcript, prompt, variable_name)`. If extraction succeeds, stores the value in context and returns it. If `required: true` and extraction fails, returns an error.

### 9.4 `subagent`

Looks up another agent by ID or name and returns a simulated delegation result. Not yet wired to a real sub-call.

### 9.5 `mcp_tool`

Calls an MCP server via `McpClient`.

Config fields:

- `server_url` — MCP server endpoint
- `auth_token` — optional bearer token
- `tool_name` — tool to call
- `parameters` — JSON object passed to the tool

Special handling: if the host is a Google MCP endpoint (`drivemcp.googleapis.com`, `calendarmcp.googleapis.com`, `gmailmcp.googleapis.com`, `peoplemcp.googleapis.com`), the executor auto-resolves an OAuth token for the user via `GoogleOAuthManager`.

The result is stored in `context["last_result"]`.

### 9.6 `custom_api`

Makes an HTTP request through `WebhookClient`.

Config fields:

- `url`, `method`, `headers`, `body`
- `api_key_id` — optional; loads key and sends as `Authorization: Bearer {key}`
- `response_mappings` — JSONPath-like dict mapping response fields to context keys

Response data is extracted and merged into `context` so downstream nodes can use it.

---

## 10. Integration Client Catalog

### 10.1 Google Calendar (`voice_platform/integrations/google_calendar.py`)

Authentication: OAuth (preferred) or service account JSON.

Actions:

| Action | Required params | Notes |
|--------|-----------------|-------|
| `create_event` | `summary`, `start`/`date`+`time` | Builds ISO datetime in agent timezone |
| `list_events` | `max_results` | Optional `time_min` |
| `update_event` | `event_id` | Optional fields merged |
| `delete_event` | `event_id` | |
| `check_availability` | `date` | Returns `available_slots`, `busy_slots` |
| `book_appointment` | `date`, `time` | Composite: check + create |

Common errors:

- `"Google Calendar not connected..."` — no OAuth token or service account JSON
- `"create_event is missing a valid datetime"` — `date`/`time` templates unresolved
- `"Time conflict"` — slot is busy

Result keys:

```python
{
  "success": True,
  "event_id": "...",
  "link": "...",
  "summary": "...",
  "start": "...",
  "end": "...",
}
```

### 10.2 Google Sheets (`voice_platform/integrations/google_sheets.py`)

Actions: `append_row`, `read_rows`, `update_cell`, etc. (see client implementation). Requires same OAuth/service-account auth as Calendar.

### 10.3 SMS (`voice_platform/integrations/sms_client.py`)

Uses platform Twilio credentials (`settings.twilio_*`) for direct `send_sms`, or an integration-specific Twilio config.

Required params: `to`, `body`.

### 10.4 Email (`voice_platform/integrations/email_client.py`)

Uses platform SMTP settings. Required: `to`, `subject`, `body`. Optional: `html_body`, `cc`, `attachments`.

### 10.5 Knowledge Base (`voice_platform/integrations/knowledge_base.py`)

Performs RAG against stored knowledge base documents. Returns `matches` / `answer`.

### 10.6 Cal.com (`voice_platform/integrations/cal_com`)

Booking integration. Actions: `check_availability`, `create_booking`. Uses Cal.com API key.

### 10.7 Calendly

Booking integration. Similar pattern.

### 10.8 CRMs: Salesforce, Pipedrive, GoHighLevel, HubSpot

Handled by `_execute_crm_action`. Each wraps its respective client. Typical actions: create/update lead or contact.

### 10.9 Support: Zendesk, Freshdesk, Intercom

`_execute_support_action` creates/updates tickets or conversations.

### 10.10 Productivity: Notion, Airtable

`_execute_productivity_action` creates pages/records.

### 10.11 Project management: Jira, Linear

`_execute_project_action` creates issues.

### 10.12 Stripe

`_execute_stripe_action` — usually payment intents, invoices, or customer lookup.

### 10.13 Shopify

`_execute_shopify_action` — orders, products, customers.

### 10.14 WhatsApp Cloud (`voice_platform/integrations/whatsapp_client.py`)

Actions: `send_message`, `send_template`. Requires `phone_number_id`, `access_token`.

### 10.15 Telegram (`voice_platform/integrations/telegram_client.py`)

Sends messages via bot token.

### 10.16 Webhook / Zapier / Slack / Make / Discord / Microsoft Teams

All routed to `_execute_webhook_action` → `WebhookClient`.

Config: `webhook_url` (loaded from `api_secret`), optional `headers`, `body`/`payload`.

Result shape:

```python
{
  "success": True/False,
  "status_code": 200,
  "body": {...},
  "headers": {...},
}
```

### 10.17 Google Drive MCP (`voice_platform/integrations/google_drive_client.py`)

Routed via `_execute_drive_action`. Uses OAuth token. Actions depend on the Drive client.

---

## 11. Live Call Execution (`voice_platform/events/call_events.py`)

### 11.1 Trigger matching

After a call transcript update:

1. Load all active workflows for the agent
2. Parse `trigger_phrases` for each workflow
3. If transcript matches a trigger, the workflow is a candidate

### 11.2 Requires approval

If `workflow.requires_approval` is true, a `ReviewQueue` row is created with `action_type="workflow_execution"`. The workflow does not run until a human approves it via `/api/reviews/{id}/approve`.

### 11.3 Immediate execution

Otherwise:

```python
context = {
    "caller_name": caller_name,
    "caller_phone": call_log.from_phone or "unknown",
    "transcript": transcript_text[:2000],
}
execution = await executor.execute_workflow(
    steps=steps,
    graph=graph,
    context=context,
)
```

Results are logged to `ActionLog`.

### 11.4 Differences from playground

- No conversation-node pausing in live calls (the graph runs to completion or error)
- Cycles are blocked before execution
- Context is much smaller (no conversation history injection)
- Results are written to `ActionLog`, not streamed over WebSocket

---

## 12. Error Handling & Debugging

### 12.1 Result shape convention

Integration handlers should return:

```python
{
  "success": True/False,
  "error": "human-readable message",
  "details": {...},
  # plus action-specific keys
}
```

This lets condition nodes and the LLM inspect `result.success` and `result.error`.

### 12.2 Common failure patterns

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `"Integration X not found"` | No active integration for the user's account | Connect the integration in Settings |
| `"URL blocked by security policy"` | Webhook points to localhost/private IP | Use a public URL |
| `"missing a valid datetime"` | Template variable unresolved | Add extraction or default value |
| `"Condition evaluated to NO"` | Expression references missing key | Check dotted path and result shape |
| `"visit_limit_exceeded"` | Infinite loop in graph | Add a condition that can break the cycle |
| `"Graph contains a cycle"` | Unconditional back-edge | Add a condition node or remove the edge |

### 12.3 Logging

The executor logs via `loguru`. Key log lines:

- `Executing workflow step N: {action}`
- `Graph execution paused at conversation node ...`
- `Workflow '{name}' auto-executed ({mode}): N steps completed`
- `Condition '{expression}' → {result}`

Enable debug logging to see resolved params and raw integration responses.

---

## 13. Best Practices

### 13.1 Designing graphs

- Always have a trigger node or a zero-incoming start node
- Avoid unconditional cycles in backend graphs
- Use `condition` nodes to gate loops
- End every branch with `end`, `end_call`, or a conversation node

### 13.2 Integration actions

- Return structured results with `success` and `error` keys
- For list checks, always include the key (e.g., `available_slots: []`) even on failure
- Validate required params early and return clear error messages
- Don't log secrets

### 13.3 Templates

- Use exact variable names already present in context
- Prefer `result.<field>` over bare variable names for action outputs
- Test unresolved-template cases explicitly

### 13.4 Testing workflows

1. Use the Flow Playground for iterative graph testing
2. Run `/api/workflows/{id}/execute` with sample context for backend validation
3. Check `ActionLog` after live calls for actual execution traces
4. Use `transition_flexibility="flex"` only when branching intent is ambiguous

---

## 14. Code Reference

### 14.1 Key files

| File | Responsibility |
|------|----------------|
| `voice_platform/integrations/executor.py` | `WorkflowExecutor`, all dispatch logic |
| `voice_platform/integrations/google_calendar.py` | Google Calendar client |
| `voice_platform/integrations/google_sheets.py` | Google Sheets client |
| `voice_platform/integrations/webhook_client.py` | Generic HTTP / webhook / custom API |
| `voice_platform/integrations/mcp_client.py` | MCP server calls |
| `voice_platform/integrations/sms_client.py` | Twilio SMS |
| `voice_platform/integrations/email_client.py` | SMTP email |
| `voice_platform/events/call_events.py` | Live-call workflow triggering |
| `voice_platform/api/workflow_routes.py` | Manual execution endpoint |
| `voice_platform/api/review_routes.py` | Approval-queue execution |

### 14.2 Important method signatures

```python
class WorkflowExecutor:
    async def execute_workflow(self, *, steps=None, graph=None, context=None, transition_flexibility="strict")
    async def execute_graph(self, graph, context=None, *, max_steps=50, max_visits_per_node=3, transition_flexibility="strict", event_callback=None)
    async def execute_steps(self, steps, context=None)
    async def execute_single_step(self, step, context=None)
    async def _execute_graph_node(self, node, context, *, event_callback=None)
    async def _execute_action(self, service_type, action, params, api_key, config)
    async def execute_direct_action(self, node_type, action, params, context=None)
    @staticmethod
    def _evaluate_condition(expression, context)
    def _resolve_templates(self, params, context)
    async def _llm_extract(self, transcript, prompt, variable_name)
```

---

## 15. Quick Checklist for Adding or Fixing an Integration

- [ ] Add/update the integration client in `voice_platform/integrations/`
- [ ] Register the service type in `known_service_types` (`_execute_graph_node`)
- [ ] Add a route in `_execute_action`
- [ ] Ensure result dict includes `success` and `error` keys
- [ ] Handle missing credentials with a clear message
- [ ] Add frontend node config in `frontend/src/components/workflow/WorkflowNodes.tsx` if needed
- [ ] Write/update tests in `tests/voice_platform/test_workflow_executor.py`
