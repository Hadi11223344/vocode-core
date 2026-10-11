'use client';

import { useState, useEffect, useCallback } from 'react';
import { SkeletonTable } from '@/components/ui/skeleton';
import {
  Calendar,
  Plus,
  Clock,
  Phone,
  Trash2,
  X,
  Loader2,
  CheckCircle,
  AlertCircle,
  PhoneOff,
  Repeat,
} from 'lucide-react';
import { scheduledCalls, agents as agentsApi } from '@/lib/api';
import { useToast } from '@/components/ui/toast';
import { EmptyState } from '@/components/ui/empty-state';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { useModalFocusTrap } from '@/hooks/use-modal-focus-trap';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';

interface ScheduledCall {
  id: number;
  agent_id: number;
  agent_name: string | null;
  contact_name: string | null;
  phone_number: string;
  scheduled_at: string;
  timezone: string;
  recurrence: string;
  from_phone: string | null;
  status: string;
  call_log_id: number | null;
  retry_count: number;
  created_at: string;
}

export default function SchedulePage() {
  const { success, error } = useToast();
  const [calls, setCalls] = useState<ScheduledCall[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [agents, setAgents] = useState<Array<{ id: number; name: string }>>([]);
  const [filter, setFilter] = useState('all');

  // Form state
  const [agentId, setAgentId] = useState('');
  const [contactName, setContactName] = useState('');
  const [phone, setPhone] = useState('');
  const [date, setDate] = useState('');
  const [time, setTime] = useState('');
  const [timezone, setTimezone] = useState('UTC');
  const [recurrence, setRecurrence] = useState('none');
  const [saving, setSaving] = useState(false);
  const [cancelTarget, setCancelTarget] = useState<ScheduledCall | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ScheduledCall | null>(null);
  const createModalRef = useModalFocusTrap(showCreate, () => setShowCreate(false));

  useEffect(() => {
    loadCalls();
    agentsApi.list().then((data) => {
      setAgents(data.agents.map((a) => ({ id: a.id, name: a.name })));
    });
  }, []);

  const loadCalls = useCallback(async () => {
    try {
      const status = filter === 'all' ? undefined : filter;
      const data = await scheduledCalls.list(status);
      setCalls(data.scheduled_calls);
    } catch {
      error('Failed to load scheduled calls');
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    loadCalls();
  }, [filter]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!agentId || !phone.trim() || !date || !time) return;

    const scheduledAt = new Date(`${date}T${time}`).toISOString();
    setSaving(true);
    try {
      await scheduledCalls.create({
        agent_id: Number(agentId),
        contact_name: contactName.trim() || undefined,
        phone_number: phone.trim(),
        scheduled_at: scheduledAt,
        timezone,
        recurrence,
      });
      success('Scheduled', 'Call scheduled successfully');
      setShowCreate(false);
      resetForm();
      loadCalls();
    } catch {
      error('Failed to schedule call');
    } finally {
      setSaving(false);
    }
  }

  function resetForm() {
    setAgentId('');
    setContactName('');
    setPhone('');
    setDate('');
    setTime('');
    setTimezone('UTC');
    setRecurrence('none');
  }

  const handleCancel = (c: ScheduledCall) => {
    setCancelTarget(c);
  };

  const confirmCancel = async () => {
    if (!cancelTarget) return;
    const c = cancelTarget;
    setCancelTarget(null);
    try {
      await scheduledCalls.update(c.id, { status: 'cancelled' });
      success('Cancelled', 'Scheduled call cancelled');
      loadCalls();
    } catch {
      error('Failed to cancel');
    }
  };

  const handleDelete = (c: ScheduledCall) => {
    setDeleteTarget(c);
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    const c = deleteTarget;
    setDeleteTarget(null);
    try {
      await scheduledCalls.delete(c.id);
      success('Deleted', 'Scheduled call removed');
      loadCalls();
    } catch {
      error('Failed to delete');
    }
  };

  const statusBadge: Record<string, { color: string; icon: React.ReactNode }> = {
    pending: { color: 'bg-blue-500/10 text-blue-400', icon: <Clock size={12} /> },
    executing: { color: 'bg-amber-500/10 text-amber-400', icon: <Loader2 size={12} className="animate-spin" /> },
    completed: { color: 'bg-green-500/10 text-green-400', icon: <CheckCircle size={12} /> },
    failed: { color: 'bg-red-500/10 text-red-400', icon: <AlertCircle size={12} /> },
    cancelled: { color: 'bg-gray-500/10 text-gray-400', icon: <PhoneOff size={12} /> },
  };

  const filters = ['all', 'pending', 'completed', 'failed', 'cancelled'];

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="page-title dash-title-gradient dash-title-glow">Scheduled Calls</h1>
        <SkeletonTable rows={5} cols={6} />
      </div>
    );
  }

  return (
    <GsapPageWrapper>
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Call Schedule</h1>
          <p className="page-subtitle">
            Schedule individual outbound calls at specific times
          </p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary">
          <Plus size={16} /> Schedule Call
        </button>
      </div>

      {/* Create dialog */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--bg-primary)]/80 backdrop-blur-sm" onClick={() => setShowCreate(false)}>
          <div
            ref={createModalRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="schedule-modal-title"
            tabIndex={-1}
            className="bg-[var(--bg-secondary)] rounded-xl p-6 w-full max-w-md shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 id="schedule-modal-title" className="font-semibold">Schedule a Call</h3>
              <button onClick={() => setShowCreate(false)} className="btn-ghost p-1">
                <X size={16} />
              </button>
            </div>
            <form onSubmit={handleCreate} className="space-y-3">
              <div>
                <label className="text-sm font-medium">Agent</label>
                <select
                  value={agentId}
                  onChange={(e) => setAgentId(e.target.value)}
                  className="input-base w-full mt-1"
                  required
                >
                  <option value="">Select an agent...</option>
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-sm font-medium">Contact Name</label>
                <input
                  value={contactName}
                  onChange={(e) => setContactName(e.target.value)}
                  placeholder="e.g., John Doe"
                  className="input-base w-full mt-1"
                />
              </div>
              <div>
                <label className="text-sm font-medium">Phone Number</label>
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="+1234567890"
                  className="input-base w-full mt-1"
                  required
                />
                <p className="text-[11px] text-[var(--text-muted)] mt-1">E.164 format (e.g., +14155551234)</p>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-sm font-medium">Date</label>
                  <input
                    type="date"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                    className="input-base w-full mt-1"
                    required
                  />
                </div>
                <div>
                  <label className="text-sm font-medium">Time</label>
                  <input
                    type="time"
                    value={time}
                    onChange={(e) => setTime(e.target.value)}
                    className="input-base w-full mt-1"
                    required
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-sm font-medium">Timezone</label>
                  <select
                    value={timezone}
                    onChange={(e) => setTimezone(e.target.value)}
                    className="input-base w-full mt-1"
                  >
                    <option value="UTC">UTC</option>
                    <option value="America/New_York">Eastern (ET)</option>
                    <option value="America/Chicago">Central (CT)</option>
                    <option value="America/Denver">Mountain (MT)</option>
                    <option value="America/Los_Angeles">Pacific (PT)</option>
                    <option value="Europe/London">London</option>
                    <option value="Europe/Paris">Paris</option>
                    <option value="Asia/Dubai">Dubai</option>
                    <option value="Asia/Karachi">Karachi</option>
                    <option value="Asia/Kolkata">Mumbai</option>
                    <option value="Asia/Tokyo">Tokyo</option>
                  </select>
                </div>
                <div>
                  <label className="text-sm font-medium">Recurrence</label>
                  <select
                    value={recurrence}
                    onChange={(e) => setRecurrence(e.target.value)}
                    className="input-base w-full mt-1"
                  >
                    <option value="none">One-time</option>
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                    <option value="monthly">Monthly</option>
                  </select>
                </div>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowCreate(false)} className="btn-ghost flex-1">
                  Cancel
                </button>
                <button type="submit" disabled={saving} className="btn-primary flex-1 disabled:opacity-40">
                  {saving ? <Loader2 size={14} className="animate-spin" /> : 'Schedule'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-2 mt-6 overflow-x-auto pb-1">
        {filters.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
              filter === f
                ? 'bg-[var(--accent)] text-white'
                : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)] hover:bg-[var(--border-hover)]'
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {calls.length === 0 ? (
        <EmptyState
          icon={Calendar}
          title="No scheduled calls"
          description="Schedule individual outbound calls to specific contacts at specific times."
          action={
            <button onClick={() => setShowCreate(true)} className="btn-primary">
              <Plus size={16} /> Schedule Your First Call
            </button>
          }
        />
      ) : (
        <div className="grid gap-3 mt-4">
          {calls.map((c) => {
            const badge = statusBadge[c.status] || statusBadge.pending;
            const scheduled = new Date(c.scheduled_at);
            return (
              <div key={c.id} className="dash-card overflow-hidden">
                <div className="flex items-center gap-4 p-4">
                  <div className="p-2.5 rounded-lg bg-[var(--bg-tertiary)]">
                    <Phone size={18} className="text-[var(--accent)]" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-medium truncate">
                        {c.contact_name || 'Unnamed Contact'}
                      </h3>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium flex items-center gap-1 ${badge.color}`}>
                        {badge.icon}
                        {c.status}
                      </span>
                      {c.recurrence !== 'none' && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400 flex items-center gap-1">
                          <Repeat size={10} />
                          {c.recurrence}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-[var(--text-muted)]">
                      {c.phone_number} · {c.agent_name || 'Agent #' + c.agent_id}
                    </p>
                    <p className="text-xs text-[var(--text-muted)] mt-0.5">
                      <Clock size={10} className="inline mr-1" />
                      {scheduled.toLocaleString(undefined, {
                        dateStyle: 'medium',
                        timeStyle: 'short',
                      })}{' '}
                      ({c.timezone})
                    </p>
                  </div>
                  <div className="flex items-center gap-1">
                    {c.status === 'pending' && (
                      <button
                        onClick={() => handleCancel(c)}
                        className="p-2 text-[var(--text-muted)] hover:text-amber-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                        title="Cancel"
                      >
                        <PhoneOff size={16} />
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(c)}
                      className="p-2 text-[var(--text-muted)] hover:text-red-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                      title="Delete"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <ConfirmDialog
        open={cancelTarget !== null}
        title="Cancel Scheduled Call"
        message={`Cancel scheduled call to ${cancelTarget?.phone_number}?`}
        confirmLabel="Cancel Call"
        variant="warning"
        onConfirm={confirmCancel}
        onCancel={() => setCancelTarget(null)}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete Scheduled Call"
        message={`Delete scheduled call to ${deleteTarget?.phone_number}? This cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
    </GsapPageWrapper>
  );
}
