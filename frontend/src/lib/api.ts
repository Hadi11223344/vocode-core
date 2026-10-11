const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3000';

/* ─── Token helpers ─────────────────────────────────────── */
export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('voia_token');
}

export function setToken(token: string) {
  localStorage.setItem('voia_token', token);
}

export function clearToken() {
  localStorage.removeItem('voia_token');
  localStorage.removeItem('voia_refresh_token');
}

/* ─── Refresh token helpers ─────────────────────────────── */
export function getRefreshToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('voia_refresh_token');
}

export function setRefreshToken(token: string) {
  localStorage.setItem('voia_refresh_token', token);
}

let isRefreshing = false;
let refreshPromise: Promise<string | null> | null = null;

export async function getValidToken(): Promise<string | null> {
  const current = getToken();
  if (current) {
    try {
      const payload = JSON.parse(atob(current.split('.')[1]));
      const exp = payload.exp * 1000;
      // Refresh if the token expires within the next 60 seconds
      if (exp - Date.now() > 60000) {
        return current;
      }
    } catch {
      // Malformed token; fall through to refresh
    }
  }
  return refreshAccessToken();
}

async function refreshAccessToken(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh) return null;

  // Deduplicate concurrent refresh requests
  if (isRefreshing && refreshPromise) {
    return refreshPromise;
  }

  isRefreshing = true;
  refreshPromise = fetch(`${API_URL}/api/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh }),
  })
    .then(async (res) => {
      if (!res.ok) {
        clearToken();
        return null;
      }
      const data = await res.json();
      if (data.access_token) {
        setToken(data.access_token);
      }
      if (data.refresh_token) {
        setRefreshToken(data.refresh_token);
      }
      return data.access_token || null;
    })
    .catch(() => {
      clearToken();
      return null;
    })
    .finally(() => {
      isRefreshing = false;
      refreshPromise = null;
    });

  return refreshPromise;
}

/* ─── Base fetch wrapper ────────────────────────────────── */
async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const isFormData = options.body instanceof FormData;
  const headers: Record<string, string> = {
    // Only set JSON content-type when body is NOT FormData
    // (browser must set multipart boundary for file uploads)
    ...(!isFormData ? { 'Content-Type': 'application/json' } : {}),
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  }).catch((err) => {
    throw new Error(
      `Cannot connect to backend (${API_URL}). Make sure the server is running.\n${err.message}`,
    );
  });

  // 401 = token expired — try refresh once before giving up
  if (res.status === 401) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      headers['Authorization'] = `Bearer ${newToken}`;
      res = await fetch(`${API_URL}${path}`, { ...options, headers });
    }
  }

  // Still 401 after refresh (or no refresh token) → redirect to login
  if (res.status === 401) {
    clearToken();
    if (typeof window !== 'undefined') {
      window.location.href = '/login';
    }
    throw new Error('Unauthorized');
  }

  // 403 = authenticated but not authorized → stay logged in and show the error
  if (res.status === 403) {
    const body = await res.json().catch(() => ({}));
    const err = body.error || body;
    throw new Error(err.message || err.detail || 'Access denied');
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = body.error || body;
    const msg = err.message || err.detail || `API error ${res.status}`;
    const enriched = new Error(msg);
    // Attach structured error metadata for the toast system
    (enriched as any).code = err.code;
    (enriched as any).detail = err.detail;
    (enriched as any).suggestion = err.suggestion;
    (enriched as any).status = res.status;
    throw enriched;
  }

  return res.json();
}

/* ─── Auth ──────────────────────────────────────────────── */
export const auth = {
  loginWithGoogle: (idToken: string) =>
    apiFetch<{ access_token: string; refresh_token: string; token_type: string; user: import('./types').User }>(
      '/api/auth/google',
      { method: 'POST', body: JSON.stringify({ id_token: idToken }) },
    ),

  devLogin: (email = 'dev@voia.local', name = 'Dev User') =>
    apiFetch<{ access_token: string; refresh_token: string; token_type: string; user: import('./types').User }>(
      '/api/auth/dev-login',
      { method: 'POST', body: JSON.stringify({ email, name }) },
    ),

  me: () =>
    apiFetch<{ user: import('./types').User }>('/api/auth/me'),
};

/* ─── Dashboard ─────────────────────────────────────────── */
export const dashboard = {
  stats: () =>
    apiFetch<import('./types').DashboardStats>('/api/dashboard/stats'),

  recent: (limit = 10) =>
    apiFetch<{ recent_calls: import('./types').CallLog[] }>(
      `/api/dashboard/recent?limit=${limit}`,
    ),
};

/* ─── Agents ────────────────────────────────────────────── */
export const agents = {
  list: (params?: { page?: number; per_page?: number; search?: string; provider?: string }) => {
    const qs = new URLSearchParams();
    if (params?.page) qs.set('page', String(params.page));
    if (params?.per_page) qs.set('per_page', String(params.per_page));
    if (params?.search) qs.set('search', params.search);
    if (params?.provider) qs.set('provider', params.provider);
    const query = qs.toString();
    return apiFetch<{
      agents: import('./types').Agent[];
      total: number;
      page: number;
      per_page: number;
      pages: number;
    }>(`/api/agents${query ? '?' + query : ''}`);
  },

  get: (id: number) =>
    apiFetch<{ agent: import('./types').Agent }>(`/api/agents/${id}`),

  create: (data: import('./types').CreateAgentRequest) =>
    apiFetch<{ agent: import('./types').Agent }>('/api/agents', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (id: number, data: import('./types').UpdateAgentRequest) =>
    apiFetch<{ agent: import('./types').Agent }>(`/api/agents/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  delete: (id: number) =>
    apiFetch<{ message: string }>(`/api/agents/${id}`, { method: 'DELETE' }),

  providers: () =>
    apiFetch<{
      llm_providers: { id: string; name: string; models: string[] }[];
      stt_providers: { id: string; name: string }[];
      tts_providers: { id: string; name: string }[];
    }>('/api/agents/providers'),

  voices: () =>
    apiFetch<{
      voices: Array<{ id: string; name: string; gender: string; locale: string; style: string }>;
      default: string;
    }>('/api/agents/voices'),

  templates: (params?: { category?: string; mode?: string; outbound?: boolean }) => {
    const qs = params ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)])).toString() : '';
    return apiFetch<{ templates: Array<{
      id: string; slug: string; name: string; tagline: string;
      description: string; category: string; mode: string;
      icon: string; color: string; demo_script: string;
      recommended_tools: string[]; outbound_ready: boolean;
      inbound_ready: boolean; estimated_setup_time: string;
      features: string[];
      config: Record<string, unknown>;
    }>; count: number }>(`/api/agents/templates${qs}`);
  },

  fromTemplate: (data: {
    template_id: string;
    name?: string;
    custom_prompt?: string;
    custom_initial_message?: string;
    llm_provider?: string;
    tts_voice_id?: string;
    team_id?: number;
    knowledge_base_id?: number | null;
    google_drive_integration_id?: number | null;
  }) =>
    apiFetch<{ agent: import('./types').Agent; template_id: string }>('/api/agents/from-template', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};

/* ─── Calls ─────────────────────────────────────────────── */
export const calls = {
  list: (params?: { page?: number; per_page?: number; status?: string; agent_id?: number }) => {
    const qs = new URLSearchParams();
    if (params?.page) qs.set('page', String(params.page));
    if (params?.per_page) qs.set('per_page', String(params.per_page));
    if (params?.status) qs.set('status', params.status);
    if (params?.agent_id) qs.set('agent_id', String(params.agent_id));
    return apiFetch<{
      calls: import('./types').CallLog[];
      total: number;
      page: number;
      per_page: number;
      pages: number;
    }>(`/api/calls?${qs.toString()}`);
  },

  active: () =>
    apiFetch<{ active_calls: import('./types').CallLog[] }>('/api/calls/active'),

  get: (id: number) =>
    apiFetch<{
      call: import('./types').CallLog;
      transcript: import('./types').Transcript[];
      actions: import('./types').ActionLog[];
    }>(`/api/calls/${id}`),

  end: (id: number) =>
    apiFetch<{ call: import('./types').CallLog; message: string }>(`/api/calls/${id}/end`, { method: 'POST' }),

  recording: (id: number) =>
    apiFetch<{ recording_url: string; duration_secs: number; sid: string }>(`/api/calls/${id}/recording`),
};

/* ─── API Keys ──────────────────────────────────────────── */
export const apiKeys = {
  list: () =>
    apiFetch<{ keys: import('./types').UserApiKey[] }>('/api/keys'),

  services: () =>
    apiFetch<{ services: { id: string; name: string; category: string; description: string }[] }>(
      '/api/keys/services',
    ),

  platformStatus: () =>
    apiFetch<{
      platform_keys: Record<string, boolean>;
      twilio_phone_number: string | null;
      default_llm_model: string;
    }>('/api/keys/platform-status'),

  create: (data: { service: string; api_key: string; api_secret?: string; label?: string; metadata_json?: string }) =>
    apiFetch<{ key: import('./types').UserApiKey; message: string }>('/api/keys', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (id: number, data: { api_key?: string; api_secret?: string; metadata_json?: string; label?: string; is_active?: boolean }) =>
    apiFetch<{ key: import('./types').UserApiKey; message: string }>(`/api/keys/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  delete: (id: number) =>
    apiFetch<{ message: string }>(`/api/keys/${id}`, { method: 'DELETE' }),

  validate: (service: string) =>
    apiFetch<{ service: string; has_key: boolean; is_active: boolean }>(
      `/api/keys/validate/${service}`,
    ),
};

/* ─── Twilio / Phone Numbers ────────────────────────────── */
export const twilio = {
  status: () =>
    apiFetch<import('./types').TwilioStatus>('/api/twilio/status'),

  numbers: () =>
    apiFetch<{ numbers: import('./types').TwilioNumber[] }>('/api/twilio/numbers'),

  searchNumbers: (data: { country?: string; area_code?: string; contains?: string; limit?: number }) =>
    apiFetch<{ available_numbers: { phone_number: string; friendly_name: string; locality: string; region: string }[] }>(
      '/api/twilio/numbers/search',
      { method: 'POST', body: JSON.stringify(data) },
    ),

  purchaseNumber: (phone_number: string) =>
    apiFetch<{ message: string; number: { sid: string; phone_number: string; friendly_name: string } }>(
      '/api/twilio/numbers/purchase',
      { method: 'POST', body: JSON.stringify({ phone_number }) },
    ),

  updateWebhook: (data: { phone_number_sid: string; voice_url?: string; status_callback?: string }) =>
    apiFetch<{ message: string }>('/api/twilio/numbers/webhook', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  releaseNumber: (sid: string) =>
    apiFetch<{ message: string }>(`/api/twilio/numbers/${sid}`, { method: 'DELETE' }),

  makeCall: (data: { to_phone: string; agent_id?: number; from_phone?: string }) =>
    apiFetch<{ message: string; call: { sid: string; from: string; to: string; status: string } }>(
      '/api/twilio/calls/outbound',
      { method: 'POST', body: JSON.stringify(data) },
    ),

  listMappings: () =>
    apiFetch<{ mappings: Array<{ id: number; phone_number: string; agent_id: number; agent_name: string | null; label: string | null }> }>(
      '/api/twilio/mappings',
    ),

  createMapping: (data: { phone_number: string; agent_id: number; label?: string }) =>
    apiFetch<{ message: string }>('/api/twilio/mappings', { method: 'POST', body: JSON.stringify(data) }),

  deleteMapping: (id: number) =>
    apiFetch<{ message: string }>(`/api/twilio/mappings/${id}`, { method: 'DELETE' }),
};

/* ─── Workflows ─────────────────────────────────────────── */
export const workflows = {
  list: (includeInactive = false, agentId?: number) =>
    apiFetch<{ workflows: import('./types').Workflow[] }>(
      `/api/workflows?include_inactive=${includeInactive}${agentId ? `&agent_id=${agentId}` : ''}`,
    ),

  get: (id: number) =>
    apiFetch<{ workflow: import('./types').Workflow }>(`/api/workflows/${id}`),

  create: (data: import('./types').CreateWorkflowRequest) =>
    apiFetch<{ workflow: import('./types').Workflow }>('/api/workflows', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (id: number, data: import('./types').UpdateWorkflowRequest) =>
    apiFetch<{ workflow: import('./types').Workflow }>(`/api/workflows/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  delete: (id: number) =>
    apiFetch<{ message: string }>(`/api/workflows/${id}`, { method: 'DELETE' }),

  execute: (id: number, context: Record<string, unknown> = {}) =>
    apiFetch<{ workflow: string; steps_executed: number; results: unknown[] }>(
      `/api/workflows/${id}/execute`,
      { method: 'POST', body: JSON.stringify({ context }) },
    ),

  templates: () =>
    apiFetch<{ templates: Array<Record<string, unknown>> }>('/api/workflows/templates'),
};

/* ─── Integrations ──────────────────────────────────────── */
export const integrations = {
  types: () =>
    apiFetch<{ types: import('./types').IntegrationType[] }>('/api/integrations/types'),

  type: (typeId: string) =>
    apiFetch<{ type: import('./types').IntegrationType }>(`/api/integrations/types/${encodeURIComponent(typeId)}`),

  list: () =>
    apiFetch<{ integrations: import('./types').Integration[] }>('/api/integrations'),

  get: (id: number) =>
    apiFetch<{ integration: import('./types').Integration }>(`/api/integrations/${id}`),

  create: (data: { service_type: string; name: string; config?: Record<string, unknown> }) =>
    apiFetch<{ integration: import('./types').Integration }>('/api/integrations', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (id: number, data: Partial<{ name: string; config: Record<string, unknown>; is_active: boolean }>) =>
    apiFetch<{ integration: import('./types').Integration }>(`/api/integrations/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  delete: (id: number) =>
    apiFetch<{ message: string }>(`/api/integrations/${id}`, { method: 'DELETE' }),

  reactivate: (id: number) =>
    apiFetch<{ integration: import('./types').Integration }>(`/api/integrations/${id}/reactivate`, { method: 'PATCH' }),

  check: (serviceType: string) =>
    apiFetch<{ exists: boolean; integration: import('./types').Integration | null }>(`/api/integrations/check?service_type=${encodeURIComponent(serviceType)}`),

  test: (id: number) =>
    apiFetch<{ status: string; message: string }>(`/api/integrations/${id}/test`, { method: 'POST' }),

  agentUsage: (id: number) =>
    apiFetch<{ integration_id: number; service_type: string; agent_usage: { tools: string[]; trigger_phrases: string[]; example_scenario: string; parameters: Array<{ name: string; description: string; required: boolean; example: string }> }; linked_agents: Array<{ id: number; name: string }> }>(`/api/integrations/${id}/agent-usage`),

  // ── Google OAuth 2.0 Flow ──────────────────────────────────────
  googleAuth: (redirectUri: string) =>
    apiFetch<{ auth_url: string; state: string }>(
      `/api/integrations/google/auth?redirect_uri=${encodeURIComponent(redirectUri)}`
    ),

  googleCallback: (code: string, state: string) =>
    apiFetch<{ success: boolean; expires_at: string }>(`/api/integrations/google/callback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ code, state }),
    }),

  googleStatus: () =>
    apiFetch<{ connected: boolean; scopes: string[] }>('/api/integrations/google/status'),

  googleDisconnect: () =>
    apiFetch<{ success: boolean }>('/api/integrations/google/disconnect', { method: 'DELETE' }),

  // ── Google Drive File Browser ──────────────────────────────────
  driveFiles: (id: number, query?: string, pageSize?: number) =>
    apiFetch<{ files: Array<{ id: string; name: string; mimeType: string; modifiedTime: string }>; error?: string; message?: string }>(
      `/api/integrations/${id}/drive/files?${new URLSearchParams({
        ...(query ? { query } : {}),
        ...(pageSize ? { page_size: String(pageSize) } : {}),
      }).toString()}`
    ),

  driveFilePreview: (integrationId: number, fileId: string) =>
    apiFetch<{
      file_id: string;
      preview: string;
      truncated: boolean;
      total_chars: number;
    }>(`/api/integrations/${integrationId}/drive/files/${fileId}/preview`),
};

/* ─── Call Actions ──────────────────────────────────────── */
export const callActions = {
  transfer: (callSid: string, destination: string) =>
    apiFetch<{ success: boolean; call_sid: string; destination: string; message: string }>(
      '/api/twilio/calls/transfer',
      {
        method: 'POST',
        body: JSON.stringify({ call_sid: callSid, destination }),
      }
    ),

  end: (callId: number) =>
    apiFetch<{ call: import('./types').CallLog; message: string }>(`/api/calls/${callId}/end`, {
      method: 'POST',
    }),
};

/* ─── Settings ──────────────────────────────────────────── */
export const settings = {
  get: () =>
    apiFetch<{ settings: Record<string, string> }>('/api/settings'),

  update: async (data: Record<string, unknown>) => {
    // Backend expects { key, value } per call — send each changed key
    const results: Array<{ key: string; value: string }> = [];
    for (const [key, value] of Object.entries(data)) {
      const res = await apiFetch<{ message: string; key: string; value: string }>('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({ key, value: String(value) }),
      });
      results.push({ key: res.key, value: res.value });
    }
    return results;
  },
};

/* ─── Reviews ───────────────────────────────────────────── */
export const reviews = {
  list: (params?: { status?: string; page?: number; per_page?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.page) qs.set('page', String(params.page));
    if (params?.per_page) qs.set('per_page', String(params.per_page));
    return apiFetch<{
      reviews: import('./types').ReviewItem[];
      total: number;
      page: number;
      per_page: number;
      pages: number;
    }>(`/api/reviews?${qs.toString()}`);
  },

  get: (id: number) =>
    apiFetch<{ review: import('./types').ReviewItem }>(`/api/reviews/${id}`),

  approve: (id: number, notes?: string) =>
    apiFetch<{ review: import('./types').ReviewItem; message: string; execution?: unknown }>(
      `/api/reviews/${id}/approve`,
      { method: 'POST', body: JSON.stringify({ notes }) },
    ),

  reject: (id: number, notes?: string) =>
    apiFetch<{ review: import('./types').ReviewItem; message: string }>(
      `/api/reviews/${id}/reject`,
      { method: 'POST', body: JSON.stringify({ notes }) },
    ),
};

/* ─── Live Dashboard ────────────────────────────────────── */
export const live = {
  active: () =>
    apiFetch<{ active_calls: import('./types').LiveCallData[]; total: number }>('/api/live/active'),

  stats: () =>
    apiFetch<import('./types').LiveStats>('/api/live/stats'),

  createWebSocket: (token: string) => {
    const wsUrl = API_URL.replace('http', 'ws');
    return new WebSocket(`${wsUrl}/api/live/ws`, ['bearer', token]);
  },
};

/* ─── Analytics ─────────────────────────────────────────── */
export const analytics = {
  analyze: (callId: number) =>
    apiFetch<{ call_id: number; analysis: import('./types').CallAnalysis }>(
      `/api/analytics/analyze/${callId}`,
      { method: 'POST' },
    ),

  reanalyze: (callId: number) =>
    apiFetch<{ call_id: number; analysis: import('./types').CallAnalysis; provider: string }>(
      `/api/analytics/reanalyze/${callId}`,
      { method: 'POST' },
    ),

  getAnalysis: (callId: number) =>
    apiFetch<{ call_id: number; analysis: import('./types').CallAnalysis }>(
      `/api/analytics/call/${callId}`,
    ),

  overview: (days = 30) =>
    apiFetch<import('./types').AnalyticsOverview>(`/api/analytics/overview?days=${days}`),

  agentAnalytics: (agentId: number, days = 30) =>
    apiFetch<Record<string, unknown>>(`/api/analytics/agent/${agentId}?days=${days}`),

  trends: (days = 30, granularity = 'day') =>
    apiFetch<{ data: import('./types').TrendDataPoint[] }>(
      `/api/analytics/trends?days=${days}&granularity=${granularity}`,
    ),

  summary: (days = 7, agentId?: number) => {
    const qs = new URLSearchParams();
    qs.set('days', String(days));
    if (agentId) qs.set('agent_id', String(agentId));
    return apiFetch<import('./types').AnalyticsSummary>(`/api/analytics/summary?${qs}`);
  },

  // ── Phase 5: Quality ──
  scoreQuality: (callId: number) =>
    apiFetch<{ call_id: number; quality_score: number; review_flag: boolean; review_reason: string | null }>(
      `/api/analytics/quality/score/${callId}`,
      { method: 'POST' },
    ),

  qualityOverview: (days = 30) =>
    apiFetch<import('./types').QualityOverview>(`/api/analytics/quality/overview?days=${days}`),

  flaggedCalls: (days = 30, limit = 50) =>
    apiFetch<{ calls: import('./types').CallLog[]; count: number }>(
      `/api/analytics/quality/flagged?days=${days}&limit=${limit}`,
    ),

  toggleFlag: (callId: number, reason = 'manual_review') =>
    apiFetch<{ call_id: number; review_flag: boolean; review_reason: string | null }>(
      `/api/analytics/quality/flag/${callId}?reason=${encodeURIComponent(reason)}`,
      { method: 'POST' },
    ),

  funnel: (days = 30) =>
    apiFetch<{ period_days: number; stages: Array<{ stage: string; count: number; pct_of_total: number; drop_off: number }> }>(
      `/api/analytics/funnel?days=${days}`,
    ),

  cohorts: (days = 30) =>
    apiFetch<{
      period_days: number;
      cohorts: Array<{ cohort: string; total_callers: number; retention_7d: number; retention_14d: number; retention_30d: number }>;
      overall: { total_unique_callers: number; repeat_callers: number };
    }>(`/api/analytics/cohorts?days=${days}`),

  abTestResults: (agentId: number, days = 30) =>
    apiFetch<{
      agent_id: number;
      agent_name: string;
      period_days: number;
      versions: Array<{
        version_id: number;
        version_number: number;
        is_active: boolean;
        traffic_percentage: number;
        call_count: number;
        avg_duration_secs: number;
        avg_quality_score: number;
        completion_rate: number;
      }>;
    }>(`/api/analytics/ab-test/${agentId}?days=${days}`),
};

/* ─── Usage / Billing ─────────────────────────────────── */
export const usage = {
  overview: (days = 30) =>
    apiFetch<import('./types').UsageOverview>(`/api/usage/overview?days=${days}`),

  daily: (days = 30) =>
    apiFetch<{ daily: import('./types').DailyUsageEntry[] }>(`/api/usage/daily?days=${days}`),

  calls: (days = 30, limit = 50) =>
    apiFetch<{ calls: import('./types').UsageLog[]; count: number }>(
      `/api/usage/calls?days=${days}&limit=${limit}`,
    ),

  estimate: (data: {
    duration_seconds: number;
    llm_model?: string;
    input_tokens?: number;
    output_tokens?: number;
    stt_provider?: string;
    tts_provider?: string;
    direction?: string;
  }) =>
    apiFetch<{
      duration_seconds: number;
      llm_model: string;
      cost_breakdown: { llm_usd: number; stt_usd: number; tts_usd: number; telephony_usd: number };
      total_usd: number;
    }>('/api/usage/estimate', { method: 'POST', body: JSON.stringify(data) }),
};

/* ─── Playground ────────────────────────────────────────── */
export const playground = {
  agents: () =>
    apiFetch<{ agents: Array<{ id: number; name: string; llm_provider: string; llm_model: string; initial_message: string; is_active: boolean; language?: string; stt_language?: string; mode?: string }> }>(
      '/api/playground/agents?active_only=true',
    ),

  message: (agentId: number, message: string, history?: Array<{ role: string; content: string }>) =>
    apiFetch<{
      response: string;
      metrics: { llm_latency_ms: number; tokens: number; tool_calls: number; turn: number };
      agent: { name: string; model: string };
    }>(
      '/api/playground/message',
      { method: 'POST', body: JSON.stringify({ agent_id: agentId, message, conversation_history: history }) },
    ),

  createWebSocket: (agentId: number, token: string) => {
    const wsUrl = API_URL.replace(/^http/, 'ws');
    return new WebSocket(`${wsUrl}/api/playground/ws/${agentId}`, ['bearer', token]);
  },

  scenarios: (agentId: number) =>
    apiFetch<{
      scenarios: Array<{ id: string; label: string; text: string }>;
    }>(`/api/playground/scenarios/${agentId}`),

  saveSession: (data: {
    agent_id: number;
    session_type: string;
    messages: Array<{ role: string; content: string; timestamp?: number }>;
    trace_events?: unknown[];
    context?: Record<string, unknown>;
    voice_mode?: string;
    tts_provider?: string;
    turn_count?: number;
    total_tokens?: number;
    total_latency_ms?: number;
  }) =>
    apiFetch<{ session: {
      id: number; agent_id: number; agent_name: string | null;
      session_type: string; messages: Array<{ role: string; content: string }>;
      trace_events: unknown[]; context: Record<string, unknown>;
      voice_mode: string; tts_provider: string | null;
      turn_count: number; total_tokens: number; total_latency_ms: number;
      status: string; created_at: string; ended_at: string | null;
    } }>(
      '/api/playground/sessions',
      { method: 'POST', body: JSON.stringify(data) },
    ),

  listSessions: (params?: { agent_id?: number; session_type?: string; limit?: number }) => {
    const search = new URLSearchParams();
    if (params?.agent_id) search.set('agent_id', String(params.agent_id));
    if (params?.session_type) search.set('session_type', params.session_type);
    if (params?.limit) search.set('limit', String(params.limit));
    const qs = search.toString();
    return apiFetch<{ sessions: Array<{
      id: number; agent_id: number; agent_name: string | null;
      session_type: string; turn_count: number; status: string; created_at: string;
    }> }>(`/api/playground/sessions${qs ? `?${qs}` : ''}`);
  },

  getSession: (sessionId: number) =>
    apiFetch<{ session: {
      id: number; agent_id: number; agent_name: string | null;
      session_type: string; messages: Array<{ role: string; content: string }>;
      trace_events: unknown[]; context: Record<string, unknown>;
      voice_mode: string; tts_provider: string | null;
      turn_count: number; total_tokens: number; total_latency_ms: number;
      status: string; created_at: string; ended_at: string | null;
    } }>(`/api/playground/sessions/${sessionId}`),

  deleteSession: (sessionId: number) =>
    apiFetch<{ deleted: boolean }>(
      `/api/playground/sessions/${sessionId}`,
      { method: 'DELETE' },
    ),
};

/* ─── Knowledge Bases ─────────────────────────────────── */
export const knowledgeBases = {
  list: () =>
    apiFetch<{ knowledge_bases: Array<{
      id: number; name: string; description: string | null;
      source_type: string; chunk_count: number;
      agent_ids: number[]; is_active: boolean; created_at: string;
    }> }>('/api/knowledge-bases'),

  get: (id: number) =>
    apiFetch<{ knowledge_base: {
      id: number; name: string; description: string | null;
      source_type: string; source_url: string | null;
      agent_ids: number[]; chunk_size: number;
      max_chunks_per_query: number; chunk_count: number;
      is_active: boolean; created_at: string; updated_at: string;
    } }>(`/api/knowledge-bases/${id}`),

  create: (data: {
    name: string; description?: string; source_type?: string;
    content?: string; source_url?: string; agent_ids?: number[];
    chunk_size?: number; max_chunks_per_query?: number;
  }) =>
    apiFetch<{ knowledge_base: { id: number }; message: string }>(
      '/api/knowledge-bases',
      { method: 'POST', body: JSON.stringify(data) },
    ),

  update: (id: number, data: Partial<{
    name: string; description: string; is_active: boolean;
    agent_ids: number[]; chunk_size: number; max_chunks_per_query: number;
  }>) =>
    apiFetch<{ knowledge_base: { id: number }; message: string }>(
      `/api/knowledge-bases/${id}`,
      { method: 'PUT', body: JSON.stringify(data) },
    ),

  delete: (id: number) =>
    apiFetch<{ message: string }>(`/api/knowledge-bases/${id}`, { method: 'DELETE' }),

  upload: (id: number, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return apiFetch<{
      knowledge_base: { id: number; chunk_count: number };
      message: string; filename: string; text_length: number;
    }>(`/api/knowledge-bases/${id}/upload`, { method: 'POST', body: formData });
  },

  preview: (id: number) =>
    apiFetch<{
      content_preview: string;
      chunks_preview: Array<{ index: number; text: string }>;
    }>(`/api/knowledge-bases/${id}/preview`),

  query: (id: number, query: string, maxResults?: number) =>
    apiFetch<{
      chunks: Array<{ text: string; score: number; index: number }>;
      method: string;
      model: string;
    }>(`/api/knowledge-bases/${id}/query`, {
      method: 'POST',
      body: JSON.stringify({ query, max_results: maxResults }),
    }),
};

/* ─── Tools ─────────────────────────────────────────────── */
export const tools = {
  available: () =>
    apiFetch<{ tools: import('./types').PlatformTool[] }>('/api/tools/available'),

  agentTools: (agentId: number) =>
    apiFetch<{
      agent_id: number;
      enabled_tools: string[];
      tools: import('./types').PlatformTool[];
      active_integration_types: string[];
    }>(`/api/tools/agent/${agentId}`),

  updateAgentTools: (agentId: number, toolIds: string[]) =>
    apiFetch<{ message: string; warning?: string }>(`/api/tools/agent/${agentId}`, {
      method: 'PUT',
      body: JSON.stringify({ tools: toolIds }),
    }),

  agentMcpBindings: (agentId: number) =>
    apiFetch<{ agent_id: number; bindings: Record<string, unknown> }>(`/api/tools/agent/${agentId}/mcp-bindings`),

  updateAgentMcpBindings: (agentId: number, bindings: Record<string, unknown>) =>
    apiFetch<{ message: string }>(`/api/tools/agent/${agentId}/mcp-bindings`, {
      method: 'PUT',
      body: JSON.stringify({ bindings }),
    }),
};

/* ─── TTS Preview ───────────────────────────────────────── */
export const tts = {
  preview: (data: { text: string; provider: string; voice_id?: string; api_key?: string | null }) => {
    const token = getToken();
    return fetch('/api/tts/preview', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(data),
    }).then((res) => {
      if (!res.ok) throw new Error(`TTS preview failed: ${res.status}`);
      return res.blob();
    });
  },
};

/* ─── Campaigns ─────────────────────────────────────────── */
export const campaigns = {
  list: (status?: string) => {
    const qs = status ? `?status=${status}` : '';
    return apiFetch<{ campaigns: import('./types').Campaign[] }>(`/api/campaigns${qs}`);
  },

  get: (id: number) =>
    apiFetch<{ campaign: import('./types').Campaign; contacts: import('./types').CampaignContact[] }>(
      `/api/campaigns/${id}`,
    ),

  create: (data: {
    name: string;
    agent_id: number;
    description?: string;
    from_phone?: string;
    max_concurrent_calls?: number;
    call_interval_secs?: number;
    contacts?: Array<{ phone_number: string; name?: string; email?: string }>;
  }) =>
    apiFetch<{ campaign: import('./types').Campaign }>('/api/campaigns', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (id: number, data: Record<string, unknown>) =>
    apiFetch<{ campaign: import('./types').Campaign }>(`/api/campaigns/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  delete: (id: number) =>
    apiFetch<{ message: string }>(`/api/campaigns/${id}`, { method: 'DELETE' }),

  addContacts: (id: number, contacts: Array<{ phone_number: string; name?: string; email?: string }>) =>
    apiFetch<{ added: number; total_contacts: number }>(`/api/campaigns/${id}/contacts`, {
      method: 'POST',
      body: JSON.stringify({ contacts }),
    }),

  start: (id: number) =>
    apiFetch<{ message: string }>(`/api/campaigns/${id}/start`, { method: 'POST' }),

  pause: (id: number) =>
    apiFetch<{ message: string }>(`/api/campaigns/${id}/pause`, { method: 'POST' }),

  resume: (id: number) =>
    apiFetch<{ message: string }>(`/api/campaigns/${id}/resume`, { method: 'POST' }),

  stats: (id: number) =>
    apiFetch<Record<string, unknown>>(`/api/campaigns/${id}/stats`),
};

/* ─── Scheduled Calls ───────────────────────────────────── */
export const scheduledCalls = {
  list: (status?: string) => {
    const qs = status ? `?status=${status}` : '';
    return apiFetch<{
      scheduled_calls: Array<{
        id: number; agent_id: number; agent_name: string | null;
        contact_name: string | null; phone_number: string;
        scheduled_at: string; timezone: string; recurrence: string;
        from_phone: string | null; status: string;
        call_log_id: number | null; retry_count: number;
        created_at: string;
      }>;
    }>(`/api/schedule${qs}`);
  },

  get: (id: number) =>
    apiFetch<{ scheduled_call: {
      id: number; agent_id: number; agent_name: string | null;
      contact_name: string | null; phone_number: string;
      scheduled_at: string; timezone: string; recurrence: string;
      from_phone: string | null; status: string;
      call_log_id: number | null; last_error: string | null; retry_count: number;
      created_at: string; updated_at: string;
    } }>(`/api/schedule/${id}`),

  create: (data: {
    agent_id: number;
    contact_name?: string;
    phone_number: string;
    scheduled_at: string;
    timezone?: string;
    recurrence?: string;
    from_phone?: string;
  }) =>
    apiFetch<{ scheduled_call: { id: number }; message: string }>(
      '/api/schedule',
      { method: 'POST', body: JSON.stringify(data) },
    ),

  update: (id: number, data: Partial<{
    contact_name: string;
    phone_number: string;
    scheduled_at: string;
    timezone: string;
    recurrence: string;
    from_phone: string;
    status: string;
  }>) =>
    apiFetch<{ scheduled_call: { id: number }; message: string }>(
      `/api/schedule/${id}`,
      { method: 'PUT', body: JSON.stringify(data) },
    ),

  delete: (id: number) =>
    apiFetch<{ message: string }>(`/api/schedule/${id}`, { method: 'DELETE' }),
};

/* ─── Alerts ────────────────────────────────────────────── */
export const alerts = {
  listRules: () =>
    apiFetch<{ rules: import('./types').AlertRule[] }>('/api/alerts/rules'),

  createRule: (data: {
    name: string;
    condition_type: string;
    threshold?: number | null;
    window_minutes?: number;
    agent_id?: number | null;
    channels?: string[];
    channel_config?: Record<string, unknown>;
    cooldown_minutes?: number;
  }) =>
    apiFetch<{ rule: import('./types').AlertRule }>('/api/alerts/rules', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  updateRule: (id: number, data: Record<string, unknown>) =>
    apiFetch<{ rule: import('./types').AlertRule }>(`/api/alerts/rules/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteRule: (id: number) =>
    apiFetch<{ message: string }>(`/api/alerts/rules/${id}`, { method: 'DELETE' }),

  history: (days = 30, limit = 50) =>
    apiFetch<{ history: import('./types').AlertHistoryEntry[]; count: number }>(
      `/api/alerts/history?days=${days}&limit=${limit}`,
    ),

  evaluate: () =>
    apiFetch<{ evaluated: number; triggered: Array<{ rule: string; message: string }> }>(
      '/api/alerts/evaluate',
      { method: 'POST' },
    ),
};

/* ─── Test Cases & Simulation ─────────────────────────── */
export const testCases = {
  list: (agentId: number) =>
    apiFetch<{ test_cases: import('./types').TestCase[] }>(
      `/api/agents/${agentId}/test_cases`,
    ),

  create: (agentId: number, data: {
    label: string;
    user_prompt: string;
    success_criteria: string;
    criteria_type: string;
  }) =>
    apiFetch<{ test_case: import('./types').TestCase }>(
      `/api/agents/${agentId}/test_cases`,
      { method: 'POST', body: JSON.stringify(data) },
    ),

  update: (agentId: number, tcId: number, data: {
    label?: string;
    user_prompt?: string;
    success_criteria?: string;
    criteria_type?: string;
  }) =>
    apiFetch<{ test_case: import('./types').TestCase }>(
      `/api/agents/${agentId}/test_cases/${tcId}`,
      { method: 'PUT', body: JSON.stringify(data) },
    ),

  delete: (agentId: number, tcId: number) =>
    apiFetch<{ deleted: boolean }>(
      `/api/agents/${agentId}/test_cases/${tcId}`,
      { method: 'DELETE' },
    ),

  simulate: (agentId: number, data: {
    test_case_id?: number;
    user_prompt?: string;
    success_criteria?: string;
    criteria_type?: string;
  }) =>
    apiFetch<{ result: import('./types').TestRunResult }>(
      `/api/agents/${agentId}/simulate`,
      { method: 'POST', body: JSON.stringify(data) },
    ),

  batchTest: (agentId: number) =>
    apiFetch<import('./types').BatchTestSummary>(
      `/api/agents/${agentId}/batch_test`,
      { method: 'POST' },
    ),

  history: (agentId: number, limit = 20) =>
    apiFetch<{ test_runs: import('./types').TestRunHistory[] }>(
      `/api/agents/${agentId}/test_history?limit=${limit}`,
    ),
};
