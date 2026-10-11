'use client';

import { useState, useEffect, useCallback } from 'react';
import { SkeletonStats, SkeletonTable } from '@/components/ui/skeleton';
import {
  ShieldCheck,
  AlertTriangle,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Flag,
  FlagOff,
  Zap,
  Clock,
  Loader2,
  RefreshCw,
  ChevronRight,
  Star,
  PhoneCall,
} from 'lucide-react';
import { analytics as analyticsApi } from '@/lib/api';
import { QualityOverview, CallLog } from '@/lib/types';
import { formatPhone, cn } from '@/lib/utils';
import { useToast } from '@/components/ui/toast';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';

/* ─── Mini Donut Chart ──────────────────────────────────── */
function MiniDonut({ data, labels, colors }: { data: number[]; labels: string[]; colors: string[] }) {
  const total = Math.max(data.reduce((a, b) => a + b, 0), 1);
  let cumulative = 0;
  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 36 36" className="w-24 h-24 shrink-0">
        {data.map((v, i) => {
          const pct = (v / total) * 100;
          const start = cumulative;
          cumulative += pct;
          return (
            <circle
              key={i}
              cx="18" cy="18" r="15.9"
              fill="none"
              stroke={colors[i] || '#6366f1'}
              strokeWidth="4"
              strokeDasharray={`${pct} ${100 - pct}`}
              strokeDashoffset={-start + 25}
              className="transition-all duration-500"
            />
          );
        })}
      </svg>
      <div className="space-y-2">
        {data.map((v, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: colors[i] }} />
            <span className="text-[var(--text-muted)]">{labels[i]}</span>
            <span className="font-medium text-[var(--text-secondary)]">{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Score Ring ────────────────────────────────────────── */
function ScoreRing({ score }: { score: number }) {
  const color = score >= 80 ? '#22c55e' : score >= 60 ? '#6366f1' : score >= 40 ? '#f59e0b' : '#ef4444';
  const circumference = 2 * Math.PI * 15.9;
  const offset = circumference - (score / 100) * circumference;
  return (
    <div className="relative w-20 h-20 shrink-0">
      <svg viewBox="0 0 36 36" className="w-full h-full">
        <circle cx="18" cy="18" r="15.9" fill="none" stroke="var(--text-muted)" strokeWidth="4" />
        <circle
          cx="18" cy="18" r="15.9" fill="none" stroke={color} strokeWidth="4"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-all duration-700"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-sm font-bold" style={{ color }}>{Math.round(score)}</span>
      </div>
    </div>
  );
}

/* ─── Main Page ─────────────────────────────────────────── */
export default function QualityPage() {
  const { success, apiError } = useToast();
  const [overview, setOverview] = useState<QualityOverview | null>(null);
  const [flagged, setFlagged] = useState<CallLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);
  const [togglingId, setTogglingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, fl] = await Promise.all([
        analyticsApi.qualityOverview(days),
        analyticsApi.flaggedCalls(days),
      ]);
      setOverview(ov);
      setFlagged(fl.calls);
    } catch (err) {
      apiError(err, 'Failed to load quality data');
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const toggleFlag = async (call: CallLog) => {
    setTogglingId(call.id);
    try {
      await analyticsApi.toggleFlag(call.id, call.review_flag ? '' : 'manual_review');
      success(call.review_flag ? 'Unflagged' : 'Flagged', 'Review status updated');
      setFlagged(prev => prev.filter(c => c.id !== call.id));
    } catch (err) {
      apiError(err, 'Failed to update flag');
    } finally {
      setTogglingId(null);
    }
  };

  const totalScored = overview
    ? overview.score_distribution.excellent +
      overview.score_distribution.good +
      overview.score_distribution.needs_work +
      overview.score_distribution.poor
    : 0;

  const scoreColor = (score?: number | null) => {
    if (score === null || score === undefined) return 'text-[var(--text-muted)]';
    if (score >= 80) return 'text-green-400';
    if (score >= 60) return 'text-brand-400';
    if (score >= 40) return 'text-amber-400';
    return 'text-red-400';
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="page-title dash-title-gradient dash-title-glow">AI Quality Assurance</h1>
        <SkeletonStats count={3} />
        <SkeletonTable rows={5} cols={4} />
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
            <ShieldCheck size={22} className="text-brand-400" />
            AI Quality Assurance
          </h1>
          <p className="page-subtitle">Monitor agent performance and catch regressions early</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={e => setDays(Number(e.target.value))}
            className="input-base text-sm"
          >
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
          </select>
          <button
            onClick={load}
            className="p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] bg-[var(--bg-card)] border border-[var(--glass-border)] rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      {totalScored === 0 && !flagged.length ? (
        <div className="dash-card p-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-[var(--bg-tertiary)] flex items-center justify-center mx-auto mb-4">
            <ShieldCheck size={28} className="text-[var(--text-muted)]" />
          </div>
          <h3 className="text-lg font-semibold mb-2">No Quality Data Yet</h3>
          <p className="text-sm text-[var(--text-muted)] max-w-md mx-auto">
            Quality scores are computed automatically for completed calls with latency metrics.
            Make some calls and they will appear here.
          </p>
        </div>
      ) : (
        <>
          {/* Overview Cards */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="dash-card p-4">
              <div className="flex items-center gap-2 mb-2">
                <Star size={16} className="text-brand-400" />
                <span className="text-xs text-[var(--text-muted)]">Avg Quality Score</span>
              </div>
              <div className="flex items-center gap-2">
                <p className="text-2xl font-semibold">{overview?.avg_quality_score ?? 0}</p>
                {(overview?.avg_quality_score ?? 0) >= 70 ? (
                  <TrendingUp size={14} className="text-green-400" />
                ) : (
                  <TrendingDown size={14} className="text-amber-400" />
                )}
              </div>
              <p className="text-[10px] text-[var(--text-muted)]">{totalScored} calls scored</p>
            </div>
            <div className="dash-card p-4">
              <div className="flex items-center gap-2 mb-2">
                <Flag size={16} className="text-red-400" />
                <span className="text-xs text-[var(--text-muted)]">Flagged for Review</span>
              </div>
              <p className="text-2xl font-semibold">{overview?.flagged_calls ?? 0}</p>
              <p className="text-[10px] text-[var(--text-muted)]">
                {totalScored > 0 ? `${Math.round(((overview?.flagged_calls ?? 0) / totalScored) * 100)}% of scored` : '0% of scored'}
              </p>
            </div>
            <div className="dash-card p-4">
              <div className="flex items-center gap-2 mb-2">
                <Zap size={16} className="text-green-400" />
                <span className="text-xs text-[var(--text-muted)]">Excellent Calls</span>
              </div>
              <p className="text-2xl font-semibold">{overview?.score_distribution.excellent ?? 0}</p>
              <p className="text-[10px] text-[var(--text-muted)]">Score 80–100</p>
            </div>
            <div className="dash-card p-4">
              <div className="flex items-center gap-2 mb-2">
                <Clock size={16} className="text-amber-400" />
                <span className="text-xs text-[var(--text-muted)]">Need Work</span>
              </div>
              <p className="text-2xl font-semibold">
                {(overview?.score_distribution.needs_work ?? 0) + (overview?.score_distribution.poor ?? 0)}
              </p>
              <p className="text-[10px] text-[var(--text-muted)]">Score &lt; 60</p>
            </div>
          </div>

          {/* Score Distribution + Agent Quality */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="dash-card p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold">Score Distribution</h3>
                <BarChart3 size={15} className="text-[var(--text-muted)]" />
              </div>
              {totalScored > 0 ? (
                <MiniDonut
                  data={[
                    overview?.score_distribution.excellent ?? 0,
                    overview?.score_distribution.good ?? 0,
                    overview?.score_distribution.needs_work ?? 0,
                    overview?.score_distribution.poor ?? 0,
                  ]}
                  labels={['Excellent (80-100)', 'Good (60-79)', 'Needs Work (40-59)', 'Poor (0-39)']}
                  colors={['#22c55e', '#6366f1', '#f59e0b', '#ef4444']}
                />
              ) : (
                <p className="text-sm text-[var(--text-muted)]">No scored calls yet</p>
              )}

              {/* Top Issues */}
              {overview && overview.top_issues.length > 0 && (
                <div className="mt-5 pt-4 border-t border-[var(--glass-border)]">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-2">Top Issues</h4>
                  <div className="space-y-1.5">
                    {overview.top_issues.map((issue, i) => (
                      <div key={i} className="flex items-center justify-between text-xs">
                        <span className="text-[var(--text-secondary)] capitalize">{issue.reason.replace(/_/g, ' ')}</span>
                        <span className="text-[var(--text-muted)] font-mono">{issue.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="dash-card p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold">Agent Quality</h3>
                <Star size={15} className="text-[var(--text-muted)]" />
              </div>
              <div className="space-y-3">
                {overview && overview.agent_quality.length > 0 ? (
                  overview.agent_quality.map((aq) => (
                    <div key={aq.agent_id} className="flex items-center gap-3">
                      <ScoreRing score={aq.avg_score} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{aq.agent_name || `Agent #${aq.agent_id}`}</p>
                        <p className="text-[10px] text-[var(--text-muted)]">{aq.calls} calls analyzed</p>
                      </div>
                      <span className={cn('text-sm font-bold', scoreColor(aq.avg_score))}>
                        {aq.avg_score}
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-[var(--text-muted)]">No agent quality data yet</p>
                )}
              </div>
            </div>
          </div>

          {/* Flagged Calls */}
          {flagged.length > 0 && (
            <div className="dash-table overflow-x-auto">
              <div className="flex items-center justify-between p-5 pb-0">
                <h3 className="font-semibold flex items-center gap-2">
                  <AlertTriangle size={16} className="text-amber-400" />
                  Flagged for Review
                </h3>
                <span className="text-xs text-[var(--text-muted)]">{flagged.length} calls</span>
              </div>
              <table className="w-full mt-3">
                <thead>
                  <tr className="border-b border-[var(--glass-border)]">
                    <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Call</th>
                    <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Agent</th>
                    <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Score</th>
                    <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Reason</th>
                    <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">When</th>
                    <th className="px-5 py-2"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-color)]">
                  {flagged.map(call => (
                    <tr key={call.id} className="hover:bg-[var(--bg-tertiary)] transition-colors">
                      <td className="px-5 py-2.5 text-sm font-mono">{formatPhone(call.from_phone)}</td>
                      <td className="px-5 py-2.5 text-sm text-[var(--text-secondary)]">{call.agent_name || `Agent #${call.agent_id}`}</td>
                      <td className="px-5 py-2.5">
                        <span className={cn('text-sm font-bold', scoreColor(call.quality_score))}>
                          {call.quality_score ?? '—'}
                        </span>
                      </td>
                      <td className="px-5 py-2.5">
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 capitalize">
                          {(call.review_reason || 'unknown').replace(/_/g, ' ')}
                        </span>
                      </td>
                      <td className="px-5 py-2.5 text-xs text-[var(--text-muted)]">
                        {call.started_at ? new Date(call.started_at).toLocaleDateString() : '—'}
                      </td>
                      <td className="px-5 py-2.5">
                        <button
                          onClick={() => toggleFlag(call)}
                          disabled={togglingId === call.id}
                          className="flex items-center gap-1 text-[10px] px-2 py-1 rounded bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--glass-border)] hover:text-green-400 transition-colors disabled:opacity-50"
                          title="Mark as reviewed"
                        >
                          {togglingId === call.id ? (
                            <Loader2 size={12} className="animate-spin" />
                          ) : (
                            <FlagOff size={12} />
                          )}
                          Reviewed
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
    </GsapPageWrapper>
  );
}
