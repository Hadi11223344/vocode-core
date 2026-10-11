"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { SkeletonCard } from "@/components/ui/skeleton";
import { ArrowLeft, Save, Play, Mic, Bot, Sparkles, Loader2, ToggleLeft, ToggleRight, X, MessageSquare, Send, Volume2, Phone, GitBranch } from "lucide-react";
import { CreateAgentRequest, PlatformTool, LLMProvider, Integration } from "@/lib/types";
import {
  agents as agentsApi,
  tools as toolsApi,
  integrations as integrationsApi,
  knowledgeBases as knowledgeBasesApi,
  playground as playgroundApi,
  tts as ttsApi,
  twilio as twilioApi,
  workflows as workflowsApi,
} from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import TemplateGallery, { PRESETS, AgentPreset } from "./template-gallery";
import BuilderPanels from "./builder-panels";

/* ─── Default Agent Config ─────────────────────────────── */
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
  end_on_goodbye: true,
  interrupt_sensitivity: "high",
  endpointing_type: "auto",
  filler_audio_enabled: true,
  mode: "single_prompt",
  knowledge_base_id: null,
  google_drive_integration_id: null,
  webhook_url: null,
  mcp_bindings: {},
  voicemail_message: null,
  outbound_ready: false,
};

/* ─── Provider Fallbacks ───────────────────────────────── */
const FALLBACK_LLM_PROVIDERS = [
  { id: "openrouter", name: "OpenRouter (DeepSeek V4 Flash)" },
  { id: "groq", name: "Groq (Free)" },
  { id: "openai", name: "OpenAI" },
  { id: "gemini", name: "Gemini" },
  { id: "anthropic", name: "Anthropic" },
  { id: "commandcode", name: "CommandCode (Discounted)" },
  { id: "ollama", name: "Ollama (Local)" },
];

const FALLBACK_LLM_MODELS: Record<string, string[]> = {
  openrouter: ["deepseek/deepseek-v4-flash"],
  groq: ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3-32b"],
  openai: ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
  gemini: ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"],
  anthropic: ["claude-3-haiku-20240307", "claude-3-sonnet-20240229", "claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-sonnet-4-20250514", "claude-opus-4-20250514"],
  commandcode: ["deepseek/deepseek-v4-pro"],
  ollama: ["granite4.1:8b", "qwen3.5:9b", "qwen3:8b", "qwen3", "qwen3:32b", "qwen3:4b", "qwen3-nothink", "phi4-mini", "gemma4:e4b", "llama3.3", "gemma3:4b"],
};

const FALLBACK_STT_PROVIDERS = [
  { id: "deepgram", name: "Deepgram" },
  { id: "google", name: "Google" },
  { id: "azure", name: "Azure" },
  { id: "assemblyai", name: "AssemblyAI" },
];

const FALLBACK_TTS_PROVIDERS = [
  { id: "deepgram", name: "Deepgram Aura" },
  { id: "gtts", name: "gTTS (Free)" },
  { id: "stream_elements", name: "StreamElements (Free)" },
  { id: "elevenlabs", name: "ElevenLabs" },
  { id: "azure", name: "Azure" },
  { id: "cartesia", name: "Cartesia" },
  { id: "polly", name: "AWS Polly" },
];

/* ─── Main Builder Component ───────────────────────────── */
export default function AgentBuilder({ agentId }: { agentId?: number }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { success, apiError } = useToast();
  const isEdit = !!agentId;

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");

  const [formData, setFormData] = useState<CreateAgentRequest>(DEFAULT_AGENT);

  const [tools, setTools] = useState<PlatformTool[]>([]);
  const [enabledTools, setEnabledTools] = useState<string[]>([]);

  const [llmProviders, setLlmProviders] = useState(FALLBACK_LLM_PROVIDERS);
  const [llmModels, setLlmModels] = useState(FALLBACK_LLM_MODELS);
  const [sttProviders, setSttProviders] = useState(FALLBACK_STT_PROVIDERS);
  const [ttsProviders, setTtsProviders] = useState(FALLBACK_TTS_PROVIDERS);

  const [kbOptions, setKbOptions] = useState<Array<{ id: number; name: string }>>([]);
  const [handbookEnabled, setHandbookEnabled] = useState(false);
  const [handbookContent, setHandbookContent] = useState("");

  const [driveOptions, setDriveOptions] = useState<Array<{ id: number; name: string }>>([]);
  const [allIntegrations, setAllIntegrations] = useState<Array<{ id: number; name: string; service_type: string }>>([]);
  const [isActive, setIsActive] = useState(true);

  // Phone number mapping state
  const [twilioNumbers, setTwilioNumbers] = useState<Array<{ sid: string; phone_number: string; friendly_name: string }>>([]);
  const [mappings, setMappings] = useState<Array<{ id: number; phone_number: string; agent_id: number }>>([]);
  const [mappingLoading, setMappingLoading] = useState(false);

  const [showTemplates, setShowTemplates] = useState(!isEdit);
  const [toolSaveStatus, setToolSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [showLeaveConfirm, setShowLeaveConfirm] = useState(false);
  const [linkedWorkflowId, setLinkedWorkflowId] = useState<number | null>(null);

  // Test LLM panel state
  const [showTestPanel, setShowTestPanel] = useState(false);
  const [testMessages, setTestMessages] = useState<Array<{ role: string; content: string }>>([]);
  const [testInput, setTestInput] = useState("");
  const [testLoading, setTestLoading] = useState(false);
  const [audioPlaying, setAudioPlaying] = useState(false);
  const testChatRef = useRef<HTMLDivElement>(null);

  // ── Auto-select preset from query param ──
  useEffect(() => {
    if (isEdit) return;
    const presetId = searchParams.get("preset");
    if (presetId) {
      const preset = PRESETS.find((p) => p.id === presetId);
      if (preset) {
        const data = preset.data;
        setFormData({
          ...DEFAULT_AGENT,
          ...data,
          llm_provider: data.llm_provider || DEFAULT_AGENT.llm_provider,
          llm_model: data.llm_model || DEFAULT_AGENT.llm_model,
          stt_provider: data.stt_provider || DEFAULT_AGENT.stt_provider,
          stt_language: data.stt_language || DEFAULT_AGENT.stt_language,
          tts_provider: data.tts_provider || DEFAULT_AGENT.tts_provider,
          tts_voice_id: data.tts_voice_id || DEFAULT_AGENT.tts_voice_id,
        });
        setShowTemplates(false);
        setDirty(true);
      }
    }
  }, [searchParams, isEdit]);

  // ── Load Initial Data ──
  useEffect(() => {
    const load = async () => {
      try {
        const p = await agentsApi.providers().catch(() => null);
        if (p) {
          if (p.llm_providers?.length) {
            setLlmProviders(p.llm_providers.map((lp) => ({ id: lp.id, name: lp.name })));
            const models: Record<string, string[]> = {};
            p.llm_providers.forEach((lp) => { models[lp.id] = lp.models; });
            setLlmModels(models);
          }
          if (p.stt_providers?.length) {
            setSttProviders(p.stt_providers.map((sp) => ({ id: sp.id, name: sp.name })));
          }
          if (p.tts_providers?.length) {
            setTtsProviders(p.tts_providers.map((tp) => ({ id: tp.id, name: tp.name })));
          }
        }

        const kbData = await knowledgeBasesApi.list().catch(() => ({ knowledge_bases: [] }));
        setKbOptions(kbData.knowledge_bases.map((kb) => ({ id: kb.id, name: kb.name })));

        const intData = await integrationsApi.list().catch(() => ({ integrations: [] }));
        setDriveOptions(
          intData.integrations
            .filter((i: Integration) => i.service_type === "google_drive_mcp" && i.is_active)
            .map((i: Integration) => ({ id: i.id, name: i.name }))
        );
        setAllIntegrations(
          intData.integrations
            .filter((i: Integration) => i.is_active)
            .map((i: Integration) => ({ id: i.id, name: i.name, service_type: i.service_type }))
        );

        if (isEdit) {
          const { agent } = await agentsApi.get(agentId);
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
            temperature: agent.temperature,
            max_tokens: agent.max_tokens,
            end_on_goodbye: agent.end_on_goodbye,
            interrupt_sensitivity: agent.interrupt_sensitivity,
            allowed_idle_time_seconds: agent.allowed_idle_time_seconds,
            initial_message_delay: agent.initial_message_delay,
            endpointing_type: agent.endpointing_type,
            filler_audio_enabled: agent.filler_audio_enabled,
            min_interrupt_confidence: agent.min_interrupt_confidence,
            stt_smart_format: agent.stt_smart_format,
            stt_diarize: agent.stt_diarize,
            stt_filter_filler_words: agent.stt_filter_filler_words,
            analysis_provider: agent.analysis_provider,
            mode: agent.mode,
            knowledge_base_id: agent.knowledge_base_id,
            google_drive_integration_id: agent.google_drive_integration_id,
            webhook_url: agent.webhook_url,
            tool_instructions: agent.tool_instructions,
            integration_overrides: agent.integration_overrides || {},
            handbook_enabled: agent.handbook_enabled,
            handbook_content: agent.handbook_content || undefined,
            llm_api_key: agent.llm_api_key === '***' ? undefined : agent.llm_api_key,
            stt_api_key: agent.stt_api_key === '***' ? undefined : agent.stt_api_key,
            tts_api_key: agent.tts_api_key === '***' ? undefined : agent.tts_api_key,
            stt_model: agent.stt_model,
            mcp_bindings: agent.mcp_bindings || {},
            voicemail_message: agent.voicemail_message || null,
            outbound_ready: agent.outbound_ready ?? false,
          });
          setHandbookEnabled(agent.handbook_enabled);
          setHandbookContent(agent.handbook_content || "");
          setIsActive(agent.is_active);

          // Look up linked workflow for conversational_flow agents
          if (agent.mode === 'conversational_flow') {
            try {
              // Prefer workflow_id from agent data if available
              if (agent.workflow_id) {
                setLinkedWorkflowId(agent.workflow_id);
              } else {
                const wfData = await workflowsApi.list(false, agentId);
                if (wfData.workflows?.length > 0) {
                  const runtimeGraph = JSON.stringify(agent.graph_json || null);
                  const matchingWorkflow = wfData.workflows.find(
                    workflow => JSON.stringify(workflow.graph || null) === runtimeGraph
                  );
                  if (matchingWorkflow) {
                    setLinkedWorkflowId(matchingWorkflow.id);
                  } else if (wfData.workflows.length === 1) {
                    setLinkedWorkflowId(wfData.workflows[0].id);
                  }
                }
              }
            } catch { /* non-critical */ }
          }
        }

        // Load tools
        if (isEdit) {
          const toolData = await toolsApi.agentTools(agentId);
          setEnabledTools(toolData.enabled_tools || []);
          setTools(toolData.tools || []);
        } else {
          const toolData = await toolsApi.available();
          setTools(toolData.tools || []);
          setEnabledTools([]);
        }
      } catch (err) {
        apiError(err, "Failed to load agent data");
      } finally {
        setLoading(false);
      }

      // Load phone numbers and mappings (async, non-blocking)
      try {
        setMappingLoading(true);
        const [numData, mapData] = await Promise.all([
          twilioApi.numbers().catch(() => ({ numbers: [] })),
          twilioApi.listMappings().catch(() => ({ mappings: [] })),
        ]);
        setTwilioNumbers(numData.numbers || []);
        setMappings(mapData.mappings || []);
      } catch {
        /* silent — telephony may not be configured */
      } finally {
        setMappingLoading(false);
      }
    };
    load();
  }, [agentId, isEdit, apiError]);

  // ── Auto-scroll Test LLM chat ──
  useEffect(() => {
    if (testChatRef.current) {
      testChatRef.current.scrollTop = testChatRef.current.scrollHeight;
    }
  }, [testMessages, testLoading]);

  // ── Dirty Form Protection ──
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [dirty]);

  const updateField = useCallback(
    <K extends keyof CreateAgentRequest>(field: K, value: CreateAgentRequest[K]) => {
      setFormData((prev) => {
        const next = { ...prev, [field]: value };
        if (field === "llm_provider") {
          const provider = value as string;
          return { ...next, llm_model: llmModels[provider]?.[0] || "" };
        }
        return next;
      });
      setDirty(true);
      setError("");
    },
    [llmModels]
  );

  const handleSave = async () => {
    if (!formData.name?.trim()) { setError("Agent name is required"); return; }
    if (!formData.prompt_preamble?.trim()) { setError("System prompt is required"); return; }

    setSaving(true);
    setError("");
    const payload: CreateAgentRequest = {
      ...formData,
      handbook_enabled: handbookEnabled,
      handbook_content: handbookContent,
      integration_overrides: formData.integration_overrides || {},
    };

    try {
      if (isEdit) {
        await agentsApi.update(agentId, payload);
        await toolsApi.updateAgentTools(agentId, enabledTools);
        success("Saved", "Agent updated successfully");
      } else {
        const { agent } = await agentsApi.create(payload);
        if (enabledTools.length > 0) await toolsApi.updateAgentTools(agent.id, enabledTools);
        success("Created", "Agent created successfully");
        router.push(`/dashboard/agents/${agent.id}/builder`);
        return;
      }
      setDirty(false);
    } catch (err) {
      apiError(err, isEdit ? "Failed to update agent" : "Failed to create agent");
    } finally {
      setSaving(false);
    }
  };

  // ── Keyboard Shortcut (Ctrl+S / Cmd+S) ──
  const handleSaveRef = useRef(handleSave);
  handleSaveRef.current = handleSave;
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        handleSaveRef.current();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const toggleActive = async () => {
    if (!isEdit) return;
    const next = !isActive;
    setIsActive(next);
    try {
      await agentsApi.update(agentId, { is_active: next });
      success(next ? "Activated" : "Deactivated", `Agent is now ${next ? "active" : "inactive"}`);
    } catch (err) {
      apiError(err, "Failed to update agent status");
      setIsActive(!next);
    }
  };

  const [audioRef, setAudioRef] = useState<HTMLAudioElement | null>(null);

  const handleTestAudio = async () => {
    if (audioPlaying && audioRef) {
      audioRef.pause();
      setAudioPlaying(false);
      return;
    }
    const text = formData.initial_message || "Hello! How can I help you today?";
    setAudioPlaying(true);
    try {
      const blob = await ttsApi.preview({
        text,
        provider: formData.tts_provider || "deepgram",
        voice_id: formData.tts_voice_id || undefined,
        api_key: formData.tts_api_key || undefined,
      });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      setAudioRef(audio);
      audio.onended = () => {
        setAudioPlaying(false);
        URL.revokeObjectURL(url);
      };
      audio.onerror = () => {
        setAudioPlaying(false);
        URL.revokeObjectURL(url);
        apiError(new Error("Playback failed"), "Failed to play TTS preview");
      };
      audio.play();
    } catch (err: unknown) {
      setAudioPlaying(false);
      const msg = err instanceof Error ? err.message : "Could not generate preview audio";
      apiError(err instanceof Error ? err : new Error(msg), msg);
    }
  };

  const handleTestLLM = () => {
    if (!isEdit) {
      setError("Save the agent first to test the LLM");
      return;
    }
    setShowTestPanel(true);
    setTestMessages([
      { role: "system", content: "Test started. The agent will respond using its current prompt and settings." },
    ]);
  };

  const sendTestMessage = async () => {
    if (!testInput.trim() || !isEdit) return;
    const userMsg = testInput.trim();
    setTestInput("");
    setTestMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setTestLoading(true);
    try {
      const history = testMessages.filter((m) => m.role === "user" || m.role === "assistant").map((m) => ({ role: m.role, content: m.content }));
      const result = await playgroundApi.message(agentId, userMsg, history);
      setTestMessages((prev) => [...prev, { role: "assistant", content: result.response }]);
    } catch (err) {
      apiError(err, "Test message failed");
      setTestMessages((prev) => [...prev, { role: "assistant", content: "Error: Could not get response. Make sure the agent is saved and active." }]);
    } finally {
      setTestLoading(false);
    }
  };

  const handleAssignNumber = async (phoneNumber: string) => {
    if (!isEdit || !agentId) return;
    try {
      await twilioApi.createMapping({ phone_number: phoneNumber, agent_id: agentId });
      const mapData = await twilioApi.listMappings();
      setMappings(mapData.mappings || []);
      success("Assigned", `Number ${phoneNumber} linked to this agent`);
    } catch (err) {
      apiError(err, "Failed to assign phone number");
    }
  };

  const handleUnassignNumber = async (mappingId: number) => {
    try {
      await twilioApi.deleteMapping(mappingId);
      setMappings((prev) => prev.filter((m) => m.id !== mappingId));
      success("Unassigned", "Phone number removed from this agent");
    } catch (err) {
      apiError(err, "Failed to unassign phone number");
    }
  };

  const toggleTool = async (toolId: string) => {
    const next = enabledTools.includes(toolId) ? enabledTools.filter((t) => t !== toolId) : [...enabledTools, toolId];
    setEnabledTools(next);
    setDirty(true);
    if (isEdit) {
      setToolSaveStatus('saving');
      try {
        const result = await toolsApi.updateAgentTools(agentId!, next);
        if (result.warning) apiError(new Error(result.warning), "Tool Warning");
        setToolSaveStatus('saved');
        setTimeout(() => setToolSaveStatus('idle'), 2000);
      } catch {
        setEnabledTools(enabledTools);
        setToolSaveStatus('error');
        setTimeout(() => setToolSaveStatus('idle'), 2000);
      }
    }
  };

  const selectPreset = (preset: AgentPreset) => {
    setFormData({
      ...DEFAULT_AGENT,
      ...preset.data,
      llm_provider: preset.data.llm_provider || DEFAULT_AGENT.llm_provider,
      llm_model: preset.data.llm_model || DEFAULT_AGENT.llm_model,
      stt_provider: preset.data.stt_provider || DEFAULT_AGENT.stt_provider,
      stt_language: preset.data.stt_language || DEFAULT_AGENT.stt_language,
      tts_provider: preset.data.tts_provider || DEFAULT_AGENT.tts_provider,
      tts_voice_id: preset.data.tts_voice_id || DEFAULT_AGENT.tts_voice_id,
    });
    if (preset.tools_config && preset.tools_config.length > 0) {
      setEnabledTools(preset.tools_config);
    } else {
      setEnabledTools([]);
    }
    setShowTemplates(false);
    setDirty(true);
  };

  const startFromScratch = () => {
    setFormData(DEFAULT_AGENT);
    setShowTemplates(false);
    setDirty(false);
  };

  const handleBack = () => {
    if (dirty) {
      setShowLeaveConfirm(true);
    } else {
      router.push('/dashboard/agents');
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-[var(--bg-tertiary)]" />
          <div className="h-6 w-32 rounded bg-[var(--bg-tertiary)]" />
        </div>
        <SkeletonCard className="h-96" />
      </div>
    );
  }

  if (!isEdit && showTemplates) {
    return <TemplateGallery onSelectPreset={selectPreset} onStartFromScratch={startFromScratch} />;
  }

  return (
    <div className="h-full flex flex-col relative">
      {/* Top Bar */}
      <div className="shrink-0 border-b border-[var(--glass-border)] bg-[var(--bg-secondary)] px-4 lg:px-6 py-3 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <button
            onClick={handleBack}
            className="p-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] rounded-lg transition-colors shrink-0"
            title="Back to agents"
          >
            <ArrowLeft size={18} />
          </button>
          <input
            type="text"
            value={formData.name || ""}
            onChange={(e) => { updateField("name", e.target.value); setError(""); }}
            placeholder="Agent name..."
            className="bg-transparent text-lg font-semibold border-none focus:ring-0 p-0 w-full placeholder:text-[var(--text-muted)]"
          />
          {dirty && <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 shrink-0">Unsaved</span>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {error && <span className="text-xs text-red-400 mr-2">{error}</span>}

          {/* Active Toggle (edit only) */}
          {isEdit && (
            <button
              onClick={toggleActive}
              className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium bg-[var(--bg-tertiary)] border border-[var(--glass-border)] rounded-lg hover:border-brand-500/40 transition-colors"
              title={isActive ? "Agent is active" : "Agent is inactive"}
            >
              {isActive ? <ToggleRight size={14} className="text-emerald-400" /> : <ToggleLeft size={14} className="text-[var(--text-muted)]" />}
              {isActive ? "Active" : "Inactive"}
            </button>
          )}

          <button
            onClick={handleTestAudio}
            className={cn(
              "flex items-center gap-1.5 px-3 py-2 text-xs font-medium border rounded-lg transition-colors",
              audioPlaying
                ? "bg-brand-500/10 border-brand-500/40 text-brand-400"
                : "bg-[var(--bg-tertiary)] border-[var(--glass-border)] text-[var(--text-muted)] hover:border-brand-500/40"
            )}
          >
            {audioPlaying ? <Volume2 size={14} /> : <Mic size={14} />}
            {audioPlaying ? "Playing..." : "Test Audio"}
          </button>

          <button
            onClick={handleTestLLM}
            className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium bg-[var(--bg-tertiary)] border border-[var(--glass-border)] rounded-lg hover:border-brand-500/40 transition-colors text-[var(--text-muted)]"
          >
            <Play size={14} /> Test LLM
          </button>

          {/* Edit Flow link for conversational_flow agents */}
          {formData.mode === 'conversational_flow' && (
            <Link
              href={linkedWorkflowId ? `/dashboard/workflows/${linkedWorkflowId}` : `/dashboard/workflows/new?agentId=${agentId}`}
              className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium bg-purple-500/10 border border-purple-500/30 rounded-lg text-purple-400 hover:border-purple-500/50 transition-colors"
              title={linkedWorkflowId ? 'Edit the conversational flow' : 'Create a workflow for this agent'}
            >
              <GitBranch size={14} /> {linkedWorkflowId ? 'Edit Flow' : 'Create Flow'}
            </Link>
          )}

          {/* Phone Number Mapping (edit only) */}
          {isEdit && twilioNumbers.length > 0 && (
            <div className="relative">
              {(() => {
                const agentMappings = mappings.filter((m) => m.agent_id === agentId);
                const mappedNumbers = new Set(mappings.map((m) => m.phone_number));
                const availableNumbers = twilioNumbers.filter((n) => !mappedNumbers.has(n.phone_number));
                return agentMappings.length > 0 ? (
                  <div className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-400">
                    <Phone size={14} />
                    <span>{agentMappings[0].phone_number}</span>
                    <button
                      onClick={() => handleUnassignNumber(agentMappings[0].id)}
                      className="ml-1 hover:text-emerald-200"
                      title="Unassign number"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ) : (
                  <select
                    value=""
                    onChange={(e) => e.target.value && handleAssignNumber(e.target.value)}
                    disabled={mappingLoading || availableNumbers.length === 0}
                    className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium bg-[var(--bg-tertiary)] border border-[var(--glass-border)] rounded-lg hover:border-brand-500/40 transition-colors text-[var(--text-muted)] appearance-none cursor-pointer"
                    style={{ maxWidth: '140px' }}
                  >
                    <option value="">{mappingLoading ? 'Loading...' : 'Assign Number'}</option>
                    {availableNumbers.map((n) => (
                      <option key={n.sid} value={n.phone_number}>
                        {n.phone_number}
                      </option>
                    ))}
                  </select>
                );
              })()}
            </div>
          )}

          <button onClick={handleSave} disabled={saving} className="flex items-center gap-1.5 px-4 py-2 text-xs font-medium bg-brand-500 text-white rounded-lg hover:bg-brand-400 transition-colors disabled:opacity-50">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {isEdit ? "Save" : "Create"}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden flex flex-col lg:flex-row">
        {/* Left Panel — Prompt Editor */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6 lg:border-r border-[var(--glass-border)]">
          <div>
            <label className="block text-sm font-medium mb-2 flex items-center gap-2">
              <Bot size={16} className="text-brand-400" /> System Prompt
            </label>
            <textarea
              value={formData.prompt_preamble}
              onChange={(e) => updateField("prompt_preamble", e.target.value)}
              rows={10}
              placeholder="Define your agent's personality, role, call flow, and knowledge..."
              className="w-full input-base resize-none font-mono text-sm leading-relaxed"
            />
            <div className="flex items-center justify-between mt-1.5">
              <p className="text-[10px] text-[var(--text-muted)]">
                This is the single prompt that controls your agent's behavior.
              </p>
              <span className={cn("text-[10px] tabular-nums", (formData.prompt_preamble?.length || 0) > 4000 ? "text-red-400" : "text-[var(--text-muted)]")}>
                {(formData.prompt_preamble?.length || 0).toLocaleString()} chars · ~{Math.ceil((formData.prompt_preamble?.length || 0) / 4).toLocaleString()} tokens
              </span>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">Greeting Message</label>
            <input
              type="text"
              value={formData.initial_message}
              onChange={(e) => updateField("initial_message", e.target.value)}
              placeholder="Hello! How can I help you today?"
              className="w-full input-base text-sm"
            />
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium mb-2">LLM Provider</label>
              <select value={formData.llm_provider} onChange={(e) => updateField("llm_provider", e.target.value as LLMProvider)} className="w-full input-base text-sm">
                {llmProviders.map((p) => (<option key={p.id} value={p.id}>{p.name}</option>))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Model</label>
              <select value={formData.llm_model} onChange={(e) => updateField("llm_model", e.target.value)} className="w-full input-base text-sm">
                {(llmModels[formData.llm_provider || "openrouter"] || []).map((m) => (<option key={m} value={m}>{m}</option>))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Temperature <span className="text-brand-400 tabular-nums">{formData.temperature}</span></label>
              <input
                type="range"
                min={0}
                max={2}
                step={0.1}
                value={formData.temperature}
                onChange={(e) => updateField("temperature", parseFloat(e.target.value))}
                className="w-full accent-brand-500"
              />
              <div className="flex justify-between text-[10px] text-[var(--text-muted)] mt-1"><span>Precise</span><span>Balanced</span><span>Creative</span></div>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium mb-2">Max Tokens</label>
            <input type="number" min={50} max={4096} value={formData.max_tokens} onChange={(e) => updateField("max_tokens", parseInt(e.target.value))} className="w-full input-base text-sm" />
          </div>
          {!isEdit && (
            <button onClick={() => setShowTemplates(true)} className="text-xs text-brand-400 hover:underline flex items-center gap-1">
              <Sparkles size={12} /> Change Template
            </button>
          )}
        </div>

        {/* Right Panel */}
        <div className="w-full lg:w-[400px] shrink-0 overflow-y-auto p-4 space-y-3 bg-[var(--bg-secondary)]">
          <BuilderPanels
            formData={formData}
            onChange={updateField}
            tools={tools}
            enabledTools={enabledTools}
            onToggleTool={toggleTool}
            toolSaveStatus={toolSaveStatus}
            kbOptions={kbOptions}
            handbookEnabled={handbookEnabled}
            handbookContent={handbookContent}
            onToggleHandbook={setHandbookEnabled}
            onChangeHandbook={setHandbookContent}
            driveOptions={driveOptions}
            allIntegrations={allIntegrations}
            agentId={agentId}
            llmProviders={llmProviders}
            llmModels={llmModels}
            sttProviders={sttProviders}
            ttsProviders={ttsProviders}
          />
        </div>
      </div>

      {/* Test LLM Slide-over */}
      {showTestPanel && (
        <div className="absolute inset-y-0 right-0 w-[400px] bg-[var(--bg-secondary)] border-l border-[var(--glass-border)] shadow-2xl z-50 flex flex-col animate-in slide-in-from-right duration-200">
          <div className="shrink-0 px-4 py-3 border-b border-[var(--glass-border)] flex items-center justify-between">
            <div className="flex items-center gap-2">
              <MessageSquare size={16} className="text-brand-400" />
              <span className="text-sm font-medium">Test LLM</span>
            </div>
            <button onClick={() => setShowTestPanel(false)} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] rounded-lg transition-colors">
              <X size={16} />
            </button>
          </div>

          <div ref={testChatRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {testMessages.map((msg, i) => (
              <div key={i} className={cn("text-xs p-2.5 rounded-lg", msg.role === "user" ? "bg-brand-500/10 text-brand-200 ml-4" : msg.role === "system" ? "bg-[var(--bg-tertiary)] text-[var(--text-muted)] text-center" : "bg-[var(--bg-primary)] text-[var(--text-secondary)] border border-[var(--glass-border)] mr-4")}>
                {msg.content}
              </div>
            ))}
            {testLoading && (
              <div className="flex items-center gap-2 text-xs text-[var(--text-muted)] mr-4 bg-[var(--bg-primary)] border border-[var(--glass-border)] p-2.5 rounded-lg">
                <Loader2 size={12} className="animate-spin" /> Thinking...
              </div>
            )}
          </div>

          <div className="shrink-0 p-3 border-t border-[var(--glass-border)]">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={testInput}
                onChange={(e) => setTestInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') sendTestMessage(); }}
                placeholder="Type a test message..."
                className="flex-1 input-base text-sm"
                disabled={testLoading}
              />
              <button
                onClick={sendTestMessage}
                disabled={testLoading || !testInput.trim()}
                className="p-2 bg-brand-500 text-white rounded-lg hover:bg-brand-400 transition-colors disabled:opacity-50"
              >
                {testLoading ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Leave without saving? confirmation modal */}
      {showLeaveConfirm && (
        <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in">
          <div className="bg-[var(--bg-secondary)] border border-[var(--glass-border)] rounded-2xl w-full max-w-sm p-6 shadow-modal animate-scale-in">
            <h3 className="text-base font-semibold mb-2">Leave without saving?</h3>
            <p className="text-sm text-[var(--text-muted)] mb-6">
              You have unsaved changes to <span className="text-[var(--text-primary)] font-medium">{formData.name || 'this agent'}</span>.
              They will be permanently lost if you leave now.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowLeaveConfirm(false)}
                className="px-4 py-2 text-sm rounded-lg border border-[var(--glass-border)] hover:bg-[var(--bg-tertiary)] transition-colors"
              >
                Keep editing
              </button>
              <button
                onClick={() => {
                  setDirty(false);
                  setShowLeaveConfirm(false);
                  router.push('/dashboard/agents');
                }}
                className="px-4 py-2 text-sm font-medium rounded-lg bg-red-600/90 hover:bg-red-500 text-white transition-colors"
              >
                Leave anyway
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
