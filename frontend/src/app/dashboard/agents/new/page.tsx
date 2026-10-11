'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { cn } from '@/lib/utils';
import {
  ArrowLeft,
  ArrowRight,
  MessageSquare,
  GitBranch,
  Brain,
  Mic,
  Globe,
  Plus,
  CheckCircle,
  Sparkles,
} from 'lucide-react';
import {
  TEMPLATE_LIBRARY,
  TEMPLATE_CATEGORIES,
  type Template,
} from '@/lib/templates';
import { agents as agentsApi } from '@/lib/api';
import { useToast } from '@/components/ui/toast';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';

const STEPS = ['mode', 'category', 'template', 'configure'] as const;
type Step = (typeof STEPS)[number];

export default function CreateAgentWizard() {
  const router = useRouter();
  const { success, apiError } = useToast();
  const [step, setStep] = useState<Step>('mode');
  const [mode, setMode] = useState<'single_prompt' | 'conversational_flow'>('conversational_flow');
  const [category, setCategory] = useState('all');
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [saving, setSaving] = useState(false);

  // Form state
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [initialMessage, setInitialMessage] = useState('');
  const [llmProvider, setLlmProvider] = useState('openrouter');
  const [llmModel, setLlmModel] = useState('deepseek/deepseek-v4-flash');
  const [voiceId, setVoiceId] = useState('aura-asteria-en');

  const filteredTemplates = TEMPLATE_LIBRARY.filter(
    (t) =>
      (category === 'all' || t.category === category) && t.mode === mode
  );

  const handleNext = () => {
    const idx = STEPS.indexOf(step);
    if (idx < STEPS.length - 1) setStep(STEPS[idx + 1]);
  };

  const handleBack = () => {
    const idx = STEPS.indexOf(step);
    if (idx > 0) setStep(STEPS[idx - 1]);
  };

  const selectTemplate = (template: Template | null) => {
    setSelectedTemplate(template);
    if (template) {
      setName(template.name);
      setPrompt(template.global_prompt);
      setInitialMessage(template.nodes?.find((n) => n.type === 'welcome')?.prompt || '');
      setLlmProvider(template.llm_provider);
      setLlmModel(template.llm_model);
      setVoiceId(template.voice_name.toLowerCase().replace(' ', '-'));
    } else {
      setName('');
      setPrompt('');
      setInitialMessage('');
    }
  };

  const handleSave = async () => {
    if (!name.trim() || !prompt.trim()) return;
    setSaving(true);
    try {
      // For conversational_flow without a template graph, create as single_prompt first
      // then redirect to workflow editor to build the flow
      const effectiveMode = mode === 'conversational_flow' && !selectedTemplate?.nodes
        ? 'single_prompt'
        : mode;

      // Build graph_json from template nodes if available for conversational_flow
      let graphJson: Record<string, unknown> | undefined;
      if (mode === 'conversational_flow' && selectedTemplate?.nodes?.length) {
        const nodes = selectedTemplate.nodes.map((n, i) => ({
          id: `node_${i}`,
          type: n.type === 'welcome' ? 'trigger' : 'conversation',
          position: { x: 250, y: i * 150 },
          data: { label: n.type.charAt(0).toUpperCase() + n.type.slice(1), prompt: n.prompt || '', nodeType: n.type === 'welcome' ? 'trigger' : 'conversation' },
        }));
        const edges = nodes.slice(1).map((n, i) => ({
          id: `edge_${i}`,
          source: `node_${i}`,
          target: n.id,
        }));
        graphJson = { nodes, edges };
      }

      const result = await agentsApi.create({
        name,
        prompt_preamble: prompt,
        initial_message: initialMessage || 'Hello! How can I help you today?',
        llm_provider: llmProvider as 'openrouter' | 'openai' | 'gemini' | 'groq' | 'anthropic' | 'commandcode' | 'ollama',
        llm_model: llmModel,
        stt_provider: 'deepgram',
        stt_language: 'en-US',
        tts_provider: 'deepgram',
        tts_voice_id: voiceId,
        temperature: 0.7,
        max_tokens: 2048,
        mode: effectiveMode as 'single_prompt' | 'conversational_flow',
        template_id: selectedTemplate?.id || null,
        graph_json: graphJson,
      });
      success('Agent Created', `${name} has been created successfully`);
      // If conversational_flow without template graph, redirect to workflow editor
      if (mode === 'conversational_flow' && !selectedTemplate?.nodes) {
        router.push(`/dashboard/workflows/new?agentId=${result.agent.id}`);
      } else {
        router.push(`/dashboard/agents/${result.agent.id}`);
      }
    } catch (err) {
      apiError(err, 'Failed to create agent');
    } finally {
      setSaving(false);
    }
  };

  const stepIndex = STEPS.indexOf(step);

  return (
    <GsapPageWrapper>
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Link
          href="/dashboard/agents"
          className="p-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] rounded-lg transition-colors"
        >
          <ArrowLeft size={18} />
        </Link>
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Create Agent</h1>
          <p className="page-subtitle">Set up a new voice AI agent</p>
        </div>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-8">
        {STEPS.map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <div
              className={cn(
                'w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium transition-colors',
                i <= stepIndex
                  ? 'bg-brand-500 text-white'
                  : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'
              )}
            >
              {i < stepIndex ? <CheckCircle size={14} /> : i + 1}
            </div>
            <span
              className={cn(
                'text-sm capitalize hidden sm:inline',
                i <= stepIndex
                  ? 'text-[var(--text-primary)]'
                  : 'text-[var(--text-muted)]'
              )}
            >
              {s.replace('_', ' ')}
            </span>
            {i < STEPS.length - 1 && (
              <div
                className={cn(
                  'w-8 h-[2px] hidden sm:block',
                  i < stepIndex ? 'bg-brand-500' : 'bg-[var(--border-color)]'
                )}
              />
            )}
          </div>
        ))}
      </div>

      {/* Step content */}
      <div className="animate-fade-in">
        {step === 'mode' && (
          <ModeSelector mode={mode} onSelect={setMode} onNext={handleNext} />
        )}
        {step === 'category' && (
          <CategorySelector
            mode={mode}
            category={category}
            onSelect={setCategory}
            onNext={handleNext}
            onBack={handleBack}
          />
        )}
        {step === 'template' && (
          <TemplatePicker
            templates={filteredTemplates}
            category={category}
            selectedTemplate={selectedTemplate}
            onSelect={selectTemplate}
            onBack={handleBack}
            onNext={handleNext}
          />
        )}
        {step === 'configure' && (
          <ConfigureStep
            name={name}
            setName={setName}
            prompt={prompt}
            setPrompt={setPrompt}
            initialMessage={initialMessage}
            setInitialMessage={setInitialMessage}
            llmProvider={llmProvider}
            setLlmProvider={setLlmProvider}
            llmModel={llmModel}
            setLlmModel={setLlmModel}
            voiceId={voiceId}
            setVoiceId={setVoiceId}
            mode={mode}
            selectedTemplate={selectedTemplate}
            onBack={handleBack}
            onSave={handleSave}
            saving={saving}
          />
        )}
      </div>
    </div>
    </GsapPageWrapper>
  );
}

/* ── Step 1: Mode Selector ──────────────────────────────────────── */
function ModeSelector({
  mode,
  onSelect,
  onNext,
}: {
  mode: string;
  onSelect: (m: 'single_prompt' | 'conversational_flow') => void;
  onNext: () => void;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold mb-2">How should your agent work?</h2>
        <p className="text-[var(--text-muted)]">
          Choose the conversation style that fits your use case.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Single Prompt */}
        <button
          onClick={() => onSelect('single_prompt')}
          className={cn(
            'p-6 rounded-xl border-2 text-left transition-all',
            mode === 'single_prompt'
              ? 'border-brand-500 bg-brand-500/5'
              : 'border-[var(--glass-border)] hover:border-[var(--text-muted)]'
          )}
        >
          <div
            className={cn(
              'w-12 h-12 rounded-lg flex items-center justify-center mb-4',
              mode === 'single_prompt'
                ? 'bg-brand-500/20 text-brand-400'
                : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'
            )}
          >
            <MessageSquare size={24} />
          </div>
          <h3 className="font-semibold text-lg mb-2">Single Prompt</h3>
          <p className="text-sm text-[var(--text-muted)]">
            Easy to start. One system prompt defines all behavior. Best for
            FAQs, simple tasks, and natural free-form conversations.
          </p>
        </button>

        {/* Conversational Flow */}
        <button
          onClick={() => onSelect('conversational_flow')}
          className={cn(
            'p-6 rounded-xl border-2 text-left transition-all',
            mode === 'conversational_flow'
              ? 'border-purple-500 bg-purple-500/5'
              : 'border-[var(--glass-border)] hover:border-[var(--text-muted)]'
          )}
        >
          <div
            className={cn(
              'w-12 h-12 rounded-lg flex items-center justify-center mb-4',
              mode === 'conversational_flow'
                ? 'bg-purple-500/20 text-purple-400'
                : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'
            )}
          >
            <GitBranch size={24} />
          </div>
          <h3 className="font-semibold text-lg mb-2">Conversational Flow</h3>
          <p className="text-sm text-[var(--text-muted)]">
            Production-ready, deterministic conversations. Visual node editor
            with branching logic. Best for multi-step processes.
          </p>
        </button>
      </div>

      <div className="flex justify-end">
        <button onClick={onNext} className="btn-primary flex items-center gap-2">
          Continue <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}

/* ── Step 2: Category Selector ──────────────────────────────────── */
function CategorySelector({
  mode,
  category,
  onSelect,
  onNext,
  onBack,
}: {
  mode: string;
  category: string;
  onSelect: (c: string) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold mb-2">Choose a category</h2>
        <p className="text-[var(--text-muted)]">
          {mode === 'conversational_flow'
            ? 'Select the type of conversational flow you want to build.'
            : 'Select the type of single-prompt agent you want to create.'}
        </p>
      </div>

      {/* Horizontal category tabs */}
      <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-hide">
        {TEMPLATE_CATEGORIES.map((cat) => (
          <button
            key={cat.id}
            onClick={() => onSelect(cat.id)}
            className={cn(
              'px-4 py-2 rounded-full text-sm font-medium whitespace-nowrap transition-colors',
              category === cat.id
                ? 'bg-[var(--bg-tertiary)] text-[var(--text-primary)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            )}
          >
            {cat.label}
          </button>
        ))}
      </div>

      <div className="flex justify-between">
        <button onClick={onBack} className="btn-ghost flex items-center gap-2">
          <ArrowLeft size={16} /> Back
        </button>
        <button onClick={onNext} className="btn-primary flex items-center gap-2">
          Continue <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}

/* ── Step 3: Template Picker ────────────────────────────────────── */
function TemplatePicker({
  templates,
  category,
  selectedTemplate,
  onSelect,
  onBack,
  onNext,
}: {
  templates: Template[];
  category: string;
  selectedTemplate: Template | null;
  onSelect: (t: Template | null) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold mb-2">Select a template</h2>
          <p className="text-[var(--text-muted)]">
            Pick a starting point or begin from scratch.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-5 gap-6">
        {/* Left: Template grid */}
        <div className="col-span-5 lg:col-span-3 space-y-3">
          {/* Blank agent */}
          <button
            onClick={() => onSelect(null)}
            className={cn(
              "w-full p-4 rounded-xl border text-center transition-colors",
              selectedTemplate === null
                ? "border-brand-500/60 bg-brand-500/5"
                : "border-dashed border-[var(--glass-border)] hover:border-brand-500/40"
            )}
          >
            <Plus size={24} className="mx-auto mb-2 text-[var(--text-muted)]" />
            <p className="font-medium text-sm">Blank agent</p>
            <p className="text-xs text-[var(--text-muted)]">Start from scratch</p>
          </button>

          {/* Template cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {templates.map((template) => (
              <button
                key={template.id}
                onClick={() => onSelect(template)}
                className={cn(
                  "dash-card p-4 text-left transition-all group",
                  selectedTemplate?.id === template.id
                    ? "border-brand-500/60 bg-brand-500/5"
                    : "hover:border-brand-500/40"
                )}
              >
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-lg bg-[var(--bg-tertiary)] flex items-center justify-center shrink-0">
                    <template.icon size={20} className="text-brand-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <h4 className="font-medium text-sm group-hover:text-brand-400 transition-colors">
                      {template.name}
                    </h4>
                    <p className="text-xs text-[var(--text-muted)] mt-1">
                      {template.description}
                    </p>
                    <div className="flex items-center gap-2 mt-2">
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
                        {template.llm_provider}
                      </span>
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
                        {template.llm_model}
                      </span>
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Right: Preview panel */}
        <div className="hidden lg:block col-span-2">
          <div className="dash-card p-5 sticky top-4 space-y-4">
            {selectedTemplate ? (
              <>
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-brand-500/20 flex items-center justify-center shrink-0">
                    <selectedTemplate.icon size={20} className="text-brand-400" />
                  </div>
                  <div className="min-w-0">
                    <h3 className="font-semibold text-sm truncate">{selectedTemplate.name}</h3>
                    <p className="text-xs text-[var(--text-muted)]">{selectedTemplate.category}</p>
                  </div>
                </div>

                <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                  {selectedTemplate.description}
                </p>

                {/* Prompt preview */}
                <div>
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">Prompt</span>
                  <p className="mt-1 text-xs text-[var(--text-secondary)] leading-relaxed line-clamp-4">
                    {selectedTemplate.global_prompt}
                  </p>
                </div>

                {/* Config details */}
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-[var(--text-muted)]">Voice</span>
                    <p className="text-[var(--text-secondary)]">{selectedTemplate.voice_name}</p>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">Language</span>
                    <p className="text-[var(--text-secondary)]">{selectedTemplate.language}</p>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">Provider</span>
                    <p className="text-[var(--text-secondary)]">{selectedTemplate.llm_provider}</p>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">Model</span>
                    <p className="text-[var(--text-secondary)]">{selectedTemplate.llm_model}</p>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">Est. Tokens</span>
                    <p className="text-[var(--text-secondary)]">{selectedTemplate.estimated_tokens}</p>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">Mode</span>
                    <p className="text-[var(--text-secondary)]">{selectedTemplate.mode === 'single_prompt' ? 'Single Prompt' : 'Flow'}</p>
                  </div>
                </div>

                {/* Recommended tools */}
                {selectedTemplate.recommended_tools && selectedTemplate.recommended_tools.length > 0 && (
                  <div>
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">Recommended Tools</span>
                    <div className="flex flex-wrap gap-1.5 mt-1.5">
                      {selectedTemplate.recommended_tools.map((tool) => (
                        <span key={tool} className="text-[10px] px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                          {tool}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Setup notes */}
                {selectedTemplate.setup_notes && (
                  <div>
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">Setup Notes</span>
                    <p className="mt-1 text-xs text-[var(--text-secondary)] leading-relaxed">{selectedTemplate.setup_notes}</p>
                  </div>
                )}
              </>
            ) : (
              <>
                <div className="flex items-center gap-2 mb-4">
                  <Sparkles size={16} className="text-brand-400" />
                  <h3 className="font-semibold">Blank Agent</h3>
                </div>
                <p className="text-sm text-[var(--text-muted)]">
                  Start from scratch with default settings. You'll configure everything manually in the next step.
                </p>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="flex justify-between">
        <button onClick={onBack} className="btn-ghost flex items-center gap-2">
          <ArrowLeft size={16} /> Back
        </button>
        <button onClick={onNext} className="btn-primary flex items-center gap-2">
          Continue <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}

/* ── Step 4: Configure ──────────────────────────────────────────── */
function ConfigureStep({
  name,
  setName,
  prompt,
  setPrompt,
  initialMessage,
  setInitialMessage,
  llmProvider,
  setLlmProvider,
  llmModel,
  setLlmModel,
  voiceId,
  setVoiceId,
  mode,
  selectedTemplate,
  onBack,
  onSave,
  saving,
}: {
  name: string;
  setName: (v: string) => void;
  prompt: string;
  setPrompt: (v: string) => void;
  initialMessage: string;
  setInitialMessage: (v: string) => void;
  llmProvider: string;
  setLlmProvider: (v: string) => void;
  llmModel: string;
  setLlmModel: (v: string) => void;
  voiceId: string;
  setVoiceId: (v: string) => void;
  mode: string;
  selectedTemplate: Template | null;
  onBack: () => void;
  onSave: () => void;
  saving: boolean;
}) {
  const llmModels: Record<string, string[]> = {
    openrouter: ['deepseek/deepseek-v4-flash'],
    openai: ['gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo'],
    gemini: ['gemini-2.0-flash', 'gemini-1.5-pro'],
    groq: ['openai/gpt-oss-120b', 'openai/gpt-oss-20b', 'llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'qwen/qwen3-32b'],
    anthropic: ['claude-3-haiku-20240307', 'claude-3-sonnet-20240229', 'claude-3-5-sonnet-20241022', 'claude-3-opus-20240229', 'claude-sonnet-4-20250514', 'claude-opus-4-20250514'],
    commandcode: ['deepseek/deepseek-v4-pro'],
    ollama: ['granite4.1:8b', 'qwen3.5:9b', 'qwen3:8b', 'qwen3', 'qwen3:32b', 'qwen3:4b', 'qwen3-nothink', 'phi4-mini', 'gemma4:e4b', 'llama3.3', 'gemma3:4b'],
  };

  const voices = [
    { id: 'aura-asteria-en', name: 'Asteria (Female, US)' },
    { id: 'aura-luna-en', name: 'Luna (Female, US)' },
    { id: 'aura-stella-en', name: 'Stella (Female, US)' },
    { id: 'aura-athena-en', name: 'Athena (Female, UK)' },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold mb-2">Configure your agent</h2>
        <p className="text-[var(--text-muted)]">
          {selectedTemplate
            ? `Customize the "${selectedTemplate.name}" template`
            : 'Set up your new agent from scratch'}
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main config */}
        <div className="lg:col-span-2 space-y-4">
          {/* Name */}
          <div className="dash-card p-5">
            <label className="text-sm font-medium mb-2 block">Agent Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input-base w-full"
              placeholder="e.g., Customer Support Agent"
            />
          </div>

          {/* Prompt */}
          <div className="dash-card p-5">
            <label className="text-sm font-medium mb-2 block">System Prompt</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              className="input-base w-full h-48 font-mono text-sm"
              placeholder="Define how your agent should behave..."
            />
            <p className="text-xs text-[var(--text-muted)] mt-2">
              {prompt.length} characters · ~{Math.ceil(prompt.length / 4)} tokens
            </p>
          </div>

          {/* Initial message */}
          <div className="dash-card p-5">
            <label className="text-sm font-medium mb-2 block">Initial Message</label>
            <input
              value={initialMessage}
              onChange={(e) => setInitialMessage(e.target.value)}
              className="input-base w-full"
              placeholder="Hello! How can I help you today?"
            />
          </div>
        </div>

        {/* Sidebar config */}
        <div className="space-y-4">
          {/* Mode badge */}
          <div className="dash-card p-5">
            <label className="text-sm font-medium mb-2 block">Mode</label>
            <div
              className={cn(
                'inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium',
                mode === 'single_prompt'
                  ? 'bg-brand-500/10 text-brand-400'
                  : 'bg-purple-500/10 text-purple-400'
              )}
            >
              {mode === 'single_prompt' ? (
                <MessageSquare size={14} />
              ) : (
                <GitBranch size={14} />
              )}
              {mode === 'single_prompt' ? 'Single Prompt' : 'Conversational Flow'}
            </div>
            {mode === 'conversational_flow' && (
              <p className="text-xs text-[var(--text-muted)] mt-2">
                {selectedTemplate?.nodes?.length
                  ? 'A starter flow will be created from the template. You can edit it in the Workflow Editor after creation.'
                  : 'After creating the agent, you will be redirected to the Workflow Editor to design your conversational flow.'}
              </p>
            )}
          </div>

          {/* LLM */}
          <div className="dash-card p-5 space-y-3">
            <label className="text-sm font-medium block">LLM Provider</label>
            <select
              value={llmProvider}
              onChange={(e) => {
                setLlmProvider(e.target.value);
                setLlmModel(llmModels[e.target.value]?.[0] || '');
              }}
              className="input-base w-full"
            >
              <option value="openrouter">OpenRouter (DeepSeek V4 Flash)</option>
              <option value="groq">Groq</option>
              <option value="openai">OpenAI</option>
              <option value="gemini">Google Gemini</option>
              <option value="anthropic">Anthropic</option>
              <option value="commandcode">CommandCode (Discounted)</option>
              <option value="ollama">Ollama (Local)</option>
            </select>

            <label className="text-sm font-medium block">Model</label>
            <select
              value={llmModel}
              onChange={(e) => setLlmModel(e.target.value)}
              className="input-base w-full"
            >
              {(llmModels[llmProvider] || []).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>

          {/* Voice */}
          <div className="dash-card p-5 space-y-3">
            <label className="text-sm font-medium block">Voice</label>
            <select
              value={voiceId}
              onChange={(e) => setVoiceId(e.target.value)}
              className="input-base w-full"
            >
              {voices.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </div>

          {/* Recommended Tools Preview */}
          {selectedTemplate?.recommended_tools && selectedTemplate.recommended_tools.length > 0 && (
            <div className="dash-card p-5 space-y-3">
              <label className="text-sm font-medium block">Recommended Tools</label>
              <div className="flex flex-wrap gap-2">
                {selectedTemplate.recommended_tools.map((tool) => (
                  <span
                    key={tool}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                  >
                    <Sparkles size={12} />
                    {tool}
                  </span>
                ))}
              </div>
              <p className="text-xs text-[var(--text-muted)]">
                These tools will be available to the agent during calls.
                Connect Google Drive in Integrations to enable file access.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Actions */}
      <div className="flex justify-between">
        <button onClick={onBack} className="btn-ghost flex items-center gap-2">
          <ArrowLeft size={16} /> Back
        </button>
        <button
          onClick={onSave}
          disabled={saving || !name.trim() || !prompt.trim()}
          className="btn-primary flex items-center gap-2 disabled:opacity-50"
        >
          {saving ? (
            <>
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Creating...
            </>
          ) : (
            <>
              <CheckCircle size={16} />
              Create Agent
            </>
          )}
        </button>
      </div>
    </div>
  );
}
