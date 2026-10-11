/* ─── User ──────────────────────────────────────────────── */
export interface User {
  id: number;
  google_id: string;
  email: string;
  name: string;
  picture_url: string | null;
  role: 'admin' | 'user';
  created_at: string;
  updated_at: string;
}

/* ─── Agent ─────────────────────────────────────────────── */
export type LLMProvider = 'openrouter' | 'openai' | 'gemini' | 'anthropic' | 'groq' | 'commandcode' | 'ollama';
export type STTProvider = 'deepgram' | 'google' | 'azure' | 'assemblyai';
export type TTSProvider = 'deepgram' | 'gtts' | 'elevenlabs' | 'azure' | 'cartesia' | 'polly' | 'stream_elements';
export type EndpointingType = 'auto' | 'punctuation' | 'time';

export interface Agent {
  id: number;
  user_id: number;
  name: string;
  prompt_preamble: string;
  initial_message: string;
  llm_provider: LLMProvider;
  llm_model: string;
  stt_provider: STTProvider;
  stt_language: string;
  stt_model: string;
  tts_provider: TTSProvider;
  tts_voice_id: string | null;
  llm_api_key: string | null;
  stt_api_key: string | null;
  tts_api_key: string | null;
  temperature: number;
  max_tokens: number;
  is_active: boolean;
  end_on_goodbye: boolean;
  interrupt_sensitivity: 'low' | 'high';
  allowed_idle_time_seconds: number;
  num_check_human_present_times: number;
  initial_message_delay: number;
  endpointing_type: EndpointingType;
  filler_audio_enabled: boolean;
  min_interrupt_confidence: number;
  stt_smart_format: boolean;
  stt_diarize: boolean;
  stt_filter_filler_words: boolean;
  analysis_provider: string;
  language: string;
  mode: 'single_prompt' | 'conversational_flow';
  agent_type: string;
  transition_flexibility: 'strict' | 'flex';
  handbook_enabled: boolean;
  handbook_content: string | null;
  template_id: string | null;
  knowledge_base_id: number | null;
  google_drive_integration_id: number | null;
  webhook_url: string | null;
  tool_instructions: string | null;
  integration_overrides: Record<string, number | null>;
  mcp_bindings: Record<string, unknown>;
  graph_json: Record<string, unknown> | null;
  graph_hash: string | null;
  workflow_id: number | null;
  voicemail_message: string | null;
  outbound_ready: boolean;
  inbound_ready: boolean;
  context_window: number | null;
  created_at: string;
  updated_at: string;
}

export interface CreateAgentRequest {
  name: string;
  prompt_preamble: string;
  initial_message?: string;
  llm_provider?: LLMProvider;
  llm_model?: string;
  stt_provider?: STTProvider;
  stt_language?: string;
  language?: string;
  tts_provider?: TTSProvider;
  tts_voice_id?: string;
  llm_api_key?: string | null;
  stt_api_key?: string | null;
  tts_api_key?: string | null;
  temperature?: number;
  max_tokens?: number;
  end_on_goodbye?: boolean;
  interrupt_sensitivity?: 'low' | 'high';
  allowed_idle_time_seconds?: number;
  num_check_human_present_times?: number;
  initial_message_delay?: number;
  stt_model?: string;
  endpointing_type?: EndpointingType;
  filler_audio_enabled?: boolean;
  min_interrupt_confidence?: number;
  stt_smart_format?: boolean;
  stt_diarize?: boolean;
  stt_filter_filler_words?: boolean;
  analysis_provider?: string;
  mode?: 'single_prompt' | 'conversational_flow';
  graph_json?: Record<string, unknown>;
  workflow_id?: number | null;
  transition_flexibility?: 'strict' | 'flex';
  handbook_enabled?: boolean;
  handbook_content?: string;
  template_id?: string | null;
  knowledge_base_id?: number | null;
  google_drive_integration_id?: number | null;
  webhook_url?: string | null;
  tool_instructions?: string | null;
  integration_overrides?: Record<string, number | null>;
  mcp_bindings?: Record<string, unknown>;
  is_active?: boolean;
  voicemail_message?: string | null;
  outbound_ready?: boolean;
  inbound_ready?: boolean;
  context_window?: number | null;
}

export type UpdateAgentRequest = Partial<CreateAgentRequest>;

/* ─── Call ──────────────────────────────────────────────── */
export type CallStatus = 'active' | 'completed' | 'failed' | 'ringing' | 'initiated' | 'busy' | 'no-answer' | 'canceled';
export type CallDirection = 'inbound' | 'outbound';

export interface CallLog {
  id: number;
  conversation_id: string;
  agent_id: number | null;
  user_id: number | null;
  from_phone: string;
  to_phone: string;
  direction: CallDirection;
  status: CallStatus;
  started_at: string;
  ended_at: string | null;
  duration_secs: number | null;
  recording_url: string | null;
  agent_name?: string;
  prompt_version_id?: number | null;
  first_response_ms?: number | null;
  avg_turn_latency_ms?: number | null;
  llm_latency_ms?: number | null;
  stt_latency_ms?: number | null;
  tts_latency_ms?: number | null;
  analysis_json?: string | null;
  // Phase 5: Quality metrics
  quality_score?: number | null;
  interruption_count?: number;
  filler_count?: number;
  review_flag?: boolean;
  review_reason?: string | null;
  // Tool actions executed during the call
  actions?: ActionLog[];
}

export interface Transcript {
  id: number;
  call_log_id: number;
  sender: 'human' | 'bot' | 'action' | 'system';
  message: string;
  timestamp: number;
}

export interface ActionLog {
  id: number;
  call_log_id: number;
  action_type: string;
  params_json: string | null;
  result_json: string | null;
  timestamp: number;
}

/* ─── API Keys ─────────────────────────────────────────── */
export type ServiceName = 'openai' | 'gemini' | 'deepgram' | 'elevenlabs' | 'twilio' | 'groq' | 'anthropic' | 'google_calendar' | 'google_sheets';

export interface UserApiKey {
  id: number;
  service: ServiceName;
  label: string | null;
  is_active: boolean;
  masked_key: string;
  created_at: string;
  updated_at: string;
}

/* ─── Twilio ───────────────────────────────────────────── */
export interface TwilioNumber {
  sid: string;
  phone_number: string;
  friendly_name: string;
  voice_url: string | null;
  status_callback: string | null;
  capabilities: Record<string, boolean>;
}

export interface TwilioStatus {
  connected: boolean;
  account_sid?: string;
  account_name?: string;
  phone_number?: string;
  status?: string;
  error?: string;
}

/* ─── Dashboard ────────────────────────────────────────── */
export interface DashboardStats {
  total_calls: number;
  total_duration_mins: number;
  avg_duration_secs: number;
  active_calls: number;
  calls_today: number;
  calls_this_week: number;
  agents_count: number;
  success_rate: number;
  completed_calls: number;
}

/* ─── Workflows ────────────────────────────────────────── */
export interface WorkflowStep {
  step_number: number;
  integration_id: number;
  action: string;
  params: Record<string, unknown>;
  config?: Record<string, unknown>;
  nodeType?: string;
}

export interface WorkflowGraph {
  nodes: Array<{
    id: string;
    type?: string;
    position: { x: number; y: number };
    data: Record<string, unknown>;
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    sourceHandle?: string;
    targetHandle?: string;
    label?: string;
    animated?: boolean;
    style?: Record<string, unknown>;
  }>;
}

export interface Workflow {
  id: number;
  user_id: number;
  name: string;
  description: string | null;
  trigger_phrases: string[];
  agent_id: number | null;
  action_type: string | null;
  action_url: string | null;
  steps: WorkflowStep[] | null;
  graph: WorkflowGraph | null;
  graph_hash: string | null;
  graph_corrupted?: boolean;
  transition_flexibility: 'strict' | 'flex';
  requires_approval: boolean;
  is_active: boolean;
  created_at: string;
  updated_at?: string;
}

export interface CreateWorkflowRequest {
  name: string;
  description?: string | null;
  trigger_phrases: string[];
  agent_id?: number | null;
  action_type?: string | null;
  action_url?: string | null;
  steps?: WorkflowStep[] | null;
  graph?: WorkflowGraph | null;
  transition_flexibility?: 'strict' | 'flex';
  requires_approval?: boolean;
}

export type UpdateWorkflowRequest = Partial<CreateWorkflowRequest> & {
  is_active?: boolean;
  expected_graph_hash?: string;
};

/* ─── Integrations ─────────────────────────────────────── */
export interface Integration {
  id: number;
  user_id: number;
  service_type: string;
  name: string;
  api_key_id: number | null;
  config: Record<string, unknown> | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface IntegrationType {
  id: string;
  name: string;
  description: string;
  config_schema: Record<string, {
    type: string;
    required?: boolean;
    secret?: boolean;
    default?: unknown;
    description?: string;
    label?: string;
    placeholder?: string;
    help_text?: string;
  }>;
  capabilities: string[];
  icon?: string;
  category?: string;
  api_key_help?: string;
  setup_guide?: {
    title: string;
    estimated_time?: string;
    difficulty?: string;
    docs_url?: string;
    steps: Array<{
      step: number;
      title: string;
      description: string;
      link?: string;
    }>;
    notes?: string[];
  };
  agent_usage?: {
    tools: string[];
    trigger_phrases: string[];
    example_scenario: string;
    parameters: Array<{
      name: string;
      description: string;
      required: boolean;
      example: string;
    }>;
  };
}

/* ─── Review Queue ─────────────────────────────────────── */
export type ReviewStatus = 'pending' | 'approved' | 'rejected';

export interface ReviewItem {
  id: number;
  call_log_id: number | null;
  workflow_id: number | null;
  user_id: number;
  action_type: string;
  action_url: string | null;
  action_params: string | null;
  trigger_context: string | null;
  status: ReviewStatus;
  reviewed_by: number | null;
  reviewed_at: string | null;
  review_notes: string | null;
  created_at: string;
}

/* ─── Paginated ────────────────────────────────────────── */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

/* ─── Analytics ────────────────────────────────────────── */
export interface CallAnalysis {
  call_id: number;
  summary: string;
  sentiment: 'positive' | 'negative' | 'neutral' | 'mixed';
  sentiment_score: number;
  topics: string[];
  action_items: string[];
  customer_satisfaction: string;
  talk_ratio: { agent: number; customer: number };
  key_phrases: string[];
  resolution_status: string;
  analyzed_at?: string;
}

export interface AnalyticsOverview {
  period_days: number;
  total_calls: number;
  by_status: Record<string, number>;
  by_direction: Record<string, number>;
  completion_rate: number;
  duration: {
    total_mins: number;
    avg_secs: number;
    min_secs: number;
    max_secs: number;
  };
  top_agents: Array<{ name: string; id: number; call_count: number; avg_duration: number }>;
}

export interface TrendDataPoint {
  date: string;
  calls: number;
  completed: number;
  failed: number;
  avg_duration_secs: number;
}

export interface AnalyticsSummary {
  period_days: number;
  total_calls: number;
  avg_duration_secs: number;
  avg_sentiment_score: number | null;
  sentiment_distribution: Record<string, number>;
  outcome_distribution: Record<string, number>;
  top_topics: Array<{ topic: string; count: number }>;
  daily_breakdown: Array<{ date: string; calls: number; avg_duration_secs: number }>;
  agent_performance: Array<{ agent_id: number; agent_name: string; calls: number; avg_duration_secs: number }>;
}

/* ─── Quality ──────────────────────────────────────────── */
export interface QualityOverview {
  period_days: number;
  avg_quality_score: number;
  score_distribution: {
    excellent: number;
    good: number;
    needs_work: number;
    poor: number;
  };
  flagged_calls: number;
  top_issues: Array<{ reason: string; count: number }>;
  agent_quality: Array<{ agent_id: number; agent_name: string; calls: number; avg_score: number }>;
}

/* ─── Alerts ───────────────────────────────────────────── */
export interface AlertRule {
  id: number;
  name: string;
  is_active: boolean;
  condition_type: string;
  threshold: number | null;
  window_minutes: number;
  agent_id: number | null;
  channels: string[];
  channel_config: Record<string, unknown>;
  cooldown_minutes: number;
  last_fired_at: string | null;
  created_at: string;
}

export interface AlertHistoryEntry {
  id: number;
  alert_rule_id: number | null;
  rule_name: string;
  condition_type: string;
  message: string;
  channels: string | null;
  sent_at: string;
  acknowledged_at: string | null;
}

/* ─── Usage / Billing ──────────────────────────────────── */
export interface UsageLog {
  id: number;
  call_id: number | null;
  agent_id: number | null;
  llm_provider: string | null;
  llm_model: string | null;
  stt_provider: string | null;
  tts_provider: string | null;
  duration_seconds: number;
  input_tokens: number;
  output_tokens: number;
  stt_seconds: number;
  tts_characters: number;
  estimated_cost_usd: number;
  recorded_at: string;
}

export interface UsageOverview {
  period_days: number;
  total_calls: number;
  total_duration_minutes: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  by_provider: Record<string, { calls: number; cost_usd: number }>;
}

export interface DailyUsageEntry {
  date: string;
  calls: number;
  duration_minutes: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

/* ─── Playground ───────────────────────────────────────── */
export interface PlaygroundMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: number;
}

/* ─── Tools ────────────────────────────────────────────── */
export interface PlatformTool {
  id: string;
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  integration_type: string;
  action: string;
  enabled?: boolean;
  integration_required?: boolean;
  integration_label?: string;
  integration_connected?: boolean;
}

/* ─── Campaigns ────────────────────────────────────────── */
export type CampaignStatus = 'draft' | 'running' | 'paused' | 'completed' | 'failed';

export interface Campaign {
  id: number;
  user_id: number;
  name: string;
  description: string | null;
  agent_id: number;
  agent_name: string | null;
  status: CampaignStatus;
  from_phone: string | null;
  max_concurrent_calls: number;
  call_interval_secs: number;
  max_retries: number;
  max_call_duration_secs: number;
  scheduled_start: string | null;
  total_contacts: number;
  completed_contacts: number;
  failed_contacts: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string | null;
  progress_pct: number;
}

export interface CampaignContact {
  id: number;
  campaign_id: number;
  phone_number: string;
  name: string | null;
  email: string | null;
  custom_data: Record<string, unknown> | null;
  status: string;
  call_log_id: number | null;
  call_duration_secs: number | null;
  call_outcome: string | null;
  retries: number;
  last_error: string | null;
  called_at: string | null;
  completed_at: string | null;
}

/* ─── Live Dashboard ───────────────────────────────────── */
export interface LiveCallData {
  id: number;
  conversation_id: string;
  agent_id: number | null;
  agent_name: string | null;
  from_phone: string;
  to_phone: string;
  status: string;
  started_at: string;
  live_duration_secs: number | null;
  recent_messages: Transcript[];
  recent_actions?: ActionLog[];
  message_count: number;
}

export interface LiveStats {
  active_calls: number;
  calls_today: number;
  calls_this_week: number;
  total_calls: number;
  avg_duration_today: number;
  active_agents: number;
  ws_connections: number;
  server_time: string;
}

/* ─── Test Cases & Simulation ─────────────────────────── */
export type CriteriaType = 'keyword' | 'contains' | 'not_contains';

export interface TestCase {
  id: number;
  agent_id: number;
  label: string;
  user_prompt: string;
  success_criteria: string;
  criteria_type: CriteriaType;
  created_at: string;
  updated_at: string | null;
}

export interface TestRunResult {
  id: number;
  test_case_id: number | null;
  label?: string;
  user_prompt: string;
  agent_response: string | null;
  passed: boolean;
  criteria_type: string;
  success_criteria: string;
  latency_ms: number;
  tokens: number;
  error?: string;
}

export interface BatchTestSummary {
  total: number;
  passed: number;
  failed: number;
  results: TestRunResult[];
}

export interface TestRunHistory {
  id: number;
  agent_id: number;
  test_case_id: number | null;
  user_prompt: string;
  agent_response: string | null;
  passed: boolean;
  criteria_type: string | null;
  success_criteria: string | null;
  latency_ms: number;
  tokens_used: number;
  created_at: string;
}
