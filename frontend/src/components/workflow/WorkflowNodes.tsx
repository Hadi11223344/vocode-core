'use client';

import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import {
  Zap,
  Calendar,
  Table,
  Globe,
  MessageSquare,
  CheckCircle,
  Bot,
  Clock,
  PhoneCall,
  Settings,
  PhoneForwarded,
  Mail,
  BookOpen,
  Hash,
  Link,
  Voicemail,
  UserCheck,
  XCircle,
  CalendarCheck,
  Cloud,
  CreditCard,
  ShoppingBag,
  LifeBuoy,
  MessageCircle,
  Inbox,
  Smartphone,
  AtSign,
  Monitor,
  Send,
  FileText,
  Layout,
  GitMerge,
  Clipboard,
  Layers,
  TrendingUp,
  Rocket,
  CalendarPlus,
  StickyNote,
  GitBranch,
  Variable,
  ListChecks,
} from 'lucide-react';

/* ─── Node type config ──────────────────────────────────── */
export const NODE_TYPES_CONFIG = {
  trigger: {
    label: 'Call Trigger',
    icon: PhoneCall,
    color: 'border-green-500/50 bg-green-500/5',
    headerColor: 'bg-green-500/20 text-green-400',
    description: 'Triggers when a call matches phrases',
    category: 'flow',
  },
  conversation: {
    label: 'Conversation',
    icon: UserCheck,
    color: 'border-violet-500/50 bg-violet-500/5',
    headerColor: 'bg-violet-500/20 text-violet-400',
    description: 'Dynamic conversation with variable extraction',
    category: 'flow',
  },
  condition: {
    label: 'Condition',
    icon: Zap,
    color: 'border-amber-500/50 bg-amber-500/5',
    headerColor: 'bg-amber-500/20 text-amber-400',
    description: 'Branch based on a condition',
    category: 'flow',
  },
  slot_validator: {
    label: 'Slot Validator',
    icon: ListChecks,
    color: 'border-orange-500/50 bg-orange-500/5',
    headerColor: 'bg-orange-500/20 text-orange-400',
    description: 'Validate required slots and route to collectors',
    category: 'flow',
  },
  end_call: {
    label: 'End Call',
    icon: XCircle,
    color: 'border-red-500/50 bg-red-500/5',
    headerColor: 'bg-red-500/20 text-red-400',
    description: 'End the call with a closing message',
    category: 'flow',
  },
  end: {
    label: 'End',
    icon: CheckCircle,
    color: 'border-gray-500/50 bg-gray-500/5',
    headerColor: 'bg-gray-500/20 text-gray-400',
    description: 'Workflow complete',
    category: 'flow',
  },
  transfer_call: {
    label: 'Transfer Call',
    icon: PhoneForwarded,
    color: 'border-orange-500/50 bg-orange-500/5',
    headerColor: 'bg-orange-500/20 text-orange-400',
    description: 'Transfer to a human agent or department',
    category: 'telephony',
  },
  send_sms: {
    label: 'Send SMS',
    icon: MessageSquare,
    color: 'border-teal-500/50 bg-teal-500/5',
    headerColor: 'bg-teal-500/20 text-teal-400',
    description: 'Send an SMS message to the caller',
    category: 'communication',
  },
  send_email: {
    label: 'Send Email',
    icon: Mail,
    color: 'border-sky-500/50 bg-sky-500/5',
    headerColor: 'bg-sky-500/20 text-sky-400',
    description: 'Send an email notification',
    category: 'communication',
  },
  google_calendar: {
    label: 'Google Calendar',
    icon: Calendar,
    color: 'border-cyan-500/50 bg-cyan-500/5',
    headerColor: 'bg-cyan-500/20 text-cyan-400',
    description: 'Create, update, or check calendar events',
    category: 'integration',
  },
  google_sheets: {
    label: 'Google Sheets',
    icon: Table,
    color: 'border-emerald-500/50 bg-emerald-500/5',
    headerColor: 'bg-emerald-500/20 text-emerald-400',
    description: 'Read, append, or update spreadsheet data',
    category: 'integration',
  },
  cal_com: {
    label: 'Cal.com',
    icon: CalendarCheck,
    color: 'border-indigo-500/50 bg-indigo-500/5',
    headerColor: 'bg-indigo-500/20 text-indigo-400',
    description: 'Check availability and book meetings',
    category: 'integration',
  },
  api_request: {
    label: 'API Request',
    icon: Globe,
    color: 'border-blue-500/50 bg-blue-500/5',
    headerColor: 'bg-blue-500/20 text-blue-400',
    description: 'Make HTTP requests to any REST API',
    category: 'integration',
  },
  webhook: {
    label: 'Webhook',
    icon: Link,
    color: 'border-blue-400/50 bg-blue-400/5',
    headerColor: 'bg-blue-400/20 text-blue-300',
    description: 'Send data to an external URL',
    category: 'integration',
  },
  knowledge_base: {
    label: 'Knowledge Base',
    icon: BookOpen,
    color: 'border-lime-500/50 bg-lime-500/5',
    headerColor: 'bg-lime-500/20 text-lime-400',
    description: 'Retrieve context from stored knowledge',
    category: 'ai',
  },
  llm_process: {
    label: 'AI Process',
    icon: Bot,
    color: 'border-brand-500/50 bg-brand-500/5',
    headerColor: 'bg-brand-500/20 text-brand-400',
    description: 'Process data with LLM',
    category: 'ai',
  },
  delay: {
    label: 'Delay',
    icon: Clock,
    color: 'border-purple-500/50 bg-purple-500/5',
    headerColor: 'bg-purple-500/20 text-purple-400',
    description: 'Wait before continuing',
    category: 'utility',
  },
  notification: {
    label: 'Notification',
    icon: Hash,
    color: 'border-pink-500/50 bg-pink-500/5',
    headerColor: 'bg-pink-500/20 text-pink-400',
    description: 'Send a notification (Slack, etc.)',
    category: 'communication',
  },
  voicemail_detect: {
    label: 'Voicemail Detect',
    icon: Voicemail,
    color: 'border-rose-500/50 bg-rose-500/5',
    headerColor: 'bg-rose-500/20 text-rose-400',
    description: 'Detect if call reached voicemail',
    category: 'telephony',
  },
  action: {
    label: 'Action',
    icon: Settings,
    color: 'border-slate-500/50 bg-slate-500/5',
    headerColor: 'bg-slate-500/20 text-slate-400',
    description: 'Generic integration action',
    category: 'integration',
  },
  // ── NEW: Scheduling Integrations ──
  calendly: {
    label: 'Calendly',
    icon: CalendarPlus,
    color: 'border-blue-400/50 bg-blue-400/5',
    headerColor: 'bg-blue-400/20 text-blue-300',
    description: 'Schedule meetings via Calendly',
    category: 'integration',
  },
  // ── NEW: Custom Integrations ──
  mcp_tool: {
    label: 'MCP Tool',
    icon: Cloud,
    color: 'border-orange-500/50 bg-orange-500/5',
    headerColor: 'bg-orange-500/20 text-orange-400',
    description: 'Connect to an MCP Server tool',
    category: 'integration',
  },
  custom_api: {
    label: 'Custom API',
    icon: Globe,
    color: 'border-blue-500/50 bg-blue-500/5',
    headerColor: 'bg-blue-500/20 text-blue-400',
    description: 'Make a generic HTTP API call',
    category: 'integration',
  },
  // ── NEW: CRM Integrations ──
  salesforce: {
    label: 'Salesforce',
    icon: Cloud,
    color: 'border-blue-600/50 bg-blue-600/5',
    headerColor: 'bg-blue-600/20 text-blue-300',
    description: 'Manage leads and contacts in Salesforce',
    category: 'integration',
  },
  pipedrive: {
    label: 'Pipedrive',
    icon: TrendingUp,
    color: 'border-green-600/50 bg-green-600/5',
    headerColor: 'bg-green-600/20 text-green-300',
    description: 'CRM deals and pipeline management',
    category: 'integration',
  },
  gohighlevel: {
    label: 'GoHighLevel',
    icon: Rocket,
    color: 'border-yellow-500/50 bg-yellow-500/5',
    headerColor: 'bg-yellow-500/20 text-yellow-300',
    description: 'CRM and marketing automation',
    category: 'integration',
  },
  // ── NEW: Support Integrations ──
  zendesk: {
    label: 'Zendesk',
    icon: LifeBuoy,
    color: 'border-green-400/50 bg-green-400/5',
    headerColor: 'bg-green-400/20 text-green-300',
    description: 'Create and manage support tickets',
    category: 'integration',
  },
  intercom: {
    label: 'Intercom',
    icon: MessageCircle,
    color: 'border-blue-500/50 bg-blue-500/5',
    headerColor: 'bg-blue-500/20 text-blue-400',
    description: 'Customer messaging and support',
    category: 'integration',
  },
  freshdesk: {
    label: 'Freshdesk',
    icon: Inbox,
    color: 'border-teal-400/50 bg-teal-400/5',
    headerColor: 'bg-teal-400/20 text-teal-300',
    description: 'Helpdesk and ticket management',
    category: 'integration',
  },
  // ── NEW: E-commerce & Payments ──
  stripe: {
    label: 'Stripe',
    icon: CreditCard,
    color: 'border-purple-500/50 bg-purple-500/5',
    headerColor: 'bg-purple-500/20 text-purple-300',
    description: 'Process payments and invoices',
    category: 'integration',
  },
  shopify: {
    label: 'Shopify',
    icon: ShoppingBag,
    color: 'border-green-500/50 bg-green-500/5',
    headerColor: 'bg-green-500/20 text-green-400',
    description: 'E-commerce order and product management',
    category: 'integration',
  },
  // ── NEW: Communication ──
  whatsapp_cloud: {
    label: 'WhatsApp',
    icon: Smartphone,
    color: 'border-green-400/50 bg-green-400/5',
    headerColor: 'bg-green-400/20 text-green-300',
    description: 'Send WhatsApp messages',
    category: 'communication',
  },
  discord: {
    label: 'Discord',
    icon: AtSign,
    color: 'border-indigo-400/50 bg-indigo-400/5',
    headerColor: 'bg-indigo-400/20 text-indigo-300',
    description: 'Send notifications to Discord',
    category: 'communication',
  },
  microsoft_teams: {
    label: 'MS Teams',
    icon: Monitor,
    color: 'border-blue-500/50 bg-blue-500/5',
    headerColor: 'bg-blue-500/20 text-blue-400',
    description: 'Send messages to Teams channels',
    category: 'communication',
  },
  // ── NEW: Productivity ──
  notion: {
    label: 'Notion',
    icon: FileText,
    color: 'border-gray-400/50 bg-gray-400/5',
    headerColor: 'bg-gray-400/20 text-gray-300',
    description: 'Create pages and manage databases',
    category: 'integration',
  },
  airtable: {
    label: 'Airtable',
    icon: Layout,
    color: 'border-yellow-400/50 bg-yellow-400/5',
    headerColor: 'bg-yellow-400/20 text-yellow-300',
    description: 'Database records and spreadsheets',
    category: 'integration',
  },
  // ── NEW: Automation ──
  make: {
    label: 'Make',
    icon: GitMerge,
    color: 'border-purple-400/50 bg-purple-400/5',
    headerColor: 'bg-purple-400/20 text-purple-300',
    description: 'Trigger Make (Integromat) scenarios',
    category: 'integration',
  },
  // ── NEW: Project Management ──
  jira: {
    label: 'Jira',
    icon: Clipboard,
    color: 'border-blue-500/50 bg-blue-500/5',
    headerColor: 'bg-blue-500/20 text-blue-400',
    description: 'Create and manage Jira issues',
    category: 'integration',
  },
  linear: {
    label: 'Linear',
    icon: Layers,
    color: 'border-violet-400/50 bg-violet-400/5',
    headerColor: 'bg-violet-400/20 text-violet-300',
    description: 'Issue tracking and project management',
    category: 'integration',
  },
  // ── NEW: Phase 3 Node Types ──
  note: {
    label: 'Note',
    icon: StickyNote,
    color: 'border-yellow-500/50 bg-yellow-500/5',
    headerColor: 'bg-yellow-500/20 text-yellow-400',
    description: 'Add context or instructions (visible only to AI)',
    category: 'utility',
  },
  // NOTE: code node removed from default palette. Sandboxed Python execution
  // is disabled by default for security; re-enable only with a real sandbox.
  // code: { ... }
  subagent: {
    label: 'Subagent',
    icon: GitBranch,
    color: 'border-cyan-500/50 bg-cyan-500/5',
    headerColor: 'bg-cyan-500/20 text-cyan-400',
    description: 'Delegate to another agent and return result',
    category: 'ai',
  },
  extract_variable: {
    label: 'Extract Variable',
    icon: Variable,
    color: 'border-pink-500/50 bg-pink-500/5',
    headerColor: 'bg-pink-500/20 text-pink-400',
    description: 'Extract a structured value from conversation',
    category: 'flow',
  },
} as const;

/** Grouped node categories for the palette */
export const NODE_CATEGORIES = {
  flow: { label: 'Flow Control', description: 'Control conversation flow' },
  telephony: { label: 'Telephony', description: 'Call transfer & voicemail' },
  communication: { label: 'Communication', description: 'SMS, email & notifications' },
  integration: { label: 'Integrations', description: 'External services & APIs' },
  ai: { label: 'AI & Knowledge', description: 'LLM processing & RAG' },
  utility: { label: 'Utility', description: 'Timing & control' },
} as const;

export type NodeType = keyof typeof NODE_TYPES_CONFIG;

/* ─── Custom Node Component ─────────────────────────────── */
export const WorkflowNode = memo(function WorkflowNode({ data, selected }: NodeProps) {
  const nodeType = (data.nodeType as NodeType) || 'webhook';
  const config = NODE_TYPES_CONFIG[nodeType] || NODE_TYPES_CONFIG.webhook;
  const Icon = config.icon;
  const isConfigured = data.isConfigured !== false;
  const isTerminal = nodeType === 'end' || nodeType === 'end_call';
  const isCondition = nodeType === 'condition';
  const hasMissingInputBranch = Array.isArray(data.config?.required_inputs)
    && data.config.required_inputs.length > 0;
  const hasError = data.hasError === true;

  return (
    <div
      className={`rounded-xl border-2 min-w-[240px] max-w-[280px] shadow-lg transition-all ${
        hasError ? 'border-red-500 bg-red-500/5' : config.color
      } ${
        selected ? 'ring-2 ring-brand-500 ring-offset-2 ring-offset-[#0a0a0f]' : ''
      } ${
        hasError ? 'ring-2 ring-red-500/50' : ''
      }`}
    >
      {/* Input Handle */}
      {nodeType !== 'trigger' && (
        <Handle
          type="target"
          position={Position.Top}
          className="!w-3 !h-3 !bg-[var(--text-muted)] !border-2 !border-[var(--bg-secondary)] hover:!bg-brand-400 transition-colors"
        />
      )}

      {/* Header */}
      <div className={`flex items-center gap-2 px-3 py-2 rounded-t-[10px] ${config.headerColor}`}>
        <Icon size={14} />
        <span className="text-xs font-semibold uppercase tracking-wider">{config.label}</span>
        {hasError && (
          <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded bg-red-500/30 text-red-300">Error</span>
        )}
        {!isConfigured && !hasError && (
          <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded bg-amber-500/30 text-amber-300">Setup needed</span>
        )}
      </div>

      {/* Body */}
      <div className="p-3">
        <p className="text-sm font-medium truncate">{data.label || config.label}</p>
        {data.description && (
          <p className="text-xs text-[var(--text-muted)] mt-1 line-clamp-2">{data.description}</p>
        )}
        {data.action && (
          <div className="mt-2 flex items-center gap-1">
            <Settings size={10} className="text-[var(--text-muted)]" />
            <span className="text-[10px] text-[var(--text-muted)] font-mono">{data.action}</span>
          </div>
        )}
        {/* Conversation node: show extracted variables */}
        {nodeType === 'conversation' && data.config?.variables_to_extract && (
          <div className="mt-2 flex flex-wrap gap-1">
            {(data.config.variables_to_extract as string[]).slice(0, 4).map((v: string) => (
              <span key={v} className="text-[10px] px-1.5 py-0.5 rounded bg-violet-500/20 text-violet-300 font-mono">
                {`{{${v}}}`}
              </span>
            ))}
          </div>
        )}
        {/* Transfer call: show target number */}
        {nodeType === 'transfer_call' && (data.config?.transfer_number || data.config?.transfer_to) && (
          <div className="mt-2 text-[10px] text-orange-300 font-mono">
            → {data.config.transfer_number || data.config.transfer_to}
          </div>
        )}
        {/* SMS: show preview */}
        {nodeType === 'send_sms' && data.config?.body && (
          <p className="mt-1 text-[10px] text-teal-300/70 line-clamp-2 italic">
            &quot;{data.config.body}&quot;
          </p>
        )}
        {/* API Request: show method + URL */}
        {nodeType === 'api_request' && data.config?.url && (
          <div className="mt-2 flex items-center gap-1">
            <span className="text-[10px] px-1 py-0.5 rounded bg-blue-500/30 text-blue-300 font-mono uppercase">
              {data.config.method || 'GET'}
            </span>
            <span className="text-[10px] text-[var(--text-muted)] font-mono truncate">{data.config.url}</span>
          </div>
        )}
        {data.stepNumber && (
          <div className="mt-1 text-[10px] text-[var(--text-muted)]">Step {data.stepNumber}</div>
        )}
      </div>

      {/* Output Handle(s) */}
      {isCondition ? (
        <>
          {/* Dual outputs for condition nodes */}
          <div className="flex justify-between px-3 pb-1">
            <span className="text-[9px] text-green-400">Yes</span>
            <span className="text-[9px] text-red-400">No</span>
          </div>
          <Handle
            type="source"
            position={Position.Bottom}
            id="yes"
            style={{ left: '30%' }}
            className="!w-3 !h-3 !bg-green-500 !border-2 !border-[var(--bg-secondary)] hover:!bg-green-400 transition-colors"
          />
          <Handle
            type="source"
            position={Position.Bottom}
            id="no"
            style={{ left: '70%' }}
            className="!w-3 !h-3 !bg-red-500 !border-2 !border-[var(--bg-secondary)] hover:!bg-red-400 transition-colors"
          />
        </>
      ) : !isTerminal && hasMissingInputBranch ? (
        <>
          <div className="flex justify-between px-3 pb-1">
            <span className="text-[9px] text-green-400">Success</span>
            <span className="text-[9px] text-red-400">Error</span>
            <span className="text-[9px] text-amber-400">Missing</span>
          </div>
          <Handle
            type="source"
            position={Position.Bottom}
            style={{ left: '18%' }}
            className="!w-3 !h-3 !bg-green-500 !border-2 !border-[var(--bg-secondary)] hover:!bg-green-400 transition-colors"
          />
          <Handle
            type="source"
            position={Position.Bottom}
            id="error"
            style={{ left: '50%' }}
            className="!w-3 !h-3 !bg-red-500 !border-2 !border-[var(--bg-secondary)] hover:!bg-red-400 transition-colors"
          />
          <Handle
            type="source"
            position={Position.Bottom}
            id="on_missing"
            style={{ left: '82%' }}
            className="!w-3 !h-3 !bg-amber-500 !border-2 !border-[var(--bg-secondary)] hover:!bg-amber-400 transition-colors"
          />
        </>
      ) : !isTerminal ? (
        <Handle
          type="source"
          position={Position.Bottom}
          className="!w-3 !h-3 !bg-[var(--text-muted)] !border-2 !border-[var(--bg-secondary)] hover:!bg-brand-400 transition-colors"
        />
      ) : null}
    </div>
  );
});

export const nodeTypes = { workflowNode: WorkflowNode };
