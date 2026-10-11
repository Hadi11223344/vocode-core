'use client';

import { useEffect, useState, useCallback } from 'react';
import { useToast } from '@/components/ui/toast';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { apiKeys } from '@/lib/api';
import { UserApiKey } from '@/lib/types';
import {
  Key, Plus, Trash2, X, CheckCircle, XCircle, Shield,
  Edit3, ToggleLeft, ToggleRight, ExternalLink,
  Mic, Volume2, Phone, Brain, Puzzle, AlertTriangle, Mail,
} from 'lucide-react';
import { timeAgo } from '@/lib/utils';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';
import SettingsTabBar from '../settings/_components/SettingsTabBar';

/* ── Service registry ─────────────────────────────────────── */
interface ServiceDef {
  label: string;
  color: string;
  category: 'LLM' | 'STT / TTS' | 'TTS' | 'Telephony' | 'Integration';
  icon: typeof Brain;
  description: string;
  docsUrl: string;
  placeholder: string;
  required?: boolean;           // core service for voice AI
  needsSecret?: boolean;        // needs api_secret field
  needsMetadata?: string[];     // metadata_json fields
}

const SERVICE_INFO: Record<string, ServiceDef> = {
  groq: {
    label: 'Groq',
    color: 'bg-orange-500/20 text-orange-400',
    category: 'LLM',
    icon: Brain,
    description: 'Ultra-fast LLaMA inference (free tier)',
    docsUrl: 'https://console.groq.com/keys',
    placeholder: 'gsk_...',
  },
  openai: {
    label: 'OpenAI',
    color: 'bg-emerald-500/20 text-emerald-400',
    category: 'LLM',
    icon: Brain,
    description: 'GPT-4o, GPT-4o-mini for agent conversations',
    docsUrl: 'https://platform.openai.com/api-keys',
    placeholder: 'sk-proj-...',
  },
  gemini: {
    label: 'Google Gemini',
    color: 'bg-blue-500/20 text-blue-400',
    category: 'LLM',
    icon: Brain,
    description: 'Gemini 2.0 Flash, Pro models',
    docsUrl: 'https://aistudio.google.com/apikey',
    placeholder: 'AIza...',
  },
  anthropic: {
    label: 'Anthropic',
    color: 'bg-amber-500/20 text-amber-400',
    category: 'LLM',
    icon: Brain,
    description: 'Claude 3 Haiku, Sonnet, Opus models',
    docsUrl: 'https://console.anthropic.com/settings/keys',
    placeholder: 'sk-ant-...',
  },
  ollama: {
    label: 'Ollama (Local)',
    color: 'bg-purple-500/20 text-purple-400',
    category: 'LLM',
    icon: Brain,
    description: 'Local LLM via Ollama — granite4.1:8b, qwen3.5:9b, qwen3:8b. No API key needed (pre-configured).',
    docsUrl: 'http://localhost:11434',
    placeholder: 'ollama (pre-configured)',
  },
  commandcode: {
    label: 'CommandCode',
    color: 'bg-cyan-500/20 text-cyan-400',
    category: 'LLM',
    icon: Brain,
    description: 'DeepSeek V4 Pro (4× usage deal). Best price/performance. Get your key at commandcode.ai/studio/api-keys',
    docsUrl: 'https://commandcode.ai/studio/api-keys',
    placeholder: 'user_...',
  },
  deepgram: {
    label: 'Deepgram',
    color: 'bg-violet-500/20 text-violet-400',
    category: 'STT / TTS',
    icon: Mic,
    description: 'Speech recognition (Nova-3) & text-to-speech (Aura) & Audio Intelligence (sentiment, summarization)',
    docsUrl: 'https://console.deepgram.com/',
    placeholder: 'dg-...',
    required: true,
  },
  elevenlabs: {
    label: 'ElevenLabs',
    color: 'bg-pink-500/20 text-pink-400',
    category: 'TTS',
    icon: Volume2,
    description: 'Premium AI voices for natural speech',
    docsUrl: 'https://elevenlabs.io/app/settings/api-keys',
    placeholder: 'xi-...',
  },
  twilio: {
    label: 'Twilio',
    color: 'bg-red-500/20 text-red-400',
    category: 'Telephony',
    icon: Phone,
    description: 'Phone number management & call routing',
    docsUrl: 'https://console.twilio.com/',
    placeholder: 'ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
    required: true,
    needsSecret: true,
    needsMetadata: ['phone_number'],
  },
  google_calendar: {
    label: 'Google Calendar',
    color: 'bg-cyan-500/20 text-cyan-400',
    category: 'Integration',
    icon: Puzzle,
    description: 'Schedule meetings during voice calls',
    docsUrl: 'https://console.cloud.google.com/apis/credentials',
    placeholder: 'Service account JSON...',
  },
  google_sheets: {
    label: 'Google Sheets',
    color: 'bg-green-500/20 text-green-400',
    category: 'Integration',
    icon: Puzzle,
    description: 'Read/write spreadsheet data during calls',
    docsUrl: 'https://console.cloud.google.com/apis/credentials',
    placeholder: 'Service account JSON...',
  },
  email: {
    label: 'Email (SMTP)',
    color: 'bg-amber-500/20 text-amber-400',
    category: 'Integration',
    icon: Mail,
    description: 'Send emails via SMTP (Gmail, Outlook, etc.)',
    docsUrl: 'https://support.google.com/mail/answer/185833',
    placeholder: 'App password...',
  },
};

const CATEGORIES = [
  { key: 'LLM', label: 'Language Models', icon: Brain, desc: 'At least one LLM key is required for agent conversations' },
  { key: 'STT / TTS', label: 'Speech Recognition & Synthesis', icon: Mic, desc: 'Deepgram powers real-time speech processing' },
  { key: 'TTS', label: 'Text-to-Speech', icon: Volume2, desc: 'Optional premium voice providers' },
  { key: 'Telephony', label: 'Telephony', icon: Phone, desc: 'Twilio handles inbound & outbound phone calls' },
  { key: 'Integration', label: 'Integrations', icon: Puzzle, desc: 'Connect external services to your voice agents' },
];

export default function APIKeysPage() {
  const [keys, setKeys] = useState<UserApiKey[]>([]);
  const [platformKeys, setPlatformKeys] = useState<Record<string, boolean>>({});
  const [twilioPhone, setTwilioPhone] = useState<string | null>(null);
  const [defaultModel, setDefaultModel] = useState('');
  const [loading, setLoading] = useState(true);
  const { success, apiError } = useToast();

  // Modal state
  const [modal, setModal] = useState<'add' | 'edit' | null>(null);
  const [editTarget, setEditTarget] = useState<UserApiKey | null>(null);
  const [formService, setFormService] = useState('openai');
  const [formKey, setFormKey] = useState('');
  const [formSecret, setFormSecret] = useState('');
  const [formLabel, setFormLabel] = useState('');
  const [formMetadata, setFormMetadata] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; label: string } | null>(null);

  const loadKeys = useCallback(async () => {
    try {
      const [keysData, statusData] = await Promise.all([
        apiKeys.list(),
        apiKeys.platformStatus().catch(() => ({ platform_keys: {}, twilio_phone_number: null, default_llm_model: '' })),
      ]);
      setKeys(keysData.keys);
      setPlatformKeys(statusData.platform_keys);
      setTwilioPhone(statusData.twilio_phone_number);
      setDefaultModel(statusData.default_llm_model);
    } catch (err) {
      apiError(err, 'Failed to load API keys');
    } finally {
      setLoading(false);
    }
  }, [apiError]);

  useEffect(() => { loadKeys(); }, [loadKeys]);

  /* ── Helpers ──────────────────────────────────────── */
  const configuredServices = new Set<string>(keys.map(k => k.service));

  // A service is "available" if user has stored a key OR platform .env has it
  const isAvailable = (svc: string) => configuredServices.has(svc) || platformKeys[svc];

  const hasLLM = (['openai', 'groq', 'gemini', 'anthropic', 'ollama'] as const).some(s => isAvailable(s));
  const hasSTT = isAvailable('deepgram');
  const hasTelephony = isAvailable('twilio');
  const coreReady = hasLLM && hasSTT && hasTelephony;

  const openAddModal = (service?: string) => {
    setModal('add');
    setEditTarget(null);
    setFormService(service || 'openai');
    setFormKey('');
    setFormSecret('');
    setFormLabel('');
    setFormMetadata({});
    setError('');
  };

  const openEditModal = (k: UserApiKey) => {
    setModal('edit');
    setEditTarget(k);
    setFormService(k.service);
    setFormKey('');
    setFormSecret('');
    setFormLabel(k.label || '');
    setFormMetadata({});
    setError('');
  };

  const closeModal = () => {
    setModal(null);
    setEditTarget(null);
  };

  /* ── CRUD ─────────────────────────────────────────── */
  const saveKey = async () => {
    if (modal === 'add' && !formKey.trim()) {
      setError('API key is required');
      return;
    }
    if (modal === 'edit' && !formKey.trim() && !formLabel.trim()) {
      setError('Enter a new key or update the label');
      return;
    }

    const svc = SERVICE_INFO[formService];
    if (svc?.needsSecret && modal === 'add' && !formSecret.trim()) {
      setError('Auth token / secret is required for this service');
      return;
    }

    setSaving(true);
    setError('');

    try {
      if (modal === 'add') {
        // Build metadata_json for services that need it
        let metadataJson: string | undefined;
        if (svc?.needsMetadata && Object.keys(formMetadata).length > 0) {
          const filtered = Object.fromEntries(
            Object.entries(formMetadata).filter(([, v]) => v.trim())
          );
          if (Object.keys(filtered).length > 0) {
            metadataJson = JSON.stringify(filtered);
          }
        }

        await apiKeys.create({
          service: formService,
          api_key: formKey,
          api_secret: formSecret || undefined,
          label: formLabel || undefined,
          ...(metadataJson ? { metadata_json: metadataJson } : {}),
        } as Parameters<typeof apiKeys.create>[0]);
        success('Key Added', `${svc?.label || formService} API key saved and encrypted`);
      } else if (modal === 'edit' && editTarget) {
        const updateData: Record<string, unknown> = {};
        if (formKey.trim()) updateData.api_key = formKey;
        if (formSecret.trim()) updateData.api_secret = formSecret;
        if (formLabel.trim() || formLabel !== (editTarget.label || '')) updateData.label = formLabel;

        await apiKeys.update(editTarget.id, updateData as Parameters<typeof apiKeys.update>[1]);
        success('Key Updated', `${svc?.label || formService} API key updated`);
      }

      closeModal();
      await loadKeys();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to save key');
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (k: UserApiKey) => {
    try {
      await apiKeys.update(k.id, { is_active: !k.is_active });
      await loadKeys();
      success(k.is_active ? 'Key Deactivated' : 'Key Activated', `${SERVICE_INFO[k.service]?.label || k.service} key ${k.is_active ? 'deactivated' : 'activated'}`);
    } catch (err) {
      apiError(err, 'Failed to toggle key');
    }
  };

  const deleteKey = (id: number, label: string) => {
    setDeleteTarget({ id, label });
  };

  const confirmDeleteKey = async () => {
    if (!deleteTarget) return;
    const { id, label } = deleteTarget;
    setDeleteTarget(null);
    try {
      await apiKeys.delete(id);
      await loadKeys();
      success('Key Deleted', `${label} API key removed`);
    } catch (err) {
      apiError(err, 'Failed to delete API key');
    }
  };

  /* ── Render ───────────────────────────────────────── */
  return (
    <GsapPageWrapper>
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">API Keys</h1>
          <p className="page-subtitle">Connect your AI, speech, and telephony providers</p>
        </div>
        <button onClick={() => openAddModal()} className="flex items-center gap-2 btn-primary">
          <Plus size={16} />
          Add Key
        </button>
      </div>

      {/* Settings Tabs */}
      <SettingsTabBar />

      {/* Setup Progress */}
      {!loading && (
        <div className={`rounded-xl border p-4 ${coreReady
          ? 'bg-green-500/5 border-green-500/20'
          : 'bg-amber-500/5 border-amber-500/20'
        }`}>
          <div className="flex items-start gap-3">
            {coreReady ? (
              <CheckCircle size={20} className="text-green-400 shrink-0 mt-0.5" />
            ) : (
              <AlertTriangle size={20} className="text-amber-400 shrink-0 mt-0.5" />
            )}
            <div className="flex-1">
              <p className={`text-sm font-medium ${coreReady ? 'text-green-300' : 'text-amber-300'}`}>
                {coreReady ? 'Voice pipeline ready' : 'Setup incomplete — configure required services'}
              </p>
              <div className="flex flex-wrap gap-3 mt-2">
                {[
                  { ok: hasLLM, label: 'LLM Provider', desc: 'OpenAI, Groq, Gemini, or Anthropic', envSvc: ['openai', 'groq', 'gemini'] },
                  { ok: hasSTT, label: 'Deepgram', desc: 'Speech-to-text & TTS', envSvc: ['deepgram'] },
                  { ok: hasTelephony, label: 'Twilio', desc: 'Phone call infrastructure', envSvc: ['twilio'] },
                ].map(item => {
                  const fromEnv = !item.ok ? false : item.envSvc.some(s => platformKeys[s] && !configuredServices.has(s));
                  return (
                  <button
                    key={item.label}
                    onClick={() => {
                      if (!item.ok) {
                        const svc = item.label === 'LLM Provider' ? 'openai'
                          : item.label === 'Deepgram' ? 'deepgram' : 'twilio';
                        openAddModal(svc);
                      }
                    }}
                    className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                      item.ok
                        ? 'bg-green-500/10 text-green-400'
                        : 'bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 cursor-pointer'
                    }`}
                  >
                    {item.ok ? <CheckCircle size={12} /> : <XCircle size={12} />}
                    {item.label}
                    {fromEnv && <span className="text-[9px] opacity-70 ml-0.5">(env)</span>}
                  </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Platform .env keys summary */}
      {!loading && Object.values(platformKeys).some(Boolean) && (
        <div className="bg-[var(--bg-secondary)] border border-[var(--glass-border)] rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-2">
            <Shield size={16} className="text-brand-400" />
            <span className="text-sm font-medium text-brand-300">Platform Keys (from .env)</span>
          </div>
          <p className="text-xs text-[var(--text-secondary)]">
            These keys are configured server-side and serve as defaults. User keys take priority when both exist.
            {defaultModel && <> Default model: <code className="text-brand-400">{defaultModel}</code></>}
          </p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(platformKeys).filter(([, v]) => v).map(([svc]) => (
              <span
                key={svc}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium ${
                  SERVICE_INFO[svc]?.color || 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'
                }`}
              >
                <CheckCircle size={11} />
                {SERVICE_INFO[svc]?.label || svc}
                {svc === 'twilio' && twilioPhone && (
                  <span className="text-[10px] opacity-70">{twilioPhone}</span>
                )}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Security notice */}
      <div className="bg-brand-600/10 border border-brand-500/20 rounded-xl p-4 flex gap-3">
        <Shield size={20} className="text-brand-400 shrink-0 mt-0.5" />
        <div className="text-sm">
          <p className="text-brand-300 font-medium">Encrypted at rest</p>
          <p className="text-[var(--text-secondary)] mt-1">
            All keys are encrypted with Fernet (AES-128-CBC) before storage. They are only decrypted at runtime when your agent makes API calls. Platform-level keys from .env serve as fallbacks.
          </p>
        </div>
      </div>

      {/* Keys by Category */}
      {loading ? (
        <div className="space-y-3 animate-stagger">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="dash-skeleton p-5 h-20" />
          ))}
        </div>
      ) : (
        <div className="space-y-8">
          {CATEGORIES.map(cat => {
            const servicesInCat = Object.entries(SERVICE_INFO).filter(([, s]) => s.category === cat.key);
            const availableInCat = servicesInCat.filter(([id]) => isAvailable(id));
            const CatIcon = cat.icon;

            return (
              <div key={cat.key}>
                <div className="flex items-center gap-2 mb-1">
                  <CatIcon size={16} className="text-brand-400" />
                  <h3 className="section-title !mb-0">{cat.label}</h3>
                  <span className="text-xs text-[var(--text-muted)] ml-1">
                    {availableInCat.length}/{servicesInCat.length} configured
                  </span>
                </div>
                <p className="text-xs text-[var(--text-muted)] mb-3 ml-6">{cat.desc}</p>

                <div className="grid gap-2">
                  {servicesInCat.map(([serviceId, svc]) => {
                    const userKey = keys.find(k => k.service === serviceId);
                    const hasPlatformKey = platformKeys[serviceId];

                    return (
                      <div
                        key={serviceId}
                        className={`dash-card p-4 flex items-center gap-4 transition-all ${
                          userKey || hasPlatformKey ? '' : 'opacity-60 hover:opacity-100'
                        }`}
                      >
                        {/* Service icon */}
                        <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 ${svc.color}`}>
                          <svc.icon size={18} />
                        </div>

                        {/* Info */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-medium text-sm">{svc.label}</span>
                            {svc.required && (
                              <span className="text-[10px] font-medium text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded-full">
                                Required
                              </span>
                            )}
                            {hasPlatformKey && !userKey && (
                              <span className="text-[10px] font-medium text-green-400 bg-green-500/10 px-1.5 py-0.5 rounded-full">
                                Platform default
                              </span>
                            )}
                            {hasPlatformKey && userKey && (
                              <span className="text-[10px] font-medium text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded-full">
                                Override
                              </span>
                            )}
                            {userKey?.label && (
                              <span className="text-xs text-[var(--text-muted)]">— {userKey.label}</span>
                            )}
                          </div>
                          {userKey ? (
                            <div className="flex items-center gap-2 mt-0.5">
                              <code className="text-xs text-[var(--text-muted)] font-mono">{userKey.masked_key}</code>
                              <span className="text-xs text-[var(--text-muted)]">• {timeAgo(userKey.updated_at)}</span>
                            </div>
                          ) : hasPlatformKey ? (
                            <p className="text-xs text-green-400/70 mt-0.5">
                              Configured via server .env — add your own to override
                              {serviceId === 'twilio' && twilioPhone && ` • ${twilioPhone}`}
                            </p>
                          ) : (
                            <p className="text-xs text-[var(--text-muted)] mt-0.5">{svc.description}</p>
                          )}
                        </div>

                        {/* Actions */}
                        <div className="flex items-center gap-1.5">
                          {userKey ? (
                            <>
                              {/* Active toggle */}
                              <button
                                onClick={() => toggleActive(userKey)}
                                className={`p-1.5 rounded-lg transition-colors ${
                                  userKey.is_active
                                    ? 'text-green-400 hover:bg-green-500/10'
                                    : 'text-[var(--text-muted)] hover:bg-[var(--bg-tertiary)]'
                                }`}
                                title={userKey.is_active ? 'Active — click to deactivate' : 'Inactive — click to activate'}
                              >
                                {userKey.is_active ? <ToggleRight size={20} /> : <ToggleLeft size={20} />}
                              </button>

                              {/* Edit */}
                              <button
                                onClick={() => openEditModal(userKey)}
                                className="p-1.5 text-[var(--text-muted)] hover:text-brand-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                                title="Update key"
                              >
                                <Edit3 size={15} />
                              </button>

                              {/* Delete */}
                              <button
                                onClick={() => deleteKey(userKey.id, svc.label)}
                                className="p-1.5 text-[var(--text-muted)] hover:text-red-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                                title="Delete key"
                              >
                                <Trash2 size={15} />
                              </button>
                            </>
                          ) : (
                            <button
                              onClick={() => openAddModal(serviceId)}
                              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-brand-400 bg-brand-500/10 hover:bg-brand-500/20 rounded-lg transition-colors"
                            >
                              <Plus size={14} />
                              Configure
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Add / Edit Modal */}
      {modal && (
        <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm animate-fade-in z-50 flex items-center justify-center">
          <div className="bg-[var(--bg-secondary)] rounded-2xl border border-[var(--glass-border)] w-full max-w-md mx-4 shadow-modal animate-scale-in">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--glass-border)]">
              <div className="flex items-center gap-3">
                {SERVICE_INFO[formService] && (
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${SERVICE_INFO[formService].color}`}>
                    {(() => { const Icon = SERVICE_INFO[formService].icon; return <Icon size={16} />; })()}
                  </div>
                )}
                <div>
                  <h2 className="text-lg font-semibold tracking-tight">
                    {modal === 'edit' ? 'Update' : 'Add'} {SERVICE_INFO[formService]?.label || 'API'} Key
                  </h2>
                  {SERVICE_INFO[formService] && (
                    <p className="text-xs text-[var(--text-muted)]">{SERVICE_INFO[formService].description}</p>
                  )}
                </div>
              </div>
              <button onClick={closeModal} className="btn-ghost p-1.5" aria-label="Close modal">
                <X size={20} />
              </button>
            </div>

            <div className="p-6 space-y-4">
              {error && (
                <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">{error}</div>
              )}

              {/* Service selector (add mode only, if not pre-selected) */}
              {modal === 'add' && (
                <div>
                  <label className="block text-[13px] font-medium text-[var(--text-secondary)] mb-1.5">Service</label>
                  <select
                    value={formService}
                    onChange={e => {
                      setFormService(e.target.value);
                      setFormSecret('');
                      setFormMetadata({});
                    }}
                    className="w-full input-base"
                  >
                    {Object.entries(SERVICE_INFO).map(([id, info]) => (
                      <option key={id} value={id}>
                        {info.label} ({info.category}){configuredServices.has(id) ? ' ✓' : ''}
                      </option>
                    ))}
                  </select>
                  {configuredServices.has(formService) && (
                    <p className="text-xs text-amber-400 mt-1">You already have a key for this service — it will be replaced.</p>
                  )}
                </div>
              )}

              {/* API Key */}
              <div>
                <label className="block text-[13px] font-medium text-[var(--text-secondary)] mb-1.5">
                  {formService === 'twilio' ? 'Account SID' : 'API Key'}
                </label>
                <input
                  type="password"
                  value={formKey}
                  onChange={e => setFormKey(e.target.value)}
                  placeholder={modal === 'edit'
                    ? 'Enter new key to replace current...'
                    : SERVICE_INFO[formService]?.placeholder || 'sk-...'
                  }
                  className="w-full input-base font-mono"
                />
              </div>

              {/* Secret (Twilio auth token) */}
              {(SERVICE_INFO[formService]?.needsSecret || formService === 'twilio') && (
                <div>
                  <label className="block text-[13px] font-medium text-[var(--text-secondary)] mb-1.5">
                    Auth Token
                  </label>
                  <input
                    type="password"
                    value={formSecret}
                    onChange={e => setFormSecret(e.target.value)}
                    placeholder={modal === 'edit' ? 'Enter new token to replace...' : 'Your Twilio auth token'}
                    className="w-full input-base font-mono"
                  />
                </div>
              )}

              {/* Metadata fields (e.g. Twilio phone number) */}
              {SERVICE_INFO[formService]?.needsMetadata?.map(field => (
                <div key={field}>
                  <label className="block text-[13px] font-medium text-[var(--text-secondary)] mb-1.5">
                    {field.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                    <span className="text-[var(--text-muted)] font-normal ml-1">(optional)</span>
                  </label>
                  <input
                    type="text"
                    value={formMetadata[field] || ''}
                    onChange={e => setFormMetadata(prev => ({ ...prev, [field]: e.target.value }))}
                    placeholder={field === 'phone_number' ? '+1234567890' : ''}
                    className="w-full input-base font-mono"
                  />
                </div>
              ))}

              {/* Label */}
              <div>
                <label className="block text-[13px] font-medium text-[var(--text-secondary)] mb-1.5">
                  Label <span className="text-[var(--text-muted)] font-normal">(optional)</span>
                </label>
                <input
                  type="text"
                  value={formLabel}
                  onChange={e => setFormLabel(e.target.value)}
                  placeholder="e.g. Production, Free Tier"
                  className="w-full input-base"
                />
              </div>

              {/* Docs link */}
              {SERVICE_INFO[formService]?.docsUrl && (
                <a
                  href={SERVICE_INFO[formService].docsUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 text-xs text-brand-400 hover:text-brand-300 transition-colors"
                >
                  <ExternalLink size={12} />
                  Get your {SERVICE_INFO[formService].label} API key
                </a>
              )}

              <button
                onClick={saveKey}
                disabled={saving}
                className="btn-primary w-full"
              >
                {saving ? 'Saving...' : modal === 'edit' ? 'Update Key' : 'Add Key'}
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete API Key"
        message={`Delete ${deleteTarget?.label} API key? This cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={confirmDeleteKey}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
    </GsapPageWrapper>
  );
}
