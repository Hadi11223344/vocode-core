# React Flow + LangGraph mapping for the playground

This document maps every LangGraph primitive used by the FLOW playground to the concrete code in `voice_platform/flow` and the frontend. It was produced while reading the official LangGraph docs end-to-end.

---

## 1. End-to-end data flow

```
React Flow canvas
      │ exports graph JSON {nodes, edges}
      ▼
voice_platform/flow/compiler.py
      │ builds a StateGraph(FlowState)
      ▼
voice_platform/flow/executor.py
      │ runs ainvoke() / Command(resume=...)
      ▼
voice_platform/api/playground_routes.py
      │ forwards events over WebSocket
      ▼
frontend/src/hooks/use-flow-playground.ts
      │ updates React state
      ▼
frontend/src/components/playground/FlowGraphCanvas.tsx
```

---

## 2. StateGraph and FlowState

**LangGraph docs:** a `StateGraph` is defined by a typed `State` schema. Each node returns a partial update that is merged into state.

**Our code:** `voice_platform/flow/state.py:13-49` defines `FlowState`:

```python
class FlowState(TypedDict):
    slots: dict[str, dict]
    extracted_vars: dict[str, Any]
    messages: Annotated[list, add_messages]   # reducer-backed channel
    current_node: str
    previous_node: str
    _condition_met: bool
    pending_variables_to_extract: list[str]
    retry_count: int
    transcript: str
    caller_name: str
    caller_phone: str
    user_id: int
    agent_id: int
    agent_timezone: str
    last_result: dict
    result: dict
    nodes_by_id: dict      # injected React Flow node definitions
    outgoing: dict         # injected adjacency list
    total_steps: int
```

Most keys use LangGraph’s **default reducer** (node update overwrites the previous value). `messages` uses `add_messages`, which appends new messages and deserializes dicts into LangChain `BaseMessage` objects.

---

## 3. Reducers and the `messages` channel

**LangGraph docs:** `add_messages` keeps message IDs, appends new messages, overwrites existing ones, and deserializes plain dicts into `HumanMessage` / `AIMessage` / `AIMessage` objects. After using `add_messages`, code should access messages with dot notation (`state["messages"][-1].content`).

**Our code:** `voice_platform/flow/state.py:21-22`:

```python
# Conversation messages (LangGraph add_messages reducer)
messages: Annotated[list, add_messages]
```

Because conversation nodes return plain dicts like `{"role": "assistant", "content": "..."}` and `add_messages` turns them into objects on the next step, every reader of `state["messages"]` must handle both shapes. We added `_message_to_dict()` in `voice_platform/flow/nodes.py:22-42` to normalize them before reading `role` or `content`.

---

## 4. Nodes and the wrapper

**LangGraph docs:** nodes are Python callables that take the current state and return a partial state update.

**Our code:** `voice_platform/flow/compiler.py:129-170` registers nodes:

1. Maps React Flow `nodeType` to a handler (`conversation`, `condition`, `action`, `trigger`, `end`, etc.).
2. Wraps each handler in `make_wrapper()` to:
   - set `current_node` / `previous_node`
   - emit `edge_traversed` events before the handler runs
   - persist `current_node` in the returned state

This wrapper is why the frontend sees `trigger_1 → conversation_1` edges even when LangGraph re-executes the same node on resume.

---

## 5. Conditional edges

**LangGraph docs:** `add_conditional_edges(source, router, path_map)` calls `router(state)` and routes to the node named by the returned value. `path_map` maps return values to node names.

**Our code:** `voice_platform/flow/compiler.py:193-237` handles condition nodes:

- Scans outgoing edges for `sourceHandle` / `label` values `yes`, `true`, `no`, `false`.
- Builds `yes_targets`, `no_targets`, `other_targets`.
- Router returns the first matching target based on `state["_condition_met"]`.
- `path_map` is built as `{target: target}` for every target.

In your trace:

```
condition_1  Emergency?  condition_met: false  →  NO
```

The router returns the first edge labeled “no”, so LangGraph routes to `conversation_2`.

**Real branching:** action/conversation nodes with multiple labeled outgoing edges now also use `add_conditional_edges`. The compiler builds a `branch_label -> target` map from `sourceHandle`/`label` and routes via `result.branch` (`compiler.py:274-328`). If no `result.branch` matches, the primary (first) edge is used.

---

## 6. Conditional edges and branching summary

- `condition` nodes route by `_condition_met`.
- `conversation`/`action`/`trigger`/`delay`/`note` nodes with multiple labeled edges route by `result.branch`.
- Conversation slot-filling loops take precedence: if `_slots_missing` is set and retries remain, the node routes back to itself.

---

## 7. Checkpointer + thread_id

**LangGraph docs:** a checkpointer saves a thread’s state snapshots. `thread_id` is the pointer; resuming requires the same `thread_id`. `MemorySaver` is in-process RAM only; for production use `PostgresSaver` / `AsyncPostgresSaver`.

**Our code:** `voice_platform/flow/executor.py:48-59`:

```python
self._thread_id = str(uuid.uuid4())
self._config = {"configurable": {"thread_id": self._thread_id}}
self._checkpointer = MemorySaver()
```

The graph is compiled with the checkpointer in `executor.py:87-93`, and reset creates a fresh `thread_id` in `executor.py:218-219`.

**Gap:** `MemorySaver` loses all state when the Docker container restarts. For production deployments the checkpointer should be swapped for `AsyncPostgresSaver` using the existing Postgres service.

---

## 7. `interrupt()` and `Command(resume=...)`

**LangGraph docs:** `interrupt(payload)` pauses execution at the call site. The payload is returned to the caller as `__interrupt__` (for `invoke`) or `stream.interrupts` (for streaming). To resume, call the graph with `Command(resume=value)`. **Crucially, the interrupted node restarts from the beginning on resume**, so side effects before the interrupt must be idempotent.

**Our code:** `voice_platform/flow/nodes.py:344-350`:

```python
user_input = interrupt({
    "node_id": node_id,
    "agent_response": full_response,
    "pending_variables": pending_vars,
})
```

The executor starts the run in `executor.py:121-124`:

```python
result = await self._compiled_graph.ainvoke(
    self._state,
    config=self._config,
)
```

and resumes in `executor.py:167-170`:

```python
result = await self._compiled_graph.ainvoke(
    Command(resume=user_text),
    config=self._config,
)
```

**Why duplicate greetings happened:** `conversation_handler()` both generates the agent response **and** calls `interrupt()` in the same node. On resume, LangGraph re-runs the node from the top, so the LLM was called again. Phase 1 fixed this by caching the generated response keyed by `(node_id, total_steps)` in `nodes.py:238-323`.

---

## 8. Streaming / events

**LangGraph docs:** `graph.stream_events(..., version="v3")` exposes typed projections: `stream.messages`, `stream.values`, `stream.interrupts`, `stream.output`.

**Our code:** we do **not** use native LangGraph streaming. Instead, every handler receives an `event_callback` and emits custom events:

- `node_start`, `node_result`
- `agent_token`, `agent_response`
- `edge_traversed`
- `condition_branch`
- `flow_start`, `flow_end`
- `error`, `info`, `variables_extracted`

These are sent over the WebSocket in `playground_routes.py:2506-2514` and consumed by `use-flow-playground.ts:200-291`.

This is a custom event bridge, not native streaming. It works for the React Flow trace but prevents us from using `stream.interrupts` directly.

---

## 9. Mapping a sample trace

```
Warning: graph contains cycles at nodes: node-21.
Note: graph has conditional retry loops at nodes: node-19, node-20.
```
→ `executor.py:94-104` emits these before invoking the graph.

```
▶ Flow started
Call Received  trigger
Call Received  0.1ms
```
→ `flow_start` event, then `node_start`/`node_result` for the trigger control node.

```
Identify Need  conversation  4792.2ms
Agent: "SmileCare Dental Clinic..."
```
→ `conversation_handler()` streams tokens, emits `agent_response`, then `interrupt()` pauses.

After the user replies:

```
Identify Need  conversation  15506.7ms
```
→ `Command(resume=user_text)` causes LangGraph to re-execute the `Identify Need` node from the beginning. With the Phase 1 cache, this now reuses the previously generated response instead of calling the LLM again.

```
condition_1  Emergency?  condition_met: false  →  NO
conversation_2  Collect Patient Info
```
→ condition router returns the `no` edge; compiler added a direct edge to `conversation_2`.

---

## 10. Current alignment summary

| LangGraph primitive | How we use it | Gap / note |
| --- | --- | --- |
| `StateGraph` + `FlowState` | Fully typed state with injected graph metadata | Good |
| `add_messages` reducer | Used for `messages`; objects normalized with `_message_to_dict()` | Good after Phase 1 |
| `add_node` / handlers | Wrapped to emit edge events and set `current_node` | Good |
| `add_conditional_edges` | For `condition` nodes and now for action/conversation nodes with multiple labeled outgoing edges | Previously non-condition nodes took only the first edge |
| `checkpointer` + `thread_id` | `AsyncPostgresSaver` (Postgres) or `MemorySaver` (SQLite fallback) | `MemorySaver` was the only option before Phase 2B |
| `interrupt()` / `Command(resume=...)` | Conversation nodes pause/resume | Good with response cache |
| Native event streaming | Not used; custom `event_callback` bridge | Works, but limits native HITL features |

---

## 11. Completed Phase 2 items

- **Phase 2A — Slot-filling loops:** conversation nodes now extract variables after the caller replies and loop back to re-ask when required slots are missing.
- **Phase 2B — Durable checkpointer:** Postgres-backed `AsyncPostgresSaver` is used in production; `MemorySaver` remains the SQLite/development fallback.
- **Phase 2C — Real branching:** action/conversation nodes with multiple labeled outgoing edges route via `result.branch`, while condition nodes and slot loops remain unchanged.

## 12. Remaining recommendations

1. **Make action handlers set `result.branch` automatically.** Update the workflow/action executor so real actions (Google Calendar, Sheets, etc.) can return a branch key that drives the graph without requiring a separate condition node.
2. **Expose branch labels in the React Flow canvas UI** so designers know which edge label maps to which `result.branch` value.
3. **Evaluate native `astream_events`** as a replacement for the custom `event_callback` bridge once the frontend trace format is stable.
