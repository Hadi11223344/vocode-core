# FastAPI + WebSocket Architecture — Reference Guide

How the VOIA backend is structured, how requests are authenticated, how async database sessions flow through routes, and how the Flow Playground WebSocket streams execution events to the frontend.

---

## 1. Application Bootstrap (`voice_platform/main.py`)

### 1.1 FastAPI factory

```python
app = FastAPI(
    title="VOIA Voice Platform",
    version="1.0.0",
    lifespan=lifespan,
)
```

The app uses the modern `lifespan` pattern instead of deprecated `@app.on_event`.

### 1.2 Lifespan startup sequence

1. **Database initialization** — `await init_db()`
2. **NLTK setup** — downloads `punkt` / `punkt_tab` for TTS sentence splitting
3. **Security checks** — warns on wildcard CORS, blocks startup if `JWT_SECRET` is weak in production
4. **Base URL resolution** — `settings.base_url`, falls back to ngrok if configured
5. **Events manager** — `PersistentEventsManager` stored in `app.state.events_manager`
6. **Telephony server** — if Twilio credentials are set, creates `TelephonyServer` with Redis config manager
7. **TTS warm-up** — pre-caches Deepgram TTS filler phrases and the agent's initial greeting
8. **Scheduled call scheduler** — background loop every 30 seconds

### 1.3 Lifespan shutdown sequence

1. Cancel scheduled-call scheduler
2. Cancel TTS warm-up task
3. 10-second grace period for active calls
4. Close all tracked WebSocket connections (`ws_tracker.close_all()`)
5. Cancel and await events manager task so pending DB writes finish

### 1.4 Middleware stack

Applied in order:

| Middleware | Purpose |
|------------|---------|
| `SlowAPIMiddleware` | Rate limiting per IP |
| `BodySizeLimitMiddleware` | Reject bodies > 10 MB |
| `SecurityHeadersMiddleware` | Browser security headers |
| `RequestLoggingMiddleware` | Log every request with method, path, status, duration, request ID |
| `CORSMiddleware` | Cross-origin access |

### 1.5 Router registration

All routers are mounted directly (no shared `/api` prefix in main.py; routes define their own prefixes):

```python
app.include_router(auth_router)
app.include_router(agent_router)
app.include_router(call_router)
...
app.include_router(playground_router)
```

---

## 2. Database Sessions (`voice_platform/database.py`)

### 2.1 Engine configuration

```python
engine = create_async_engine(DATABASE_URL, ...)
async_session = async_sessionmaker(engine, expire_on_commit=False)
```

- Supports SQLite (`sqlite+aiosqlite`) and PostgreSQL (`postgresql+asyncpg`)
- For SQLite, foreign keys are explicitly enabled via `PRAGMA foreign_keys=ON`
- PostgreSQL uses `pool_size=20`, `max_overflow=40`, `pool_recycle=3600`, `pool_pre_ping=True`

### 2.2 Per-request dependency

```python
async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
```

Usage:

```python
@router.get("/agents")
async def list_agents(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent).where(Agent.user_id == user.id))
    return result.scalars().all()
```

The session is automatically closed after the request, even on exception.

### 2.3 Inline sessions for background work

For WebSocket handlers or background tasks that outlive a single HTTP request, create an explicit session:

```python
async with async_session() as db:
    agent = await _fetch_agent_for_user(db, agent_id, user_id)
```

Always close or let the context manager close the session when the work finishes.

---

## 3. Authentication (`voice_platform/middleware/auth_middleware.py`)

### 3.1 HTTP authentication

`get_current_user` is a FastAPI dependency:

1. Extracts `Authorization: Bearer <token>`
2. Decodes and validates the JWT via `decode_access_token(token)`
3. Looks up the user by ID from the token's `sub` claim
4. Raises `401` on any failure

Usage:

```python
@router.get("/protected")
async def protected_route(user: User = Depends(get_current_user)):
    return {"message": f"Hello {user.name}"}
```

`require_admin` chains `get_current_user` and checks `user.role == "admin"`.

### 3.2 WebSocket authentication

`get_current_user_ws` supports three token transports (in order of preference):

1. `Authorization: Bearer <token>` header
2. `Sec-WebSocket-Protocol: bearer,<token>` subprotocol
3. Query parameter `?token=<token>` (only if `ALLOW_WS_QUERY_TOKEN_AUTH=true`)

```python
@router.websocket("/ws/{agent_id}/flow")
async def playground_flow_ws(websocket: WebSocket, agent_id: int):
    try:
        user = await get_current_user_ws(websocket)
    except Exception:
        await websocket.close(code=4001, reason="Unauthorized")
        return
```

WebSocket auth failures close the connection with code `4001`.

---

## 4. Error Handling (`voice_platform/errors.py` + `main.py`)

### 4.1 Structured error convention

All application errors extend `AppError` and include:

- `code` — machine-readable (`ErrorCode` enum)
- `message` — human-readable
- `status_code` — HTTP status
- `detail` — safe extra context
- `suggestion` — actionable advice

Example:

```python
raise AgentNotFoundError(
    agent_id,
    suggestion="Check the agent ID or create a new agent."
)
```

### 4.2 Global exception handlers

| Handler | Catches | Response |
|---------|---------|----------|
| `app_error_handler` | `AppError` | `{"error": exc.to_dict()}` |
| `validation_exception_handler` | `RequestValidationError` | Field-level detail + suggestion |
| `global_exception_handler` | Generic `Exception` | Redacted safe message + `INTERNAL_ERROR` |

The global handler specifically redacts:

- Twilio account SIDs / keys
- API keys (`sk-...`, 32+ hex strings)
- Bearer tokens
- Email addresses
- Phone numbers

---

## 5. WebSocket Lifecycle — Flow Playground

### 5.1 Endpoint

```python
@router.websocket("/ws/{agent_id}/flow")
async def playground_flow_ws(websocket: WebSocket, agent_id: int):
```

Route is in `voice_platform/api/playground_routes.py`.

### 5.2 Connection setup

1. Authenticate user (`get_current_user_ws`)
2. Enforce concurrent connection limit (`ws_tracker.can_connect(user_id)`)
3. Accept with `bearer` subprotocol if client offered it
4. Track connection in `ws_tracker`
5. Load agent and validate:
   - Agent exists and belongs to user
   - Agent is active
   - `agent.mode == "conversational_flow"`
   - Graph exists and has nodes
6. Build `FlowPlaygroundConversation` and `PlaygroundConversation`
7. Send `agent_info` event

### 5.3 Client → Server messages

| Type | Purpose |
|------|---------|
| `start` | Begin flow execution |
| `message` | Send caller/user text; auto-starts flow if not already started |
| `set_context` | Inject mock variables into `flow_conv.context` |
| `reset` | Reset the conversation and re-build the playground conv |
| `ping` | Keep-alive |

### 5.4 Server → Client events

| Type | Payload | Frontend handler |
|------|---------|------------------|
| `agent_info` | name, model, provider, mode | — |
| `flow_start` | graph | `started=true`, `flowStartTime` |
| `node_start` | node_id, node_type, label | `activeNodeId` |
| `node_result` | status, result, duration_ms, error | `completedNodes`, `failedNodes` |
| `edge_traversed` | source, target, label | `traversedEdges` |
| `agent_token` | text | accumulated in `pendingTokensRef` |
| `agent_response` | text | `agentResponses`, `onAgentResponse` callback |
| `condition_branch` | condition_met | trace event |
| `variables_extracted` | variables | trace event |
| `context_updated` | context | trace event |
| `flow_end` | total_nodes | `onFlowEnd` callback |
| `error` | text, fatal? | `error` state, `onError` callback |
| `pong` | — | — |

### 5.5 Event callback bridge

Inside the WebSocket handler:

```python
async def event_callback(event: dict):
    if "event" in event and "type" not in event:
        event["type"] = event.pop("event")
    await websocket.send_json(event)
```

The backend uses the internal key `"event"`; the frontend expects `"type"`. The bridge renames it.

### 5.6 Disconnect and cleanup

- `WebSocketDisconnect` is silently ignored
- Other exceptions are logged
- `finally` block closes the conversation session and removes the connection from `ws_tracker`

---

## 6. WebSocket Connection Tracker (`voice_platform/middleware/ws_tracker.py`)

A singleton tracks active WebSocket connections per user.

```python
ws_tracker = WebSocketTracker()
```

Features:

- Max 5 concurrent connections per user (`MAX_CONNECTIONS_PER_USER`)
- `add`, `remove`, `can_connect`, `get_user_count`, `get_total_count`
- `close_all(reason="Server shutting down")` used during graceful shutdown

Used by:

- Flow playground WebSocket
- Production voice WebSocket
- Shutdown cleanup in `main.py`

---

## 7. Frontend Hook (`frontend/src/hooks/use-flow-playground.ts`)

### 7.1 Connection setup

```typescript
const ws = new WebSocket(
  `${wsUrl}/api/playground/ws/${agentId}/flow`,
  ['bearer', token]
);
```

- Builds WS URL from `NEXT_PUBLIC_API_URL`
- Sends token via WebSocket subprotocol
- 30-second heartbeat ping interval
- Exponential backoff auto-reconnect (max 5 attempts, capped at 16s)

### 7.2 State management

The hook uses `useState` for:

- `connected`, `connecting`, `started`
- `activeNodeId`
- `completedNodes: Map<string, FlowNodeEvent>`
- `failedNodes: Set<string>`
- `traversedEdges: FlowEdgeEvent[]`
- `traceEvents: TraceEvent[]`
- `agentResponses`
- `error`, `flowStartTime`

### 7.3 Event handling

`handleEvent` switches on `data.type` and updates state:

- `node_start` → set `activeNodeId`
- `node_result` → add to completed/failed maps, clear active
- `edge_traversed` → append to traversed list
- `agent_token` → accumulate text
- `agent_response` → flush accumulated tokens, call `onAgentResponse`
- `flow_end` → clear active, call `onFlowEnd`
- `error` → set `error`, mark fatal if `data.fatal`

---

## 8. HTTP API Patterns

### 8.1 Typical route shape

```python
@router.get("/{agent_id}")
async def get_agent(
    agent_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id)
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise AgentNotFoundError(agent_id)
    return agent.to_dict()
```

### 8.2 Validation

Routes use Pydantic models for request bodies. The global `RequestValidationError` handler converts Pydantic errors into field-level messages.

### 8.3 Common response conventions

- Single resource: `agent.to_dict()`
- List: list of dicts
- Action result: `{ "success": bool, ... }` for integrations/actions
- Workflow execution: `{ "workflow": name, "mode": ..., "steps_executed": N, "results": [...] }`

---

## 9. Security & Deployment Considerations

### 9.1 CORS

```python
_cors_origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
if "*" in _cors_origins and not settings.allow_dev_login:
    logger.critical("SEC-03: CORS wildcard '*' is forbidden in production.")
    _cors_origins = []
```

Wildcard CORS disables `allow_credentials` per the CORS spec.

### 9.2 Rate limiting

SlowAPI `limiter` is attached to `app.state.limiter`. Per-route limits use:

```python
@limiter.limit("10/minute")
```

### 9.3 Body size

`BodySizeLimitMiddleware` rejects bodies > 10 MB.

### 9.4 JWT secret

Startup blocks if `JWT_SECRET` matches known weak defaults and `allow_dev_login` is false.

---

## 10. Common Errors & Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `4001 Unauthorized` on WebSocket | Token missing/invalid/subprotocol not sent | Ensure `getToken()` returns valid JWT; verify subprotocol negotiation |
| `1013 Too many connections` | Same user has > 5 open tabs/connections | Close stale tabs or increase `MAX_CONNECTIONS_PER_USER` |
| WebSocket disconnects after idle | Proxy timeout or missing heartbeat | Frontend pings every 30s; check reverse proxy idle timeout |
| `CORS error` in browser | Origin not in `CORS_ALLOWED_ORIGINS` or wildcard with credentials | Set exact origins in `.env`; wildcard disables credentials |
| `Invalid or expired token` | JWT expired or wrong secret | Re-login; verify `JWT_SECRET` matches auth service |
| `Database error occurred` | SQLite locked or async session misused | Use async drivers (`aiosqlite`/`asyncpg`); don't call sync DB from async |
| Frontend sees bare `500` | Exception leaked past handlers | Check logs; ensure custom exception inherits `AppError` or is caught |
| Events stop streaming mid-flow | `event_callback` swallowed exception | Add try/except around `websocket.send_json` and log failures |

---

## 11. Best Practices

### 11.1 Writing routes

- Accept `user: User = Depends(get_current_user)` and `db: AsyncSession = Depends(get_db)`
- Scope queries by `user.id` (and `team_id` where applicable)
- Raise `AppError` subclasses for expected failure modes
- Let the global handlers turn exceptions into structured responses

### 11.2 WebSocket handlers

- Authenticate first, then `await websocket.accept()`
- Check `ws_tracker.can_connect(user_id)` before accepting
- Wrap the receive loop in `try/finally` to always remove from `ws_tracker`
- Keep handler thin; delegate business logic to service classes
- Don't let `event_callback` exceptions silently break streaming

### 11.3 Database sessions

- Prefer `Depends(get_db)` for HTTP routes
- Use explicit `async with async_session()` for long-lived work (WebSockets, background tasks)
- Avoid passing ORM objects across async boundaries after session closes

### 11.4 Testing

- Use `TestClient` for HTTP routes
- For WebSocket tests, use `client.websocket_connect(...)` with headers/subprotocols
- Override `get_db` dependency with an in-memory SQLite session for isolated tests

---

## 12. Code Reference

### 12.1 Key files

| File | Responsibility |
|------|----------------|
| `voice_platform/main.py` | FastAPI factory, lifespan, middleware, routers |
| `voice_platform/database.py` | Async engine, session factory, ORM models |
| `voice_platform/middleware/auth_middleware.py` | `get_current_user`, `get_current_user_ws` |
| `voice_platform/middleware/ws_tracker.py` | Per-user WebSocket connection tracking |
| `voice_platform/middleware/security_headers.py` | Security headers middleware |
| `voice_platform/middleware/request_logging.py` | Request logging middleware |
| `voice_platform/middleware/body_size_limit.py` | Body size limit middleware |
| `voice_platform/errors.py` | `AppError`, concrete errors, `ErrorCode` enum |
| `voice_platform/api/playground_routes.py` | Flow playground WebSocket |
| `frontend/src/hooks/use-flow-playground.ts` | Frontend WebSocket client and state |

### 12.2 Important method signatures

```python
# main.py
@asynccontextmanager
async def lifespan(application: FastAPI): ...
app = FastAPI(title="...", lifespan=lifespan)

# database.py
async def get_db() -> AsyncSession: ...

# auth_middleware.py
async def get_current_user(credentials, db) -> User: ...
async def get_current_user_ws(websocket: WebSocket) -> User: ...

# ws_tracker.py
class WebSocketTracker:
    def can_connect(self, user_id: int) -> bool: ...
    async def add(self, user_id: int, websocket: WebSocket) -> None: ...
    async def remove(self, user_id: int, websocket: WebSocket) -> None: ...
    async def close_all(self, reason: str = "...") -> None: ...

# playground_routes.py
@router.websocket("/ws/{agent_id}/flow")
async def playground_flow_ws(websocket: WebSocket, agent_id: int): ...
```

---

## 13. Quick Checklist for Adding a WebSocket Feature

- [ ] Define route and required auth
- [ ] Check `ws_tracker.can_connect(user_id)` before accepting
- [ ] Accept `bearer` subprotocol if frontend uses token-based auth
- [ ] Handle client message types in a receive loop
- [ ] Send structured events; use `event`→`type` rename if needed
- [ ] Cleanup in `finally` (close sessions, remove from tracker)
- [ ] Add frontend message/event handling in the corresponding hook
- [ ] Test with `TestClient.websocket_connect` and valid auth header/subprotocol
