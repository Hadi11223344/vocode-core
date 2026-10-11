'use client';

import { useState, useEffect, useCallback } from 'react';
import { SkeletonStats, SkeletonCard } from '@/components/ui/skeleton';
import {
  CreditCard,
  DollarSign,
  Phone,
  Clock,
  Hash,
  RefreshCw,
  BarChart3,
  TrendingUp,
  Calculator,
} from 'lucide-react';
import { usage as usageApi } from '@/lib/api';
import { UsageOverview, DailyUsageEntry, UsageLog } from '@/lib/types';
import { useToast } from '@/components/ui/toast';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';

function BarSegment({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const pct = total > 0 ? (value / total) * 100 : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-[var(--text-muted)] capitalize">{label}</span>
        <span className="font-medium">{value.toLocaleString()} calls · ${(value > 0 ? value : 0).toFixed(4)}</span>
      </div>
      <div className="h-2 w-full bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}

const COLORS = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];

export default function BillingPage() {
  const { apiError } = useToast();
  const [days, setDays] = useState(30);
  const [overview, setOverview] = useState<UsageOverview | null>(null);
  const [daily, setDaily] = useState<DailyUsageEntry[]>([]);
  const [calls, setCalls] = useState<UsageLog[]>([]);
  const [loading, setLoading] = useState(true);

  const [estDuration, setEstDuration] = useState(120);
  const [estModel, setEstModel] = useState('gpt-4o-mini');
  const [estTokens, setEstTokens] = useState(300);
  const [estResult, setEstResult] = useState<{ total_usd: number; cost_breakdown: Record<string, number> } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [o, d, c] = await Promise.all([
        usageApi.overview(days),
        usageApi.daily(days),
        usageApi.calls(days, 50),
      ]);
      setOverview(o);
      setDaily(d.daily);
      setCalls(c.calls);
    } catch (err) {
      apiError(err, 'Failed to load usage data');
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const runEstimate = async () => {
    try {
      const res = await usageApi.estimate({
        duration_seconds: estDuration,
        llm_model: estModel,
        input_tokens: estTokens,
        output_tokens: Math.floor(estTokens * 0.4),
      });
      setEstResult(res);
    } catch (err) {
      apiError(err, 'Estimate failed');
    }
  };

  const maxDailyCost = Math.max(...daily.map(d => d.cost_usd), 0.001);

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="page-title dash-title-gradient dash-title-glow flex items-center gap-2"><CreditCard size={22} className="text-brand-400" /> Billing & Usage</h1>
        <SkeletonStats count={3} />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <SkeletonCard className="h-64" />
          <SkeletonCard className="h-64" />
        </div>
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
            <CreditCard size={22} className="text-brand-400" />
            Billing & Usage
          </h1>
          <p className="page-subtitle">Track costs and manage usage across all providers</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={e => setDays(parseInt(e.target.value))}
            className="input-base text-sm py-1.5"
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
          <button onClick={load} className="p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] bg-[var(--bg-card)] border border-[var(--glass-border)] rounded-lg transition-colors">
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {/* Overview Cards */}
      {overview && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="dash-card p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider">Est. Cost</span>
              <DollarSign size={16} className="text-green-400" />
            </div>
            <div className="text-2xl font-bold">${overview.estimated_cost_usd.toFixed(4)}</div>
            <div className="text-xs text-[var(--text-muted)] mt-1">{overview.period_days} days</div>
          </div>
          <div className="dash-card p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider">Calls</span>
              <Phone size={16} className="text-brand-400" />
            </div>
            <div className="text-2xl font-bold">{overview.total_calls}</div>
            <div className="text-xs text-[var(--text-muted)] mt-1">{overview.total_duration_minutes.toFixed(0)} min total</div>
          </div>
          <div className="dash-card p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider">Tokens</span>
              <Hash size={16} className="text-amber-400" />
            </div>
            <div className="text-2xl font-bold">{(overview.total_tokens).toLocaleString()}</div>
            <div className="text-xs text-[var(--text-muted)] mt-1">{overview.total_input_tokens.toLocaleString()} in / {overview.total_output_tokens.toLocaleString()} out</div>
          </div>
          <div className="dash-card p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-[var(--text-muted)] uppercase tracking-wider">Avg / Call</span>
              <Clock size={16} className="text-purple-400" />
            </div>
            <div className="text-2xl font-bold">
              ${overview.total_calls > 0 ? (overview.estimated_cost_usd / overview.total_calls).toFixed(4) : '0.0000'}
            </div>
            <div className="text-xs text-[var(--text-muted)] mt-1">estimated</div>
          </div>
        </div>
      )}

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Provider Breakdown */}
        {overview && Object.keys(overview.by_provider).length > 0 && (
          <div className="dash-card p-5">
            <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
              <BarChart3 size={16} className="text-brand-400" />
              By Provider
            </h3>
            <div className="space-y-4">
              {Object.entries(overview.by_provider).map(([provider, data], i) => (
                <BarSegment
                  key={provider}
                  label={provider}
                  value={data.calls}
                  total={overview.total_calls}
                  color={COLORS[i % COLORS.length]}
                />
              ))}
            </div>
          </div>
        )}

        {/* Daily Cost Trend */}
        {daily.length > 0 && (
          <div className="dash-card p-5">
            <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
              <TrendingUp size={16} className="text-brand-400" />
              Daily Cost Trend
            </h3>
            <div className="flex items-end gap-1 h-40">
              {daily.map((day, i) => {
                const h = maxDailyCost > 0 ? (day.cost_usd / maxDailyCost) * 100 : 0;
                return (
                  <div key={day.date} className="flex-1 flex flex-col items-center gap-1 group">
                    <div className="relative w-full flex justify-center">
                      <div
                        className="w-full max-w-[20px] bg-brand-500/60 hover:bg-brand-400 rounded-sm transition-all"
                        style={{ height: `${Math.max(h, 4)}px` }}
                        title={`${day.date}: $${day.cost_usd.toFixed(4)} · ${day.calls} calls`}
                      />
                      <div className="absolute -top-8 hidden group-hover:block bg-[var(--bg-tertiary)] border border-[var(--glass-border)] rounded px-2 py-1 text-[10px] whitespace-nowrap z-10">
                        {day.date}: ${day.cost_usd.toFixed(4)}
                      </div>
                    </div>
                    <span className="text-[8px] text-[var(--text-muted)] rotate-0">{day.date.slice(5)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Cost Estimator */}
      <div className="dash-card p-5">
        <h3 className="font-semibold text-sm mb-4 flex items-center gap-2">
          <Calculator size={16} className="text-brand-400" />
          Cost Estimator
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 items-end">
          <div>
            <label className="label-base text-[10px]">Duration (sec)</label>
            <input type="number" value={estDuration} onChange={e => setEstDuration(parseInt(e.target.value))} className="input-base w-full text-sm" />
          </div>
          <div>
            <label className="label-base text-[10px]">LLM Model</label>
            <select value={estModel} onChange={e => setEstModel(e.target.value)} className="input-base w-full text-sm">
              <option value="gpt-4o-mini">gpt-4o-mini</option>
              <option value="gpt-4o">gpt-4o</option>
              <option value="claude-3-haiku">claude-3-haiku</option>
              <option value="gemini-1.5-flash">gemini-1.5-flash</option>
            </select>
          </div>
          <div>
            <label className="label-base text-[10px]">Est. Tokens</label>
            <input type="number" value={estTokens} onChange={e => setEstTokens(parseInt(e.target.value))} className="input-base w-full text-sm" />
          </div>
          <button onClick={runEstimate} className="btn-primary text-sm py-2">Estimate</button>
        </div>
        {estResult && (
          <div className="mt-4 grid grid-cols-5 gap-3 text-center">
            {Object.entries(estResult.cost_breakdown).map(([key, val]) => (
              <div key={key} className="bg-[var(--bg-tertiary)] rounded-lg p-3">
                <div className="text-[10px] text-[var(--text-muted)] uppercase">{key.replace('_usd', '')}</div>
                <div className="text-sm font-semibold mt-1">${val.toFixed(6)}</div>
              </div>
            ))}
            <div className="bg-brand-500/10 rounded-lg p-3 border border-brand-500/20">
              <div className="text-[10px] text-brand-400 uppercase">Total</div>
              <div className="text-sm font-bold mt-1 text-brand-400">${estResult.total_usd.toFixed(6)}</div>
            </div>
          </div>
        )}
      </div>

      {/* Recent Calls Table */}
      {calls.length > 0 && (
        <div className="dash-table overflow-x-auto">
          <h3 className="font-semibold text-sm p-5 pb-0 flex items-center gap-2">
            <Phone size={16} className="text-brand-400" />
            Recent Call Usage
          </h3>
          <table className="w-full mt-3">
            <thead>
              <tr className="border-b border-[var(--glass-border)]">
                <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Call</th>
                <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Duration</th>
                <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Tokens</th>
                <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Model</th>
                <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Cost</th>
                <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-color)]">
              {calls.map(entry => (
                <tr key={entry.id} className="hover:bg-[var(--bg-tertiary)]">
                  <td className="px-5 py-2.5 text-sm font-medium">#{entry.call_id}</td>
                  <td className="px-5 py-2.5 text-xs text-[var(--text-secondary)]">{Math.round(entry.duration_seconds)}s</td>
                  <td className="px-5 py-2.5 text-xs text-[var(--text-secondary)]">{(entry.input_tokens + entry.output_tokens).toLocaleString()}</td>
                  <td className="px-5 py-2.5 text-xs text-[var(--text-secondary)]">{entry.llm_model || '—'}</td>
                  <td className="px-5 py-2.5 text-xs font-medium text-green-400">${entry.estimated_cost_usd.toFixed(4)}</td>
                  <td className="px-5 py-2.5 text-xs text-[var(--text-muted)]">
                    {entry.recorded_at ? new Date(entry.recorded_at).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
    </GsapPageWrapper>
  );
}
