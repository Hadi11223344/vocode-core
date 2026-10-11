'use client';

import { useState, useEffect, useCallback } from 'react';
import { SkeletonTable } from '@/components/ui/skeleton';
import {
  Bell,
  Plus,
  Trash2,
  Loader2,
  RefreshCw,
  Play,
  ChevronDown,
  ChevronUp,
  Mail,
  Slack,
  Globe,
  Clock,
  AlertTriangle,
  X,
} from 'lucide-react';
import { EmptyState } from '@/components/ui/empty-state';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { alerts as alertsApi, agents as agentsApi } from '@/lib/api';
import { AlertRule, AlertHistoryEntry, Agent } from '@/lib/types';
import { cn } from '@/lib/utils';
import { useToast } from '@/components/ui/toast';
import { useModalFocusTrap } from '@/hooks/use-modal-focus-trap';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';

const CONDITION_LABELS: Record<string, string> = {
  call_failed_count: 'Failed Calls',
  avg_latency_spike: 'Latency Spike',
  call_duration_short: 'Short Calls',
  quality_score_drop: 'Quality Drop',
  no_calls: 'No Calls',
};

const CHANNEL_ICONS: Record<string, React.ElementType> = {
  email: Mail,
  slack: Slack,
  webhook: Globe,
  in_app: Bell,
};

export default function AlertsPage() {
  const { success, apiError } = useToast();
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [history, setHistory] = useState<AlertHistoryEntry[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [expandedHistory, setExpandedHistory] = useState(true);
  const [evaluating, setEvaluating] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null);
  const createModalRef = useModalFocusTrap(showCreate, () => setShowCreate(false));

  const [form, setForm] = useState({
    name: '',
    condition_type: 'call_failed_count',
    threshold: 3,
    window_minutes: 10,
    agent_id: '',
    channels: ['in_app'] as string[],
    cooldown_minutes: 15,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, h, a] = await Promise.all([
        alertsApi.listRules(),
        alertsApi.history(30),
        agentsApi.list().catch(() => ({ agents: [] })),
      ]);
      setRules(r.rules);
      setHistory(h.history);
      setAgents(a.agents);
    } catch (err) {
      apiError(err, 'Failed to load alerts');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const createRule = async () => {
    if (!form.name) return;
    try {
      await alertsApi.createRule({
        name: form.name,
        condition_type: form.condition_type,
        threshold: form.threshold,
        window_minutes: form.window_minutes,
        agent_id: form.agent_id ? parseInt(form.agent_id) : null,
        channels: form.channels,
        cooldown_minutes: form.cooldown_minutes,
      });
      success('Created', 'Alert rule created');
      setShowCreate(false);
      resetForm();
      await load();
    } catch (err) {
      apiError(err, 'Failed to create rule');
    }
  };

  const updateRule = async (id: number, patch: Partial<AlertRule>) => {
    try {
      await alertsApi.updateRule(id, patch);
      success('Updated', 'Rule updated');
      await load();
    } catch (err) {
      apiError(err, 'Failed to update rule');
    }
  };

  const deleteRule = async (id: number) => {
    setDeleteConfirmId(id);
  };

  const confirmDeleteRule = async () => {
    if (deleteConfirmId === null) return;
    const id = deleteConfirmId;
    setDeleteConfirmId(null);
    try {
      await alertsApi.deleteRule(id);
      success('Deleted', 'Rule removed');
      await load();
    } catch (err) {
      apiError(err, 'Failed to delete rule');
    }
  };

  const runEvaluate = async () => {
    setEvaluating(true);
    try {
      const data = await alertsApi.evaluate();
      success('Evaluated', `${data.triggered.length} of ${data.evaluated} rules triggered`);
      await load();
    } catch (err) {
      apiError(err, 'Evaluation failed');
    } finally {
      setEvaluating(false);
    }
  };

  const resetForm = () => {
    setForm({
      name: '',
      condition_type: 'call_failed_count',
      threshold: 3,
      window_minutes: 10,
      agent_id: '',
      channels: ['in_app'],
      cooldown_minutes: 15,
    });
  };

  const toggleChannel = (ch: string) => {
    setForm(prev => ({
      ...prev,
      channels: prev.channels.includes(ch)
        ? prev.channels.filter(c => c !== ch)
        : [...prev.channels, ch],
    }));
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="page-title dash-title-gradient dash-title-glow">Alerting</h1>
        <SkeletonTable rows={4} cols={4} />
      </div>
    );
  }

  return (
    <GsapPageWrapper>
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow flex items-center gap-2">
            <Bell size={22} className="text-brand-400" />
            Alerting
          </h1>
          <p className="page-subtitle">Get notified when things need attention</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={runEvaluate}
            disabled={evaluating}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-[var(--bg-card)] border border-[var(--glass-border)] rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors disabled:opacity-50"
          >
            {evaluating ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            Evaluate Now
          </button>
          <button
            onClick={load}
            className="p-2 text-[var(--text-secondary)] hover:text-white bg-[var(--bg-card)] border border-[var(--glass-border)] rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw size={16} />
          </button>
          <button
            onClick={() => { resetForm(); setShowCreate(true); }}
            className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg text-sm font-medium transition-colors"
          >
            <Plus size={16} />
            New Rule
          </button>
        </div>
      </div>

      {/* Rules List */}
      <div className="space-y-3">
        {rules.length === 0 ? (
          <EmptyState
            icon={Bell}
            title="No Alert Rules"
            description="Create alert rules to get notified when calls fail, latency spikes, or quality drops."
            action={
              <button
                onClick={() => { resetForm(); setShowCreate(true); }}
                className="inline-flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg text-sm font-medium transition-colors"
              >
                <Plus size={16} />
                Create First Rule
              </button>
            }
          />
        ) : (
          rules.map(rule => (
            <div
              key={rule.id}
              className={cn(
                'dash-card p-4 flex items-center gap-4 transition-opacity',
                !rule.is_active && 'opacity-60'
              )}
            >
              <div className={cn(
                'w-2 h-2 rounded-full shrink-0',
                rule.is_active ? 'bg-green-400' : 'bg-gray-500'
              )} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{rule.name}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
                    {CONDITION_LABELS[rule.condition_type] || rule.condition_type}
                  </span>
                </div>
                <div className="flex items-center gap-3 mt-1 text-[11px] text-[var(--text-muted)]">
                  <span className="flex items-center gap-1">
                    <Clock size={10} />
                    Window: {rule.window_minutes}m
                  </span>
                  {rule.threshold !== null && (
                    <span>Threshold: {rule.threshold}</span>
                  )}
                  <span>Cooldown: {rule.cooldown_minutes}m</span>
                  {rule.last_fired_at && (
                    <span className="text-amber-400">Last fired: {new Date(rule.last_fired_at).toLocaleString()}</span>
                  )}
                </div>
                <div className="flex items-center gap-1.5 mt-1.5">
                  {rule.channels.map(ch => {
                    const Icon = CHANNEL_ICONS[ch] || Bell;
                    return <Icon key={ch} size={12} className="text-[var(--text-muted)]" />;
                  })}
                </div>
              </div>
              <label className="relative inline-flex items-center cursor-pointer shrink-0">
                <input
                  type="checkbox"
                  checked={rule.is_active}
                  onChange={e => updateRule(rule.id, { is_active: e.target.checked })}
                  className="sr-only peer"
                />
                <div className="w-9 h-5 bg-[var(--bg-tertiary)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-[var(--text-inverse)] after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-[var(--text-primary)] after:border-[var(--border-color)] after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-brand-600" />
              </label>
              <button
                onClick={() => deleteRule(rule.id)}
                className="p-1.5 text-red-400 hover:bg-red-500/20 rounded-lg transition-colors"
                title="Delete rule"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))
        )}
      </div>

      {/* Alert History */}
      {history.length > 0 && (
        <div className="dash-card overflow-hidden">
          <button
            onClick={() => setExpandedHistory(!expandedHistory)}
            className="w-full flex items-center justify-between p-5 pb-0"
          >
            <h3 className="font-semibold flex items-center gap-2">
              <AlertTriangle size={16} className="text-amber-400" />
              Alert History
            </h3>
            {expandedHistory ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          {expandedHistory && (
            <div className="overflow-x-auto">
            <table className="w-full mt-3">
              <thead>
                <tr className="border-b border-[var(--glass-border)]">
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Rule</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Message</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Channels</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-color)]">
                {history.map(entry => (
                  <tr key={entry.id} className="hover:bg-[var(--bg-tertiary)]">
                    <td className="px-5 py-2.5 text-sm font-medium">{entry.rule_name}</td>
                    <td className="px-5 py-2.5 text-xs text-[var(--text-secondary)]">{entry.message}</td>
                    <td className="px-5 py-2.5">
                      <span className="text-[10px] text-[var(--text-muted)]">{entry.channels}</span>
                    </td>
                    <td className="px-5 py-2.5 text-xs text-[var(--text-muted)]">
                      {entry.sent_at ? new Date(entry.sent_at).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          )}
        </div>
      )}

      {/* Create/Edit Modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm z-50 flex items-center justify-center animate-fade-in" onClick={() => setShowCreate(false)}>
          <div
            ref={createModalRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="alert-rule-modal-title"
            tabIndex={-1}
            className="bg-[var(--bg-secondary)] rounded-2xl border border-[var(--glass-border)] w-full max-w-lg mx-4 shadow-modal animate-scale-in"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--glass-border)]">
              <h2 id="alert-rule-modal-title" className="text-lg font-semibold tracking-tight">New Alert Rule</h2>
              <button onClick={() => setShowCreate(false)} className="btn-ghost p-1.5">
                <X size={18} />
              </button>
            </div>
            <div className="px-6 py-5 space-y-4">
              <div>
                <label className="label-base">Rule Name</label>
                <input
                  value={form.name}
                  onChange={e => setForm({ ...form, name: e.target.value })}
                  placeholder="e.g. Too many failed calls"
                  className="input-base w-full"
                />
              </div>

              <div>
                <label className="label-base">Condition</label>
                <select
                  value={form.condition_type}
                  onChange={e => setForm({ ...form, condition_type: e.target.value })}
                  className="input-base w-full"
                >
                  <option value="call_failed_count">Failed Calls (count)</option>
                  <option value="avg_latency_spike">Latency Spike (ms)</option>
                  <option value="call_duration_short">Short Calls (secs)</option>
                  <option value="quality_score_drop">Quality Drop (score)</option>
                  <option value="no_calls">No Calls</option>
                </select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                {form.condition_type !== 'no_calls' && (
                  <div>
                    <label className="label-base">Threshold</label>
                    <input
                      type="number"
                      value={form.threshold}
                      onChange={e => setForm({ ...form, threshold: parseFloat(e.target.value) })}
                      className="input-base w-full"
                    />
                  </div>
                )}
                <div>
                  <label className="label-base">Window (minutes)</label>
                  <input
                    type="number"
                    value={form.window_minutes}
                    onChange={e => setForm({ ...form, window_minutes: parseInt(e.target.value) })}
                    className="input-base w-full"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label-base">Agent (optional)</label>
                  <select
                    value={form.agent_id}
                    onChange={e => setForm({ ...form, agent_id: e.target.value })}
                    className="input-base w-full"
                  >
                    <option value="">All agents</option>
                    {agents.map(a => (
                      <option key={a.id} value={a.id}>{a.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label-base">Cooldown (minutes)</label>
                  <input
                    type="number"
                    value={form.cooldown_minutes}
                    onChange={e => setForm({ ...form, cooldown_minutes: parseInt(e.target.value) })}
                    className="input-base w-full"
                  />
                </div>
              </div>

              <div>
                <label className="label-base">Channels</label>
                <div className="flex flex-wrap gap-2 mt-1">
                  {(['in_app', 'email', 'slack', 'webhook'] as const).map(ch => (
                    <button
                      key={ch}
                      onClick={() => toggleChannel(ch)}
                      className={cn(
                        'text-[10px] px-2.5 py-1 rounded-full border transition-colors capitalize',
                        form.channels.includes(ch)
                          ? 'bg-brand-500/10 text-brand-400 border-brand-500/30'
                          : 'bg-[var(--bg-card)] text-[var(--text-muted)] border-[var(--glass-border)]'
                      )}
                    >
                      {ch}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-[var(--glass-border)]">
              <button onClick={() => setShowCreate(false)} className="btn-ghost px-4 py-2 text-sm">Cancel</button>
              <button
                onClick={createRule}
                disabled={!form.name}
                className="btn-primary px-4 py-2 text-sm disabled:opacity-50"
              >
                Create Rule
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={deleteConfirmId !== null}
        title="Delete Alert Rule"
        message="Are you sure you want to delete this alert rule? This cannot be undone."
        confirmLabel="Delete"
        variant="danger"
        onConfirm={confirmDeleteRule}
        onCancel={() => setDeleteConfirmId(null)}
      />
    </div>
    </GsapPageWrapper>
  );
}
