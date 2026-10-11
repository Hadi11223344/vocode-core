'use client';

import { useEffect, useState, useMemo, useCallback } from 'react';
import { useToast } from '@/components/ui/toast';
import { EmptyState } from '@/components/ui/empty-state';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { integrations as integrationsApi, apiKeys } from '@/lib/api';
import { usePageTitle } from '@/hooks/usePageTitle';
import { Integration, IntegrationType } from '@/lib/types';
import { formatTimestamp } from '@/lib/utils';
import { SkeletonCard } from '@/components/ui/skeleton';
import {
  Plug, Plus, Trash2, CheckCircle, XCircle, Loader2,
  Calendar, Table, TestTube, Eye, EyeOff, AlertTriangle,
  Pencil, MessageSquare, Mail, Globe, BookOpen, Cloud,
  TrendingUp, Rocket, LifeBuoy, MessageCircle, Inbox,
  CreditCard, ShoppingBag, Smartphone, AtSign, Monitor,
  Send, FileText, Layout, GitMerge, Clipboard, Layers,
  CalendarPlus, Zap, ExternalLink, HelpCircle, ChevronDown,
  ChevronUp, Search, ArrowLeft, Info, Shield, Server, Code,
  HardDrive, X, FileSpreadsheet, FileImage, FileAudio,
  FileVideo, FileCode, FileType, Presentation, Folder,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { IntegrationHelpDrawer } from '@/components/integrations/IntegrationHelpDrawer';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';
import SettingsTabBar from '../settings/_components/SettingsTabBar';

/* \u2500\u2500\u2500 Category Labels \u2500\u2500\u2500 */
const CATEGORY_LABELS: Record<string, string> = {
  developer: '🛠 Extensibility',
  productivity: '📊 Productivity',
  communication: '💬 Communication',
  crm: '📇 CRM & Sales',
  support: '🎧 Support',
  commerce: '🛒 Commerce',
  project: '📋 Project Management',
  other: '🔌 Other',
};

const DIFFICULTY_COLORS: Record<string, string> = {
  Easy: 'text-green-400 bg-green-400/10 border-green-400/20',
  Medium: 'text-amber-400 bg-amber-400/10 border-amber-400/20',
  Advanced: 'text-red-400 bg-red-400/10 border-red-400/20',
};

/* \u2500\u2500\u2500 Setup Guide Panel \u2500\u2500\u2500 */
function SetupGuidePanel({ guide, apiKeyHelp }: {
  guide: IntegrationType['setup_guide'];
  apiKeyHelp?: string;
}) {
  const [expanded, setExpanded] = useState(true);
  if (!guide) return null;

  return (
    <div className="rounded-xl border border-[var(--glass-border)] bg-[var(--bg-secondary)] overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-[var(--bg-tertiary)] transition-colors"
      >
        <div className="flex items-center gap-2">
          <BookOpen size={16} className="text-brand-400" />
          <span className="text-sm font-semibold">Setup Guide</span>
          {guide.difficulty && (
            <span className={cn('px-2 py-0.5 text-[10px] rounded-full border', DIFFICULTY_COLORS[guide.difficulty] || '')}>
              {guide.difficulty}
            </span>
          )}
          {guide.estimated_time && (
            <span className="text-[10px] text-[var(--text-muted)]">~{guide.estimated_time}</span>
          )}
        </div>
        {expanded ? <ChevronUp size={16} className="text-[var(--text-muted)]" /> : <ChevronDown size={16} className="text-[var(--text-muted)]" />}
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-4">
          {guide.docs_url && (
            <a
              href={guide.docs_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-brand-500/10 border border-brand-500/20 text-brand-400 text-xs hover:bg-brand-500/20 transition-colors"
            >
              <ExternalLink size={14} />
              Official Documentation
            </a>
          )}

          {apiKeyHelp && (
            <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
              <Shield size={14} className="text-amber-400 mt-0.5 shrink-0" />
              <p className="text-xs text-amber-200">{apiKeyHelp}</p>
            </div>
          )}

          {guide.steps && guide.steps.length > 0 && (
            <div className="space-y-3">
              <p className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Steps</p>
              {guide.steps.map((step: { step?: number; title: string; description: string; link?: string }) => (
                <div key={step.step || step.title} className="flex gap-3">
                  <div className="flex-shrink-0 w-6 h-6 rounded-full bg-brand-500/20 text-brand-400 text-[10px] flex items-center justify-center font-bold">
                    {step.step || '\u2022'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium">{step.title}</p>
                    <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{step.description}</p>
                    {step.link && (
                      <a
                        href={step.link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-[10px] text-brand-400 hover:underline mt-1"
                      >
                        <ExternalLink size={10} /> Open Link
                      </a>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {guide.notes && guide.notes.length > 0 && (
            <div className="rounded-lg bg-[var(--bg-primary)] border border-[var(--glass-border)] p-3">
              <div className="flex items-center gap-1.5 mb-2">
                <AlertTriangle size={12} className="text-amber-400" />
                <span className="text-[10px] font-medium text-amber-400 uppercase tracking-wider">Important Notes</span>
              </div>
              <ul className="space-y-1">
                {guide.notes.map((note: string, i: number) => (
                  <li key={i} className="text-[11px] text-[var(--text-muted)] flex gap-1.5">
                    <span className="text-[var(--text-muted)]">\u2022</span>
                    <span>{note}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* \u2500\u2500\u2500 Config Field Renderer \u2500\u2500\u2500 */
function ConfigField({ fieldName, fieldSchema, value, onChange }: {
  fieldName: string;
  fieldSchema: {
    type: string;
    label?: string;
    placeholder?: string;
    help_text?: string;
    secret?: boolean;
    required?: boolean;
    default?: unknown;
    description?: string;
  };
  value: unknown;
  onChange: (val: unknown) => void;
}) {
  const [showHelp, setShowHelp] = useState(false);
  const [showSecret, setShowSecret] = useState(false);

  const label = fieldSchema.label || fieldName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  const placeholder = fieldSchema.placeholder || fieldSchema.default?.toString() || '';
  const helpText = fieldSchema.help_text || fieldSchema.description || '';
  const isSecret = fieldSchema.secret || fieldName.includes('key') || fieldName.includes('secret') || fieldName.includes('token') || fieldName.includes('password');

  if (fieldSchema.type === 'boolean') {
    return (
      <div className="flex items-center justify-between py-2">
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium">{label}</label>
          {helpText && (
            <button type="button" onClick={() => setShowHelp(!showHelp)} className="text-[var(--text-muted)] hover:text-brand-400">
              <HelpCircle size={12} />
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={() => onChange(!(value as boolean))}
          className={cn(
            'relative w-9 h-5 rounded-full transition-colors',
            value ? 'bg-brand-500' : 'bg-[var(--bg-tertiary)] border border-[var(--glass-border)]'
          )}
        >
          <span
            className={cn(
              'absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform',
              value ? 'left-[18px]' : 'left-0.5'
            )}
          />
        </button>
      </div>
    );
  }

  if (fieldSchema.type === 'integer' || fieldSchema.type === 'number') {
    return (
      <div>
        <div className="flex items-center gap-2 mb-1">
          <label className="text-xs font-medium">{label}</label>
          {fieldSchema.required && <span className="text-red-400 text-[10px]">*</span>}
          {helpText && (
            <button type="button" onClick={() => setShowHelp(!showHelp)} className="text-[var(--text-muted)] hover:text-brand-400">
              <HelpCircle size={12} />
            </button>
          )}
        </div>
        <input
          type="number"
          value={value?.toString() || ''}
          onChange={e => onChange(e.target.value ? Number(e.target.value) : '')}
          placeholder={placeholder}
          className="w-full input-base text-sm"
        />
        {showHelp && <p className="text-[10px] text-[var(--text-muted)] mt-1">{helpText}</p>}
      </div>
    );
  }

  if (fieldSchema.type === 'object') {
    return (
      <div>
        <div className="flex items-center gap-2 mb-1">
          <label className="text-xs font-medium">{label}</label>
          {helpText && (
            <button type="button" onClick={() => setShowHelp(!showHelp)} className="text-[var(--text-muted)] hover:text-brand-400">
              <HelpCircle size={12} />
            </button>
          )}
        </div>
        <textarea
          value={typeof value === 'string' ? value : JSON.stringify(value || {}, null, 2)}
          onChange={e => {
            try { onChange(JSON.parse(e.target.value)); } catch { onChange(e.target.value); }
          }}
          rows={3}
          className="w-full input-base font-mono text-xs"
          placeholder={placeholder || '{ }'}
        />
        {showHelp && <p className="text-[10px] text-[var(--text-muted)] mt-1">{helpText}</p>}
      </div>
    );
  }

  // Default: string
  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        <label className="text-xs font-medium">{label}</label>
        {fieldSchema.required && <span className="text-red-400 text-[10px]">*</span>}
        {helpText && (
          <button type="button" onClick={() => setShowHelp(!showHelp)} className="text-[var(--text-muted)] hover:text-brand-400">
            <HelpCircle size={12} />
          </button>
        )}
      </div>
      <div className="relative">
        <input
          type={isSecret && !showSecret ? 'password' : 'text'}
          value={value?.toString() || ''}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full input-base text-sm pr-8"
        />
        {isSecret && (
          <button
            type="button"
            onClick={() => setShowSecret(!showSecret)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
          >
            {showSecret ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        )}
      </div>
      {showHelp && <p className="text-[10px] text-[var(--text-muted)] mt-1">{helpText}</p>}
    </div>
  );
}

/* \u2500\u2500\u2500 Main Page \u2500\u2500\u2500 */
export default function IntegrationsPage() {
  usePageTitle('Integrations');
  const [integrationList, setIntegrationList] = useState<Integration[]>([]);
  const [integrationTypes, setIntegrationTypes] = useState<IntegrationType[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [testing, setTesting] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);
  const [helpDrawerType, setHelpDrawerType] = useState<IntegrationType | null>(null);
  const [helpDrawerIntegration, setHelpDrawerIntegration] = useState<Integration | null>(null);
  const [reactivating, setReactivating] = useState<number | null>(null);
  const [googleOAuthStatus, setGoogleOAuthStatus] = useState<{ connected: boolean; scopes: string[] } | null>(null);
  const [platformEmailReady, setPlatformEmailReady] = useState(false);
  const { success, apiError } = useToast();

  // Form state
  const [formType, setFormType] = useState('');
  const [formName, setFormName] = useState('');
  const [formConfig, setFormConfig] = useState<Record<string, unknown>>({});
  const [formApiKey, setFormApiKey] = useState('');
  const [formSaving, setFormSaving] = useState(false);
  const [showCredentials, setShowCredentials] = useState<Record<number, boolean>>({});
  const [typeSearch, setTypeSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');

  // Drive file browser state
  const [driveBrowserOpen, setDriveBrowserOpen] = useState(false);
  const [driveBrowserId, setDriveBrowserId] = useState<number | null>(null);
  const [driveFiles, setDriveFiles] = useState<Array<{ id: string; name: string; mimeType: string; modifiedTime: string }>>([]);
  const [driveBrowserMessage, setDriveBrowserMessage] = useState<string | null>(null);
  const [driveSearch, setDriveSearch] = useState('');
  const [driveLoading, setDriveLoading] = useState(false);

  // Drive file preview state
  const [previewFileId, setPreviewFileId] = useState<string | null>(null);
  const [previewFileName, setPreviewFileName] = useState('');
  const [previewContent, setPreviewContent] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  const selectedType = integrationTypes.find(t => t.id === formType);
  const isGoogleIntegration = formType === 'google_calendar' || formType === 'google_sheets' || formType === 'google_drive_mcp';

  const load = useCallback(async () => {
    try {
      const [intRes, typesRes, platRes] = await Promise.all([
        integrationsApi.list(),
        integrationsApi.types(),
        apiKeys.platformStatus().catch(() => ({ platform_keys: {} as Record<string, boolean>, twilio_phone_number: null, default_llm_model: '' })),
      ]);
      setIntegrationList(intRes.integrations);
      setIntegrationTypes(typesRes.types || typesRes);
      setPlatformEmailReady(!!platRes.platform_keys?.email);
    } catch (err) {
      apiError(err, 'Failed to load integrations');
    } finally {
      setLoading(false);
    }
  }, [apiError]);

  const refreshGoogleStatus = useCallback(async () => {
    if (!isGoogleIntegration) {
      setGoogleOAuthStatus(null);
      return null;
    }

    try {
      const status = await integrationsApi.googleStatus();
      setGoogleOAuthStatus(status);
      return status;
    } catch {
      setGoogleOAuthStatus(null);
      return null;
    }
  }, [isGoogleIntegration]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (isGoogleIntegration) {
      void refreshGoogleStatus();
      return;
    }

    setGoogleOAuthStatus(null);
  }, [isGoogleIntegration, refreshGoogleStatus]);

  const typesByCategory = useMemo(() => {
    const groups: Record<string, IntegrationType[]> = {};
    for (const t of integrationTypes) {
      const cat = t.category || 'other';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(t);
    }
    return groups;
  }, [integrationTypes]);

  const filteredTypes = useMemo(() => {
    return integrationTypes.filter(t => {
      const matchesSearch = !typeSearch ||
        t.name.toLowerCase().includes(typeSearch.toLowerCase()) ||
        t.description?.toLowerCase().includes(typeSearch.toLowerCase());
      const matchesCategory = !categoryFilter || t.category === categoryFilter;
      return matchesSearch && matchesCategory;
    });
  }, [integrationTypes, typeSearch, categoryFilter]);

  const selectType = (typeId: string) => {
    const t = integrationTypes.find(x => x.id === typeId);
    setFormType(typeId);
    setFormName(t?.name || '');
    const defaults: Record<string, unknown> = {};
    if (t?.config_schema) {
      for (const [k, v] of Object.entries(t.config_schema)) {
        if (v.default !== undefined) defaults[k] = v.default;
        else if (v.type === 'boolean') defaults[k] = false;
        else defaults[k] = '';
      }
    }
    setFormConfig(defaults);
    setFormApiKey('');
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormSaving(true);
    try {
      const creds: Record<string, unknown> = { ...formConfig };
      if (formApiKey) creds.api_key = formApiKey;
      for (const k of Object.keys(creds)) {
        if (creds[k] === '') delete creds[k];
      }

      if (editingId) {
        await integrationsApi.update(editingId, { name: formName, config: creds });
        success('Integration Updated', '"' + formName + '" has been updated');
      } else {
        await integrationsApi.create({ service_type: formType, name: formName, config: creds });
        success('Integration Created', '"' + formName + '" is ready to use');
      }
      setShowForm(false);
      setEditingId(null);
      setFormType('');
      setFormName('');
      setFormConfig({});
      setFormApiKey('');
      load();
    } catch (err: unknown) {
      apiError(err, 'Failed to save integration');
    } finally {
      setFormSaving(false);
    }
  };

  const openDriveBrowser = async (id: number) => {
    setDriveBrowserId(id);
    setDriveBrowserOpen(true);
    setDriveLoading(true);
    setDriveFiles([]);
    setDriveBrowserMessage(null);
    try {
      const result = await integrationsApi.driveFiles(id, driveSearch || undefined);
      if (result.error) {
        apiError(new Error(result.error), 'Drive browse failed');
      } else if (result.message) {
        setDriveBrowserMessage(result.message);
      } else {
        setDriveFiles(result.files || []);
      }
    } catch (err) {
      apiError(err, 'Failed to load Drive files');
    } finally {
      setDriveLoading(false);
    }
  };

  const closeDriveBrowser = () => {
    setDriveBrowserOpen(false);
    setDriveBrowserId(null);
    setDriveFiles([]);
    setDriveBrowserMessage(null);
    setDriveSearch('');
  };

  const searchDrive = async () => {
    if (!driveBrowserId) return;
    setDriveLoading(true);
    setDriveBrowserMessage(null);
    try {
      const result = await integrationsApi.driveFiles(driveBrowserId, driveSearch || undefined);
      if (result.message) {
        setDriveBrowserMessage(result.message);
        setDriveFiles([]);
      } else {
        setDriveFiles(result.files || []);
      }
    } catch (err) {
      apiError(err, 'Search failed');
    } finally {
      setDriveLoading(false);
    }
  };

  const loadPreview = async (fileId: string, fileName: string) => {
    if (!driveBrowserId) return;
    setPreviewFileId(fileId);
    setPreviewFileName(fileName);
    setPreviewOpen(true);
    setPreviewLoading(true);
    setPreviewContent('');
    try {
      const result = await integrationsApi.driveFilePreview(driveBrowserId, fileId);
      setPreviewContent(result.preview);
    } catch (err) {
      apiError(err, 'Failed to load file preview');
      setPreviewContent('Unable to load preview.');
    } finally {
      setPreviewLoading(false);
    }
  };

  const closePreview = () => {
    setPreviewOpen(false);
    setPreviewFileId(null);
    setPreviewFileName('');
    setPreviewContent('');
  };

  const openEdit = (integration: Integration) => {
    const t = integrationTypes.find(x => x.id === integration.service_type);
    setEditingId(integration.id);
    setFormType(integration.service_type);
    setFormName(integration.name);
    const config = { ...(integration.config || {}) };
    const apiKey = (config.api_key as string) || '';
    delete config.api_key;
    setFormApiKey(apiKey);
    if (t?.config_schema) {
      for (const [k, v] of Object.entries(t.config_schema)) {
        if (!(k in config)) {
          config[k] = v.default !== undefined ? v.default : '';
        }
      }
    }
    setFormConfig(config);
    setShowForm(true);
  };

  const handleTest = async (id: number) => {
    setTesting(id);
    try {
      const result = await integrationsApi.test(id);
      const ok = result.status === 'ok' || result.status === 'success' || result.status === 'connected' || result.status === 'configured';
      if (ok) {
        success('Test Passed', result.message || 'Connection successful!');
      } else {
        apiError(new Error(result.message || 'Connection failed'), 'Connection test failed');
      }
    } catch (err: unknown) {
      apiError(err, 'Connection test failed');
    } finally {
      setTesting(null);
    }
  };

  const handleDelete = (id: number) => {
    setDeleteTarget(id);
  };

  const confirmDelete = async () => {
    if (deleteTarget === null) return;
    const id = deleteTarget;
    setDeleteTarget(null);
    setDeleting(id);
    try {
      await integrationsApi.delete(id);
      success('Integration Deleted', 'Integration removed successfully');
      load();
    } catch (err: unknown) {
      apiError(err, 'Failed to delete integration');
    } finally {
      setDeleting(null);
    }
  };

  const handleReactivate = async (id: number) => {
    setReactivating(id);
    try {
      await integrationsApi.reactivate(id);
      success('Integration Reactivated', 'Integration is now active and ready to use');
      load();
    } catch (err: unknown) {
      apiError(err, 'Failed to reactivate integration');
    } finally {
      setReactivating(null);
    }
  };

  const ICON_MAP: Record<string, LucideIcon> = {
    mcp: Server, custom_api: Code, webhook: Globe,
    google_calendar: Calendar, google_sheets: Table,
    sms: Smartphone, email: Mail, sendgrid: Send,
    slack: MessageSquare, discord: MessageCircle, microsoft_teams: Monitor,
    whatsapp_cloud: MessageCircle,
    telegram_bot: Send,
    salesforce: Cloud, hubspot: TrendingUp, pipedrive: TrendingUp,
    gohighlevel: Rocket,
    zendesk: LifeBuoy, freshdesk: LifeBuoy, intercom: Inbox,
    notion: FileText, airtable: Layout,
    jira: Clipboard, linear: GitMerge,
    zapier: Zap, make: Layers,
    cal_com: CalendarPlus, calendly: CalendarPlus,
    stripe: CreditCard, shopify: ShoppingBag,
    knowledge_base: BookOpen,
    google_drive_mcp: HardDrive,
  };

  const COLOR_MAP: Record<string, string> = {
    mcp: 'text-green-400 bg-green-400/10',
    custom_api: 'text-blue-400 bg-blue-400/10',
    webhook: 'text-rose-400 bg-rose-400/10',
    google_calendar: 'text-sky-400 bg-sky-400/10',
    google_sheets: 'text-emerald-400 bg-emerald-400/10',
    sms: 'text-violet-400 bg-violet-400/10',
    email: 'text-amber-400 bg-amber-400/10',
    sendgrid: 'text-blue-300 bg-blue-300/10',
    slack: 'text-purple-400 bg-purple-400/10',
    discord: 'text-indigo-400 bg-indigo-400/10',
    microsoft_teams: 'text-blue-500 bg-blue-500/10',
    whatsapp_cloud: 'text-green-500 bg-green-500/10',
    telegram_bot: 'text-sky-400 bg-sky-400/10',
    salesforce: 'text-sky-500 bg-sky-500/10',
    hubspot: 'text-orange-400 bg-orange-400/10',
    pipedrive: 'text-green-300 bg-green-300/10',
    gohighlevel: 'text-teal-400 bg-teal-400/10',
    zendesk: 'text-emerald-300 bg-emerald-300/10',
    freshdesk: 'text-green-400 bg-green-400/10',
    intercom: 'text-blue-400 bg-blue-400/10',
    notion: 'text-gray-300 bg-gray-300/10',
    airtable: 'text-yellow-400 bg-yellow-400/10',
    jira: 'text-blue-500 bg-blue-500/10',
    linear: 'text-violet-400 bg-violet-400/10',
    zapier: 'text-orange-500 bg-orange-500/10',
    make: 'text-purple-500 bg-purple-500/10',
    cal_com: 'text-gray-300 bg-gray-300/10',
    calendly: 'text-blue-400 bg-blue-400/10',
    stripe: 'text-violet-500 bg-violet-500/10',
    shopify: 'text-green-500 bg-green-500/10',
    knowledge_base: 'text-amber-300 bg-amber-300/10',
    google_drive_mcp: 'text-blue-400 bg-blue-400/10',
  };

  const getIcon = (stype: string): LucideIcon => ICON_MAP[stype] || Plug;
  const getColor = (stype: string): string => COLOR_MAP[stype] || 'text-blue-400 bg-blue-400/10';

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="page-title dash-title-gradient dash-title-glow">Integrations</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <SkeletonCard className="h-32" />
          <SkeletonCard className="h-32" />
          <SkeletonCard className="h-32" />
          <SkeletonCard className="h-32" />
        </div>
      </div>
    );
  }

  const configFields = selectedType?.config_schema
    ? Object.entries(selectedType.config_schema).filter(([k]) => k !== 'api_key')
    : [];

  return (
    <GsapPageWrapper>
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Integrations</h1>
          <p className="page-subtitle">Connect external services to use in your workflows</p>
        </div>
        <button onClick={() => { setShowForm(true); setFormType(''); setEditingId(null); }} className="flex items-center gap-2 btn-primary">
          <Plus size={16} /> Add Integration
        </button>
      </div>

      {/* Settings Tabs */}
      <SettingsTabBar />

      {/* Create / Edit Form */}
      {showForm && (
        <div className="dash-card p-6">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              {formType && (
                <button onClick={() => setFormType('')} className="p-1 rounded hover:bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
                  <ArrowLeft size={18} />
                </button>
              )}
              <h2 className="text-lg font-semibold">
                {editingId ? 'Edit Integration' : formType ? 'Configure ' + (selectedType?.name || '') : 'Choose Integration Type'}
              </h2>
            </div>
            <button onClick={() => { setShowForm(false); setEditingId(null); setFormType(''); }} className="btn-ghost p-1">
              <XCircle size={20} />
            </button>
          </div>

          {/* Type Picker */}
          {!formType && !editingId && (
            <div className="space-y-4">
              <div className="flex gap-3">
                <div className="flex-1 relative">
                  <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
                  <input
                    type="text"
                    value={typeSearch}
                    onChange={e => setTypeSearch(e.target.value)}
                    placeholder="Search integrations..."
                    className="w-full pl-9 input-base text-sm"
                  />
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => setCategoryFilter('')}
                  className={cn(
                    'px-3 py-1 text-xs rounded-full border transition-colors',
                    !categoryFilter
                      ? 'bg-brand-500/20 border-brand-500/30 text-brand-400'
                      : 'border-[var(--glass-border)] text-[var(--text-muted)] hover:text-white hover:border-[var(--border-hover)]'
                  )}
                >
                  All
                </button>
                {Object.entries(CATEGORY_LABELS).map(([key, label]) => {
                  const count = integrationTypes.filter(t => t.category === key).length;
                  if (count === 0) return null;
                  return (
                    <button
                      key={key}
                      onClick={() => setCategoryFilter(categoryFilter === key ? '' : key)}
                      className={cn(
                        'px-3 py-1 text-xs rounded-full border transition-colors',
                        categoryFilter === key
                          ? 'bg-brand-500/20 border-brand-500/30 text-brand-400'
                          : 'border-[var(--glass-border)] text-[var(--text-muted)] hover:text-white hover:border-[var(--border-hover)]'
                      )}
                    >
                      {label} ({count})
                    </button>
                  );
                })}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {filteredTypes.map(t => {
                  const Icon = getIcon(t.id);
                  const color = getColor(t.id);
                  const difficulty = t.setup_guide?.difficulty;
                  const existing = integrationList.find(i => i.service_type === t.id);
                  const isActive = existing?.is_active;
                  if (isActive) return null;
                  return (
                    <div
                      key={t.id}
                      className="flex items-start gap-3 p-4 rounded-xl border border-[var(--glass-border)] bg-[var(--bg-primary)] hover:border-brand-500/40 hover:bg-[var(--bg-tertiary)] transition-all text-left group relative"
                    >
                      <button
                        onClick={() => selectType(t.id)}
                        className="flex items-start gap-3 flex-1 min-w-0 text-left"
                      >
                        <div className={cn('p-2 rounded-lg shrink-0', color)}>
                          <Icon size={18} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-medium group-hover:text-brand-400 transition-colors">{t.name}</p>
                            {difficulty && (
                              <span className={cn('px-1.5 py-0.5 text-[9px] rounded-full border', DIFFICULTY_COLORS[difficulty] || '')}>
                                {difficulty}
                              </span>
                            )}
                            {existing && !isActive && (
                              <span className="px-1.5 py-0.5 text-[9px] rounded-full border text-amber-400 border-amber-400/20 bg-amber-400/10">
                                Inactive
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-[var(--text-muted)] mt-0.5 line-clamp-2">{t.description}</p>
                        </div>
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setHelpDrawerType(t);
                          setHelpDrawerIntegration(existing || null);
                        }}
                        className="shrink-0 p-1.5 rounded-md text-[var(--text-muted)] hover:text-brand-400 hover:bg-brand-500/10 transition-colors"
                        title="Learn more"
                      >
                        <HelpCircle size={14} />
                      </button>
                    </div>
                  );
                })}
              </div>
              {filteredTypes.length === 0 && (
                <div className="text-center py-8 text-[var(--text-muted)]">
                  <Search size={24} className="mx-auto mb-2 opacity-40" />
                  <p className="text-sm">No integrations match your search</p>
                </div>
              )}
            </div>
          )}

          {/* Existing integration guard */}
          {formType && !editingId && selectedType && (
            (() => {
              const existing = integrationList.find(i => i.service_type === formType);
              if (!existing) return null;
              return (
                <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-5 mb-4">
                  <div className="flex items-start gap-3">
                    <AlertTriangle size={18} className="text-amber-400 shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <h3 className="text-sm font-medium text-amber-200">Integration already exists</h3>
                      <p className="text-xs text-amber-200/70 mt-1">
                        You already have a <strong>{selectedType.name}</strong> integration.
                        {existing.is_active
                          ? ' You cannot create another one of the same type. Edit the existing integration instead.'
                          : ' It is currently inactive. You can reactivate it or edit it instead of creating a new one.'}
                      </p>
                      <div className="flex gap-2 mt-3">
                        {!existing.is_active && (
                          <button
                            type="button"
                            onClick={() => handleReactivate(existing.id)}
                            disabled={reactivating === existing.id}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-green-500/10 hover:bg-green-500/20 border border-green-500/20 rounded-lg text-xs text-green-400 transition-colors disabled:opacity-50"
                          >
                            {reactivating === existing.id ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
                            Reactivate
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => openEdit(existing)}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-tertiary)] hover:bg-[var(--bg-primary)] border border-[var(--glass-border)] rounded-lg text-xs transition-colors"
                        >
                          <Pencil size={12} /> Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => setFormType('')}
                          className="px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:text-white transition-colors"
                        >
                          Back
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })()
          )}

          {/* Config Form */}
          {(formType || editingId) && selectedType && !integrationList.find(i => i.service_type === formType && !editingId) && (
            <div className="flex gap-6 flex-col lg:flex-row">
              {/* Left: Form */}
              <form onSubmit={handleCreate} className="flex-[3] space-y-5 min-w-0">
                <div>
                  <label className="text-xs font-medium mb-1 block">Integration Name</label>
                  <input
                    type="text"
                    value={formName}
                    onChange={e => setFormName(e.target.value)}
                    required
                    className="w-full input-base text-sm"
                    placeholder={'My ' + (selectedType?.name || '')}
                  />
                </div>

                <div className="rounded-xl border border-[var(--glass-border)] p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <Shield size={14} className="text-brand-400" />
                    <h3 className="text-xs font-semibold uppercase tracking-wider">Authentication</h3>
                  </div>

                  {selectedType.api_key_help && (
                    <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
                      <Info size={14} className="text-blue-400 mt-0.5 shrink-0" />
                      <p className="text-[11px] text-blue-200">{selectedType.api_key_help}</p>
                    </div>
                  )}

                  {/* Google OAuth Connect Button */}
                  {isGoogleIntegration && (
                    <div className="space-y-2">
                      <div className="rounded-lg border border-brand-500/20 bg-brand-500/5 px-3 py-2 text-xs text-[var(--text-secondary)] space-y-2">
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <Shield size={13} className="text-brand-400" />
                            <span className="font-medium text-[var(--text-primary)]">Google OAuth</span>
                          </div>
                          <span className={cn(
                            'px-2 py-0.5 rounded-full text-[10px] border',
                            googleOAuthStatus?.connected
                              ? 'text-green-400 border-green-400/20 bg-green-400/10'
                              : 'text-amber-400 border-amber-400/20 bg-amber-400/10'
                          )}>
                            {googleOAuthStatus?.connected ? 'Connected' : 'Not connected'}
                          </span>
                        </div>
                        <p className="text-[11px] text-[var(--text-muted)] leading-relaxed">
                          OAuth tokens are stored securely in the backend and will not appear as a visible key here.
                          {formType === 'google_drive_mcp'
                            ? 'Google Drive MCP uses OAuth for authentication — no API key needed. Just connect your Google account.'
                            : 'Add the calendar or spreadsheet details below, then click Create Integration.'}
                        </p>
                        {googleOAuthStatus?.scopes?.length ? (
                          <p className="text-[10px] text-[var(--text-muted)]">
                            Granted scopes: {googleOAuthStatus.scopes.length}
                          </p>
                        ) : null}
                      </div>
                      <button
                        type="button"
                        onClick={async () => {
                          try {
                            const redirectUri = process.env.NEXT_PUBLIC_GOOGLE_OAUTH_REDIRECT_URI || 'http://localhost:3001/oauth/google/callback';
                            const res = await integrationsApi.googleAuth(redirectUri);
                            const popup = window.open(
                              res.auth_url,
                              'google-oauth',
                              'width=500,height=600,top=100,left=100'
                            );
                            if (!popup) {
                              apiError(new Error('Popup blocked. Please allow popups for this site.'), 'Popup blocked');
                              return;
                            }
                            // Poll for popup close
                            const timer = setInterval(async () => {
                              if (popup.closed) {
                                clearInterval(timer);
                                // Check if connected
                                const status = await refreshGoogleStatus();
                                if (status?.connected) {
                                  await load();
                                  success('Google Connected', 'Your Google account is linked. OAuth tokens are stored securely; save the integration config to use it in workflows or agents.');
                                }
                              }
                            }, 1000);
                          } catch (err: unknown) {
                            apiError(err, 'Failed to start Google OAuth');
                          }
                        }}
                        className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-white text-gray-900 rounded-lg text-sm font-medium hover:bg-gray-100 transition-colors"
                      >
                        <svg className="w-5 h-5" viewBox="0 0 24 24">
                          <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/>
                          <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                          <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                          <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
                        </svg>
                        Connect with Google
                      </button>
                      <p className="text-[10px] text-[var(--text-muted)] text-center">
                        Recommended: one-click OAuth login. Service account JSON is optional and only needed for advanced fallback setups.
                      </p>
                    </div>
                  )}

                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <label className="text-xs font-medium">
                        {isGoogleIntegration ? 'Service Account JSON (optional)' : 'API Key / Token'}
                      </label>
                      {!isGoogleIntegration && <span className="text-red-400 text-[10px]">*</span>}
                    </div>
                    <input
                      type="password"
                      value={formApiKey}
                      onChange={e => setFormApiKey(e.target.value)}
                      className="w-full input-base text-sm font-mono"
                      placeholder={isGoogleIntegration
                        ? 'Optional: paste a Google service account JSON key here'
                        : 'Paste your API key or token here'}
                    />
                  </div>
                </div>

                {configFields.length > 0 && (
                  <div className="rounded-xl border border-[var(--glass-border)] p-4 space-y-4">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">Service Configuration</h3>
                    {configFields.map(([key, schema]) => {
                      // For Google Drive MCP, show server_url as read-only info
                      if (formType === 'google_drive_mcp' && key === 'server_url') {
                        return (
                          <div key={key} className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--glass-border)]">
                            <Server size={14} className="text-blue-400 shrink-0" />
                            <div className="flex-1 min-w-0">
                              <p className="text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-wider">MCP Server (auto-configured)</p>
                              <p className="text-xs font-mono text-[var(--text-secondary)] truncate mt-0.5">
                                {(formConfig[key] as string) || 'https://drivemcp.googleapis.com/mcp/v1'}
                              </p>
                            </div>
                            <CheckCircle size={14} className="text-green-400 shrink-0" />
                          </div>
                        );
                      }
                      return (
                        <ConfigField
                          key={key}
                          fieldName={key}
                          fieldSchema={schema}
                          value={formConfig[key]}
                          onChange={(val) => setFormConfig(prev => ({ ...prev, [key]: val }))}
                        />
                      );
                    })}
                  </div>
                )}

                {selectedType.capabilities && selectedType.capabilities.length > 0 && (
                  <div className="rounded-xl border border-[var(--glass-border)] p-4">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">Capabilities</h3>
                    <div className="flex flex-wrap gap-1.5">
                      {selectedType.capabilities.map((c: string) => (
                        <span key={c} className="px-2 py-0.5 text-[10px] bg-brand-500/10 border border-brand-500/20 text-brand-400 rounded-full">
                          {c.replace(/_/g, ' ')}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => { setShowForm(false); setEditingId(null); setFormType(''); }}
                    className="px-4 py-2 text-sm text-[var(--text-secondary)] hover:text-white transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={formSaving}
                    className="flex items-center gap-2 btn-primary disabled:opacity-50"
                  >
                    {formSaving && <Loader2 size={14} className="animate-spin" />}
                    {editingId ? 'Update Integration' : 'Create Integration'}
                  </button>
                </div>
              </form>

              {/* Right: Setup Guide */}
              <div className="flex-[2] hidden lg:block">
                <SetupGuidePanel guide={selectedType.setup_guide} apiKeyHelp={selectedType.api_key_help} />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Platform Defaults */}
      {platformEmailReady && !showForm && (
        <div className="dash-card p-4">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle size={16} className="text-emerald-400" />
            <h2 className="text-sm font-medium text-emerald-300">Platform Defaults</h2>
          </div>
          <p className="text-xs text-[var(--text-muted)] mb-3">
            System-level integrations configured via server .env. Connect your own to override.
          </p>
          <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
            <Mail size={18} className="text-amber-400 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium">Email (SMTP)</p>
              <p className="text-xs text-[var(--text-muted)]">Connected via platform Gmail — ready to send emails</p>
            </div>
            <span className="text-[10px] font-medium text-emerald-400 bg-emerald-500/10 px-2 py-1 rounded-full">
              Active
            </span>
          </div>
        </div>
      )}

      {/* Available Types (when no integrations yet) */}
      {integrationList.length === 0 && !showForm && integrationTypes.length > 0 && (
        <div className="dash-card p-6">
          <h2 className="text-sm font-medium text-[var(--text-muted)] mb-4">Available Integration Types</h2>
          <div className="space-y-6">
            {Object.entries(typesByCategory).map(([category, types]) => (
              <div key={category}>
                <h3 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">
                  {CATEGORY_LABELS[category] || category}
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {types.map(t => {
                    const Icon = getIcon(t.id);
                    const color = getColor(t.id);
                    return (
                      <div
                        key={t.id}
                        className="flex items-start gap-3 p-4 bg-[var(--bg-primary)] rounded-lg border border-[var(--glass-border)] hover:border-[var(--border-hover)] transition-colors cursor-pointer"
                        onClick={() => { selectType(t.id); setShowForm(true); }}
                      >
                        <div className={cn('p-2 rounded-lg shrink-0', color)}>
                          <Icon size={18} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium">{t.name}</p>
                          <p className="text-[11px] text-[var(--text-muted)] mt-0.5 line-clamp-2">{t.description}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Connected Google Drive Summary */}
      {(() => {
        const driveInts = integrationList.filter(i => i.service_type === 'google_drive_mcp' && i.is_active);
        if (driveInts.length === 0) return null;
        return (
          <div className="dash-card p-5 bg-gradient-to-r from-blue-500/5 to-transparent border-blue-500/20">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-lg bg-blue-500/10">
                  <HardDrive size={20} className="text-blue-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-[var(--text-primary)]">Google Drive Connected</h3>
                  <p className="text-xs text-[var(--text-muted)] mt-0.5">
                    {driveInts.length} integration{driveInts.length !== 1 ? 's' : ''} active · Click Browse to explore files
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {driveInts.map(d => (
                  <button
                    key={d.id}
                    onClick={() => openDriveBrowser(d.id)}
                    className="text-xs bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5"
                  >
                    <HardDrive size={12} /> Browse {d.name}
                  </button>
                ))}
              </div>
            </div>
          </div>
        );
      })()}

      {/* Inactive Google Drive Summary */}
      {(() => {
        const inactiveDriveInts = integrationList.filter(i => i.service_type === 'google_drive_mcp' && !i.is_active);
        if (inactiveDriveInts.length === 0) return null;
        return (
          <div className="dash-card p-5 bg-gradient-to-r from-amber-500/5 to-transparent border-amber-500/20 opacity-80">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-lg bg-amber-500/10">
                  <HardDrive size={20} className="text-amber-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-[var(--text-primary)]">Google Drive (Inactive)</h3>
                  <p className="text-xs text-[var(--text-muted)] mt-0.5">
                    {inactiveDriveInts.length} inactive integration{inactiveDriveInts.length !== 1 ? 's' : ''} · Reactivate to use Drive tools
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {inactiveDriveInts.map(d => (
                  <button
                    key={d.id}
                    onClick={() => handleReactivate(d.id)}
                    disabled={reactivating === d.id}
                    className="text-xs bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5 disabled:opacity-50"
                  >
                    {reactivating === d.id ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
                    Reactivate {d.name}
                  </button>
                ))}
              </div>
            </div>
          </div>
        );
      })()}

      {/* Integration List */}
      {integrationList.length > 0 && (
        <div className="space-y-3">
          {integrationList.map(integration => {
            const Icon = getIcon(integration.service_type);
            const color = getColor(integration.service_type);
            const showCreds = showCredentials[integration.id];
            return (
              <div key={integration.id} className={cn('dash-card p-5 hover:border-[var(--border-hover)] transition-colors', !integration.is_active && 'opacity-60')}>                <div className="flex items-start gap-4">
                  <div className={cn('p-2.5 rounded-lg', color)}>
                    <Icon size={20} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-semibold">{integration.name}</h3>
                      <span className="px-2 py-0.5 text-[10px] rounded-full bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
                        {integration.service_type}
                      </span>
                      {integration.is_active ? (
                        <span className="flex items-center gap-1 text-[10px] text-green-400">
                          <CheckCircle size={10} /> Active
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-[10px] text-red-400">
                          <XCircle size={10} /> Inactive
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-[var(--text-muted)] mt-0.5">
                      Created {formatTimestamp(integration.created_at)}
                    </p>
                    <button
                      onClick={() => setShowCredentials(prev => ({ ...prev, [integration.id]: !prev[integration.id] }))}
                      className="flex items-center gap-1 mt-2 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
                    >
                      {showCreds ? <EyeOff size={12} /> : <Eye size={12} />}
                      {showCreds ? 'Hide' : 'Show'} credentials
                    </button>
                    {showCreds && (
                      <pre className="mt-1 p-2 bg-[var(--bg-primary)] rounded text-[10px] font-mono text-[var(--text-muted)] overflow-x-auto max-h-32">
                        {JSON.stringify(integration.config || { note: 'Config hidden by server' }, null, 2)}
                      </pre>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    {integration.service_type === 'google_drive_mcp' && integration.is_active && (
                      <button
                        onClick={() => openDriveBrowser(integration.id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 rounded-lg text-xs text-blue-400 transition-colors"
                      >
                        <HardDrive size={12} /> Browse
                      </button>
                    )}
                    <button
                      onClick={() => {
                        const type = integrationTypes.find(t => t.id === integration.service_type);
                        if (type) {
                          setHelpDrawerType(type);
                          setHelpDrawerIntegration(integration);
                        }
                      }}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-tertiary)] hover:bg-[var(--bg-primary)] border border-[var(--glass-border)] rounded-lg text-xs transition-colors"
                    >
                      <BookOpen size={12} /> Help
                    </button>
                    <button
                      onClick={() => openEdit(integration)}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-tertiary)] hover:bg-[var(--bg-primary)] border border-[var(--glass-border)] rounded-lg text-xs transition-colors"
                    >
                      <Pencil size={12} /> Edit
                    </button>
                    {integration.is_active ? (
                      <>
                        <button
                          onClick={() => handleTest(integration.id)}
                          disabled={testing === integration.id}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-tertiary)] hover:bg-[var(--bg-primary)] border border-[var(--glass-border)] rounded-lg text-xs transition-colors disabled:opacity-50"
                        >
                          {testing === integration.id ? <Loader2 size={12} className="animate-spin" /> : <TestTube size={12} />}
                          Test
                        </button>
                        <button
                          onClick={() => handleDelete(integration.id)}
                          disabled={deleting === integration.id}
                          className="p-1.5 text-[var(--text-muted)] hover:text-red-400 transition-colors disabled:opacity-50"
                        >
                          {deleting === integration.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                        </button>
                      </>
                    ) : (
                      <button
                        onClick={() => handleReactivate(integration.id)}
                        disabled={reactivating === integration.id}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-green-500/10 hover:bg-green-500/20 border border-green-500/20 rounded-lg text-xs text-green-400 transition-colors disabled:opacity-50"
                      >
                        {reactivating === integration.id ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
                        Reactivate
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Empty state */}
      {/* Help Drawer */}
      {helpDrawerType && (
        <IntegrationHelpDrawer
          integrationType={helpDrawerType}
          integration={helpDrawerIntegration}
          isOpen={!!helpDrawerType}
          onClose={() => { setHelpDrawerType(null); setHelpDrawerIntegration(null); }}
        />
      )}

      {integrationList.length === 0 && !showForm && integrationTypes.length === 0 && (
        <EmptyState
          icon={Plug}
          title="No extensions yet"
          description="Connect external services via MCP or Custom Webhooks to give your agents new capabilities."
          action={
            <button onClick={() => setShowForm(true)} className="btn-primary">
              <Plus size={16} />
              Add Your First Extension
            </button>
          }
        />
      )}

      {/* Drive File Browser Modal */}
      {driveBrowserOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--bg-primary)]/80 backdrop-blur-sm p-4">
          <div className="bg-[var(--bg-secondary)] rounded-xl w-full max-w-2xl max-h-[80vh] flex flex-col shadow-2xl">
            <div className="flex items-center justify-between p-4 border-b border-[var(--glass-border)]">
              <div className="flex items-center gap-2">
                <HardDrive size={18} className="text-blue-400" />
                <h3 className="font-semibold">Google Drive Files</h3>
              </div>
              <button onClick={closeDriveBrowser} className="btn-ghost p-1">
                <X size={16} />
              </button>
            </div>

            <div className="p-4 border-b border-[var(--glass-border)]">
              <div className="flex gap-2">
                <input
                  value={driveSearch}
                  onChange={(e) => setDriveSearch(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') searchDrive(); }}
                  placeholder="Search files by name..."
                  className="input-base flex-1 text-sm"
                />
                <button
                  onClick={searchDrive}
                  disabled={driveLoading}
                  className="btn-primary px-3 disabled:opacity-40"
                >
                  {driveLoading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4">
              {driveLoading && driveFiles.length === 0 ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 size={24} className="animate-spin text-[var(--accent)]" />
                </div>
              ) : driveBrowserMessage ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <Info size={24} className="text-amber-400 mb-3" />
                  <p className="text-sm text-amber-200 max-w-md">{driveBrowserMessage}</p>
                  <p className="text-xs text-[var(--text-muted)] mt-2">This MCP server may not expose file browsing tools.</p>
                </div>
              ) : driveFiles.length === 0 ? (
                <p className="text-sm text-[var(--text-muted)] text-center py-12">
                  {driveSearch ? 'No files match your search.' : 'No files found in this Drive.'}
                </p>
              ) : (
                <div className="space-y-2">
                  {driveFiles.map((file) => {
                    const m = file.mimeType.toLowerCase();
                    let FileIcon = FileText;
                    let typeLabel = 'File';
                    let typeColor = 'text-gray-400';
                    let badgeBg = 'bg-gray-500/10';
                    if (m.includes('spreadsheet') || m.includes('sheet') || m.includes('csv')) {
                      FileIcon = FileSpreadsheet; typeLabel = 'Sheet'; typeColor = 'text-green-400'; badgeBg = 'bg-green-500/10';
                    } else if (m.includes('presentation') || m.includes('slide')) {
                      FileIcon = Presentation; typeLabel = 'Slides'; typeColor = 'text-yellow-400'; badgeBg = 'bg-yellow-500/10';
                    } else if (m.includes('document') || m.includes('word') || m.includes('plain')) {
                      FileIcon = FileText; typeLabel = 'Doc'; typeColor = 'text-blue-400'; badgeBg = 'bg-blue-500/10';
                    } else if (m.includes('pdf')) {
                      FileIcon = FileType; typeLabel = 'PDF'; typeColor = 'text-red-400'; badgeBg = 'bg-red-500/10';
                    } else if (m.includes('image')) {
                      FileIcon = FileImage; typeLabel = 'Image'; typeColor = 'text-purple-400'; badgeBg = 'bg-purple-500/10';
                    } else if (m.includes('audio')) {
                      FileIcon = FileAudio; typeLabel = 'Audio'; typeColor = 'text-pink-400'; badgeBg = 'bg-pink-500/10';
                    } else if (m.includes('video')) {
                      FileIcon = FileVideo; typeLabel = 'Video'; typeColor = 'text-orange-400'; badgeBg = 'bg-orange-500/10';
                    } else if (m.includes('code') || m.includes('json') || m.includes('javascript')) {
                      FileIcon = FileCode; typeLabel = 'Code'; typeColor = 'text-cyan-400'; badgeBg = 'bg-cyan-500/10';
                    } else if (m.includes('folder')) {
                      FileIcon = Folder; typeLabel = 'Folder'; typeColor = 'text-amber-400'; badgeBg = 'bg-amber-500/10';
                    }
                    return (
                      <button
                        key={file.id}
                        onClick={() => loadPreview(file.id, file.name)}
                        className="w-full flex items-center gap-3 p-3 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--glass-border)] hover:border-blue-500/30 transition-colors text-left"
                      >
                        <FileIcon size={18} className={`${typeColor} shrink-0`} />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium truncate">{file.name}</p>
                          <p className="text-[10px] text-[var(--text-muted)]">
                            {file.modifiedTime ? new Date(file.modifiedTime).toLocaleDateString() : ''}
                          </p>
                        </div>
                        <span className={`text-[10px] px-2 py-0.5 rounded ${badgeBg} ${typeColor} font-medium shrink-0`}>
                          {typeLabel}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Drive File Preview Modal */}
      {previewOpen && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[var(--bg-primary)]/80 backdrop-blur-sm p-4">
          <div className="bg-[var(--bg-secondary)] rounded-xl w-full max-w-xl max-h-[80vh] flex flex-col shadow-2xl">
            <div className="flex items-center justify-between p-4 border-b border-[var(--glass-border)]">
              <div className="flex items-center gap-2 min-w-0">
                <FileText size={18} className="text-blue-400 shrink-0" />
                <h3 className="font-semibold truncate">{previewFileName}</h3>
              </div>
              <button onClick={closePreview} className="btn-ghost p-1 shrink-0">
                <X size={16} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {previewLoading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 size={24} className="animate-spin text-[var(--accent)]" />
                </div>
              ) : (
                <div className="space-y-3">
                  <pre className="text-sm text-[var(--text-secondary)] bg-[var(--bg-primary)] p-4 rounded-lg border border-[var(--glass-border)] whitespace-pre-wrap font-mono max-h-[50vh] overflow-y-auto">
                    {previewContent}
                  </pre>
                  {previewContent.length > 0 && (
                    <p className="text-[10px] text-[var(--text-muted)] text-center">
                      Read-only preview · {previewContent.length} chars shown
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Deactivate Integration"
        message="Deactivate this integration? It will stop working in workflows but can be reactivated later."
        confirmLabel="Deactivate"
        variant="warning"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
    </GsapPageWrapper>
  );
}
