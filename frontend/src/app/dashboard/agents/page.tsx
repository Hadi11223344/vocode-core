"use client";

import { useEffect, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { agents as agentsApi, integrations as integrationsApi, knowledgeBases as knowledgeBasesApi } from "@/lib/api";
import { usePageTitle } from "@/hooks/usePageTitle";
import GsapPageWrapper from "@/components/three/gsap-page-wrapper";
import {
  Agent,
  CreateAgentRequest,
  LLMProvider,
  STTProvider,
  TTSProvider,
} from "@/lib/types";
import {
  Bot,
  Plus,
  X,
  Search,
  Sparkles,
  MessageSquare,
  ShieldCheck,
  Calendar,
  PhoneCall,
  HelpCircle,
  Zap,
  ArrowRight,
  Info,
  Wrench,
  Stethoscope,
  type LucideIcon,
} from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { useToast } from '@/components/ui/toast';
import { useDebounce } from '@/hooks/use-debounce';
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { AgentCard } from "./_components/agent-card";
import { ToolsSection } from "./_components/tools-section";

/* ─── LLM Models Fallback ────────────────────────────────── */
const FALLBACK_LLM_MODELS: Record<string, string[]> = {
  openrouter: ["deepseek/deepseek-v4-flash"],
  openai: ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
  gemini: ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"],
  groq: [
    "llama-3.3-70b-versatile",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "gemma-7b-it",
  ],
  anthropic: ["claude-3-haiku-20240307", "claude-3-sonnet-20240229", "claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-sonnet-4-20250514", "claude-opus-4-20250514"],
  commandcode: ["deepseek/deepseek-v4-pro"],
  ollama: ["granite4.1:8b", "qwen3.5:9b", "qwen3:8b", "qwen3", "qwen3:32b", "qwen3:4b", "qwen3-nothink", "phi4-mini", "gemma4:e4b", "llama3.3", "gemma3:4b"],
};

/* ─── Default Agent Config ───────────────────────────────── */
const DEFAULT_AGENT: CreateAgentRequest = {
  name: "",
  prompt_preamble:
    "You are a helpful AI voice assistant. Be concise and friendly.",
  initial_message: "Hello! How can I help you today?",
  llm_provider: "openrouter",
  llm_model: "deepseek/deepseek-v4-flash",
  stt_provider: "deepgram",
  stt_model: "nova-3",
  stt_language: "en-US",
  stt_smart_format: true,
  stt_diarize: true,
  stt_filter_filler_words: false,
  analysis_provider: "auto",
  tts_provider: "deepgram",
  tts_voice_id: "aura-asteria-en",
  temperature: 0.7,
  max_tokens: 2048,
  knowledge_base_id: null,
  google_drive_integration_id: null,
};

/* ─── Agent Presets ──────────────────────────────────────── */
interface AgentPreset {
  id: string;
  title: string;
  subtitle: string;
  icon: LucideIcon;
  color: string;
  data: CreateAgentRequest;
}

const AGENT_PRESETS: AgentPreset[] = [
  {
    id: "support",
    title: "Customer Support",
    subtitle: "Friendly support agent that resolves issues",
    icon: MessageSquare,
    color: "text-cyan-400 bg-cyan-400/10 border-cyan-400/20",
    data: {
      name: "Customer Support Agent",
      prompt_preamble:
        "You are a friendly and professional customer support agent. Your goal is to help callers resolve their issues quickly and efficiently. Listen carefully to their problem, ask clarifying questions when needed, and provide clear solutions. If you cannot resolve the issue, offer to escalate to a human agent. Always maintain a calm and empathetic tone.",
      initial_message:
        "Thank you for calling! My name is Alex, how can I help you today?",
      llm_provider: "groq",
      llm_model: "llama-3.3-70b-versatile",
      stt_provider: "deepgram",
      stt_language: "en-US",
      tts_provider: "deepgram",
      tts_voice_id: "aura-asteria-en",
      temperature: 0.5,
      max_tokens: 256,
      end_on_goodbye: true,
      interrupt_sensitivity: "high",
      filler_audio_enabled: true,
    },
  },
  {
    id: "sales",
    title: "Sales Representative",
    subtitle: "Persuasive agent that qualifies and converts leads",
    icon: Zap,
    color: "text-amber-400 bg-amber-400/10 border-amber-400/20",
    data: {
      name: "Sales Agent",
      prompt_preamble:
        "You are an enthusiastic and knowledgeable sales representative. Your goal is to understand the caller\\'s needs, present relevant solutions, and guide them toward making a purchase decision. Be persuasive but not pushy. Ask qualifying questions to understand their budget, timeline, and requirements. Always highlight value and benefits rather than just features.",
      initial_message:
        "Hi there! Thanks for your interest. I\\'d love to learn about what you\\'re looking for so I can find the perfect solution for you.",
      llm_provider: "groq",
      llm_model: "llama-3.3-70b-versatile",
      stt_provider: "deepgram",
      stt_language: "en-US",
      tts_provider: "deepgram",
      tts_voice_id: "aura-orpheus-en",
      temperature: 0.7,
      max_tokens: 300,
      end_on_goodbye: true,
      interrupt_sensitivity: "low",
      filler_audio_enabled: true,
    },
  },
  {
    id: "scheduler",
    title: "Appointment Scheduler",
    subtitle: "Books and manages appointments smoothly",
    icon: Calendar,
    color: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
    data: {
      name: "Appointment Scheduler",
      prompt_preamble:
        "You are a professional appointment scheduling assistant. Help callers book, reschedule, or cancel appointments. Collect their name, preferred date and time, reason for the appointment, and contact information. Confirm all details before finalizing. Be efficient and organized while maintaining a warm, helpful tone.",
      initial_message:
        "Hello! I\\'d be happy to help you schedule an appointment. Would you like to book a new appointment or manage an existing one?",
      llm_provider: "groq",
      llm_model: "llama-3.3-70b-versatile",
      stt_provider: "deepgram",
      stt_language: "en-US",
      tts_provider: "deepgram",
      tts_voice_id: "aura-athena-en",
      temperature: 0.3,
      max_tokens: 200,
      end_on_goodbye: true,
      interrupt_sensitivity: "high",
      filler_audio_enabled: false,
    },
  },
  {
    id: "receptionist",
    title: "Virtual Receptionist",
    subtitle: "Greets callers and routes them to the right place",
    icon: PhoneCall,
    color: "text-purple-400 bg-purple-400/10 border-purple-400/20",
    data: {
      name: "Virtual Receptionist",
      prompt_preamble:
        "You are a professional virtual receptionist. Greet callers warmly and determine the purpose of their call. Route them to the appropriate department or person. If the person they want to reach is unavailable, take a message including their name, phone number, and reason for calling. Be polite, professional, and efficient.",
      initial_message:
        "Good day! Thank you for calling. How may I direct your call?",
      llm_provider: "groq",
      llm_model: "llama-3.3-70b-versatile",
      stt_provider: "deepgram",
      stt_language: "en-US",
      tts_provider: "deepgram",
      tts_voice_id: "aura-helios-en",
      temperature: 0.4,
      max_tokens: 200,
      end_on_goodbye: true,
      interrupt_sensitivity: "high",
      filler_audio_enabled: false,
    },
  },
  {
    id: "healthcare_faq",
    title: "Healthcare FAQ & Scheduler",
    subtitle: "Answers patient questions and books appointments",
    icon: Stethoscope,
    color: "text-rose-400 bg-rose-400/10 border-rose-400/20",
    data: {
      name: "Healthcare FAQ Agent",
      prompt_preamble:
        "You are a friendly receptionist at a healthcare practice. Help callers with questions about services, hours, and insurance. Use calendar tools to book, reschedule, or cancel appointments. Collect name, reason for visit, preferred date/time, and contact info when booking. Escalate distressed callers, medical diagnosis requests, billing disputes, or legal matters to a human immediately.",
      initial_message:
        "Thank you for calling. How can I help you today?",
      llm_provider: "groq",
      llm_model: "llama-3.3-70b-versatile",
      stt_provider: "deepgram",
      stt_language: "en-US",
      tts_provider: "deepgram",
      tts_voice_id: "aura-luna-en",
      temperature: 0.3,
      max_tokens: 300,
      end_on_goodbye: true,
      interrupt_sensitivity: "low",
      filler_audio_enabled: true,
    },
  },
];

/* ─── Field Help Tooltips ────────────────────────────────── */
const FIELD_HELP: Record<string, string> = {
  name: "A descriptive name to identify this agent in your dashboard",
  prompt_preamble:
    "The system prompt defines your agent's personality, role, knowledge, and behavior. This is the most important setting.",
  initial_message:
    "The first thing the agent says when answering a call. Leave empty for the agent to listen first.",
  llm_provider: "The AI model provider. Groq is free and fast. OpenAI offers GPT-4. Anthropic offers Claude.",
  llm_model: "The specific AI model to use. Larger models are smarter but slower.",
  knowledge_base_id:
    "Link an existing knowledge base so the agent can ground responses in your documents.",
  google_drive_integration_id:
    "Attach a connected Google Drive integration so the agent can search and read Drive files during calls.",
  temperature:
    "Controls randomness. Lower (0.1-0.3) = focused and deterministic. Higher (0.7-1.0) = creative and varied.",
  stt_provider:
    "Speech-to-Text engine that transcribes caller speech. Deepgram is recommended for speed and accuracy.",
  tts_provider:
    "Text-to-Speech engine that generates the agent's voice. Deepgram Aura is fast and natural-sounding.",
  tts_voice_id:
    "The specific voice the agent will speak with. All Deepgram Aura voices share the same API key.",
  stt_language:
    "The language the STT engine should expect. Use 'Multi' for auto-detection across languages.",
  max_tokens:
    "Maximum length of each AI response. Default 2048 for detailed responses; lower for short conversational agents.",
  allowed_idle_time_seconds:
    "How long to wait in silence before the agent prompts the caller or ends the call.",
  interrupt_sensitivity:
    "How easily the caller can interrupt the agent. 'High' lets callers cut in quickly. 'Low' lets the agent finish.",
  endpointing_type:
    "'Auto' detects sentence endings. 'Punctuation' waits for natural pauses. 'Time' uses a fixed delay.",
  initial_message_delay:
    "Delay before the greeting plays. Small delay (0.3-0.5s) sounds natural. 0 can sound abrupt.",
  filler_audio_enabled:
    "Plays 'um', 'let me check' sounds while the AI thinks. Makes conversations feel more natural.",
  end_on_goodbye:
    "Automatically end the call when the caller says goodbye. Recommended for most use cases.",
};

/* ─── FieldLabel Component ───────────────────────────────── */
function FieldLabel({
  label,
  helpKey,
  className,
}: {
  label: string;
  helpKey?: string;
  className?: string;
}) {
  const [showHelp, setShowHelp] = useState(false);
  const helpText = helpKey ? FIELD_HELP[helpKey] : undefined;

  return (
    <div className={cn("flex items-center gap-1.5 mb-1.5", className)}>
      <label className="block text-[13px] font-medium text-[var(--text-secondary)]">
        {label}
      </label>
      {helpText && (
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowHelp(!showHelp)}
            className="text-[var(--text-muted)] hover:text-brand-400 transition-colors"
          >
            <HelpCircle size={13} />
          </button>
          {showHelp && (
            <>
              <div
                className="fixed inset-0 z-40"
                onClick={() => setShowHelp(false)}
              />
              <div className="absolute left-0 bottom-full mb-2 z-50 w-64 p-3 bg-[var(--bg-tertiary)] border border-[var(--glass-border)] rounded-lg shadow-lg text-xs text-[var(--text-secondary)] leading-relaxed">
                {helpText}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ─── Main Page ──────────────────────────────────────────── */
export default function AgentsPage() {
  usePageTitle('Agents');
  const router = useRouter();
  const { success, apiError } = useToast();
  const [agentList, setAgentList] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const [formData, setFormData] = useState<CreateAgentRequest>(DEFAULT_AGENT);
  const [saving, setSaving] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const debouncedSearch = useDebounce(searchQuery, 300);
  const [providerFilter, setProviderFilter] = useState("");
  const [formSection, setFormSection] = useState<"core" | "voice" | "behavior" | "tools">(
    "core"
  );
  const [confirmDelete, setConfirmDelete] = useState<Agent | null>(null);
  const [knowledgeBaseOptions, setKnowledgeBaseOptions] = useState<Array<{ id: number; name: string }>>([]);
  const [driveIntegrationOptions, setDriveIntegrationOptions] = useState<Array<{ id: number; name: string }>>([]);

  const [llmModels, setLlmModels] = useState<Record<string, string[]>>(
    FALLBACK_LLM_MODELS
  );
  const [sttProviders, setSttProviders] = useState<
    { id: string; name: string }[]
  >([
    { id: "deepgram", name: "Deepgram" },
    { id: "google", name: "Google" },
    { id: "azure", name: "Azure" },
    { id: "assemblyai", name: "AssemblyAI" },
  ]);
  const [ttsProviders, setTtsProviders] = useState<
    { id: string; name: string }[]
  >([
    { id: "deepgram", name: "Deepgram Aura" },
    { id: "gtts", name: "gTTS (Free)" },
    { id: "stream_elements", name: "StreamElements (Free)" },
    { id: "elevenlabs", name: "ElevenLabs" },
    { id: "azure", name: "Azure" },
    { id: "cartesia", name: "Cartesia" },
    { id: "polly", name: "AWS Polly" },
  ]);
  const [llmProviders, setLlmProviders] = useState<
    { id: string; name: string }[]
  >([
    { id: "groq", name: "Groq (Free)" },
    { id: "openai", name: "OpenAI" },
    { id: "gemini", name: "Gemini" },
    { id: "anthropic", name: "Anthropic" },
    { id: "commandcode", name: "CommandCode (Discounted)" },
  ]);

  const loadAgents = async () => {
    try {
      const data = await agentsApi.list();
      setAgentList(data.agents);
    } catch (err) {
      apiError(err, "Failed to load agents");
    } finally {
      setLoading(false);
    }
  };

  const loadProviders = async () => {
    try {
      const p = await agentsApi.providers();
      if (p.llm_providers?.length) {
        setLlmProviders(
          p.llm_providers.map((lp) => ({ id: lp.id, name: lp.name }))
        );
        const models: Record<string, string[]> = {};
        p.llm_providers.forEach((lp) => {
          models[lp.id] = lp.models;
        });
        setLlmModels(models);
      }
      if (p.stt_providers?.length) setSttProviders(p.stt_providers);
      if (p.tts_providers?.length) setTtsProviders(p.tts_providers);
    } catch {
      // Keep fallback values
    }
  };

  useEffect(() => {
    loadAgents();
    loadProviders();
  }, []);

  useEffect(() => {
    knowledgeBasesApi.list()
      .then((data) => {
        setKnowledgeBaseOptions(
          data.knowledge_bases.map((kb) => ({ id: kb.id, name: kb.name }))
        );
      })
      .catch(() => setKnowledgeBaseOptions([]));
  }, []);

  useEffect(() => {
    integrationsApi.list()
      .then((data) => {
        setDriveIntegrationOptions(
          data.integrations
            .filter((integration) => integration.service_type === 'google_drive_mcp' && integration.is_active)
            .map((integration) => ({ id: integration.id, name: integration.name }))
        );
      })
      .catch(() => setDriveIntegrationOptions([]));
  }, []);

  /* ─── Filtered Agents ─────────────────────────────────── */
  const filteredAgents = useMemo(() => {
    let list = [...agentList];
    if (debouncedSearch) {
      const q = debouncedSearch.toLowerCase();
      list = list.filter(
        (a) =>
          a.name.toLowerCase().includes(q) ||
          a.prompt_preamble.toLowerCase().includes(q) ||
          a.llm_model.toLowerCase().includes(q)
      );
    }
    if (providerFilter) {
      list = list.filter((a) => a.llm_provider === providerFilter);
    }
    return list;
  }, [agentList, debouncedSearch, providerFilter]);

  /* ─── Stats ────────────────────────────────────────────── */
  const stats = useMemo(() => {
    const active = agentList.filter((a) => a.is_active).length;
    const providers = new Set(agentList.map((a) => a.llm_provider));
    return { total: agentList.length, active, providers: providers.size };
  }, [agentList]);

  /* ─── Modal Handlers ───────────────────────────────────── */
  const openCreate = (preset?: AgentPreset) => {
    setEditingAgent(null);
    setFormData(
      preset
        ? { ...preset.data, knowledge_base_id: null, google_drive_integration_id: null }
        : { ...DEFAULT_AGENT, knowledge_base_id: null, google_drive_integration_id: null }
    );
    setFormSection("core");
    setError("");
    setShowModal(true);
  };

  const openEdit = (agent: Agent) => {
    setEditingAgent(agent);
    setFormData({
      name: agent.name,
      prompt_preamble: agent.prompt_preamble,
      initial_message: agent.initial_message,
      llm_provider: agent.llm_provider,
      llm_model: agent.llm_model,
      stt_provider: agent.stt_provider,
      stt_language: agent.stt_language,
      tts_provider: agent.tts_provider,
      tts_voice_id: agent.tts_voice_id || undefined,
      knowledge_base_id: agent.knowledge_base_id,
      google_drive_integration_id: agent.google_drive_integration_id,
      temperature: agent.temperature,
      max_tokens: agent.max_tokens,
      end_on_goodbye: agent.end_on_goodbye,
      interrupt_sensitivity: agent.interrupt_sensitivity,
      allowed_idle_time_seconds: agent.allowed_idle_time_seconds,
      initial_message_delay: agent.initial_message_delay,
      stt_model: agent.stt_model,
      endpointing_type: agent.endpointing_type,
      filler_audio_enabled: agent.filler_audio_enabled,
      min_interrupt_confidence: agent.min_interrupt_confidence,
      stt_smart_format: agent.stt_smart_format,
      stt_diarize: agent.stt_diarize,
      stt_filter_filler_words: agent.stt_filter_filler_words,
      analysis_provider: agent.analysis_provider,
      mode: agent.mode,
      webhook_url: agent.webhook_url,
      language: agent.language,
      transition_flexibility: agent.transition_flexibility,
      handbook_enabled: agent.handbook_enabled,
      handbook_content: agent.handbook_content || undefined,
      template_id: agent.template_id,
      graph_json: agent.graph_json || undefined,
      voicemail_message: agent.voicemail_message,
      outbound_ready: agent.outbound_ready,
      tool_instructions: agent.tool_instructions,
      integration_overrides: agent.integration_overrides,
      mcp_bindings: agent.mcp_bindings,
    });
    setFormSection("core");
    setError("");
    setShowModal(true);
  };

  const handleSave = async () => {
    if (!formData.name.trim()) {
      setError("Agent name is required");
      return;
    }
    if (!formData.prompt_preamble?.trim()) {
      setError("System prompt is required");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (editingAgent) {
        await agentsApi.update(editingAgent.id, formData);
      } else {
        await agentsApi.create(formData);
      }
      setShowModal(false);
      success(
        editingAgent ? "Agent Updated" : "Agent Created",
        '"' + formData.name + '" saved successfully.'
      );
      await loadAgents();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save agent");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = (agent: Agent) => {
    setConfirmDelete(agent);
  };

  const doDelete = async () => {
    if (!confirmDelete) return;
    const agent = confirmDelete;
    setConfirmDelete(null);
    try {
      await agentsApi.delete(agent.id);
      success("Agent Deleted", `"${agent.name}" has been removed.`);
      await loadAgents();
    } catch (err) {
      apiError(err, "Failed to delete agent");
    }
  };

  const updateField = <K extends keyof CreateAgentRequest>(
    field: K,
    value: CreateAgentRequest[K]
  ) => {
    setFormData((prev) => {
      const updated = { ...prev, [field]: value };
      if (field === "llm_provider") {
        const provider = value as string;
        updated.llm_model = llmModels[provider]?.[0] || "";
      }
      return updated;
    });
  };

  const providerBadgeColor: Record<string, string> = {
    openai: "bg-emerald-500/20 text-emerald-400",
    gemini: "bg-blue-500/20 text-blue-400",
    groq: "bg-orange-500/20 text-orange-400",
    anthropic: "bg-amber-500/20 text-amber-400",
    ollama: "bg-purple-500/20 text-purple-400",
  };

  const FORM_SECTIONS = [
    { id: "core" as const, label: "Core", desc: "Identity & Intelligence" },
    { id: "voice" as const, label: "Voice", desc: "Speech & Language" },
    { id: "behavior" as const, label: "Behavior", desc: "Conversation Flow" },
    { id: "tools" as const, label: "Tools", desc: "MCP & API Extensions" },
  ];

  return (
    <GsapPageWrapper>
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Agents</h1>
          <p className="page-subtitle">
            Create and manage your AI voice agents
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/dashboard/templates"
            className="flex items-center gap-2 px-4 py-2 bg-[var(--bg-tertiary)] border border-[var(--glass-border)] rounded-lg text-sm hover:border-brand-500/40 transition-colors"
          >
            <Sparkles size={16} />
            Browse Templates
          </Link>
          <Link
            href="/dashboard/agents/new"
            className="flex items-center gap-2 btn-primary"
          >
            <Plus size={16} />
            Create Agent
          </Link>
        </div>
      </div>

      {/* Stats Bar */}
      {agentList.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          {[
            {
              label: "Total Agents",
              value: stats.total,
              icon: Bot,
              color: "text-brand-400",
            },
            {
              label: "Active",
              value: stats.active,
              icon: ShieldCheck,
              color: "text-green-400",
            },
            {
              label: "Providers Used",
              value: stats.providers,
              icon: Zap,
              color: "text-purple-400",
            },
          ].map((stat) => (
            <div
              key={stat.label}
              className="dash-card p-4 flex items-center gap-3"
            >
              <div
                className={cn(
                  "p-2 rounded-lg bg-[var(--bg-tertiary)]",
                  stat.color
                )}
              >
                <stat.icon size={16} />
              </div>
              <div>
                <p className="text-lg font-bold">{stat.value}</p>
                <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
                  {stat.label}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Search & Filters */}
      {agentList.length > 0 && (
        <div className="flex flex-wrap gap-3 items-center">
          <div className="flex-1 relative min-w-[200px]">
            <Search
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
            />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search agents by name, prompt, model..."
              className="w-full pl-9 input-base text-sm"
            />
          </div>
          <select
            value={providerFilter}
            onChange={(e) => setProviderFilter(e.target.value)}
            className="input-base text-sm min-w-[140px]"
          >
            <option value="">All Providers</option>
            {llmProviders.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Empty State */}
      {!loading && agentList.length === 0 && (
        <div className="space-y-6">
          <div className="dash-card p-12 text-center">
            <Bot
              size={48}
              className="mx-auto mb-4 text-brand-400 opacity-60"
            />
            <h3 className="text-xl font-semibold mb-2">
              Create Your First Agent
            </h3>
            <p className="text-[var(--text-secondary)] mb-6 max-w-md mx-auto">
              Agents are AI personalities that handle your phone calls. Each
              agent has its own voice, prompt, and behavior. Start from a preset
              or build from scratch.
            </p>
            <div className="flex items-center justify-center gap-3">
              <Link
                href="/dashboard/agents/new"
                className="flex items-center gap-2 btn-primary"
              >
                <Plus size={16} />
                Create Agent
              </Link>
              <Link
                href="/dashboard/templates"
                className="flex items-center gap-2 px-4 py-2 bg-[var(--bg-tertiary)] border border-[var(--glass-border)] rounded-lg text-sm hover:border-brand-500/40 transition-colors"
              >
                <Sparkles size={16} />
                Browse Templates
              </Link>
            </div>
          </div>

          {/* Preset Cards */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider">
                Quick Starters
              </h2>
              <Link
                href="/dashboard/templates"
                className="text-xs font-medium text-brand-400 hover:text-brand-300 flex items-center gap-1 transition-colors"
              >
                Browse All Templates
                <ArrowRight size={12} />
              </Link>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {AGENT_PRESETS.map((preset) => (
                <Link
                  key={preset.id}
                  href="/dashboard/agents/new"
                  className="dash-card dash-card-hover p-5 text-left group"
                >
                  <div className="flex items-start gap-4">
                    <div
                      className={cn(
                        "p-3 rounded-xl border shrink-0",
                        preset.color
                      )}
                    >
                      <preset.icon size={22} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 className="font-semibold group-hover:text-brand-400 transition-colors">
                          {preset.title}
                        </h3>
                        <ArrowRight
                          size={14}
                          className="text-[var(--text-muted)] group-hover:text-brand-400 group-hover:translate-x-0.5 transition-all"
                        />
                      </div>
                      <p className="text-xs text-[var(--text-muted)] mt-1">
                        {preset.subtitle}
                      </p>
                      <div className="flex items-center gap-2 mt-2">
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
                          temp: {preset.data.temperature}
                        </span>
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
                          {preset.data.llm_model}
                        </span>
                      </div>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </div>

          {/* How Agents Work */}
          <div className="dash-card p-6">
            <div className="flex items-center gap-2 mb-4">
              <Info size={16} className="text-brand-400" />
              <h2 className="text-sm font-semibold">How Agents Work</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {[
                {
                  step: "1",
                  title: "Define Personality",
                  desc: "Write a system prompt that describes who the agent is, what it knows, and how it should respond to callers.",
                },
                {
                  step: "2",
                  title: "Choose Voice Stack",
                  desc: "Pick your LLM for intelligence (Groq is free!), STT for hearing (Deepgram), and TTS for speaking.",
                },
                {
                  step: "3",
                  title: "Tune Behavior",
                  desc: "Adjust temperature, interruption handling, endpointing, and other settings to make conversations feel natural.",
                },
              ].map((item) => (
                <div key={item.step} className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-brand-500/20 text-brand-400 flex items-center justify-center text-sm font-bold shrink-0">
                    {item.step}
                  </div>
                  <div>
                    <p className="text-sm font-medium">{item.title}</p>
                    <p className="text-xs text-[var(--text-muted)] mt-1">
                      {item.desc}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="dash-skeleton p-5 h-20" />
          ))}
        </div>
      )}

      {/* Agent List */}
      {!loading && filteredAgents.length > 0 && (
        <div className="space-y-3">
          {filteredAgents.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              expanded={expandedId === agent.id}
              onToggleExpand={() =>
                setExpandedId(expandedId === agent.id ? null : agent.id)
              }
              onEdit={(agent) => router.push(`/dashboard/agents/${agent.id}/builder`)}
              onDelete={handleDelete}
              providerBadgeColor={providerBadgeColor}
            />
          ))}
        </div>
      )}

      {/* No Search Results */}
      {!loading &&
        agentList.length > 0 &&
        filteredAgents.length === 0 &&
        (searchQuery || providerFilter) && (
          <div className="text-center py-12 dash-card">
            <Search
              size={32}
              className="mx-auto text-[var(--text-muted)] mb-3 opacity-40"
            />
            <p className="text-sm text-[var(--text-muted)]">
              No agents match your search
            </p>
            <button
              onClick={() => {
                setSearchQuery("");
                setProviderFilter("");
              }}
              className="mt-2 text-xs text-brand-400 hover:underline"
            >
              Clear filters
            </button>
          </div>
        )}


      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm z-50 flex items-start justify-center pt-[3vh] overflow-y-auto animate-fade-in">
          <div className="bg-[var(--bg-secondary)] rounded-2xl border border-[var(--glass-border)] w-full max-w-2xl mx-4 my-8 shadow-modal animate-scale-in">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--glass-border)]">
              <h2 className="text-lg font-semibold tracking-tight">
                {editingAgent ? "Edit Agent" : "Create Agent"}
              </h2>
              <button
                onClick={() => setShowModal(false)}
                className="btn-ghost p-1.5"
              >
                <X size={20} />
              </button>
            </div>

            {/* Section Tabs */}
            <div className="flex border-b border-[var(--glass-border)]">
              {FORM_SECTIONS.map((sec) => (
                <button
                  key={sec.id}
                  onClick={() => setFormSection(sec.id)}
                  className={cn(
                    "flex-1 py-3 text-sm font-medium text-center transition-colors border-b-2",
                    formSection === sec.id
                      ? "border-brand-500 text-brand-400"
                      : "border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                  )}
                >
                  {sec.label}
                  <span className="block text-[10px] text-[var(--text-muted)] mt-0.5">
                    {sec.desc}
                  </span>
                </button>
              ))}
            </div>

            {/* Body */}
            <div className="p-6 space-y-5 max-h-[65vh] overflow-y-auto">
              {error && (
                <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
                  {error}
                </div>
              )}

              {/* Core Section */}
              {formSection === "core" && (
                <>
                  <div>
                    <FieldLabel label="Agent Name" helpKey="name" />
                    <input
                      type="text"
                      value={formData.name}
                      onChange={(e) => updateField("name", e.target.value)}
                      placeholder="e.g. Customer Support Agent"
                      className="input-base transition-colors"
                    />
                  </div>
                  <div>
                    <FieldLabel label="System Prompt" helpKey="prompt_preamble" />
                    <textarea
                      value={formData.prompt_preamble}
                      onChange={(e) =>
                        updateField("prompt_preamble", e.target.value)
                      }
                      rows={5}
                      placeholder="Define your agent's personality, role, and behavior..."
                      className="input-base transition-colors resize-none"
                    />
                    <p className="text-[10px] text-[var(--text-muted)] mt-1">
                      Tip: Be specific about the agent&apos;s role, tone, and what
                      information it should collect from callers.
                    </p>
                  </div>
                  <div>
                    <FieldLabel label="Knowledge Base" helpKey="knowledge_base_id" />
                    <select
                      value={formData.knowledge_base_id ?? ""}
                      onChange={(e) =>
                        updateField(
                          "knowledge_base_id",
                          e.target.value ? Number(e.target.value) : null
                        )
                      }
                      className="input-base transition-colors"
                      disabled={knowledgeBaseOptions.length === 0}
                    >
                      <option value="">
                        {knowledgeBaseOptions.length === 0
                          ? "No knowledge bases available"
                          : "No knowledge base linked"}
                      </option>
                      {knowledgeBaseOptions.map((kb) => (
                        <option key={kb.id} value={kb.id}>
                          {kb.name}
                        </option>
                      ))}
                    </select>
                    <p className="text-[10px] text-[var(--text-muted)] mt-1">
                      Ground the agent in uploaded documents during calls and playground tests.
                    </p>
                  </div>
                  <div>
                    <FieldLabel label="Google Drive" helpKey="google_drive_integration_id" />
                    <select
                      value={formData.google_drive_integration_id ?? ""}
                      onChange={(e) =>
                        updateField(
                          "google_drive_integration_id",
                          e.target.value ? Number(e.target.value) : null
                        )
                      }
                      className="input-base transition-colors"
                      disabled={driveIntegrationOptions.length === 0}
                    >
                      <option value="">
                        {driveIntegrationOptions.length === 0
                          ? "No Google Drive integrations available"
                          : "No Google Drive integration linked"}
                      </option>
                      {driveIntegrationOptions.map((integration) => (
                        <option key={integration.id} value={integration.id}>
                          {integration.name}
                        </option>
                      ))}
                    </select>
                    <p className="text-[10px] text-[var(--text-muted)] mt-1">
                      Attach a connected Google Drive integration so the agent can search and read Drive files during calls.
                    </p>
                    {driveIntegrationOptions.length === 0 && (
                      <Link href="/dashboard/integrations?type=google_drive_mcp" className="text-[10px] text-brand-400 hover:underline mt-1 inline-block">
                        Connect Google Drive first
                      </Link>
                    )}
                  </div>
                  <div>
                    <FieldLabel
                      label="Greeting Message"
                      helpKey="initial_message"
                    />
                    <input
                      type="text"
                      value={formData.initial_message}
                      onChange={(e) =>
                        updateField("initial_message", e.target.value)
                      }
                      placeholder="Hello! How can I help you today?"
                      className="input-base transition-colors"
                    />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                      <FieldLabel
                        label="LLM Provider"
                        helpKey="llm_provider"
                      />
                      <select
                        value={formData.llm_provider}
                        onChange={(e) =>
                          updateField(
                            "llm_provider",
                            e.target.value as LLMProvider
                          )
                        }
                        className="input-base"
                      >
                        {llmProviders.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <FieldLabel label="Model" helpKey="llm_model" />
                      <select
                        value={formData.llm_model}
                        onChange={(e) =>
                          updateField("llm_model", e.target.value)
                        }
                        className="input-base"
                      >
                        {(
                          llmModels[formData.llm_provider || "groq"] || []
                        ).map((m) => (
                          <option key={m} value={m}>
                            {m}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <FieldLabel label="Temperature" helpKey="temperature" />
                      <input
                        type="number"
                        min={0}
                        max={2}
                        step={0.1}
                        value={formData.temperature}
                        onChange={(e) =>
                          updateField(
                            "temperature",
                            parseFloat(e.target.value)
                          )
                        }
                        className="input-base"
                      />
                      <div className="flex justify-between text-[10px] text-[var(--text-muted)] mt-1">
                        <span>Focused</span>
                        <span>Creative</span>
                      </div>
                    </div>
                  </div>
                </>
              )}

              {/* Voice Section */}
              {formSection === "voice" && (
                <>
                  <div className="dash-card p-4 border-brand-500/20 bg-brand-500/5">
                    <div className="flex items-start gap-3">
                      <Info
                        size={16}
                        className="text-brand-400 shrink-0 mt-0.5"
                      />
                      <p className="text-xs text-[var(--text-secondary)]">
                        <strong>Recommended stack:</strong> Deepgram for STT
                        (fastest, most accurate) + Deepgram Aura for TTS (low
                        latency, natural voice). Use gTTS or StreamElements for
                        free alternatives.
                      </p>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <FieldLabel
                        label="STT Provider"
                        helpKey="stt_provider"
                      />
                      <select
                        value={formData.stt_provider}
                        onChange={(e) =>
                          updateField(
                            "stt_provider",
                            e.target.value as STTProvider
                          )
                        }
                        className="input-base"
                      >
                        {sttProviders.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <FieldLabel
                        label="TTS Provider"
                        helpKey="tts_provider"
                      />
                      <select
                        value={formData.tts_provider}
                        onChange={(e) =>
                          updateField(
                            "tts_provider",
                            e.target.value as TTSProvider
                          )
                        }
                        className="input-base"
                      >
                        {ttsProviders.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <FieldLabel label="Language" helpKey="stt_language" />
                      <select
                        value={formData.stt_language}
                        onChange={(e) =>
                          updateField("stt_language", e.target.value)
                        }
                        className="input-base"
                      >
                        <option value="en-US">English (US)</option>
                        <option value="en-GB">English (UK)</option>
                        <option value="es">Spanish</option>
                        <option value="de">German</option>
                        <option value="fr">French</option>
                        <option value="hi">Hindi</option>
                        <option value="ur">Urdu</option>
                        <option value="multi">Multi (auto-detect)</option>
                      </select>
                    </div>
                    <div>
                      <FieldLabel label="Deepgram Voice" helpKey="tts_voice_id" />
                      <select
                        value={formData.tts_voice_id || "aura-asteria-en"}
                        onChange={(e) =>
                          updateField("tts_voice_id", e.target.value)
                        }
                        className="input-base"
                      >
                        <option value="aura-asteria-en">Asteria — Female, US (Conversational)</option>
                        <option value="aura-luna-en">Luna — Female, US (Conversational)</option>
                        <option value="aura-stella-en">Stella — Female, US (Conversational)</option>
                        <option value="aura-athena-en">Athena — Female, UK (Professional)</option>
                        <option value="aura-hera-en">Hera — Female, US (Professional)</option>
                        <option value="aura-orion-en">Orion — Male, US (Conversational)</option>
                        <option value="aura-arcas-en">Arcas — Male, US (Conversational)</option>
                        <option value="aura-perseus-en">Perseus — Male, US (Conversational)</option>
                        <option value="aura-angus-en">Angus — Male, Irish (Warm)</option>
                        <option value="aura-orpheus-en">Orpheus — Male, US (Professional)</option>
                        <option value="aura-helios-en">Helios — Male, UK (Professional)</option>
                        <option value="aura-zeus-en">Zeus — Male, US (Authoritative)</option>
                      </select>
                      <p className="text-[10px] text-[var(--text-muted)] mt-1">
                        All Deepgram Aura voices use the same API key as STT.
                      </p>
                    </div>
                  </div>
                </>
              )}

              {/* Behavior Section */}
              {formSection === "behavior" && (
                <>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <FieldLabel label="Max Tokens" helpKey="max_tokens" />
                      <input
                        type="number"
                        min={50}
                        max={4096}
                        value={formData.max_tokens}
                        onChange={(e) =>
                          updateField("max_tokens", parseInt(e.target.value))
                        }
                        className="input-base"
                      />
                    </div>
                    <div>
                      <FieldLabel
                        label="Idle Timeout (seconds)"
                        helpKey="allowed_idle_time_seconds"
                      />
                      <input
                        type="number"
                        min={15}
                        max={300}
                        value={formData.allowed_idle_time_seconds}
                        onChange={(e) =>
                          updateField(
                            "allowed_idle_time_seconds",
                            parseFloat(e.target.value)
                          )
                        }
                        className="input-base"
                      />
                    </div>
                    <div>
                      <FieldLabel
                        label="Interruption Sensitivity"
                        helpKey="interrupt_sensitivity"
                      />
                      <select
                        value={formData.interrupt_sensitivity}
                        onChange={(e) =>
                          updateField(
                            "interrupt_sensitivity",
                            e.target.value as "low" | "high"
                          )
                        }
                        className="input-base"
                      >
                        <option value="low">Low &mdash; Agent finishes speaking</option>
                        <option value="high">
                          High &mdash; Caller can cut in
                        </option>
                      </select>
                    </div>
                    <div>
                      <FieldLabel
                        label="Endpointing"
                        helpKey="endpointing_type"
                      />
                      <select
                        value={formData.endpointing_type}
                        onChange={(e) =>
                          updateField(
                            "endpointing_type",
                            e.target.value as "auto" | "punctuation" | "time"
                          )
                        }
                        className="input-base"
                      >
                        <option value="auto">Auto &mdash; Smart detection</option>
                        <option value="punctuation">
                          Punctuation &mdash; Wait for pauses
                        </option>
                        <option value="time">
                          Time-based &mdash; Fixed delay
                        </option>
                      </select>
                    </div>
                    <div>
                      <FieldLabel
                        label="Greeting Delay (seconds)"
                        helpKey="initial_message_delay"
                      />
                      <input
                        type="number"
                        min={0}
                        max={3}
                        step={0.1}
                        value={formData.initial_message_delay}
                        onChange={(e) =>
                          updateField(
                            "initial_message_delay",
                            parseFloat(e.target.value)
                          )
                        }
                        className="input-base"
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-4 pt-2">
                    <label className="dash-card p-4 flex items-center gap-3 cursor-pointer hover:border-brand-500/40 transition-colors">
                      <input
                        type="checkbox"
                        checked={formData.filler_audio_enabled}
                        onChange={(e) =>
                          updateField(
                            "filler_audio_enabled",
                            e.target.checked
                          )
                        }
                        className="rounded"
                      />
                      <div>
                        <p className="text-sm font-medium">Filler Audio</p>
                        <p className="text-[10px] text-[var(--text-muted)]">
                          Plays &ldquo;um&rdquo;, &ldquo;let me check&rdquo;
                          while AI thinks
                        </p>
                      </div>
                    </label>
                    <label className="dash-card p-4 flex items-center gap-3 cursor-pointer hover:border-brand-500/40 transition-colors">
                      <input
                        type="checkbox"
                        checked={formData.end_on_goodbye}
                        onChange={(e) =>
                          updateField("end_on_goodbye", e.target.checked)
                        }
                        className="rounded"
                      />
                      <div>
                        <p className="text-sm font-medium">End on Goodbye</p>
                        <p className="text-[10px] text-[var(--text-muted)]">
                          Auto-hang up when caller says bye
                        </p>
                      </div>
                    </label>
                  </div>
                </>
              )}
            </div>

              {formSection === "tools" && (
                <div className="space-y-6 animate-in fade-in slide-in-from-right-2 duration-300">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-base font-semibold text-[var(--text-primary)]">
                        Connected Tools
                      </h3>
                      <p className="text-sm text-[var(--text-muted)] mt-1">
                        Extend your agent's capabilities with external APIs.
                      </p>
                    </div>
                  </div>

                  {editingAgent ? (
                    <ToolsSection agentId={editingAgent.id} />
                  ) : (
                    <div className="bg-[var(--bg-tertiary)] border border-[var(--glass-border)] rounded-xl p-8 text-center">
                      <Wrench className="mx-auto text-[var(--text-muted)] mb-3 opacity-50" size={32} />
                      <h3 className="text-sm font-semibold mb-2">Save Agent First</h3>
                      <p className="text-xs text-[var(--text-secondary)]">
                        You must create and save the agent before you can configure its connected tools.
                      </p>
                    </div>
                  )}
                </div>
              )}

            {/* Footer */}
            <div className="flex items-center justify-between px-6 py-4 border-t border-[var(--glass-border)]">
              <div className="flex items-center gap-2">
                {formSection !== "core" && (
                  <button
                    onClick={() =>
                      setFormSection(
                        formSection === "tools"
                          ? "behavior"
                          : formSection === "behavior"
                          ? "voice"
                          : "core"
                      )
                    }
                    className="text-xs text-[var(--text-muted)] hover:text-white transition-colors"
                  >
                    &larr; Back
                  </button>
                )}
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 text-sm text-[var(--text-secondary)] hover:text-white transition-colors"
                >
                  Cancel
                </button>
                {formSection !== "tools" ? (
                  <button
                    onClick={() =>
                      setFormSection(
                        formSection === "core"
                          ? "voice"
                          : formSection === "voice"
                          ? "behavior"
                          : "tools"
                      )
                    }
                    className="px-4 py-2 text-sm bg-[var(--bg-tertiary)] border border-[var(--glass-border)] rounded-lg hover:border-brand-500/40 transition-colors"
                  >
                    Next &rarr;
                  </button>
                ) : null}
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="btn-primary disabled:opacity-50"
                >
                  {saving
                    ? "Saving..."
                    : editingAgent
                    ? "Update Agent"
                    : "Create Agent"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Confirm Delete Dialog */}
      <ConfirmDialog
        open={!!confirmDelete}
        title="Delete Agent"
        message={confirmDelete ? `Are you sure you want to delete "${confirmDelete.name}"? This action cannot be undone.` : ""}
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={doDelete}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
    </GsapPageWrapper>
  );
}
