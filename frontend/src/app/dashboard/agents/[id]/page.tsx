'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { agents as agentsApi } from '@/lib/api';
import { Skeleton, SkeletonCard } from '@/components/ui/skeleton';
import {
  ArrowLeft,
  Play,
  BarChart3,
  PhoneCall,
  Clock,
  TrendingUp,
  Smile,
  Frown,
  Meh,
  Activity,
  Wrench,
  GitBranch,
  FlaskConical,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { AnalyticsSummary, CallLog } from '@/lib/types';
import { analytics as analyticsApi, calls as callsApi } from '@/lib/api';
import { useToast } from '@/components/ui/toast';
import AgentBuilder from '../_components/agent-builder';
import { SimulationTab } from '../_components/simulation-tab';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';

const TABS = [
  { id: 'playground', label: 'Playground', icon: Play },
  { id: 'simulation', label: 'Simulation', icon: FlaskConical },
  { id: 'builder', label: 'Builder', icon: Wrench },
  { id: 'analytics', label: 'Analytics', icon: BarChart3 },
] as const;

const FLOW_TAB = { id: 'flow', label: 'Flow', icon: GitBranch } as const;

export default function AgentDetailPage() {
  const { id } = useParams();
  const [activeTab, setActiveTab] = useState('playground');
  const [agentMode, setAgentMode] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    agentsApi.get(Number(id)).then(({ agent }) => {
      setAgentMode(agent.mode || 'single_prompt');
    }).catch(() => setAgentMode('single_prompt'));
  }, [id]);

  const isFlowAgent = agentMode === 'conversational_flow';
  const visibleTabs = isFlowAgent ? [...TABS, FLOW_TAB] : TABS;

  return (
    <GsapPageWrapper>
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      {/* Header */}
      <div className="flex items-center gap-3 shrink-0 pb-4">
        <Link
          href="/dashboard/agents"
          className="p-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] rounded-lg transition-colors"
        >
          <ArrowLeft size={18} />
        </Link>
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Agent #{id}</h1>
          <p className="page-subtitle">
            Test, configure, and monitor your agent
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[var(--glass-border)] shrink-0">
        {visibleTabs.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
                isActive
                  ? 'border-brand-400 text-brand-400'
                  : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
              )}
            >
              <tab.icon size={16} />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden pt-4">
        {activeTab === 'playground' && (
          <iframe
            src={`/dashboard/playground?agent=${id}&embedded=1`}
            className="w-full h-full border-0 rounded-xl"
            title="Agent Playground"
          />
        )}

        {activeTab === 'simulation' && (
          <SimulationTab agentId={Number(id)} />
        )}

        {activeTab === 'builder' && (
          <AgentBuilder agentId={Number(id)} />
        )}

        {activeTab === 'analytics' && (
          <AgentAnalyticsTab agentId={Number(id)} />
        )}

        {activeTab === 'flow' && isFlowAgent && (
          <iframe
            src={`/dashboard/workflows?agentId=${id}&embedded=1`}
            className="w-full h-full border-0 rounded-xl"
            title="Workflow Flow Editor"
          />
        )}
      </div>
    </div>
    </GsapPageWrapper>
  );
}

/* ── Agent Analytics Tab ──────────────────────────────────────── */
function AgentAnalyticsTab({ agentId }: { agentId: number }) {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [agentMetrics, setAgentMetrics] = useState<Record<string, unknown> | null>(null);
  const [recentCalls, setRecentCalls] = useState<CallLog[]>([]);
  const [loading, setLoading] = useState(true);
  const { apiError } = useToast();

  useEffect(() => {
    const load = async () => {
      try {
        const [s, m, c] = await Promise.all([
          analyticsApi.summary(30, agentId).catch(() => null),
          analyticsApi.agentAnalytics(agentId, 30).catch(() => null),
          callsApi.list({ agent_id: agentId, per_page: 5 }).catch(() => ({ calls: [] })),
        ]);
        if (s) setSummary(s);
        if (m) setAgentMetrics(m);
        setRecentCalls(c.calls);
      } catch {
        apiError(null, 'Failed to load analytics');
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [agentId]);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3">
          <Link href="/dashboard/agents" className="p-2 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors">
            <ArrowLeft size={18} />
          </Link>
          <Skeleton className="h-8 w-48" />
        </div>
        <SkeletonCard className="h-96" />
      </div>
    );
  }

  if (!summary || summary.total_calls === 0) {
    return (
      <div className="dash-card p-12 text-center">
        <BarChart3 size={32} className="mx-auto mb-3 text-[var(--text-muted)]" />
        <h3 className="font-semibold mb-1">No Data Yet</h3>
        <p className="text-sm text-[var(--text-muted)]">
          This agent hasn&apos;t handled any analyzed calls in the last 30 days.
        </p>
      </div>
    );
  }

  const totalSentiment = Object.values(summary.sentiment_distribution || {}).reduce((a, b) => a + b, 0) || 1;
  const sentimentPct = (key: string) => Math.round(((summary.sentiment_distribution?.[key] || 0) / totalSentiment) * 100);

  return (
    <div className="space-y-6">
      {/* Metrics Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="dash-card p-4">
          <div className="flex items-center gap-2 mb-2">
            <PhoneCall size={16} className="text-brand-400" />
            <span className="text-xs text-[var(--text-muted)]">Total Calls</span>
          </div>
          <p className="text-2xl font-semibold">{summary.total_calls}</p>
          <p className="text-[10px] text-[var(--text-muted)]">Last 30 days</p>
        </div>
        <div className="dash-card p-4">
          <div className="flex items-center gap-2 mb-2">
            <Clock size={16} className="text-blue-400" />
            <span className="text-xs text-[var(--text-muted)]">Avg Duration</span>
          </div>
          <p className="text-2xl font-semibold">{Math.round(summary.avg_duration_secs / 60)}m</p>
          <p className="text-[10px] text-[var(--text-muted)]">Per call</p>
        </div>
        <div className="dash-card p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp size={16} className="text-emerald-400" />
            <span className="text-xs text-[var(--text-muted)]">Completion</span>
          </div>
          <p className="text-2xl font-semibold">{`${agentMetrics?.completion_rate ?? 0}%`}</p>
          <p className="text-[10px] text-[var(--text-muted)]">{`${agentMetrics?.completed_calls ?? 0} completed`}</p>
        </div>
        <div className="dash-card p-4">
          <div className="flex items-center gap-2 mb-2">
            <Activity size={16} className="text-purple-400" />
            <span className="text-xs text-[var(--text-muted)]">Sentiment</span>
          </div>
          <p className="text-2xl font-semibold">
            {summary.avg_sentiment_score !== null ? summary.avg_sentiment_score.toFixed(2) : '—'}
          </p>
          <p className="text-[10px] text-[var(--text-muted)]">Avg score (0–1)</p>
        </div>
      </div>

      {/* Sentiment + Topics */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="dash-card p-5">
          <h3 className="font-semibold mb-4">Sentiment Distribution</h3>
          <div className="space-y-3">
            {(['positive', 'neutral', 'negative', 'mixed'] as const).map(s => {
              const count = summary.sentiment_distribution?.[s] || 0;
              const pct = sentimentPct(s);
              return (
                <div key={s} className="flex items-center gap-3">
                  {s === 'positive' ? <Smile size={16} className="text-green-400 shrink-0" />
                    : s === 'negative' ? <Frown size={16} className="text-red-400 shrink-0" />
                    : <Meh size={16} className="text-[var(--text-muted)] shrink-0" />}
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs text-[var(--text-secondary)] capitalize">{s}</span>
                      <span className="text-xs font-medium">{count} ({pct}%)</span>
                    </div>
                    <div className="h-2 bg-[var(--bg-tertiary)] rounded-full overflow-hidden">
                      <div
                        className={`h-2 rounded-full ${
                          s === 'positive' ? 'bg-green-400'
                          : s === 'negative' ? 'bg-red-400'
                          : s === 'mixed' ? 'bg-amber-400'
                          : 'bg-[var(--text-muted)]'
                        }`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="dash-card p-5">
          <h3 className="font-semibold mb-4">Top Topics</h3>
          <div className="space-y-2">
            {summary.top_topics.slice(0, 8).map((t, i) => (
              <div key={i} className="flex items-center justify-between">
                <span className="text-xs text-[var(--text-secondary)]">{t.topic}</span>
                <span className="text-xs text-[var(--text-muted)] font-mono">{t.count}</span>
              </div>
            ))}
            {summary.top_topics.length === 0 && (
              <p className="text-xs text-[var(--text-muted)]">No topics found</p>
            )}
          </div>
        </div>
      </div>

      {/* Recent Calls with Analysis */}
      <div className="dash-card overflow-hidden">
        <h3 className="font-semibold p-5 pb-0">Recent Calls</h3>
        {recentCalls.length === 0 ? (
          <div className="p-8 text-center text-sm text-[var(--text-muted)]">No recent calls</div>
        ) : (
          <table className="w-full mt-3">
            <thead>
              <tr className="border-b border-[var(--glass-border)]">
                <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">From</th>
                <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Duration</th>
                <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Sentiment</th>
                <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">Resolution</th>
                <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase px-5 py-2">When</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-color)]">
              {recentCalls.map(call => {
                let analysis: any = null;
                try { analysis = call.analysis_json ? JSON.parse(call.analysis_json) : null; } catch { analysis = null; }
                return (
                  <tr key={call.id} className="hover:bg-[var(--bg-tertiary)]">
                    <td className="px-5 py-2.5 text-sm font-mono">{call.from_phone}</td>
                    <td className="px-5 py-2.5 text-sm text-[var(--text-secondary)]">{Math.round((call.duration_secs || 0) / 60)}m</td>
                    <td className="px-5 py-2.5">
                      {analysis?.sentiment ? (
                        <span className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border ${
                          analysis.sentiment === 'positive' ? 'text-green-400 bg-green-500/10 border-green-500/20'
                          : analysis.sentiment === 'negative' ? 'text-red-400 bg-red-500/10 border-red-500/20'
                          : 'text-[var(--text-muted)] bg-[var(--bg-tertiary)] border-[var(--glass-border)]'
                        }`}>
                          {analysis.sentiment}
                        </span>
                      ) : <span className="text-xs text-[var(--text-muted)]">—</span>}
                    </td>
                    <td className="px-5 py-2.5">
                      {analysis?.resolution_status ? (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--glass-border)]">
                          {analysis.resolution_status}
                        </span>
                      ) : <span className="text-xs text-[var(--text-muted)]">—</span>}
                    </td>
                    <td className="px-5 py-2.5 text-xs text-[var(--text-muted)]">{new Date(call.started_at).toLocaleDateString()}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
