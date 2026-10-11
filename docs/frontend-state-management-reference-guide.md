# Frontend + State Management — Reference Guide

Guide to the Next.js/React frontend: app structure, API client, auth, state patterns, the workflow builder, the flow playground UI, theming, and how backend events drive the interface.

---

## 1. Frontend Architecture Overview

### 1.1 Stack

- **Framework**: Next.js with App Router
- **Language**: TypeScript
- **Styling**: Tailwind CSS + custom CSS variables
- **State**: React Context for auth; local component state and custom hooks for domain state (no Zustand store in this codebase)
- **Flow canvas**: React Flow
- **Icons**: Lucide React

### 1.2 Directory layout

```
frontend/src/
  app/              # Next.js App Router pages and layouts
  components/       # React components organized by domain
  hooks/            # Custom React hooks
  lib/              # API client, contexts, types, utilities
```

Key groups:

- `app/dashboard/` — authenticated dashboard pages
- `app/login/` — login page
- `components/workflow/` — workflow builder and node UI
- `components/playground/` — flow playground canvas and chat
- `components/ui/` — shared UI primitives (toast, theme provider, error boundary)
- `components/landing/` — marketing page sections
- `hooks/use-flow-playground.ts` — WebSocket client and execution state
- `lib/api.ts` — HTTP API client
- `lib/auth-context.tsx` — authentication context

---

## 2. Layout & Providers

### 2.1 Root layout (`app/layout.tsx`)

```tsx
<body className="antialiased">
  <ThemeProvider>
    <AuthProvider>
      <ToastProvider>
        <ErrorBoundary>
          <CursorFollower />
          {children}
        </ErrorBoundary>
      </ToastProvider>
    </AuthProvider>
  </ThemeProvider>
</body>
```

Order matters for dependencies:

- `ThemeProvider` wraps everything so theme class is available
- `AuthProvider` provides `user`, `login`, `logout`
- `ToastProvider` allows any child to show toasts
- `ErrorBoundary` catches React render errors
- `CursorFollower` is a global visual effect

### 2.2 Theme system

Theme is resolved at runtime by an inline script in `<head>`:

```js
var t = localStorage.getItem('voia-theme');
if (!t) t = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
document.documentElement.classList.add(t);
```

`ThemeProvider` syncs this class and exposes a toggle. Dark mode is the default.

---

## 3. API Client Layer (`lib/api.ts`)

### 3.1 Token helpers

Tokens are stored in `localStorage`:

```ts
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3000';

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('voia_token');
}

export function setToken(token: string) { localStorage.setItem('voia_token', token); }
export function clearToken() { localStorage.removeItem('voia_token'); localStorage.removeItem('voia_refresh_token'); }
```

### 3.2 `apiFetch` wrapper

The core wrapper handles auth, refresh, redirects, and error enrichment:

```ts
async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let res = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (res.status === 401) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      headers['Authorization'] = `Bearer ${newToken}`;
      res = await fetch(`${API_URL}${path}`, { ...options, headers });
    }
  }

  if (res.status === 401) {
    clearToken();
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }

  if (res.status === 403) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error?.message || 'Access denied');
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = body.error || body;
    const enriched = new Error(err.message || `API error ${res.status}`);
    (enriched as any).code = err.code;
    (enriched as any).detail = err.detail;
    (enriched as any).suggestion = err.suggestion;
    (enriched as any).status = res.status;
    throw enriched;
  }

  return res.json();
}
```

### 3.3 API namespaces

The client is organized by domain:

```ts
import { auth, agents, calls, apiKeys, twilio, workflows, integrations, knowledgeBase, settings } from '@/lib/api';
```

Examples:

```ts
agents.list({ page: 1, per_page: 20 })
agents.update(id, { name, prompt_preamble })
workflows.execute(id, { caller_name: 'Alice' })
twilio.makeCall({ to_phone: '+1...', agent_id: 1 })
```

### 3.4 Error enrichment

Errors thrown by `apiFetch` carry backend metadata:

```ts
try {
  await agents.update(id, data);
} catch (err: any) {
  console.error(err.code);        // e.g., VALIDATION_ERROR
  console.error(err.message);     // human-readable
  console.error(err.suggestion);  // actionable advice
}
```

Components can show `err.suggestion` in toasts.

---

## 4. Authentication (`lib/auth-context.tsx`)

### 4.1 Auth context shape

```ts
interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (idToken: string) => Promise<void>;
  logout: () => void;
}
```

### 4.2 Initialization

On mount, the provider:

1. Calls `getToken()`
2. If token exists, calls `auth.me()` to load the user
3. If that fails, clears the token and sets `user: null`
4. Sets `loading: false`

### 4.3 Login/logout

```ts
const login = async (idToken: string) => {
  const data = await auth.loginWithGoogle(idToken);
  setToken(data.access_token);
  setRefreshToken(data.refresh_token);
  setUser(data.user);
};

const logout = () => {
  clearToken();
  setUser(null);
  window.location.href = '/login';
};
```

### 4.4 Dev login

During development the backend exposes `/api/auth/dev-login`:

```ts
const data = await auth.devLogin('dev@voia.local', 'Dev User');
```

---

## 5. State Management Patterns

### 5.1 No Zustand/global store

This frontend does not use Zustand or Redux. State lives in:

- **React Context** — auth, theme, toast
- **Custom hooks** — `use-flow-playground.ts`, `use-production-voice.ts`, `use-voice-chat.ts`
- **Local component state** — page-level data and UI state
- **React Query is not used** — data fetching is done via direct `useEffect` + `apiFetch`

### 5.2 Typical page data pattern

```tsx
const [agents, setAgents] = useState<Agent[]>([]);
const [loading, setLoading] = useState(true);
const [error, setError] = useState<string | null>(null);

useEffect(() => {
  agents.list()
    .then(data => setAgents(data.agents))
    .catch(err => setError(err.message))
    .finally(() => setLoading(false));
}, []);
```

### 5.3 WebSocket state is isolated

The playground and voice hooks manage their own WebSocket lifecycle internally. Parent pages subscribe via callbacks (`onAgentResponse`, `onFlowEnd`, `onError`).

---

## 6. Workflow Builder (`components/workflow/`)

### 6.1 Node type config

`WorkflowNodes.tsx` exports `NODE_TYPES_CONFIG`, a single source of truth for node UI metadata:

```ts
export const NODE_TYPES_CONFIG = {
  trigger: { label: 'Call Trigger', icon: PhoneCall, color: 'border-green-500/50 bg-green-500/5', category: 'flow' },
  conversation: { label: 'Conversation', icon: UserCheck, color: 'border-violet-500/50 bg-violet-500/5', category: 'flow' },
  condition: { label: 'Condition', icon: Zap, color: 'border-amber-500/50 bg-amber-500/5', category: 'flow' },
  google_calendar: { label: 'Google Calendar', icon: Calendar, color: 'border-cyan-500/50 bg-cyan-500/5', category: 'integration' },
  // ... etc
} as const;

export type NodeType = keyof typeof NODE_TYPES_CONFIG;
```

### 6.2 Custom node component

```tsx
export const nodeTypes = { workflowNode: WorkflowNode };
```

The `WorkflowNode` component renders:

- Header with icon and label
- "Setup needed" badge if `data.isConfigured === false`
- "Error" badge if `data.hasError === true`
- Body with label, description, and service-specific previews
- Input handle at top (except trigger)
- Output handle at bottom (except end/end_call)
- Condition nodes get two outputs: `id="yes"` at 30% and `id="no"` at 70%`

### 6.3 Node body previews

The component shows context-aware previews:

- **Conversation**: chips for `variables_to_extract`
- **Transfer call**: `→ {transfer_number}`
- **SMS**: message body preview
- **API request**: method badge + URL

### 6.4 Node categories

`NODE_CATEGORIES` groups nodes for the palette:

```ts
export const NODE_CATEGORIES = {
  flow: { label: 'Flow Control', description: 'Control conversation flow' },
  telephony: { label: 'Telephony', description: 'Call transfer & voicemail' },
  communication: { label: 'Communication', description: 'SMS, email & notifications' },
  integration: { label: 'Integrations', description: 'External services & APIs' },
  ai: { label: 'AI & Knowledge', description: 'LLM processing & RAG' },
  utility: { label: 'Utility', description: 'Timing & control' },
};
```

### 6.5 Graph persistence

The builder serializes React Flow nodes and edges into the backend's `graph_json` format. Each node's `data.config` becomes the backend `config` used by `WorkflowExecutor`.

---

## 7. Flow Playground UI (`components/playground/`)

### 7.1 `FlowGraphCanvas.tsx`

A read-only React Flow canvas that visualizes execution:

| Backend state | Visual |
|---------------|--------|
| `activeNodeId` | Amber pulsing border + glow |
| `failedNodeIds` | Red border + glow |
| `completedNodeIds` | Green border + glow |
| `traversedEdgeKeys` | Green animated edge |

```tsx
<FlowGraphCanvas
  nodes={nodes}
  edges={edges}
  activeNodeId={state.activeNodeId}
  completedNodeIds={state.completedNodes.keysSet()} // pseudocode
  failedNodeIds={state.failedNodes}
  traversedEdgeKeys={traversedEdgeKeys}
/>
```

The canvas disables dragging, connecting, and selecting.

### 7.2 Chat / message panel

The playground page combines:

- The flow canvas
- A message input
- Trace event log
- Agent response display
- Controls: Start, Reset, Set Context

It calls the `useFlowPlayground` hook and maps its state to the UI.

---

## 8. WebSocket State Flow (`hooks/use-flow-playground.ts`)

### 8.1 Connection

```ts
const ws = new WebSocket(
  `${wsUrl}/api/playground/ws/${agentId}/flow`,
  ['bearer', token],
);
```

- Sends token via `Sec-WebSocket-Protocol`
- Heartbeat every 30 seconds
- Auto-reconnect with exponential backoff (max 5 attempts, cap 16s)

### 8.2 State shape

```ts
interface FlowPlaygroundState {
  connected: boolean;
  connecting: boolean;
  started: boolean;
  activeNodeId: string | null;
  completedNodes: Map<string, FlowNodeEvent>;
  failedNodes: Set<string>;
  traversedEdges: FlowEdgeEvent[];
  traceEvents: TraceEvent[];
  agentResponses: { nodeId: string; text: string }[];
  error: string | null;
  flowStartTime: number | null;
}
```

### 8.3 Backend event → UI mapping

| Backend event | Hook action | UI effect |
|---------------|-------------|-----------|
| `flow_start` | `started=true`, `flowStartTime` | Canvas shows start |
| `node_start` | `activeNodeId=node_id` | Node pulses amber |
| `node_result` | Add to completed/failed maps | Node turns green/red |
| `edge_traversed` | Append to traversed edges | Edge animates green |
| `agent_token` | Accumulate in ref | Streaming text preview |
| `agent_response` | Append to agentResponses, call callback | Chat bubble appears |
| `flow_end` | Clear active, call `onFlowEnd` | Run complete |
| `error` | Set `error`, mark fatal | Toast / banner |
| `reset_ack` | `resetFlowState()` | Clear execution state |

### 8.4 Exposing to components

The hook returns state and actions:

```ts
const { connected, started, activeNodeId, completedNodes, failedNodes,
        traversedEdges, traceEvents, agentResponses, error,
        sendMessage, startFlow, setContext, reset, connect, disconnect } =
  useFlowPlayground({ agentId, onAgentResponse, onFlowEnd, onError });
```

---

## 9. Theming & Styling (`app/globals.css`)

### 9.1 Design tokens

```css
:root {
  --bg-primary: #09090b;
  --bg-secondary: #0f0f14;
  --bg-tertiary: #18181f;
  --text-primary: #fafafa;
  --text-secondary: #d4d4d8;
  --text-muted: #a1a1aa;
  --accent: #6366f1;
  --success: #22c55e;
  --warning: #f59e0b;
  --danger: #ef4444;
  --glass-bg: rgba(18, 18, 26, 0.96);
  --glass-blur: 16px;
  --radius: 0.75rem;
}
```

Light theme overrides these via `.light` class.

### 9.2 Key utility classes

| Class | Purpose |
|-------|---------|
| `.glass` | Frosted-glass background |
| `.glass-card` | Glass card with border |
| `.dash-card` | Dashboard card |
| `.dash-stat-card` | Dashboard stat card |
| `.dash-table` | Dashboard table container |
| `.flow-node-active` | Amber pulse on active node |
| `.flow-node-completed` | Green border on completed node |
| `.flow-node-failed` | Red border + shake on failed node |
| `.flow-edge-traversed` | Green traversed edge |

### 9.3 Execution status colors

- Active: `#f59e0b` (amber)
- Completed: `#22c55e` (green)
- Failed: `#ef4444` (red)
- Idle/default: `#6366f1` (indigo)

---

## 10. Frontend Error Handling

### 10.1 API errors

`apiFetch` attaches backend metadata to thrown errors. Components/toasts consume:

```ts
(err as any).code;
(err as any).message;
(err as any).suggestion;
(err as any).status;
```

### 10.2 Global error boundary

`ErrorBoundary` catches render errors and displays a fallback UI. It is wrapped around `{children}` in the root layout.

### 10.3 Auth failures

- 401 triggers token refresh once
- Persistent 401 clears token and redirects to `/login`
- 403 stays on the page and shows an access-denied message

### 10.4 WebSocket errors

- Connection refused → auto-reconnect
- `4001 Unauthorized` → fatal; user must re-login
- `1013 Too many connections` → close other tabs

---

## 11. Common Frontend Issues & Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Blank page after login | Auth context loading or 401 redirect loop | Check token, backend health, and `/api/auth/me` |
| `NEXT_PUBLIC_API_URL is not defined` | Missing env var | Set `NEXT_PUBLIC_API_URL=http://localhost:3000` |
| Playground stuck on "Connecting" | Token missing, WebSocket blocked, backend down | Verify `getToken()`, CORS, and backend `/ws` route |
| Nodes don't highlight during execution | `activeNodeId` not matching node IDs | Ensure backend sends matching `node_id` strings |
| Condition branch not taken visually | Edge lacks `sourceHandle` matching `yes`/`no` | Check edge data has `sourceHandle: "yes"` or `"no"` |
| Graph not saving | Validation failure or dirty state not tracked | Check browser network tab for 422 and `err.detail` |
| Toasts not showing | Component not inside `ToastProvider` | Verify provider is in root layout |
| Dark theme flashes on load | Theme class set after first paint | Inline script in `layout.tsx` prevents this |
| Dashboard cards unreadable on 3D background | `glass-bg` opacity too low / particles too bright | Increase `--glass-bg` alpha or add solid backdrop overlay |

---

## 12. Best Practices

### 12.1 Components

- Mark client components with `'use client'` when using hooks, browser APIs, or React Flow
- Keep server components for static/marketing pages
- Reuse primitives from `components/ui/`

### 12.2 Data fetching

- Use `lib/api.ts` namespaces; don't call `fetch` directly
- Handle loading, error, and empty states explicitly
- Attach backend `suggestion` to error UIs

### 12.3 State

- Prefer local state for page-level UI
- Lift shared state to a parent component or Context
- Keep WebSocket hook state self-contained; expose callbacks for page-level side effects

### 12.4 Workflow builder

- Treat `NODE_TYPES_CONFIG` as the single source of truth for node metadata
- Always set `data.config` so the backend can execute the node
- Validate graph connectivity before saving

### 12.5 Playground

- Pass stable callback refs to `useFlowPlayground`
- Reset hook state when switching agents
- Map `error` to a visible banner, not just console logs

---

## 13. Code Reference

### 13.1 Key files

| File | Responsibility |
|------|----------------|
| `frontend/src/app/layout.tsx` | Root layout, providers, theme script |
| `frontend/src/app/globals.css` | Design tokens, Tailwind utilities, component styles |
| `frontend/src/lib/api.ts` | HTTP client, token management, error enrichment |
| `frontend/src/lib/auth-context.tsx` | Auth state and login/logout |
| `frontend/src/lib/types.ts` | TypeScript interfaces for API models |
| `frontend/src/hooks/use-flow-playground.ts` | WebSocket client and execution state |
| `frontend/src/components/workflow/WorkflowNodes.tsx` | Node type config and `WorkflowNode` component |
| `frontend/src/components/workflow/` | Workflow builder canvas, panels, config forms |
| `frontend/src/components/playground/FlowGraphCanvas.tsx` | Read-only execution canvas |
| `frontend/src/components/ui/toast.tsx` | Toast system |
| `frontend/src/components/ui/theme-provider.tsx` | Theme class management |
| `frontend/src/components/ui/error-boundary.tsx` | Global error boundary |

### 13.2 Important signatures

```ts
// api.ts
function apiFetch<T>(path: string, options?: RequestInit): Promise<T>
export const auth = { loginWithGoogle, devLogin, me };
export const agents = { list, get, create, update, delete, providers, voices, templates, fromTemplate };
export const workflows = { list, get, create, update, delete, execute, templates };
export const twilio = { status, numbers, searchNumbers, purchaseNumber, makeCall, ... };

// auth-context.tsx
const { user, loading, login, logout } = useAuth();

// use-flow-playground.ts
const state = useFlowPlayground({
  agentId,
  onAgentResponse?: (nodeId, text) => void,
  onFlowEnd?: (totalNodes) => void,
  onError?: (text) => void,
});
```

---

## 14. Quick Checklist for Adding a Frontend Page

- [ ] Add route under `app/dashboard/` or `app/`
- [ ] Add to sidebar/navigation if dashboard page
- [ ] Fetch data via `lib/api.ts` namespace
- [ ] Handle loading, error, and empty states
- [ ] Wrap forms with validation feedback from backend `detail`
- [ ] Use `useAuth()` for user info and logout
- [ ] Test both light and dark themes
