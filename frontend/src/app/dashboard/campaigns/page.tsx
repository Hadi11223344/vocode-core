'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { campaigns, agents as agentsApi } from '@/lib/api';
import { usePageTitle } from '@/hooks/usePageTitle';
import { Campaign, CampaignContact, Agent } from '@/lib/types';
import { formatDuration, formatPhone, timeAgo } from '@/lib/utils';
import { useToast } from '@/components/ui/toast';
import { EmptyState } from '@/components/ui/empty-state';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';
import { SkeletonTable } from '@/components/ui/skeleton';
import {
  Megaphone,
  Plus,
  Play,
  Pause,
  RotateCcw,
  Loader2,
  Search,
  ChevronRight,
  ArrowLeft,
  Upload,
  Users,
  PhoneCall,
  CheckCircle,
  XCircle,
  Clock,
  Trash2,
  Bot,
  X,
  AlertCircle,
  TrendingUp,
} from 'lucide-react';

type View = 'list' | 'detail' | 'create';

export default function CampaignsPage() {
  usePageTitle('Campaigns');
  const { success, error } = useToast();
  const [view, setView] = useState<View>('list');
  const [loading, setLoading] = useState(true);
  const [campaignList, setCampaignList] = useState<Campaign[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);
  const [contacts, setContacts] = useState<CampaignContact[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [actionLoading, setActionLoading] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);

  // Create form
  const [form, setForm] = useState({
    name: '',
    description: '',
    agent_id: 0,
    from_phone: '',
    max_concurrent_calls: 1,
    call_interval_secs: 5,
    contacts_text: '', // phone per line
  });

  const loadCampaigns = useCallback(async () => {
    try {
      const data = await campaigns.list(statusFilter || undefined);
      setCampaignList(data.campaigns);
    } catch {
      error('Failed to load campaigns');
    } finally {
      setLoading(false);
    }
  }, [statusFilter, error]);

  const loadCampaignDetail = useCallback(async (id: number) => {
    try {
      const data = await campaigns.get(id);
      setSelectedCampaign(data.campaign);
      setContacts(data.contacts);
    } catch {
      error('Failed to load campaign');
    }
  }, [error]);

  useEffect(() => { loadCampaigns(); }, [loadCampaigns]);
  useEffect(() => {
    agentsApi.list().then(d => setAgents(d.agents)).catch(() => {});
  }, []);

  function openDetail(id: number) {
    setSelectedId(id);
    loadCampaignDetail(id);
    setView('detail');
  }

  async function handleCreate() {
    if (!form.name || !form.agent_id) {
      error('Name and agent are required');
      return;
    }
    setActionLoading(true);
    try {
      const contactsList = form.contacts_text
        .split('\n')
        .map(line => line.trim())
        .filter(Boolean)
        .map(phone => ({ phone_number: phone }));

      await campaigns.create({
        name: form.name,
        agent_id: form.agent_id,
        description: form.description || undefined,
        from_phone: form.from_phone || undefined,
        max_concurrent_calls: form.max_concurrent_calls,
        call_interval_secs: form.call_interval_secs,
        contacts: contactsList.length > 0 ? contactsList : undefined,
      });
      success('Campaign created!');
      setView('list');
      loadCampaigns();
      setForm({ name: '', description: '', agent_id: 0, from_phone: '', max_concurrent_calls: 1, call_interval_secs: 5, contacts_text: '' });
    } catch {
      error('Failed to create campaign');
    } finally {
      setActionLoading(false);
    }
  }

  async function handleStart(id: number) {
    setActionLoading(true);
    try {
      await campaigns.start(id);
      success('Campaign started!');
      loadCampaignDetail(id);
      loadCampaigns();
    } catch {
      error('Failed to start campaign');
    } finally {
      setActionLoading(false);
    }
  }

  async function handlePause(id: number) {
    setActionLoading(true);
    try {
      await campaigns.pause(id);
      success('Campaign paused');
      loadCampaignDetail(id);
      loadCampaigns();
    } catch {
      error('Failed to pause campaign');
    } finally {
      setActionLoading(false);
    }
  }

  async function handleResume(id: number) {
    setActionLoading(true);
    try {
      await campaigns.resume(id);
      success('Campaign resumed!');
      loadCampaignDetail(id);
      loadCampaigns();
    } catch {
      error('Failed to resume');
    } finally {
      setActionLoading(false);
    }
  }

  function handleDelete(id: number) {
    setDeleteTarget(id);
  }

  async function confirmDelete() {
    if (deleteTarget === null) return;
    const id = deleteTarget;
    setDeleteTarget(null);
    try {
      await campaigns.delete(id);
      success('Campaign deleted');
      setView('list');
      loadCampaigns();
    } catch {
      error('Failed to delete');
    }
  }

  const filtered = campaignList.filter(c =>
    c.name.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="page-title dash-title-gradient dash-title-glow">Campaigns</h1>
        </div>
        <SkeletonTable rows={5} cols={5} />
      </div>
    );
  }

  /* ─── Create View ─────────────────────────────────────── */
  if (view === 'create') {
    return (
      <div className="space-y-6 max-w-2xl">
        <button onClick={() => setView('list')} className="flex items-center gap-2 text-sm text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
          <ArrowLeft size={14} /> Back to Campaigns
        </button>

        <h1 className="page-title dash-title-gradient dash-title-glow">Create Campaign</h1>

        <div className="dash-card p-6 space-y-5">
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] mb-1.5 block">Campaign Name *</label>
            <input
              className="input-base w-full"
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="e.g. Q1 Outreach"
            />
          </div>

          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] mb-1.5 block">Description</label>
            <textarea
              className="input-base w-full"
              rows={2}
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              placeholder="Campaign description..."
            />
          </div>

          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] mb-1.5 block">Agent *</label>
            <select
              className="input-base w-full"
              value={form.agent_id}
              onChange={e => setForm(f => ({ ...f, agent_id: Number(e.target.value) }))}
            >
              <option value={0}>Select an agent...</option>
              {agents.map(a => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] mb-1.5 block">From Phone Number</label>
            <input
              className="input-base w-full"
              value={form.from_phone}
              onChange={e => setForm(f => ({ ...f, from_phone: e.target.value }))}
              placeholder="+1234567890"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-[var(--text-muted)] mb-1.5 block">Max Concurrent Calls</label>
              <input
                type="number"
                className="input-base w-full"
                min={1}
                max={10}
                value={form.max_concurrent_calls}
                onChange={e => setForm(f => ({ ...f, max_concurrent_calls: Number(e.target.value) }))}
              />
            </div>
            <div>
              <label className="text-xs font-medium text-[var(--text-muted)] mb-1.5 block">Interval (secs)</label>
              <input
                type="number"
                className="input-base w-full"
                min={1}
                value={form.call_interval_secs}
                onChange={e => setForm(f => ({ ...f, call_interval_secs: Number(e.target.value) }))}
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] mb-1.5 block">
              Contacts (one phone number per line)
            </label>
            <textarea
              className="input-base w-full font-mono text-sm"
              rows={6}
              value={form.contacts_text}
              onChange={e => setForm(f => ({ ...f, contacts_text: e.target.value }))}
              placeholder={"+12125551234\n+13105554321\n+14155552222"}
            />
            <p className="text-[10px] text-[var(--text-muted)] mt-1">
              {form.contacts_text.split('\n').filter(l => l.trim()).length} contacts
            </p>
          </div>

          <div className="flex gap-3 pt-2">
            <button onClick={() => setView('list')} className="btn-secondary flex-1">Cancel</button>
            <button onClick={handleCreate} disabled={actionLoading} className="btn-primary flex-1 flex items-center justify-center gap-2">
              {actionLoading ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
              Create Campaign
            </button>
          </div>
        </div>
      </div>
    );
  }

  /* ─── Detail View ─────────────────────────────────────── */
  if (view === 'detail' && selectedCampaign) {
    const c = selectedCampaign;
    const progressPct = c.total_contacts > 0
      ? Math.round(((c.completed_contacts + c.failed_contacts) / c.total_contacts) * 100)
      : 0;

    return (
      <div className="space-y-6">
        <button onClick={() => setView('list')} className="flex items-center gap-2 text-sm text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
          <ArrowLeft size={14} /> Back to Campaigns
        </button>

        <div className="flex items-start justify-between">
          <div>
            <h1 className="page-title dash-title-gradient dash-title-glow flex items-center gap-3">
              {c.name}
              <CampaignStatusBadge status={c.status} />
            </h1>
            {c.description && <p className="page-subtitle">{c.description}</p>}
          </div>
          <div className="flex items-center gap-2">
            {c.status === 'draft' && (
              <button onClick={() => handleStart(c.id)} disabled={actionLoading} className="btn-primary text-sm">
                {actionLoading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />} Start
              </button>
            )}
            {c.status === 'running' && (
              <button onClick={() => handlePause(c.id)} disabled={actionLoading} className="btn-secondary text-sm">
                {actionLoading ? <Loader2 size={14} className="animate-spin" /> : <Pause size={14} />} Pause
              </button>
            )}
            {c.status === 'paused' && (
              <button onClick={() => handleResume(c.id)} disabled={actionLoading} className="btn-primary text-sm">
                {actionLoading ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />} Resume
              </button>
            )}
            <button onClick={() => handleDelete(c.id)} className="p-2 rounded-lg text-red-400 hover:bg-red-500/10 transition-colors">
              <Trash2 size={16} />
            </button>
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-stagger">
          <MiniStat label="Total Contacts" value={c.total_contacts} icon={Users} />
          <MiniStat label="Completed" value={c.completed_contacts} icon={CheckCircle} color="text-green-400" />
          <MiniStat label="Failed" value={c.failed_contacts} icon={XCircle} color="text-red-400" />
          <MiniStat label="Progress" value={`${progressPct}%`} icon={TrendingUp} />
        </div>

        {/* Progress Bar */}
        <div className="dash-card p-4">
          <div className="flex items-center justify-between text-xs mb-2">
            <span className="text-[var(--text-muted)]">Campaign Progress</span>
            <span className="font-medium">{progressPct}%</span>
          </div>
          <div className="h-3 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
            <div className="h-full rounded-full bg-gradient-to-r from-[var(--accent)] to-[var(--accent-hover)] transition-all duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <div className="flex justify-between text-[10px] text-[var(--text-muted)] mt-1.5">
            <span>{c.completed_contacts + c.failed_contacts} / {c.total_contacts} processed</span>
            {c.started_at && <span>Started {timeAgo(c.started_at)}</span>}
          </div>
        </div>

        {/* Contacts Table */}
        <div className="dash-table overflow-hidden">
          <div className="p-4 border-b border-[var(--glass-border)]">
            <h3 className="text-sm font-semibold">Contacts ({contacts.length})</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--glass-border)]">
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] py-3 px-4">Phone</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] py-3 px-4">Name</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] py-3 px-4">Status</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] py-3 px-4">Outcome</th>
                  <th className="text-right text-xs font-medium text-[var(--text-muted)] py-3 px-4">Duration</th>
                </tr>
              </thead>
              <tbody>
                {contacts.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-sm text-[var(--text-muted)]">
                      No contacts added yet
                    </td>
                  </tr>
                ) : (
                  contacts.map(contact => (
                    <tr key={contact.id} className="border-b border-[var(--glass-border)] last:border-0 hover:bg-[var(--bg-secondary)] transition-colors">
                      <td className="py-3 px-4 text-sm font-mono">{formatPhone(contact.phone_number)}</td>
                      <td className="py-3 px-4 text-sm">{contact.name || '—'}</td>
                      <td className="py-3 px-4"><ContactStatusBadge status={contact.status} /></td>
                      <td className="py-3 px-4 text-sm text-[var(--text-muted)]">{contact.call_outcome || '—'}</td>
                      <td className="py-3 px-4 text-sm text-right text-[var(--text-muted)]">
                        {contact.call_duration_secs ? formatDuration(contact.call_duration_secs) : '—'}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    );
  }

  /* ─── List View ───────────────────────────────────────── */
  return (
    <GsapPageWrapper>
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Campaigns</h1>
          <p className="page-subtitle">Manage batch outbound calling campaigns</p>
        </div>
        <button onClick={() => setView('create')} className="btn-primary text-sm">
          <Plus size={14} /> New Campaign
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 items-center">
        <div className="relative flex-1 max-w-sm">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            className="input-base pl-9 w-full"
            placeholder="Search campaigns..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <select
          className="input-base text-sm py-2 px-3 rounded-lg"
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
        >
          <option value="">All Statuses</option>
          <option value="draft">Draft</option>
          <option value="running">Running</option>
          <option value="paused">Paused</option>
          <option value="completed">Completed</option>
        </select>
      </div>

      {/* Campaign List */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={Megaphone}
          title="No campaigns yet"
          description="Create your first campaign to start batch calling. Upload contacts and let your agent reach out at scale."
        />
      ) : (
        <div className="grid gap-3">
          {filtered.map(campaign => {
            const pct = campaign.total_contacts > 0
              ? Math.round(((campaign.completed_contacts + campaign.failed_contacts) / campaign.total_contacts) * 100)
              : 0;

            return (
              <button
                key={campaign.id}
                onClick={() => openDetail(campaign.id)}
                className="dash-stat-card text-left group"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-[var(--accent)]/20">
                      <Megaphone size={16} className="text-[var(--accent)]" />
                    </div>
                    <div>
                      <h3 className="text-sm font-medium group-hover:text-[var(--accent)] transition-colors">
                        {campaign.name}
                      </h3>
                      <p className="text-xs text-[var(--text-muted)]">
                        {campaign.agent_name || 'No agent'} &middot; Created {timeAgo(campaign.created_at)}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <CampaignStatusBadge status={campaign.status} />
                    <ChevronRight size={14} className="text-[var(--text-muted)] group-hover:translate-x-0.5 transition-transform" />
                  </div>
                </div>

                {/* Progress */}
                <div className="flex items-center gap-4">
                  <div className="flex-1">
                    <div className="h-1.5 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
                      <div className="h-full rounded-full bg-[var(--accent)] transition-all" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-[var(--text-muted)]">
                    <span className="flex items-center gap-1"><Users size={10} /> {campaign.total_contacts}</span>
                    <span className="flex items-center gap-1 text-green-400"><CheckCircle size={10} /> {campaign.completed_contacts}</span>
                    {campaign.failed_contacts > 0 && (
                      <span className="flex items-center gap-1 text-red-400"><XCircle size={10} /> {campaign.failed_contacts}</span>
                    )}
                    <span className="font-medium">{pct}%</span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete Campaign"
        message="Are you sure you want to delete this campaign? This cannot be undone."
        confirmLabel="Delete"
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
    </GsapPageWrapper>
  );
}

/* ─── Helpers ───────────────────────────────────────────── */
function CampaignStatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    draft: 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]',
    running: 'bg-green-500/20 text-green-400',
    paused: 'bg-amber-500/20 text-amber-400',
    completed: 'bg-brand-500/15 text-brand-400',
    failed: 'bg-red-500/20 text-red-400',
  };
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] || 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'}`}>
      {status === 'running' && <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse flex-shrink-0" />}
      {status}
    </span>
  );
}

function ContactStatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]',
    calling: 'bg-amber-500/20 text-amber-400',
    completed: 'bg-green-500/20 text-green-400',
    failed: 'bg-red-500/20 text-red-400',
    skipped: 'bg-brand-500/15 text-brand-400',
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${colors[status] || 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'}`}>
      {status}
    </span>
  );
}

function MiniStat({ label, value, icon: Icon, color }: { label: string; value: string | number; icon: React.ElementType; color?: string }) {
  return (
    <div className="dash-card p-4">
      <div className="flex items-center gap-2 text-xs text-[var(--text-muted)] mb-1">
        <Icon size={12} className={color} /> {label}
      </div>
      <p className="text-xl font-semibold">{value}</p>
    </div>
  );
}
