'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import dynamic from 'next/dynamic';
import { analytics, agents as agentsApi, calls as callsApi } from '@/lib/api';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useGsapPageEnter, useGsapScrollReveal } from '@/hooks/use-gsap-animations';
import { AnalyticsOverview, TrendDataPoint, CallAnalysis } from '@/lib/types';
import { formatDuration, timeAgo } from '@/lib/utils';
import { useToast } from '@/components/ui/toast';
import { EmptyState } from '@/components/ui/empty-state';
import { SkeletonPage } from '@/components/ui/skeleton';
import {
  BarChart3,
  TrendingUp,
  PhoneCall,
  Clock,
  Users,
  RefreshCw,
  CheckCircle,
  XCircle,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Activity,
  Target,
  Zap,
  ArrowRight,
  ArrowUpRight,
  ArrowDownRight,
  Search,
  Shield,
  AlertTriangle,
  Filter,
  Repeat,
} from 'lucide-react';

const Donut3D = dynamic(() => import('@/components/three/donut3d'), { ssr: false });
const SentimentGlobe = dynamic(() => import('@/components/three/sentiment-globe'), { ssr: false });

type TabKey = 'overview' | 'trends' | 'quality' | 'funnel' | 'cohorts';

export default function AnalyticsPage() {
  usePageTitle('Analytics');
  const { error } = useToast();
  const pageRef = useRef<HTMLDivElement>(null);
  useGsapPageEnter(pageRef);
  useGsapScrollReveal(pageRef);
  const [tab, setTab] = useState<TabKey>('overview');
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [trends, setTrends] = useState<TrendDataPoint[]>([]);
  const [agentMetrics, setAgentMetrics] = useState<Record<string, unknown>[]>([]);

  // Phase 5 state
  const [quality, setQuality] = useState<{
    avg_quality_score: number;
    score_distribution: Record<string, number>;
    flagged_calls: number;
    top_issues: Array<{ reason: string; count: number }>;
    agent_quality: Array<{ agent_id: number; agent_name: string; calls: number; avg_score: number }>;
  } | null>(null);
  const [funnelData, setFunnelData] = useState<Array<{ stage: string; count: number; pct_of_total: number; drop_off: number }>>([]);
  const [cohortData, setCohortData] = useState<{
    cohorts: Array<{ cohort: string; total_callers: number; retention_7d: number; retention_14d: number; retention_30d: number }>;
    overall: { total_unique_callers: number; repeat_callers: number };
  } | null>(null);

  const loadOverview = useCallback(async () => {
    try {
      const data = await analytics.overview(days);
      setOverview(data);
    } catch {
      error('Failed to load analytics');
    }
  }, [days, error]);

  const loadTrends = useCallback(async () => {
    try {
      const data = await analytics.trends(days, 'day');
      setTrends(data.data);
    } catch {
      error('Failed to load trends');
    }
  }, [days, error]);

  const loadQuality = useCallback(async () => {
    try {
      const data = await analytics.qualityOverview(days);
      setQuality(data);
    } catch {
      error('Failed to load quality data');
    }
  }, [days, error]);

  const loadFunnel = useCallback(async () => {
    try {
      const data = await analytics.funnel(days);
      setFunnelData(data.stages);
    } catch {
      error('Failed to load funnel data');
    }
  }, [days, error]);

  const loadCohorts = useCallback(async () => {
    try {
      const data = await analytics.cohorts(days);
      setCohortData(data);
    } catch {
      error('Failed to load cohort data');
    }
  }, [days, error]);

  useEffect(() => {
    setLoading(true);
    Promise.all([loadOverview(), loadTrends(), loadQuality(), loadFunnel(), loadCohorts()]).finally(() => setLoading(false));
  }, [loadOverview, loadTrends, loadQuality, loadFunnel, loadCohorts]);

  if (loading) {
    return (
      <div className="space-y-6">
        <SkeletonPage />
      </div>
    );
  }

  return (
    <div ref={pageRef} className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between" data-gsap="header">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Analytics</h1>
          <p className="page-subtitle">Call insights and performance metrics</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={days}
            onChange={e => setDays(Number(e.target.value))}
            className="input-base text-sm py-2 px-3 rounded-lg w-auto"
          >
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
          <button onClick={() => { loadOverview(); loadTrends(); loadQuality(); loadFunnel(); loadCohorts(); }} className="btn-secondary text-sm">
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 rounded-xl w-fit border border-[var(--glass-border)]" style={{ background: 'rgba(255,255,255,0.02)' }} data-gsap="header">
        {([
          { key: 'overview' as TabKey, label: 'Overview' },
          { key: 'trends' as TabKey, label: 'Trends' },
          { key: 'quality' as TabKey, label: 'Quality' },
          { key: 'funnel' as TabKey, label: 'Funnel' },
          { key: 'cohorts' as TabKey, label: 'Cohorts' },
        ]).map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              tab === t.key
                ? 'bg-[var(--accent)] text-[var(--text-inverse)] shadow-md'
                : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'overview' && overview && <OverviewTab overview={overview} />}
      {tab === 'trends' && <TrendsTab trends={trends} />}
      {tab === 'quality' && <QualityTab quality={quality} />}
      {tab === 'funnel' && <FunnelTab stages={funnelData} />}
      {tab === 'cohorts' && <CohortsTab data={cohortData} />}
    </div>
  );
}

/* ─── Overview Tab ──────────────────────────────────────── */
function OverviewTab({ overview }: { overview: AnalyticsOverview }) {
  const byStatus = (overview.by_status || {}) as Record<string, number>;
  const byDirection = (overview.by_direction || {}) as Record<string, number>;
  const topAgents = (overview.top_agents || []) as Array<{ name?: string; agent_name?: string; id?: number; call_count: number; avg_duration: number }>;

  return (
    <div className="space-y-6">
      {/* Stat Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-stagger" data-gsap="stat">
        <MetricCard
          label="Total Calls"
          value={overview.total_calls}
          icon={PhoneCall}
          color="bg-blue-500/20 text-blue-400"
        />
        <MetricCard
          label="Avg Duration"
          value={formatDuration(overview.duration?.avg_secs ?? 0)}
          icon={Clock}
          color="bg-amber-500/20 text-amber-400"
        />
        <MetricCard
          label="Completion Rate"
          value={`${Math.round(overview.completion_rate || 0)}%`}
          icon={Target}
          color="bg-green-500/20 text-green-400"
        />
        <MetricCard
          label="Active Agents"
          value={topAgents.length}
          icon={Users}
          color="bg-purple-500/20 text-purple-400"
        />
      </div>

      {/* Breakdown Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4" data-gsap="card">
        {/* Status Breakdown */}
        <div className="dash-card p-5 space-y-4" data-gsap="reveal">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Activity size={14} className="text-[var(--accent)]" /> Status Breakdown
          </h3>
          {Object.entries(byStatus).length === 0 ? (
            <p className="text-xs text-[var(--text-muted)]">No data</p>
          ) : (
            <div className="space-y-3">
              {/* 3D Donut for status */}
              <div className="three-canvas-container" style={{ height: 180 }}>
                <Donut3D data={Object.entries(byStatus).map(([k, v]) => ({ label: k, value: v, color: k === 'completed' ? '#22c55e' : k === 'active' ? '#3b82f6' : k === 'failed' ? '#ef4444' : '#6b7280' }))} height={180} />
              </div>
              {Object.entries(byStatus).map(([status, count]) => (
                <div key={status}>
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="capitalize">{status}</span>
                    <span className="text-[var(--text-muted)]">{count}</span>
                  </div>
                  <div className="h-2 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        status === 'completed' ? 'bg-green-500' :
                        status === 'active' ? 'bg-blue-500' :
                        status === 'failed' ? 'bg-red-500' : 'bg-[var(--text-muted)]'
                      }`}
                      style={{ width: `${Math.min(100, (count / (Object.values(byStatus).reduce((a, b) => a + b, 0) || 1)) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Direction Breakdown */}
        <div className="dash-card p-5 space-y-4" data-gsap="reveal">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Zap size={14} className="text-[var(--accent)]" /> Call Direction
          </h3>
          {Object.entries(byDirection).length === 0 ? (
            <p className="text-xs text-[var(--text-muted)]">No data</p>
          ) : (
            <div className="space-y-3">
              {Object.entries(byDirection).map(([dir, count]) => (
                <div key={dir} className="flex items-center justify-between p-3 rounded-lg bg-[var(--bg-secondary)]">
                  <span className="text-sm capitalize flex items-center gap-2">
                    {dir === 'inbound' ? <ArrowDownRight size={14} className="text-green-400" /> : <ArrowUpRight size={14} className="text-blue-400" />}
                    {dir}
                  </span>
                  <span className="text-lg font-semibold">{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Top Agents */}
        <div className="dash-card p-5 space-y-4" data-gsap="reveal">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Users size={14} className="text-[var(--accent)]" /> Top Agents
          </h3>
          {topAgents.length === 0 ? (
            <p className="text-xs text-[var(--text-muted)]">No data</p>
          ) : (
            <div className="space-y-2">
              {topAgents.slice(0, 5).map((agent, i) => (
                <div key={i} className="flex items-center justify-between p-2.5 rounded-lg bg-[var(--bg-secondary)]">
                  <div className="flex items-center gap-2">
                    <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${
                      i === 0 ? 'bg-amber-500/20 text-amber-400' :
                      i === 1 ? 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]' :
                      'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'
                    }`}>{i + 1}</span>
                    <span className="text-sm truncate">{agent.name || agent.agent_name}</span>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-medium">{agent.call_count}</p>
                    <p className="text-[10px] text-[var(--text-muted)]">{formatDuration(agent.avg_duration)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── Trends Tab ────────────────────────────────────────── */
function TrendsTab({ trends }: { trends: TrendDataPoint[] }) {
  if (trends.length === 0) {
    return (
      <EmptyState
        icon={BarChart3}
        title="No trend data yet"
        description="Data will appear as calls are made. Start making calls to see analytics."
      />
    );
  }

  const maxCalls = Math.max(...trends.map(t => t.calls), 1);

  return (
    <div className="space-y-6">
      {/* Bar Chart */}
      <div className="dash-card p-6" data-gsap="reveal">
        <h3 className="text-sm font-semibold mb-6 flex items-center gap-2">
          <TrendingUp size={14} className="text-[var(--accent)]" /> Call Volume
        </h3>
        <div className="flex items-end gap-1.5 h-48">
          {trends.map((point, i) => {
            const height = (point.calls / maxCalls) * 100;
            return (
              <div key={i} className="flex-1 flex flex-col items-center gap-1 group relative">
                {/* Tooltip */}
                <div className="absolute bottom-full mb-2 hidden group-hover:block z-10">
                  <div className="bg-[var(--bg-primary)] border border-[var(--glass-border)] rounded-lg p-2 text-xs shadow-xl whitespace-nowrap">
                    <p className="font-medium">{point.date}</p>
                    <p className="text-[var(--text-muted)]">{point.calls} calls</p>
                    {point.avg_duration_secs !== undefined && (
                      <p className="text-[var(--text-muted)]">Avg: {formatDuration(point.avg_duration_secs)}</p>
                    )}
                  </div>
                </div>
                <div
                  className="w-full rounded-t-md bg-[var(--accent)] opacity-80 hover:opacity-100 transition-all duration-200 cursor-pointer min-h-[2px]"
                  style={{ height: `${height}%` }}
                />
                {trends.length <= 14 && (
                  <span className="text-[9px] text-[var(--text-muted)] transform -rotate-45 origin-top-left mt-1">
                    {point.date.slice(5)}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Trend Table */}
      <div className="dash-table overflow-hidden" data-gsap="reveal">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[var(--glass-border)]">
                <th className="text-left text-xs font-medium text-[var(--text-muted)] py-3 px-4">Date</th>
                <th className="text-right text-xs font-medium text-[var(--text-muted)] py-3 px-4">Calls</th>
                <th className="text-right text-xs font-medium text-[var(--text-muted)] py-3 px-4">Completed</th>
                <th className="text-right text-xs font-medium text-[var(--text-muted)] py-3 px-4">Failed</th>
                <th className="text-right text-xs font-medium text-[var(--text-muted)] py-3 px-4">Avg Duration</th>
              </tr>
            </thead>
            <tbody>
              {trends.slice().reverse().map((point, i) => (
                <tr key={i} className="border-b border-[var(--glass-border)] last:border-0 hover:bg-brand-500/[0.04] transition-colors">
                  <td className="py-3 px-4 text-sm">{point.date}</td>
                  <td className="py-3 px-4 text-sm text-right font-medium">{point.calls}</td>
                  <td className="py-3 px-4 text-sm text-right text-green-400">{point.completed || 0}</td>
                  <td className="py-3 px-4 text-sm text-right text-red-400">{point.failed || 0}</td>
                  <td className="py-3 px-4 text-sm text-right text-[var(--text-muted)]">
                    {point.avg_duration_secs ? formatDuration(point.avg_duration_secs) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ─── Metric Card ───────────────────────────────────────── */
function MetricCard({
  label,
  value,
  icon: Icon,
  color,
}: {
  label: string;
  value: string | number;
  icon: React.ElementType;
  color: string;
}) {
  return (
    <div className="dash-stat-card group">
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <p className="text-[13px] text-[var(--text-muted)] font-medium">{label}</p>
          <p className="text-2xl font-semibold tracking-tight">{value}</p>
        </div>
        <div className={`p-2.5 rounded-xl ${color} transition-transform duration-200 group-hover:scale-110`}>
          <Icon size={18} />
        </div>
      </div>
    </div>
  );
}

/* ─── Quality Tab ───────────────────────────────────────── */
function QualityTab({
  quality,
}: {
  quality: {
    avg_quality_score: number;
    score_distribution: Record<string, number>;
    flagged_calls: number;
    top_issues: Array<{ reason: string; count: number }>;
    agent_quality: Array<{ agent_id: number; agent_name: string; calls: number; avg_score: number }>;
  } | null;
}) {
  if (!quality) {
    return (
      <EmptyState
        icon={Shield}
        title="No quality data"
        description="Quality scores are computed after calls end. Make some calls to see data."
      />
    );
  }

  const dist = quality.score_distribution || {};
  const totalScored = Object.values(dist).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-6">
      {/* Top Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-gsap="stat">
        <MetricCard label="Avg Quality Score" value={Math.round(quality.avg_quality_score || 0)} icon={Shield} color="bg-blue-500/20 text-blue-400" />
        <MetricCard label="Flagged Calls" value={quality.flagged_calls} icon={AlertTriangle} color="bg-red-500/20 text-red-400" />
        <MetricCard label="Excellent" value={dist.excellent || 0} icon={CheckCircle} color="bg-green-500/20 text-green-400" />
        <MetricCard label="Needs Work" value={(dist.needs_work || 0) + (dist.poor || 0)} icon={XCircle} color="bg-amber-500/20 text-amber-400" />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-gsap="card">
        {/* Score Distribution */}
        <div className="dash-card p-5 space-y-4" data-gsap="reveal">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Activity size={14} className="text-[var(--accent)]" /> Score Distribution
          </h3>
          {totalScored === 0 ? (
            <p className="text-xs text-[var(--text-muted)]">No scored calls yet</p>
          ) : (
            <>
            {/* 3D Donut for score distribution */}
            <div className="three-canvas-container" style={{ height: 180 }}>
              <Donut3D data={[
                { label: 'Excellent', value: dist.excellent || 0, color: '#22c55e' },
                { label: 'Good', value: dist.good || 0, color: '#3b82f6' },
                { label: 'Needs Work', value: dist.needs_work || 0, color: '#f59e0b' },
                { label: 'Poor', value: dist.poor || 0, color: '#ef4444' },
              ]} height={180} />
            </div>
            <div className="space-y-3">
              {[
                { key: 'excellent', label: 'Excellent (80-100)', color: 'bg-green-500' },
                { key: 'good', label: 'Good (60-79)', color: 'bg-blue-500' },
                { key: 'needs_work', label: 'Needs Work (40-59)', color: 'bg-amber-500' },
                { key: 'poor', label: 'Poor (0-39)', color: 'bg-red-500' },
              ].map(({ key, label, color }) => {
                const count = dist[key] || 0;
                const pct = totalScored ? (count / totalScored) * 100 : 0;
                return (
                  <div key={key}>
                    <div className="flex items-center justify-between text-xs mb-1">
                      <span>{label}</span>
                      <span className="text-[var(--text-muted)]">{count}</span>
                    </div>
                    <div className="h-2 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
            </>
          )}
        </div>

        {/* Top Issues */}
        <div className="dash-card p-5 space-y-4" data-gsap="reveal">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <AlertTriangle size={14} className="text-[var(--accent)]" /> Top Issues
          </h3>
          {(!quality.top_issues || quality.top_issues.length === 0) ? (
            <p className="text-xs text-[var(--text-muted)]">No flagged issues</p>
          ) : (
            <div className="space-y-2">
              {quality.top_issues.map((issue, i) => (
                <div key={i} className="flex items-center justify-between p-2.5 rounded-lg bg-[var(--bg-secondary)]">
                  <span className="text-sm capitalize">{issue.reason.replace(/_/g, ' ')}</span>
                  <span className="text-sm font-medium text-red-400">{issue.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Agent Quality Table */}
      <div className="dash-table overflow-hidden" data-gsap="reveal">
        <h3 className="text-sm font-semibold p-5 pb-0 flex items-center gap-2">
          <Users size={14} className="text-[var(--accent)]" /> Agent Quality Rankings
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[var(--glass-border)]">
                <th className="text-left text-xs font-medium text-[var(--text-muted)] py-3 px-5">Agent</th>
                <th className="text-right text-xs font-medium text-[var(--text-muted)] py-3 px-5">Calls</th>
                <th className="text-right text-xs font-medium text-[var(--text-muted)] py-3 px-5">Avg Score</th>
              </tr>
            </thead>
            <tbody>
              {quality.agent_quality.map((a, i) => (
                <tr key={i} className="border-b border-[var(--glass-border)] last:border-0 hover:bg-brand-500/[0.04]">
                  <td className="py-3 px-5 text-sm font-medium">{a.agent_name}</td>
                  <td className="py-3 px-5 text-sm text-right">{a.calls}</td>
                  <td className="py-3 px-5 text-sm text-right">
                    <span className={`font-medium ${a.avg_score >= 80 ? 'text-green-400' : a.avg_score >= 60 ? 'text-blue-400' : 'text-red-400'}`}>
                      {a.avg_score}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ─── Funnel Tab ────────────────────────────────────────── */
function FunnelTab({ stages }: { stages: Array<{ stage: string; count: number; pct_of_total: number; drop_off: number }> }) {
  if (stages.length === 0) {
    return (
      <EmptyState
        icon={Filter}
        title="No funnel data"
        description="Start making calls to see conversion funnel stages."
      />
    );
  }

  const total = stages[0]?.count || 1;
  const colors = ['bg-blue-500', 'bg-green-500', 'bg-amber-500', 'bg-purple-500'];
  const labels: Record<string, string> = {
    initiated: 'Call Initiated',
    connected: 'Connected',
    completed: 'Completed',
    resolved: 'Resolved (Goal)',
  };

  return (
    <div className="space-y-6">
      <div className="dash-card p-6 space-y-6" data-gsap="reveal">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Filter size={14} className="text-[var(--accent)]" /> Conversion Funnel
        </h3>

        <div className="space-y-4">
          {stages.map((s, i) => {
            const width = total ? (s.count / total) * 100 : 0;
            const color = colors[i % colors.length];
            return (
              <div key={s.stage} className="space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium capitalize">{labels[s.stage] || s.stage}</span>
                  <div className="flex items-center gap-4">
                    <span className="text-[var(--text-muted)]">{s.count} calls</span>
                    <span className="font-medium w-12 text-right">{s.pct_of_total}%</span>
                  </div>
                </div>
                <div className="relative h-10 bg-[var(--bg-tertiary)] rounded-lg overflow-hidden">
                  <div
                    className={`absolute top-0 left-0 h-full ${color} opacity-80 flex items-center justify-end pr-3 transition-all duration-500`}
                    style={{ width: `${width}%` }}
                  >
                    {width > 15 && <span className="text-[var(--text-inverse)] text-xs font-medium">{s.count}</span>}
                  </div>
                </div>
                {s.drop_off > 0 && (
                  <p className="text-xs text-red-400 flex items-center gap-1">
                    <ArrowDownRight size={12} /> {s.drop_off}% drop-off
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Funnel Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-gsap="stat">
        {stages.map((s, i) => (
          <MetricCard
            key={s.stage}
            label={labels[s.stage] || s.stage}
            value={s.count}
            icon={[PhoneCall, Activity, CheckCircle, Target][i]}
            color={['bg-blue-500/20 text-blue-400', 'bg-green-500/20 text-green-400', 'bg-amber-500/20 text-amber-400', 'bg-purple-500/20 text-purple-400'][i]}
          />
        ))}
      </div>
    </div>
  );
}

/* ─── Cohorts Tab ───────────────────────────────────────── */
function CohortsTab({
  data,
}: {
  data: {
    cohorts: Array<{ cohort: string; total_callers: number; retention_7d: number; retention_14d: number; retention_30d: number }>;
    overall: { total_unique_callers: number; repeat_callers: number };
  } | null;
}) {
  if (!data || data.cohorts.length === 0) {
    return (
      <EmptyState
        icon={Repeat}
        title="No cohort data"
        description="As callers return over time, retention cohorts will appear here."
      />
    );
  }

  const repeatRate = data.overall.total_unique_callers
    ? Math.round((data.overall.repeat_callers / data.overall.total_unique_callers) * 100)
    : 0;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4" data-gsap="stat">
        <MetricCard
          label="Unique Callers"
          value={data.overall.total_unique_callers}
          icon={Users}
          color="bg-blue-500/20 text-blue-400"
        />
        <MetricCard
          label="Repeat Callers"
          value={data.overall.repeat_callers}
          icon={Repeat}
          color="bg-green-500/20 text-green-400"
        />
        <MetricCard
          label="Repeat Rate"
          value={`${repeatRate}%`}
          icon={Target}
          color="bg-purple-500/20 text-purple-400"
        />
      </div>

      <div className="dash-table overflow-hidden" data-gsap="reveal">
        <h3 className="text-sm font-semibold p-5 pb-0 flex items-center gap-2">
          <Repeat size={14} className="text-[var(--accent)]" /> Caller Retention Cohorts
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[var(--glass-border)]">
                <th className="text-left text-xs font-medium text-[var(--text-muted)] py-3 px-5">Cohort (Week)</th>
                <th className="text-right text-xs font-medium text-[var(--text-muted)] py-3 px-5">Callers</th>
                <th className="text-right text-xs font-medium text-[var(--text-muted)] py-3 px-5">7-Day</th>
                <th className="text-right text-xs font-medium text-[var(--text-muted)] py-3 px-5">14-Day</th>
                <th className="text-right text-xs font-medium text-[var(--text-muted)] py-3 px-5">30-Day</th>
              </tr>
            </thead>
            <tbody>
              {data.cohorts.map((c, i) => (
                <tr key={i} className="border-b border-[var(--glass-border)] last:border-0 hover:bg-brand-500/[0.04]">
                  <td className="py-3 px-5 text-sm font-medium">{c.cohort}</td>
                  <td className="py-3 px-5 text-sm text-right">{c.total_callers}</td>
                  <td className="py-3 px-5 text-sm text-right">
                    <RetentionCell value={c.retention_7d} />
                  </td>
                  <td className="py-3 px-5 text-sm text-right">
                    <RetentionCell value={c.retention_14d} />
                  </td>
                  <td className="py-3 px-5 text-sm text-right">
                    <RetentionCell value={c.retention_30d} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function RetentionCell({ value }: { value: number }) {
  return (
    <span className={`font-medium ${value >= 50 ? 'text-green-400' : value >= 25 ? 'text-blue-400' : value > 0 ? 'text-amber-400' : 'text-[var(--text-muted)]'}`}>
      {value}%
    </span>
  );
}
