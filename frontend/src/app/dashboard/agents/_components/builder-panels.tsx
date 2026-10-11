"use client";

import { useState, memo } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import {
  Wrench,
  BookOpen,
  Library,
  Volume2,
  PhoneCall,
  Webhook,
  HardDrive,
  Calendar,
  Cloud,
  ShieldCheck,
  ChevronDown,
  ChevronRight,
  Check,
  AlertTriangle,
  Key,
  Table,
  MessageCircle,
  Send,
  Mail,
  MessageSquare,
  Settings,
  Database,
  FileText,
  Loader2,
} from "lucide-react";
import { CreateAgentRequest, PlatformTool, LLMProvider, STTProvider, TTSProvider } from "@/lib/types";
import { ToolsSection } from "./tools-section";
import { IntegrationHelpButton } from "@/components/integrations/IntegrationHelpButton";

/* ─── Deepgram Voices ───────────────────────────────────── */
const DEEPGRAM_STT_MODELS = [
  { value: "nova-3", label: "Nova 3 — Best accuracy (Recommended)" },
  { value: "nova-3-phonecall", label: "Nova 3 Phonecall — Telephony optimized" },
  { value: "nova-3-conversationalai", label: "Nova 3 Conversational AI — Voice agents" },
  { value: "nova-2-phonecall", label: "Nova 2 Phonecall — Legacy telephony" },
  { value: "nova-2", label: "Nova 2 — General purpose" },
  { value: "nova-2-meeting", label: "Nova 2 Meeting — Multi-speaker" },
  { value: "nova-2-drivethru", label: "Nova 2 Drive-Thru — Noisy environments" },
  { value: "enhanced", label: "Enhanced — Legacy optimized" },
];

const DEEPGRAM_VOICES = [
  { value: "aura-asteria-en", label: "Asteria — Female, US (Conversational)" },
  { value: "aura-luna-en", label: "Luna — Female, US (Conversational)" },
  { value: "aura-stella-en", label: "Stella — Female, US (Conversational)" },
  { value: "aura-athena-en", label: "Athena — Female, UK (Professional)" },
  { value: "aura-hera-en", label: "Hera — Female, US (Professional)" },
  { value: "aura-orion-en", label: "Orion — Male, US (Conversational)" },
  { value: "aura-arcas-en", label: "Arcas — Male, US (Conversational)" },
  { value: "aura-perseus-en", label: "Perseus — Male, US (Conversational)" },
  { value: "aura-angus-en", label: "Angus — Male, Irish (Warm)" },
  { value: "aura-orpheus-en", label: "Orpheus — Male, US (Professional)" },
  { value: "aura-helios-en", label: "Helios — Male, UK (Professional)" },
  { value: "aura-zeus-en", label: "Zeus — Male, US (Authoritative)" },
];

/* ─── Collapsible Section Wrapper ──────────────────────── */
function Section({
  title,
  icon: Icon,
  children,
  defaultOpen = false,
}: {
  title: string;
  icon: React.ElementType;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-[var(--glass-border)] rounded-xl bg-[var(--bg-primary)] overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-[var(--bg-tertiary)] transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <Icon size={16} className="text-brand-400" />
          <span className="text-sm font-medium">{title}</span>
        </div>
        {open ? (
          <ChevronDown size={14} className="text-[var(--text-muted)]" />
        ) : (
          <ChevronRight size={14} className="text-[var(--text-muted)]" />
        )}
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-4 border-t border-[var(--glass-border)] pt-4">
          {children}
        </div>
      )}
    </div>
  );
}

/* ─── Panel Props ──────────────────────────────────────── */
interface PanelsProps {
  formData: CreateAgentRequest;
  onChange: <K extends keyof CreateAgentRequest>(field: K, value: CreateAgentRequest[K]) => void;

  tools: PlatformTool[];
  enabledTools: string[];
  onToggleTool: (toolId: string) => void;
  toolSaveStatus?: 'idle' | 'saving' | 'saved' | 'error';

  kbOptions: Array<{ id: number; name: string }>;
  handbookEnabled: boolean;
  handbookContent: string;
  onToggleHandbook: (v: boolean) => void;
  onChangeHandbook: (v: string) => void;

  driveOptions: Array<{ id: number; name: string }>;
  allIntegrations: Array<{ id: number; name: string; service_type: string }>;
  agentId?: number;

  llmProviders: Array<{ id: string; name: string }>;
  llmModels: Record<string, string[]>;
  sttProviders: Array<{ id: string; name: string }>;
  ttsProviders: Array<{ id: string; name: string }>;
}

function BuilderPanels({
  formData,
  onChange,
  tools,
  enabledTools,
  onToggleTool,
  toolSaveStatus = 'idle',
  kbOptions,
  handbookEnabled,
  handbookContent,
  onToggleHandbook,
  onChangeHandbook,
  driveOptions,
  allIntegrations,
  agentId,
  llmProviders,
  llmModels,
  sttProviders,
  ttsProviders,
}: PanelsProps) {
  const [activeTab, setActiveTab] = useState<"tools" | "settings" | "resources">("tools");

  const missingIntegrationTools = tools.filter(
    (t) => enabledTools.includes(t.id) && t.integration_required && !t.integration_connected
  );

  const tabs = [
    { id: "tools" as const, label: "Tools", icon: Wrench },
    { id: "settings" as const, label: "Settings", icon: Settings },
    { id: "resources" as const, label: "Resources", icon: Database },
  ];

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="flex items-center gap-1 border-b border-[var(--glass-border)] mb-3 shrink-0">
        {tabs.map((t) => {
          const Icon = t.icon;
          const active = activeTab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors border-b-2 -mb-px",
                active
                  ? "text-brand-400 border-brand-400"
                  : "text-[var(--text-muted)] border-transparent hover:text-[var(--text-primary)]"
              )}
            >
              <Icon size={13} />
              {t.label}
              {t.id === 'tools' && toolSaveStatus === 'saving' && (
                <Loader2 size={11} className="animate-spin text-brand-400 ml-0.5" />
              )}
              {t.id === 'tools' && toolSaveStatus === 'saved' && (
                <Check size={11} className="text-emerald-400 ml-0.5" />
              )}
            </button>
          );
        })}
      </div>

      {/* Scrollable tab content */}
      <div className="flex-1 overflow-y-auto min-h-0 space-y-3">
        {activeTab === "tools" && (
          <>
            {/* Tool Usage Instructions */}
            <div className="mb-3">
              <label className="block text-xs font-medium mb-1.5 flex items-center gap-1.5">
                <BookOpen size={12} className="text-brand-400" />
                Tool Usage Instructions
              </label>
          <textarea
            value={formData.tool_instructions ?? ""}
            onChange={(e) => onChange("tool_instructions", e.target.value || null)}
            rows={3}
            placeholder="e.g. When booking appointments, only offer 30-minute slots between 9am–5pm. When reading the inventory sheet, always sort by date descending."
            className="w-full input-base resize-none text-xs"
          />
          <p className="text-[10px] text-[var(--text-muted)] mt-1">
            These instructions are injected into each enabled tool's description so the LLM follows them during calls.
          </p>
          <p className="text-[10px] text-amber-400/80 mt-1 flex items-center gap-1">
            <AlertTriangle size={10} />
            Do not include sensitive data (passwords, API keys, personal info) — instructions are sent to the LLM provider.
          </p>
        </div>

        {missingIntegrationTools.length > 0 && (
          <div className="p-2.5 rounded-lg border border-amber-500/20 bg-amber-500/5 text-amber-200 text-xs">
            <div className="flex items-center gap-1.5 font-medium">
              <AlertTriangle size={12} />
              {missingIntegrationTools.length} enabled tool
              {missingIntegrationTools.length > 1 ? "s" : ""} missing integration
            </div>
            <p className="mt-1 text-[10px]">
              {[
                ...new Set(
                  missingIntegrationTools.map((t) => t.integration_label).filter(Boolean)
                ),
              ].join(", ")}
              .{" "}
              <Link
                href="/dashboard/integrations"
                className="underline text-amber-300 hover:text-amber-100"
              >
                Connect →
              </Link>
            </p>
          </div>
        )}
        <div className="grid grid-cols-2 gap-2">
          {tools.map((tool) => {
            const isEnabled = enabledTools.includes(tool.id);
            const isMissing = tool.integration_required && !tool.integration_connected;
            const overrides = formData.integration_overrides || {};
            const overrideId = tool.integration_type ? overrides[tool.integration_type] : undefined;
            const overrideName = overrideId ? allIntegrations.find((i) => i.id === overrideId)?.name : undefined;
            return (
              <button
                key={tool.id}
                onClick={() => {
                  if (!isMissing || isEnabled) onToggleTool(tool.id);
                }}
                disabled={isMissing && !isEnabled}
                className={cn(
                  "text-left p-2.5 rounded-lg border text-xs transition-all duration-150 relative",
                  isEnabled && !isMissing
                    ? "border-[var(--border-active)] bg-[var(--accent-muted)] shadow-glow-sm"
                    : isMissing
                    ? "border-amber-500/20 bg-amber-500/5 opacity-70 cursor-not-allowed"
                    : "border-[var(--glass-border)] bg-[var(--bg-primary)] hover:border-[var(--border-hover)]"
                )}
              >
                {isMissing && (
                  <span className="absolute top-1.5 right-1.5 text-[9px] font-medium text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded">
                    Needs {tool.integration_label}
                  </span>
                )}
                {!isMissing && tool.integration_connected && tool.integration_required && !overrideName && (
                  <span className="absolute top-1.5 right-1.5 text-[9px] font-medium text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">
                    Ready
                  </span>
                )}
                {overrideName && (
                  <span className="absolute top-1.5 right-1.5 text-[9px] font-medium text-brand-400 bg-brand-500/10 px-1.5 py-0.5 rounded truncate max-w-[80px]">
                    {overrideName}
                  </span>
                )}
                {tool.integration_type && (
                  <span className="absolute bottom-1.5 right-1.5">
                    <IntegrationHelpButton
                      typeId={tool.integration_type}
                      size="sm"
                      title={`Learn about ${tool.integration_label || tool.name}`}
                    />
                  </span>
                )}
                <p className="font-medium truncate pr-16">{tool.name}</p>
                <p className="text-[var(--text-muted)] truncate mt-0.5">
                  {tool.description.slice(0, 100)}
                </p>
              </button>
            );
          })}
        </div>

        {/* MCP Bindings — Google Drive scope */}
        {enabledTools.includes("read_drive_file") && tools.find((t) => t.id === "read_drive_file")?.integration_connected && (
          <div className="mt-3 pt-3 border-t border-[var(--glass-border)]">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-medium mb-1.5 flex items-center gap-1.5">
                <Cloud size={12} className="text-brand-400" />
                Google Drive Scope
              </label>
              {formData.google_drive_integration_id && (
                <button
                  onClick={() => onChange("google_drive_integration_id", null)}
                  className="text-[10px] text-red-400 hover:text-red-300 transition-colors"
                >
                  Revoke
                </button>
              )}
            </div>
            <select
              value={formData.google_drive_integration_id ?? ""}
              onChange={(e) => onChange("google_drive_integration_id", e.target.value ? Number(e.target.value) : null)}
              className="w-full input-base text-sm"
            >
              <option value="">Full Drive Access</option>
              {driveOptions.map((d) => (
                <option key={d.id} value={d.id}>{d.name}</option>
              ))}
            </select>
            <p className="text-[10px] text-[var(--text-muted)] mt-1">
              Restrict this agent to a specific Drive folder or leave empty for full access.
            </p>
            {/* Warning when no files are bound */}
            {(() => {
              const driveBindings = (formData.mcp_bindings as Record<string, { file_ids?: string[] }>)?.drive;
              const fileCount = driveBindings?.file_ids?.length ?? 0;
              if (fileCount === 0) {
                return (
                  <div className="mt-2 p-2 rounded-lg border border-amber-500/20 bg-amber-500/5 text-amber-200 text-xs flex items-start gap-2">
                    <AlertTriangle size={12} className="text-amber-400 shrink-0 mt-0.5" />
                    <div>
                      <p className="font-medium">No files bound</p>
                      <p className="mt-0.5">The agent won't know which files to read. Scroll down to "Bound Resources" below to select specific Drive files for this agent.</p>
                    </div>
                  </div>
                );
              }
              return (
                <p className="text-[10px] text-emerald-400 mt-1 flex items-center gap-1">
                  <Check size={10} /> {fileCount} file{fileCount !== 1 ? 's' : ''} bound to this agent
                </p>
              );
            })()}
          </div>
        )}

        {/* Per-Agent Integration Selectors */}
        {(() => {
          const overrides = formData.integration_overrides || {};
          const setOverride = (type: string, id: number | null) => {
            onChange("integration_overrides", { ...overrides, [type]: id });
          };
          const byType = (type: string) => allIntegrations.filter((i) => i.service_type === type);

          return (
            <>
              {/* Google Sheets */}
              {(enabledTools.includes("read_sheet") || enabledTools.includes("append_sheet")) && byType("google_sheets").length > 0 && (
                <div className="mt-3 pt-3 border-t border-[var(--glass-border)]">
                  <div className="flex items-center justify-between">
                    <label className="block text-xs font-medium mb-1.5 flex items-center gap-1.5">
                      <Table size={12} className="text-green-400" />
                      Google Sheets Integration
                    </label>
                    {overrides["google_sheets"] && (
                      <button
                        onClick={() => setOverride("google_sheets", null)}
                        className="text-[10px] text-red-400 hover:text-red-300 transition-colors"
                      >
                        Revoke
                      </button>
                    )}
                  </div>
                  <select
                    value={overrides["google_sheets"] ?? ""}
                    onChange={(e) => setOverride("google_sheets", e.target.value ? Number(e.target.value) : null)}
                    className="w-full input-base text-sm"
                  >
                    <option value="">Use default (first connected)</option>
                    {byType("google_sheets").map((i) => (
                      <option key={i.id} value={i.id}>{i.name}</option>
                    ))}
                  </select>
                  <p className="text-[10px] text-[var(--text-muted)] mt-1">
                    Choose which spreadsheet integration this agent uses. The agent will access sheets from this account at runtime — use tool instructions to specify which sheet.
                  </p>
                </div>
              )}

              {/* Google Calendar */}
              {(enabledTools.includes("check_calendar") || enabledTools.includes("create_event") || enabledTools.includes("book_appointment")) && byType("google_calendar").length > 0 && (
                <div className="mt-3 pt-3 border-t border-[var(--glass-border)]">
                  <div className="flex items-center justify-between">
                    <label className="block text-xs font-medium mb-1.5 flex items-center gap-1.5">
                      <Calendar size={12} className="text-blue-400" />
                      Google Calendar Integration
                    </label>
                    {overrides["google_calendar"] && (
                      <button
                        onClick={() => setOverride("google_calendar", null)}
                        className="text-[10px] text-red-400 hover:text-red-300 transition-colors"
                      >
                        Revoke
                      </button>
                    )}
                  </div>
                  <select
                    value={overrides["google_calendar"] ?? ""}
                    onChange={(e) => setOverride("google_calendar", e.target.value ? Number(e.target.value) : null)}
                    className="w-full input-base text-sm"
                  >
                    <option value="">Use default (first connected)</option>
                    {byType("google_calendar").map((i) => (
                      <option key={i.id} value={i.id}>{i.name}</option>
                    ))}
                  </select>
                  <p className="text-[10px] text-[var(--text-muted)] mt-1">
                    Choose which calendar integration this agent uses.
                  </p>
                </div>
              )}

              {/* WhatsApp Cloud */}
              {enabledTools.includes("send_whatsapp") && byType("whatsapp_cloud").length > 0 && (
                <div className="mt-3 pt-3 border-t border-[var(--glass-border)]">
                  <div className="flex items-center justify-between">
                    <label className="block text-xs font-medium mb-1.5 flex items-center gap-1.5">
                      <MessageCircle size={12} className="text-emerald-400" />
                      WhatsApp Integration
                    </label>
                    {overrides["whatsapp_cloud"] && (
                      <button
                        onClick={() => setOverride("whatsapp_cloud", null)}
                        className="text-[10px] text-red-400 hover:text-red-300 transition-colors"
                      >
                        Revoke
                      </button>
                    )}
                  </div>
                  <select
                    value={overrides["whatsapp_cloud"] ?? ""}
                    onChange={(e) => setOverride("whatsapp_cloud", e.target.value ? Number(e.target.value) : null)}
                    className="w-full input-base text-sm"
                  >
                    <option value="">Use default (first connected)</option>
                    {byType("whatsapp_cloud").map((i) => (
                      <option key={i.id} value={i.id}>{i.name}</option>
                    ))}
                  </select>
                  <p className="text-[10px] text-[var(--text-muted)] mt-1">
                    Choose which WhatsApp integration this agent uses.
                  </p>
                </div>
              )}

              {/* Telegram Bot */}
              {enabledTools.includes("send_telegram") && byType("telegram_bot").length > 0 && (
                <div className="mt-3 pt-3 border-t border-[var(--glass-border)]">
                  <div className="flex items-center justify-between">
                    <label className="block text-xs font-medium mb-1.5 flex items-center gap-1.5">
                      <Send size={12} className="text-sky-400" />
                      Telegram Integration
                    </label>
                    {overrides["telegram_bot"] && (
                      <button
                        onClick={() => setOverride("telegram_bot", null)}
                        className="text-[10px] text-red-400 hover:text-red-300 transition-colors"
                      >
                        Revoke
                      </button>
                    )}
                  </div>
                  <select
                    value={overrides["telegram_bot"] ?? ""}
                    onChange={(e) => setOverride("telegram_bot", e.target.value ? Number(e.target.value) : null)}
                    className="w-full input-base text-sm"
                  >
                    <option value="">Use default (first connected)</option>
                    {byType("telegram_bot").map((i) => (
                      <option key={i.id} value={i.id}>{i.name}</option>
                    ))}
                  </select>
                  <p className="text-[10px] text-[var(--text-muted)] mt-1">
                    Choose which Telegram integration this agent uses.
                  </p>
                </div>
              )}

              {/* Email (SMTP) */}
              {enabledTools.includes("send_email") && (
                <div className="mt-3 pt-3 border-t border-[var(--glass-border)]">
                  <div className="flex items-center justify-between">
                    <label className="block text-xs font-medium mb-1.5 flex items-center gap-1.5">
                      <Mail size={12} className="text-orange-400" />
                      Email Integration
                    </label>
                    {overrides["email"] && (
                      <button
                        onClick={() => setOverride("email", null)}
                        className="text-[10px] text-red-400 hover:text-red-300 transition-colors"
                      >
                        Revoke
                      </button>
                    )}
                  </div>
                  {byType("email").length > 0 ? (
                    <>
                      <select
                        value={overrides["email"] ?? ""}
                        onChange={(e) => setOverride("email", e.target.value ? Number(e.target.value) : null)}
                        className="w-full input-base text-sm"
                      >
                        <option value="">Use default (first connected)</option>
                        {byType("email").map((i) => (
                          <option key={i.id} value={i.id}>{i.name}</option>
                        ))}
                      </select>
                      <p className="text-[10px] text-[var(--text-muted)] mt-1">
                        Choose which email integration this agent uses.
                      </p>
                    </>
                  ) : (
                    <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
                      <Check size={12} className="text-emerald-400 flex-shrink-0" />
                      <p className="text-[10px] text-emerald-300">
                        Using platform SMTP (Gmail). Connect your own email integration in Settings to override.
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* SMS (Twilio) */}
              {enabledTools.includes("send_sms") && byType("sms").length > 0 && (
                <div className="mt-3 pt-3 border-t border-[var(--glass-border)]">
                  <div className="flex items-center justify-between">
                    <label className="block text-xs font-medium mb-1.5 flex items-center gap-1.5">
                      <MessageSquare size={12} className="text-purple-400" />
                      SMS Integration
                    </label>
                    {overrides["sms"] && (
                      <button
                        onClick={() => setOverride("sms", null)}
                        className="text-[10px] text-red-400 hover:text-red-300 transition-colors"
                      >
                        Revoke
                      </button>
                    )}
                  </div>
                  <select
                    value={overrides["sms"] ?? ""}
                    onChange={(e) => setOverride("sms", e.target.value ? Number(e.target.value) : null)}
                    className="w-full input-base text-sm"
                  >
                    <option value="">Use default (first connected)</option>
                    {byType("sms").map((i) => (
                      <option key={i.id} value={i.id}>{i.name}</option>
                    ))}
                  </select>
                  <p className="text-[10px] text-[var(--text-muted)] mt-1">
                    Choose which SMS integration this agent uses.
                  </p>
                </div>
              )}
            </>
          );
        })()}
          </>
        )}

        {activeTab === "settings" && (
          <>
            {/* ── Knowledge Base ── */}
            <Section title="Knowledge Base" icon={Library} defaultOpen={false}>
        <div>
          <label className="block text-xs font-medium mb-1.5">Linked Knowledge Base</label>
          <select
            value={formData.knowledge_base_id ?? ""}
            onChange={(e) =>
              onChange(
                "knowledge_base_id",
                e.target.value ? Number(e.target.value) : null
              )
            }
            className="w-full input-base text-sm"
            disabled={kbOptions.length === 0}
          >
            <option value="">
              {kbOptions.length === 0
                ? "No knowledge bases available"
                : "No knowledge base linked"}
            </option>
            {kbOptions.map((kb) => (
              <option key={kb.id} value={kb.id}>
                {kb.name}
              </option>
            ))}
          </select>
          {kbOptions.length === 0 && (
            <Link
              href="/dashboard/knowledge-base"
              className="text-[10px] text-brand-400 hover:underline mt-1 inline-block"
            >
              Create a knowledge base first →
            </Link>
          )}
        </div>

        <div className="border-t border-[var(--glass-border)] pt-3">
          <div className="flex items-center justify-between mb-2">
            <label className="flex items-center gap-2 text-sm font-medium">
              <BookOpen size={14} className="text-brand-400" />
              Agent Handbook
            </label>
            <button
              onClick={() => onToggleHandbook(!handbookEnabled)}
              className={cn(
                "px-2.5 py-1 rounded-lg text-[10px] font-medium transition-colors",
                handbookEnabled
                  ? "bg-brand-500/20 text-brand-400"
                  : "bg-[var(--bg-tertiary)] text-[var(--text-muted)]"
              )}
            >
              {handbookEnabled ? "Enabled" : "Disabled"}
            </button>
          </div>
          {handbookEnabled && (
            <textarea
              value={handbookContent}
              onChange={(e) => onChangeHandbook(e.target.value)}
              rows={6}
              placeholder="## Company Policy\n\n- Always greet callers by name\n- Refund requests under $50 can be approved immediately\n- Escalate technical issues to Tier 2..."
              className="w-full input-base resize-none text-xs font-mono"
            />
          )}
        </div>
      </Section>

      {/* ── Speech Settings ── */}
      <Section title="Speech Settings" icon={Volume2} defaultOpen={false}>
        <div>
          <label className="block text-xs font-medium mb-1.5">Agent Language</label>
          <select
            value={formData.language ?? "en-US"}
            onChange={(e) => onChange("language", e.target.value)}
            className="w-full input-base text-sm"
          >
            <option value="en-US">English (US)</option>
            <option value="en-GB">English (UK)</option>
            <option value="es">Spanish</option>
            <option value="de">German</option>
            <option value="fr">French</option>
            <option value="hi">Hindi</option>
            <option value="ur">Urdu</option>
            <option value="ar">Arabic</option>
            <option value="auto">Auto-detect</option>
          </select>
          <p className="text-[10px] text-[var(--text-muted)] mt-1">Controls STT/TTS language auto-configuration</p>
        </div>
        <div>
          <label className="block text-xs font-medium mb-1.5">STT Provider</label>
          <select
            value={formData.stt_provider}
            onChange={(e) => onChange("stt_provider", e.target.value as STTProvider)}
            className="w-full input-base text-sm"
          >
            {sttProviders.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        {formData.stt_provider === "deepgram" && (
          <div>
            <label className="block text-xs font-medium mb-1.5">STT Model</label>
            <select
              value={formData.stt_model || "nova-3"}
              onChange={(e) => onChange("stt_model", e.target.value)}
              className="w-full input-base text-sm"
            >
              {DEEPGRAM_STT_MODELS.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </div>
        )}
        {formData.stt_provider === "deepgram" && (
          <div className="space-y-2">
            <label className="block text-xs font-medium mb-0.5">STT Enhancements</label>
            <div className="flex flex-col gap-1.5">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.stt_smart_format ?? true}
                  onChange={(e) => onChange("stt_smart_format", e.target.checked)}
                  className="rounded border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)]"
                />
                <span className="text-xs text-[var(--text-secondary)]">Smart Formatting — Numbers, dates, currencies</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.stt_diarize ?? true}
                  onChange={(e) => onChange("stt_diarize", e.target.checked)}
                  className="rounded border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)]"
                />
                <span className="text-xs text-[var(--text-secondary)]">Speaker Diarization — Identify speakers</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formData.stt_filter_filler_words ?? false}
                  onChange={(e) => onChange("stt_filter_filler_words", e.target.checked)}
                  className="rounded border-[var(--border)] bg-[var(--bg-secondary)] text-[var(--accent)] focus:ring-1 focus:ring-[var(--accent)]"
                />
                <span className="text-xs text-[var(--text-secondary)]">Filter Filler Words — Remove "um", "uh"</span>
              </label>
            </div>
          </div>
        )}
        <div>
          <label className="block text-xs font-medium mb-1.5">Post-Call Analysis</label>
          <select
            value={formData.analysis_provider || "auto"}
            onChange={(e) => onChange("analysis_provider", e.target.value)}
            className="w-full input-base text-sm"
          >
            <option value="auto">Auto — Deepgram if recording, else LLM</option>
            <option value="deepgram">Deepgram Audio Intelligence — Requires recording</option>
            <option value="llm">LLM Analysis — Transcript-based</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium mb-1.5">Language</label>
          <select
            value={formData.stt_language}
            onChange={(e) => onChange("stt_language", e.target.value)}
            className="w-full input-base text-sm"
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
          <label className="block text-xs font-medium mb-1.5">TTS Provider</label>
          <select
            value={formData.tts_provider}
            onChange={(e) => onChange("tts_provider", e.target.value as TTSProvider)}
            className="w-full input-base text-sm"
          >
            {ttsProviders.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        {formData.tts_provider === "deepgram" && (
          <div>
            <label className="block text-xs font-medium mb-1.5">Voice</label>
            <select
              value={formData.tts_voice_id || "aura-asteria-en"}
              onChange={(e) => onChange("tts_voice_id", e.target.value)}
              className="w-full input-base text-sm"
            >
              {DEEPGRAM_VOICES.map((v) => (
                <option key={v.value} value={v.value}>
                  {v.label}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* API Key Overrides */}
        <div className="border-t border-[var(--glass-border)] pt-3 space-y-3">
          <label className="flex items-center gap-1.5 text-xs font-medium text-[var(--text-muted)]">
            <Key size={12} /> Custom API Keys (optional)
          </label>
          <div>
            <label className="block text-[10px] font-medium mb-1 text-[var(--text-muted)]">{formData.llm_provider?.toUpperCase()} API Key</label>
            <input
              type="password"
              value={formData.llm_api_key || ""}
              onChange={(e) => onChange("llm_api_key", e.target.value || null)}
              placeholder={formData.llm_api_key ? "••••••••" : "Use platform default"}
              className="w-full input-base text-xs"
            />
          </div>
          <div>
            <label className="block text-[10px] font-medium mb-1 text-[var(--text-muted)]">{formData.stt_provider?.toUpperCase()} API Key</label>
            <input
              type="password"
              value={formData.stt_api_key || ""}
              onChange={(e) => onChange("stt_api_key", e.target.value || null)}
              placeholder={formData.stt_api_key ? "••••••••" : "Use platform default"}
              className="w-full input-base text-xs"
            />
          </div>
          <div>
            <label className="block text-[10px] font-medium mb-1 text-[var(--text-muted)]">{formData.tts_provider?.toUpperCase()} API Key</label>
            <input
              type="password"
              value={formData.tts_api_key || ""}
              onChange={(e) => onChange("tts_api_key", e.target.value || null)}
              placeholder={formData.tts_api_key ? "••••••••" : "Use platform default"}
              className="w-full input-base text-xs"
            />
          </div>
        </div>
      </Section>

      {/* ── Call Settings ── */}
      <Section title="Call Settings" icon={PhoneCall} defaultOpen={false}>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium mb-1.5 flex items-center justify-between">
              <span>Idle Timeout</span>
              <span className="text-[10px] text-[var(--text-muted)]">{formData.allowed_idle_time_seconds ?? 30}s</span>
            </label>
            <input
              type="range"
              min={15}
              max={300}
              step={5}
              value={formData.allowed_idle_time_seconds ?? 30}
              onChange={(e) =>
                onChange("allowed_idle_time_seconds", parseInt(e.target.value))
              }
              className="w-full accent-brand-500"
            />
            <p className="text-[10px] text-[var(--text-muted)] mt-1">Hang up after this much silence</p>
          </div>
          <div>
            <label className="block text-xs font-medium mb-1.5 flex items-center justify-between">
              <span>Greeting Delay</span>
              <span className="text-[10px] text-[var(--text-muted)]">{(formData.initial_message_delay ?? 0).toFixed(1)}s</span>
            </label>
            <input
              type="range"
              min={0}
              max={2}
              step={0.1}
              value={formData.initial_message_delay ?? 0}
              onChange={(e) =>
                onChange("initial_message_delay", parseFloat(e.target.value))
              }
              className="w-full accent-brand-500"
            />
            <p className="text-[10px] text-[var(--text-muted)] mt-1">Wait before first greeting</p>
          </div>
        </div>
        <div>
          <label className="block text-xs font-medium mb-1.5">Interrupt Sensitivity</label>
          <select
            value={formData.interrupt_sensitivity}
            onChange={(e) =>
              onChange("interrupt_sensitivity", e.target.value as "low" | "high")
            }
            className="w-full input-base text-sm"
          >
            <option value="low">Low — Agent finishes speaking</option>
            <option value="high">High — Caller can cut in</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium mb-1.5">Endpointing</label>
          <select
            value={formData.endpointing_type}
            onChange={(e) =>
              onChange("endpointing_type", e.target.value as "auto" | "punctuation" | "time")
            }
            className="w-full input-base text-sm"
          >
            <option value="auto">Auto — Smart detection</option>
            <option value="punctuation">Punctuation — Wait for pauses</option>
            <option value="time">Time-based — Fixed delay</option>
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium mb-1.5">Min Interrupt Confidence</label>
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={formData.min_interrupt_confidence ?? 0.8}
              onChange={(e) => onChange("min_interrupt_confidence", parseFloat(e.target.value))}
              className="w-full input-base text-sm"
            />
            <p className="text-[10px] text-[var(--text-muted)] mt-1">0 = noise tolerant, 1 = strict</p>
          </div>
          <div>
            <label className="block text-xs font-medium mb-1.5">Check Human Present</label>
            <input
              type="number"
              min={0}
              max={10}
              value={formData.num_check_human_present_times ?? 0}
              onChange={(e) => onChange("num_check_human_present_times", parseInt(e.target.value))}
              className="w-full input-base text-sm"
            />
            <p className="text-[10px] text-[var(--text-muted)] mt-1">Times to confirm human is still there</p>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 pt-1">
          <label className="dash-card p-3 flex items-center gap-2.5 cursor-pointer hover:border-brand-500/40 transition-colors">
            <input
              type="checkbox"
              checked={formData.filler_audio_enabled}
              onChange={(e) => onChange("filler_audio_enabled", e.target.checked)}
              className="rounded"
            />
            <div>
              <p className="text-xs font-medium">Filler Audio</p>
              <p className="text-[10px] text-[var(--text-muted)]">
                "um", "let me check" while AI thinks
              </p>
            </div>
          </label>
          <label className="dash-card p-3 flex items-center gap-2.5 cursor-pointer hover:border-brand-500/40 transition-colors">
            <input
              type="checkbox"
              checked={formData.end_on_goodbye}
              onChange={(e) => onChange("end_on_goodbye", e.target.checked)}
              className="rounded"
            />
            <div>
              <p className="text-xs font-medium">End on Goodbye</p>
              <p className="text-[10px] text-[var(--text-muted)]">
                Auto-hang up when caller says bye
              </p>
            </div>
          </label>
        </div>

        {/* Outbound Ready Toggle */}
        <div className="mt-3">
          <label className="dash-card p-3 flex items-center gap-2.5 cursor-pointer hover:border-brand-500/40 transition-colors">
            <input
              type="checkbox"
              checked={formData.outbound_ready ?? false}
              onChange={(e) => onChange("outbound_ready", e.target.checked)}
              className="rounded"
            />
            <div>
              <p className="text-xs font-medium">Outbound Ready</p>
              <p className="text-[10px] text-[var(--text-muted)]">
                Allow this agent to make outbound calls (campaigns, scheduled calls, manual dial)
              </p>
            </div>
          </label>
        </div>

        {/* Voicemail Message */}
        <div className="mt-3">
          <label className="block text-xs font-medium mb-1.5">
            Voicemail Message (optional)
          </label>
          <textarea
            value={formData.voicemail_message ?? ""}
            onChange={(e) => onChange("voicemail_message", e.target.value || null)}
            rows={2}
            className="w-full input-base text-sm resize-none"
            placeholder="Hi, this is the assistant. I couldn't reach you, so I'll try again later. Thanks!"
          />
          <p className="text-[10px] text-[var(--text-muted)] mt-1">
            Message left when voicemail is detected on outbound calls. Leave empty to simply hang up.
          </p>
        </div>
      </Section>

      {/* ── Webhook ── */}
      <Section title="Webhook" icon={Webhook} defaultOpen={false}>
        <div>
          <label className="block text-xs font-medium mb-1.5">
            Post-Call Webhook URL
          </label>
          <input
            type="url"
            value={formData.webhook_url ?? ""}
            onChange={(e) =>
              onChange("webhook_url", e.target.value || null)
            }
            placeholder="https://your-app.com/webhooks/call-events"
            className="w-full input-base text-sm"
          />
          <p className="text-[10px] text-[var(--text-muted)] mt-1">
            Receive call_started and call_ended events at this URL.
          </p>
        </div>
      </Section>

      {/* ── Connected Resources ── */}
      <Section title="Connected Resources" icon={ShieldCheck} defaultOpen={false}>
        <div>
          <label className="block text-xs font-medium mb-1.5">
            Google Drive Integration
          </label>
          <select
            value={formData.google_drive_integration_id ?? ""}
            onChange={(e) =>
              onChange(
                "google_drive_integration_id",
                e.target.value ? Number(e.target.value) : null
              )
            }
            className="w-full input-base text-sm"
            disabled={driveOptions.length === 0}
          >
            <option value="">
              {driveOptions.length === 0
                ? "No Google Drive integrations available"
                : "No Google Drive integration linked"}
            </option>
            {driveOptions.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
          {driveOptions.length === 0 && (
            <Link
              href="/dashboard/integrations?type=google_drive_mcp"
              className="text-[10px] text-brand-400 hover:underline mt-1 inline-block"
            >
              Connect Google Drive first →
            </Link>
          )}
        </div>
      </Section>
          </>
        )}

        {activeTab === "resources" && (
          <>
            {/* ── Agent Configuration Quick Info ── */}
            <div className="border border-[var(--glass-border)] rounded-xl bg-[var(--bg-primary)] p-4">
              <h3 className="text-sm font-medium mb-3">Agent Configuration</h3>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <span className="text-[var(--text-muted)]">Mode</span>
                  <p className="font-medium">{formData.mode || "single_prompt"}</p>
                </div>
                <div>
                  <span className="text-[var(--text-muted)]">LLM</span>
                  <p className="font-medium">{formData.llm_provider} / {formData.llm_model}</p>
                </div>
                <div>
                  <span className="text-[var(--text-muted)]">Voice</span>
                  <p className="font-medium">{formData.tts_provider} / {formData.tts_voice_id || "default"}</p>
                </div>
                <div>
                  <span className="text-[var(--text-muted)]">Language</span>
                  <p className="font-medium">{formData.language || formData.stt_language || "en-US"}</p>
                </div>
              </div>
            </div>

            {/* ── Connected Resources Summary ── */}
            <div className="border border-[var(--glass-border)] rounded-xl bg-[var(--bg-primary)] p-4">
              <h3 className="text-sm font-medium mb-3">Connected Resources</h3>
              <div className="space-y-2">
                {/* Knowledge Base */}
                <div className="flex items-center gap-3 p-2.5 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--glass-border)]">
                  <Library size={16} className="text-[var(--accent)] shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-[10px] text-[var(--text-muted)]">Knowledge Base</p>
                    {formData.knowledge_base_id ? (
                      <p className="text-xs font-medium text-brand-400 truncate">
                        {kbOptions.find(k => k.id === formData.knowledge_base_id)?.name || `KB #${formData.knowledge_base_id}`}
                      </p>
                    ) : (
                      <p className="text-xs text-[var(--text-muted)]">Not linked</p>
                    )}
                  </div>
                  {formData.knowledge_base_id ? (
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-green-500/10 text-green-400 shrink-0">Active</span>
                  ) : (
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--bg-primary)] text-[var(--text-muted)] shrink-0">—</span>
                  )}
                </div>

                {/* Google Drive */}
                <div className="flex items-center gap-3 p-2.5 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--glass-border)]">
                  <HardDrive size={16} className="text-blue-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-[10px] text-[var(--text-muted)]">Google Drive</p>
                    {formData.google_drive_integration_id ? (
                      <p className="text-xs font-medium text-blue-400 truncate">
                        {driveOptions.find(d => d.id === formData.google_drive_integration_id)?.name || `Integration #${formData.google_drive_integration_id}`}
                      </p>
                    ) : (
                      <p className="text-xs text-[var(--text-muted)]">Not linked</p>
                    )}
                  </div>
                  {formData.google_drive_integration_id ? (
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-green-500/10 text-green-400 shrink-0">Active</span>
                  ) : (
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--bg-primary)] text-[var(--text-muted)] shrink-0">—</span>
                  )}
                </div>

                {/* MCP Bindings — Drive Files */}
                {(() => {
                  const driveBindings = (formData.mcp_bindings as Record<string, any>)?.drive;
                  const fileIds = driveBindings?.file_ids as string[] || [];
                  if (fileIds.length > 0) {
                    return (
                      <div className="flex items-center gap-3 p-2.5 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--glass-border)]">
                        <FileText size={16} className="text-amber-400 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-[10px] text-[var(--text-muted)]">Bound Drive Files</p>
                          <p className="text-xs font-medium truncate">{fileIds.length} file{fileIds.length !== 1 ? 's' : ''}</p>
                        </div>
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 shrink-0">Bound</span>
                      </div>
                    );
                  }
                  return null;
                })()}

                {/* MCP Bindings — Calendars */}
                {(() => {
                  const calBindings = (formData.mcp_bindings as Record<string, any>)?.calendar;
                  const calIds = calBindings?.calendar_ids as string[] || [];
                  if (calIds.length > 0) {
                    return (
                      <div className="flex items-center gap-3 p-2.5 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--glass-border)]">
                        <Calendar size={16} className="text-purple-400 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-[10px] text-[var(--text-muted)]">Bound Calendars</p>
                          <p className="text-xs font-medium truncate">{calIds.length} calendar{calIds.length !== 1 ? 's' : ''}</p>
                        </div>
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400 shrink-0">Bound</span>
                      </div>
                    );
                  }
                  return null;
                })()}
              </div>
            </div>

            {/* ── Resource Bindings (file picker, calendar bindings) ── */}
            {agentId && (
              <ToolsSection
                agentId={agentId}
                variant="builder"
                onBindingsChange={(bindings) => onChange("mcp_bindings", bindings)}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default memo(BuilderPanels);
