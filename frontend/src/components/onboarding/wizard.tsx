'use client';

import { useState, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import {
  X,
  ChevronRight,
  ChevronLeft,
  Sparkles,
  Bot,
  BookOpen,
  Plug,
  MessageSquare,
  Zap,
  CheckCircle,
  Loader2,
  PartyPopper,
  Phone,
  Users,
  Send,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useOnboarding } from '@/hooks/useOnboarding';
import { TooltipField } from './tooltip-field';
import { IntegrationHelpButton } from '@/components/integrations/IntegrationHelpButton';
import {
  type Template,
  buildTemplateCategories,
  loadTemplates,
} from '@/lib/agent-templates';
import { agents as agentsApi, knowledgeBases as kbApi, playground as playgroundApi } from '@/lib/api';
import { useToast } from '@/components/ui/toast';

const WIZARD_STEPS = [
  { id: 0, label: 'Template', icon: Sparkles },
  { id: 1, label: 'Configure', icon: Bot },
  { id: 2, label: 'Knowledge', icon: BookOpen },
  { id: 3, label: 'Integrations', icon: Plug },
  { id: 4, label: 'Test', icon: MessageSquare },
] as const;

export function OnboardingWizard({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const { state, nextStep, prevStep, goToStep, complete, update } = useOnboarding();
  const { success, error } = useToast();
  const step = state.currentStep;

  // Wizard form state
  const [selectedTemplate, setSelectedTemplate] = useState<Template | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const [initialMessage, setInitialMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const [createdAgentId, setCreatedAgentId] = useState<number | null>(state.agentId);

  // KB step state
  const [kbName, setKbName] = useState('');
  const [kbContent, setKbContent] = useState('');
  const [kbFile, setKbFile] = useState<File | null>(null);
  const [kbCreatedId, setKbCreatedId] = useState<number | null>(state.kbId);

  // Integration step state
  const [integrationType, setIntegrationType] = useState<string | null>(null);

  // Test step state
  const [testMessage, setTestMessage] = useState('');
  const [testResponse, setTestResponse] = useState('');
  const [testLoading, setTestLoading] = useState(false);
  const [celebrated, setCelebrated] = useState(false);

  // Load existing progress
  useEffect(() => {
    if (open && selectedTemplate === null && state.agentId) {
      // Resume — try to load agent details
      agentsApi.get(state.agentId).then((data) => {
        const a = data.agent;
        setName(a.name);
        setPrompt(a.prompt_preamble);
        setInitialMessage(a.initial_message || '');
        setCreatedAgentId(a.id);
      }).catch(() => {});
    }
  }, [open, state.agentId]);

  useEffect(() => {
    if (!open) {
      return;
    }

    let cancelled = false;
    setTemplatesLoading(true);

    loadTemplates({ mode: 'single_prompt' })
      .then((items) => {
        if (!cancelled) {
          setTemplates(items);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setTemplates([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setTemplatesLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  const isLast = step === WIZARD_STEPS.length - 1;
  const isFirst = step === 0;

  async function handleCreateAgent() {
    if (!name.trim() || !prompt.trim() || !selectedTemplate) return;
    setSaving(true);
    try {
      const result = await agentsApi.create({
        name,
        prompt_preamble: prompt,
        initial_message: initialMessage || 'Hello! How can I help you today?',
        llm_provider: selectedTemplate.llm_provider as 'openai' | 'gemini' | 'groq' | 'anthropic',
        llm_model: selectedTemplate.llm_model,
        stt_provider: selectedTemplate.stt_provider as 'deepgram' | 'google' | 'azure' | 'assemblyai',
        stt_language: selectedTemplate.stt_language,
        tts_provider: selectedTemplate.tts_provider as 'deepgram' | 'elevenlabs' | 'azure' | 'gtts' | 'cartesia' | 'polly' | 'stream_elements',
        tts_voice_id: selectedTemplate.tts_voice_id,
        temperature: 0.7,
        max_tokens: 2048,
        mode: selectedTemplate.mode as 'single_prompt' | 'conversational_flow',
        template_id: selectedTemplate.id,
      });
      setCreatedAgentId(result.agent.id);
      update({ agentId: result.agent.id });
      success('Agent Created', `${name} is ready!`);
      nextStep();
    } catch {
      error('Failed to create agent');
    } finally {
      setSaving(false);
    }
  }

  async function handleCreateKB() {
    if (!kbName.trim()) {
      // Skip KB step
      nextStep();
      return;
    }
    setSaving(true);
    try {
      const result = await kbApi.create({
        name: kbName.trim(),
        content: kbContent || undefined,
      });
      const kbId = result.knowledge_base.id;
      setKbCreatedId(kbId);
      update({ kbId });

      if (kbFile) {
        await kbApi.upload(kbId, kbFile);
      }

      // Link KB to agent
      if (createdAgentId) {
        await agentsApi.update(createdAgentId, { knowledge_base_id: kbId });
      }

      success('Knowledge Base Linked', 'Your agent now has document context');
      nextStep();
    } catch {
      error('Failed to create knowledge base');
    } finally {
      setSaving(false);
    }
  }

  async function handleTestMessage() {
    if (!testMessage.trim() || !createdAgentId) return;
    setTestLoading(true);
    try {
      const data = await playgroundApi.message(createdAgentId, testMessage.trim());
      setTestResponse(data.response);
      if (!celebrated) setCelebrated(true);
    } catch {
      error('Test failed');
    } finally {
      setTestLoading(false);
    }
  }

  function handleFinish() {
    complete();
    onClose();
    if (createdAgentId) {
      router.push(`/dashboard/playground?agent=${createdAgentId}`);
    }
  }

  function handleSkip() {
    if (step === 2 || step === 3) {
      nextStep();
    }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[var(--bg-primary)]/80 backdrop-blur-sm">
      <div className="bg-[var(--bg-secondary)] rounded-2xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-color)] flex-shrink-0">
          <div className="flex items-center gap-2">
            <Zap size={18} className="text-[var(--accent)]" />
            <h2 className="font-semibold">Getting Started</h2>
          </div>
          <button onClick={onClose} className="btn-ghost p-1">
            <X size={18} />
          </button>
        </div>

        {/* Progress bar */}
        <div className="px-6 pt-4 flex-shrink-0">
          <div className="flex items-center gap-2">
            {WIZARD_STEPS.map((s, i) => (
              <div key={s.id} className="flex items-center gap-2 flex-1">
                <div
                  className={cn(
                    'w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium transition-colors',
                    i < step
                      ? 'bg-green-500/20 text-green-400'
                      : i === step
                      ? 'bg-[var(--accent)] text-[var(--text-inverse)]'
                      : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'
                  )}
                >
                  {i < step ? <CheckCircle size={14} /> : i + 1}
                </div>
                <span
                  className={cn(
                    'text-xs hidden sm:block',
                    i <= step ? 'text-[var(--text-secondary)]' : 'text-[var(--text-muted)]'
                  )}
                >
                  {s.label}
                </span>
                {i < WIZARD_STEPS.length - 1 && (
                  <div
                    className={cn(
                      'flex-1 h-0.5 rounded-full',
                      i < step ? 'bg-green-500/30' : 'bg-[var(--border-color)]'
                    )}
                  />
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {step === 0 && (
            <StepTemplate
              selected={selectedTemplate}
              templates={templates}
              loading={templatesLoading}
              onSelect={(t) => { setSelectedTemplate(t); setName(t.name); setPrompt(t.global_prompt); setInitialMessage(t.initial_message); }}
            />
          )}
          {step === 1 && (
            <StepConfigure
              name={name}
              setName={setName}
              prompt={prompt}
              setPrompt={setPrompt}
              initialMessage={initialMessage}
              setInitialMessage={setInitialMessage}
            />
          )}
          {step === 2 && (
            <StepKnowledge
              kbName={kbName}
              setKbName={setKbName}
              kbContent={kbContent}
              setKbContent={setKbContent}
              kbFile={kbFile}
              setKbFile={setKbFile}
            />
          )}
          {step === 3 && (
            <StepIntegrations
              selected={integrationType}
              onSelect={setIntegrationType}
            />
          )}
          {step === 4 && (
            <StepTest
              agentId={createdAgentId}
              agentName={name}
              testMessage={testMessage}
              setTestMessage={setTestMessage}
              testResponse={testResponse}
              testLoading={testLoading}
              celebrated={celebrated}
              onSend={handleTestMessage}
            />
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[var(--border-color)] flex items-center justify-between flex-shrink-0">
          <button
            onClick={isFirst ? onClose : prevStep}
            className="btn-ghost"
            disabled={saving}
          >
            {isFirst ? 'Close' : <><ChevronLeft size={14} /> Back</>}
          </button>

          <div className="flex items-center gap-3">
            {(step === 2 || step === 3) && (
              <button onClick={handleSkip} className="btn-ghost text-sm" disabled={saving}>
                Skip
              </button>
            )}
            {isLast ? (
              <button onClick={handleFinish} className="btn-primary">
                Finish <CheckCircle size={14} />
              </button>
            ) : step === 1 ? (
              <button
                onClick={handleCreateAgent}
                disabled={!name.trim() || !prompt.trim() || saving}
                className="btn-primary disabled:opacity-40"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <>
                  Create Agent <ChevronRight size={14} />
                </>}
              </button>
            ) : step === 2 ? (
              <button
                onClick={handleCreateKB}
                disabled={saving}
                className="btn-primary disabled:opacity-40"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <>
                  {kbName.trim() ? 'Save & Continue' : 'Skip & Continue'} <ChevronRight size={14} />
                </>}
              </button>
            ) : step === 3 ? (
              <button onClick={nextStep} className="btn-primary">
                Continue <ChevronRight size={14} />
              </button>
            ) : (
              <button
                onClick={() => selectedTemplate && nextStep()}
                disabled={!selectedTemplate}
                className="btn-primary disabled:opacity-40 disabled:cursor-not-allowed"
                title={!selectedTemplate ? 'Select a template to continue' : undefined}
              >
                Next <ChevronRight size={14} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Step 1: Template Selection ─────────────────────────────── */

function StepTemplate({
  selected,
  templates,
  loading,
  onSelect,
}: {
  selected: Template | null;
  templates: Template[];
  loading: boolean;
  onSelect: (t: Template) => void;
}) {
  const [category, setCategory] = useState('all');
  const categories = useMemo(() => buildTemplateCategories(templates), [templates]);
  const filtered = useMemo(
    () => templates.filter((t) => (category === 'all' || t.category === category) && t.mode === 'single_prompt'),
    [templates, category]
  );

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold mb-1">Choose a Template</h3>
        <p className="text-sm text-[var(--text-muted)]">
          Start with a pre-built template or customize your own agent from scratch.
        </p>
      </div>

      <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
        {categories.map((c) => (
          <button
            key={c.id}
            onClick={() => setCategory(c.id)}
            className={cn(
              'px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors shrink-0',
              category === c.id
                ? 'bg-[var(--accent)] text-[var(--text-inverse)]'
                : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)] hover:bg-[var(--border-hover)]'
            )}
          >
            {c.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="p-4 rounded-xl border border-[var(--border-color)] bg-[var(--bg-tertiary)] animate-pulse">
              <div className="h-5 w-2/3 rounded bg-[var(--border-color)] mb-3" />
              <div className="h-3 w-full rounded bg-[var(--border-color)] mb-2" />
              <div className="h-3 w-5/6 rounded bg-[var(--border-color)]" />
            </div>
          ))}
        </div>
      ) : filtered.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {filtered.map((template) => {
            const Icon = template.icon;
            return (
              <button
                key={template.id}
                onClick={() => onSelect(template)}
                className={cn(
                  'text-left p-4 rounded-xl border transition-all',
                  selected?.id === template.id
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10 shadow-lg shadow-[var(--accent)]/5'
                    : 'border-[var(--border-color)] bg-[var(--bg-tertiary)] hover:border-[var(--border-hover)]'
                )}
              >
                <div className="flex items-center gap-2 mb-2">
                  <Icon size={18} className="text-[var(--accent)]" />
                  <h4 className="font-medium text-sm">{template.name}</h4>
                </div>
                <p className="text-xs text-[var(--text-muted)] line-clamp-2">{template.description}</p>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-[var(--border-color)] bg-[var(--bg-tertiary)] p-6 text-center text-sm text-[var(--text-muted)]">
          No templates match this category.
        </div>
      )}
    </div>
  );
}

/* ── Step 2: Configure Agent ─────────────────────────────────── */

function StepConfigure({
  name, setName,
  prompt, setPrompt,
  initialMessage, setInitialMessage,
}: {
  name: string; setName: (v: string) => void;
  prompt: string; setPrompt: (v: string) => void;
  initialMessage: string; setInitialMessage: (v: string) => void;
}) {
  return (
    <div className="space-y-5 max-w-xl mx-auto">
      <div>
        <h3 className="text-lg font-semibold mb-1">Configure Your Agent</h3>
        <p className="text-sm text-[var(--text-muted)]">
          Give your agent a name, greeting, and instructions for how it should behave.
        </p>
      </div>

      <TooltipField
        label="Agent Name"
        tooltip="This is how your agent will appear in the dashboard and playground. Choose something descriptive like 'Support Bot' or 'Booking Assistant'."
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g., Restaurant Booking Assistant"
          className="input-base w-full"
        />
      </TooltipField>

      <TooltipField
        label="First Greeting"
        tooltip="The very first thing your agent says when a conversation starts. Keep it friendly and short."
      >
        <input
          value={initialMessage}
          onChange={(e) => setInitialMessage(e.target.value)}
          placeholder="Hello! How can I help you today?"
          className="input-base w-full"
        />
      </TooltipField>

      <TooltipField
        label="System Prompt"
        tooltip="The main instructions that define your agent's personality, tone, and capabilities. Be specific about what the agent should and shouldn't do."
      >
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="You are a helpful restaurant booking assistant..."
          rows={6}
          className="input-base w-full resize-none"
        />
      </TooltipField>
    </div>
  );
}

/* ── Step 3: Knowledge Base ────────────────────────────────── */

function StepKnowledge({
  kbName, setKbName,
  kbContent, setKbContent,
  kbFile, setKbFile,
}: {
  kbName: string; setKbName: (v: string) => void;
  kbContent: string; setKbContent: (v: string) => void;
  kbFile: File | null; setKbFile: (f: File | null) => void;
}) {
  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) setKbFile(f);
  };

  return (
    <div className="space-y-5 max-w-xl mx-auto">
      <div>
        <h3 className="text-lg font-semibold mb-1">Add Knowledge (Optional)</h3>
        <p className="text-sm text-[var(--text-muted)]">
          Upload documents or paste text so your agent can answer questions from real data.
          You can skip this and add it later.
        </p>
      </div>

      <TooltipField
        label="Knowledge Base Name"
        tooltip="A short name to identify this document collection, e.g., 'Menu PDF' or 'FAQ'."
      >
        <input
          value={kbName}
          onChange={(e) => setKbName(e.target.value)}
          placeholder="e.g., Product Manual"
          className="input-base w-full"
        />
      </TooltipField>

      <TooltipField
        label="Paste Text (Optional)"
        tooltip="You can paste plain text directly. It will be automatically chunked into retrievable segments."
      >
        <textarea
          value={kbContent}
          onChange={(e) => setKbContent(e.target.value)}
          placeholder="Paste relevant text here..."
          rows={5}
          className="input-base w-full resize-none"
        />
      </TooltipField>

      <div>
        <label className="text-sm font-medium mb-1.5 block">Or Upload a File</label>
        <div className="flex items-center gap-3">
          <label className="btn-secondary cursor-pointer text-sm">
            <input type="file" accept=".txt,.pdf" onChange={handleFile} className="hidden" />
            {kbFile ? kbFile.name : 'Choose .txt or .pdf'}
          </label>
          {kbFile && (
            <button onClick={() => setKbFile(null)} className="text-xs text-red-400 hover:text-red-300">
              Remove
            </button>
          )}
        </div>
        <p className="text-[11px] text-[var(--text-muted)] mt-1">Maximum file size: 10MB</p>
      </div>
    </div>
  );
}

/* ── Step 4: Integrations ───────────────────────────────────── */

function StepIntegrations({
  selected,
  onSelect,
}: {
  selected: string | null;
  onSelect: (v: string | null) => void;
}) {
  const integrations = [
    {
      id: 'google_calendar',
      name: 'Google Calendar',
      description: 'Allow your agent to check availability and book appointments.',
      icon: '📅',
    },
    {
      id: 'google_sheets',
      name: 'Google Sheets',
      description: 'Read and write data to spreadsheets during calls.',
      icon: '📊',
    },
    {
      id: 'slack',
      name: 'Slack',
      description: 'Post call summaries and alerts to your team channels.',
      icon: '💬',
    },
  ];

  return (
    <div className="space-y-4 max-w-xl mx-auto">
      <div>
        <h3 className="text-lg font-semibold mb-1">Connect Integrations (Optional)</h3>
        <p className="text-sm text-[var(--text-muted)]">
          Link external tools so your agent can take real actions during conversations.
          Skip this if you want a simple Q&A agent.
        </p>
      </div>

      <div className="space-y-3">
        {integrations.map((i) => (
          <button
            key={i.id}
            onClick={() => onSelect(selected === i.id ? null : i.id)}
            className={cn(
              'w-full text-left p-4 rounded-xl border transition-all flex items-start gap-3 group relative',
              selected === i.id
                ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                : 'border-[var(--border-color)] bg-[var(--bg-tertiary)] hover:border-[var(--border-hover)]'
            )}
          >
            <span className="text-2xl">{i.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <h4 className="font-medium text-sm">{i.name}</h4>
                <IntegrationHelpButton
                  typeId={i.id}
                  size="sm"
                  title={`Learn about ${i.name}`}
                  className="opacity-0 group-hover:opacity-100 transition-opacity"
                />
              </div>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">{i.description}</p>
            </div>
          </button>
        ))}
      </div>

      <div className="bg-[var(--bg-tertiary)] rounded-lg p-3 text-xs text-[var(--text-muted)]">
        <strong className="text-[var(--text-secondary)]">MCP Support:</strong> VOIA supports the{' '}
        <a href="https://modelcontextprotocol.io" target="_blank" rel="noopener" className="text-[var(--accent)] hover:underline">
          Model Context Protocol
        </a>{' '}
        for custom integrations. You can add your own tools in the agent settings after setup.
      </div>
    </div>
  );
}

/* ── Step 5: Live Test ───────────────────────────────────────── */

function StepTest({
  agentId,
  agentName,
  testMessage,
  setTestMessage,
  testResponse,
  testLoading,
  celebrated,
  onSend,
}: {
  agentId: number | null;
  agentName: string;
  testMessage: string;
  setTestMessage: (v: string) => void;
  testResponse: string;
  testLoading: boolean;
  celebrated: boolean;
  onSend: () => void;
}) {
  return (
    <div className="space-y-4 max-w-xl mx-auto">
      <div className="text-center">
        {celebrated ? (
          <div className="animate-bounce">
            <PartyPopper size={40} className="mx-auto text-[var(--accent)] mb-2" />
          </div>
        ) : (
          <MessageSquare size={32} className="mx-auto text-[var(--text-muted)] mb-2" />
        )}
        <h3 className="text-lg font-semibold">
          {celebrated ? 'Your agent is live!' : 'Test Your Agent'}
        </h3>
        <p className="text-sm text-[var(--text-muted)]">
          {celebrated
            ? `Great job! ${agentName || 'Your agent'} responded. Try another question or finish setup.`
            : 'Send a message to see how your agent responds with the knowledge base you configured.'}
        </p>
      </div>

      {agentId ? (
        <div className="card-base p-4 space-y-3">
          <div className="flex gap-2">
            <input
              value={testMessage}
              onChange={(e) => setTestMessage(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && onSend()}
              placeholder="Type a test message..."
              className="input-base flex-1 text-sm"
            />
            <button
              onClick={onSend}
              disabled={!testMessage.trim() || testLoading}
              className="btn-primary px-3 disabled:opacity-40"
            >
              {testLoading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            </button>
          </div>

          {testResponse && (
            <div className="bg-[var(--bg-tertiary)] rounded-lg p-3 border border-[var(--border-color)]">
              <p className="text-xs text-[var(--text-muted)] mb-1">Agent response:</p>
              <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{testResponse}</p>
            </div>
          )}
        </div>
      ) : (
        <p className="text-sm text-amber-400 text-center">
          Agent not found. Go back to configure step.
        </p>
      )}

      {/* Next step cards */}
      {celebrated && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
          <button
            onClick={() => window.location.href = '/dashboard/numbers'}
            className="card-base p-4 text-left hover:border-[var(--accent)] transition-colors"
          >
            <Phone size={20} className="text-[var(--accent)] mb-2" />
            <h4 className="text-sm font-medium">Buy Phone Number</h4>
            <p className="text-[11px] text-[var(--text-muted)] mt-1">Connect a real phone line</p>
          </button>
          <button
            onClick={() => window.location.href = '/dashboard/campaigns'}
            className="card-base p-4 text-left hover:border-[var(--accent)] transition-colors"
          >
            <Send size={20} className="text-green-400 mb-2" />
            <h4 className="text-sm font-medium">Run Campaign</h4>
            <p className="text-[11px] text-[var(--text-muted)] mt-1">Start outbound calls</p>
          </button>
          <button
            onClick={() => window.location.href = '/dashboard/settings'}
            className="card-base p-4 text-left hover:border-[var(--accent)] transition-colors"
          >
            <Users size={20} className="text-blue-400 mb-2" />
            <h4 className="text-sm font-medium">Invite Team</h4>
            <p className="text-[11px] text-[var(--text-muted)] mt-1">Collaborate with others</p>
          </button>
        </div>
      )}
    </div>
  );
}
