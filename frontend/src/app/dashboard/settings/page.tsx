'use client';

import { useEffect, useState } from 'react';
import Image from 'next/image';
import { useAuth } from '@/lib/auth-context';
import { useToast } from '@/components/ui/toast';
import { settings as settingsApi } from '@/lib/api';
import { usePageTitle } from '@/hooks/usePageTitle';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';
import { SkeletonCard } from '@/components/ui/skeleton';
import {
  Shield,
  LogOut,
  Loader2,
  Save,
  CheckCircle,
  AlertTriangle,
  Mic,
  Brain,
  Volume2,
  Phone,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import SettingsTabBar from './_components/SettingsTabBar';

interface PlatformSettings {
  platform_name: string;
  platform_greeting: string;
  default_llm_provider: string;
  default_llm_model: string;
  default_voice: string;
  max_call_duration: number;
  enable_recording: boolean;
  enable_transcription: boolean;
  [key: string]: string | number | boolean;
}

const DEFAULTS: PlatformSettings = {
  platform_name: 'VOIA',
  platform_greeting: 'Hello! How can I help you today?',
  default_llm_provider: 'openrouter',
  default_llm_model: 'deepseek/deepseek-v4-flash',
  default_voice: 'aura-asteria-en',
  max_call_duration: 600,
  enable_recording: true,
  enable_transcription: true,
};

export default function SettingsPage() {
  usePageTitle('Settings');
  const { user, logout } = useAuth();
  const [settings, setSettings] = useState<PlatformSettings>(DEFAULTS);
  const [original, setOriginal] = useState<PlatformSettings>(DEFAULTS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { success, apiError } = useToast();

  const isAdmin = user?.role === 'admin';
  const hasChanges = JSON.stringify(settings) !== JSON.stringify(original);

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const data = await settingsApi.get();
        const merged = { ...DEFAULTS, ...data.settings };
        setSettings(merged);
        setOriginal(merged);
      } catch (err) {
        apiError(err, 'Failed to load settings');
      } finally {
        setLoading(false);
      }
    };
    fetchSettings();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      const changed: Record<string, unknown> = {};
      for (const key of Object.keys(settings)) {
        if (settings[key] !== original[key]) {
          changed[key] = settings[key];
        }
      }
      await settingsApi.update(changed);
      setOriginal({ ...settings });
      success('Settings Saved', 'Your changes have been applied');
    } catch (err: unknown) {
      apiError(err, 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const update = (key: string, value: string | number | boolean) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  };

  if (loading) {
    return (
      <div className="space-y-6 max-w-3xl">
        <h1 className="page-title dash-title-gradient dash-title-glow">Settings</h1>
        <SkeletonCard className="h-96" />
      </div>
    );
  }

  return (
    <GsapPageWrapper>
    <div className="space-y-6 max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Settings</h1>
          <p className="page-subtitle">Account and platform configuration</p>
        </div>
        {isAdmin && hasChanges && (
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 btn-primary"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        )}
      </div>

      {/* Settings Tabs */}
      <SettingsTabBar />

      {/* Profile */}
      <div className="dash-card p-6">
        <h2 className="section-title mb-4">Profile</h2>
        <div className="flex items-center gap-4">
          {user?.picture_url ? (
            <Image src={user.picture_url} alt="" width={56} height={56} className="w-14 h-14 rounded-full" referrerPolicy="no-referrer" />
          ) : (
            <div className="w-14 h-14 rounded-full bg-brand-600 flex items-center justify-center text-xl font-medium text-[var(--text-inverse)]">
              {user?.name?.[0] || '?'}
            </div>
          )}
          <div>
            <p className="font-semibold text-lg">{user?.name}</p>
            <p className="text-sm text-[var(--text-secondary)]">{user?.email}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className={cn(
                'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
                user?.role === 'admin' ? 'bg-amber-500/20 text-amber-400' : 'bg-brand-500/20 text-brand-400'
              )}>
                <Shield size={10} />
                {user?.role}
              </span>
              <span className="text-xs text-[var(--text-muted)]">
                Joined {user?.created_at ? new Date(user.created_at).toLocaleDateString() : '—'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Platform Settings */}
      <div className="dash-card p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="section-title">Platform Settings</h2>
          {!isAdmin && (
            <span className="text-[10px] text-amber-400 bg-amber-400/10 px-2 py-0.5 rounded-full">Admin only</span>
          )}
        </div>
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-[var(--text-muted)] mb-1">Platform Name</label>
              <input
                type="text"
                value={settings.platform_name}
                onChange={e => update('platform_name', e.target.value)}
                disabled={!isAdmin}
                className="w-full input-base disabled:opacity-50"
              />
            </div>
            <div>
              <label className="block text-xs text-[var(--text-muted)] mb-1">Max Call Duration (seconds)</label>
              <input
                type="number"
                value={settings.max_call_duration}
                onChange={e => update('max_call_duration', parseInt(e.target.value) || 0)}
                disabled={!isAdmin}
                className="w-full input-base disabled:opacity-50"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-[var(--text-muted)] mb-1">Platform Greeting</label>
            <input
              type="text"
              value={settings.platform_greeting}
              onChange={e => update('platform_greeting', e.target.value)}
              disabled={!isAdmin}
              className="w-full input-base disabled:opacity-50"
            />
          </div>
          <div className="flex items-center gap-6">
            <label className="flex items-center gap-2 text-sm text-[var(--text-secondary)] cursor-pointer">
              <input
                type="checkbox"
                checked={settings.enable_recording}
                onChange={e => update('enable_recording', e.target.checked)}
                disabled={!isAdmin}
                className="rounded"
              />
              Enable recording
            </label>
            <label className="flex items-center gap-2 text-sm text-[var(--text-secondary)] cursor-pointer">
              <input
                type="checkbox"
                checked={settings.enable_transcription}
                onChange={e => update('enable_transcription', e.target.checked)}
                disabled={!isAdmin}
                className="rounded"
              />
              Enable transcription
            </label>
          </div>
        </div>
      </div>

      {/* Voice/LLM Defaults */}
      <div className="dash-card p-6">
        <h2 className="section-title mb-4">Default Providers</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] mb-1">
              <Brain size={12} /> LLM Provider
            </label>
            <select
              value={settings.default_llm_provider}
              onChange={e => update('default_llm_provider', e.target.value)}
              disabled={!isAdmin}
              className="w-full input-base disabled:opacity-50"
            >
              <option value="groq">Groq</option>
              <option value="openai">OpenAI</option>
              <option value="gemini">Google Gemini</option>
              <option value="anthropic">Anthropic</option>
              <option value="commandcode">CommandCode</option>
            </select>
          </div>
          <div>
            <label className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] mb-1">
              <Brain size={12} /> LLM Model
            </label>
            <select
              value={settings.default_llm_model}
              onChange={e => update('default_llm_model', e.target.value)}
              disabled={!isAdmin}
              className="w-full input-base disabled:opacity-50"
            >
              <option value="llama-3.3-70b-versatile">Llama 3.3 70B (Groq)</option>
              <option value="llama-3.1-8b-instant">Llama 3.1 8B (Groq)</option>
              <option value="gpt-4o-mini">GPT-4o Mini (OpenAI)</option>
              <option value="gpt-4o">GPT-4o (OpenAI)</option>
              <option value="deepseek/deepseek-v4-pro">DeepSeek V4 Pro (CommandCode)</option>
            </select>
          </div>
          <div>
            <label className="flex items-center gap-1.5 text-xs text-[var(--text-muted)] mb-1">
              <Volume2 size={12} /> Default Voice
            </label>
            <select
              value={settings.default_voice}
              onChange={e => update('default_voice', e.target.value)}
              disabled={!isAdmin}
              className="w-full input-base disabled:opacity-50"
            >
              <option value="aura-asteria-en">Asteria (Female)</option>
              <option value="aura-luna-en">Luna (Female)</option>
              <option value="aura-stella-en">Stella (Female)</option>
              <option value="aura-athena-en">Athena (Female)</option>
              <option value="aura-hera-en">Hera (Female)</option>
              <option value="aura-orion-en">Orion (Male)</option>
              <option value="aura-arcas-en">Arcas (Male)</option>
              <option value="aura-perseus-en">Perseus (Male)</option>
              <option value="aura-angus-en">Angus (Male)</option>
              <option value="aura-orpheus-en">Orpheus (Male)</option>
              <option value="aura-helios-en">Helios (Male)</option>
              <option value="aura-zeus-en">Zeus (Male)</option>
            </select>
          </div>
        </div>
      </div>

      {/* Tech Stack */}
      <div className="dash-card p-6">
        <h2 className="section-title mb-4">Tech Stack</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          <div className="bg-[var(--bg-primary)] rounded-xl p-3.5">
            <div className="flex items-center gap-1.5 text-[var(--text-muted)] text-xs mb-1">
              <Mic size={12} /> STT
            </div>
            <p className="font-medium">Deepgram Nova-3</p>
          </div>
          <div className="bg-[var(--bg-primary)] rounded-xl p-3.5">
            <div className="flex items-center gap-1.5 text-[var(--text-muted)] text-xs mb-1">
              <Brain size={12} /> LLM
            </div>
            <p className="font-medium">{settings.default_llm_provider === 'groq' ? 'Groq' : 'OpenAI'}</p>
            <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{settings.default_llm_model}</p>
          </div>
          <div className="bg-[var(--bg-primary)] rounded-xl p-3.5">
            <div className="flex items-center gap-1.5 text-[var(--text-muted)] text-xs mb-1">
              <Volume2 size={12} /> TTS
            </div>
            <p className="font-medium">Deepgram Aura</p>
            <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{settings.default_voice}</p>
          </div>
          <div className="bg-[var(--bg-primary)] rounded-xl p-3.5">
            <div className="flex items-center gap-1.5 text-[var(--text-muted)] text-xs mb-1">
              <Phone size={12} /> Telephony
            </div>
            <p className="font-medium">Twilio</p>
          </div>
        </div>
      </div>

      {/* System Info */}
      <div className="dash-card p-6">
        <h2 className="section-title mb-4">System Info</h2>
        <div className="space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-[var(--text-secondary)]">Version</span>
            <span className="font-medium">VOIA v1.0.0</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[var(--text-secondary)]">API Endpoint</span>
            <span className="font-mono text-xs text-[var(--text-muted)]">{process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3000'}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-[var(--text-secondary)]">Frontend</span>
            <span className="font-mono text-xs text-[var(--text-muted)]">Next.js 14 + React 18</span>
          </div>
        </div>
      </div>

      {/* Danger Zone */}
      <div className="bg-[var(--bg-card)] rounded-xl border border-red-500/20 p-6">
        <h2 className="text-sm font-medium text-red-400 uppercase tracking-wider mb-4">Account</h2>
        <button
          onClick={logout}
          className="flex items-center gap-2 px-4 py-2.5 bg-red-600/20 hover:bg-red-600/30 text-red-400 rounded-lg text-sm font-medium transition-colors"
        >
          <LogOut size={16} />
          Sign Out
        </button>
      </div>
    </div>
    </GsapPageWrapper>
  );
}
