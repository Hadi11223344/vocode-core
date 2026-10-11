'use client';

import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import dynamic from 'next/dynamic';
import { dashboard, calls as callsApi, agents as agentsApi, twilio, getToken, analytics, live, getValidToken } from '@/lib/api';
import { useOnboarding } from '@/hooks/useOnboarding';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useGsapPageEnter, useGsapCounter } from '@/hooks/use-gsap-animations';
import { usePerformance } from '@/lib/performance-context';
import { useModalFocusTrap } from '@/hooks/use-modal-focus-trap';
import { DashboardStats, CallLog, Agent, TrendDataPoint, AnalyticsSummary } from '@/lib/types';
import { formatDuration, formatPhone, timeAgo, formatTimestamp } from '@/lib/utils';
import { useToast } from '@/components/ui/toast';
import { EmptyState } from '@/components/ui/empty-state';
import Link from 'next/link';
import {
  PhoneCall,
  Clock,
  Bot,
  Activity,
  PhoneIncoming,
  PhoneOutgoing,
  PhoneOff,
  TrendingUp,
  ArrowRight,
  BarChart3,
  GitBranch,
  Zap,
  X,
  Loader2,
  RefreshCw,
  MessageSquare,
  User,
  Smile,
  Frown,
  Meh,
  Tag,
} from 'lucide-react';
import StatusBadge from '@/components/ui/status-badge';

const Bar3DChart = dynamic(() => import('@/components/three/bar3d-chart'), { ssr: false });
const ParticleNetwork = dynamic(() => import('@/components/three/particle-network'), { ssr: false });

/* ─── Stat Card with GSAP Counter ──────────────────────── */
function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  color,
  trend,
  numericValue,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ElementType;
  color: string;
  trend?: string;
  numericValue?: number;
}) {
  const { quality } = usePerformance();
  const counterRef = useRef<HTMLSpanElement>(null);
  const isNumeric = numericValue !== undefined && typeof value === 'number';

  useGsapCounter(counterRef, numericValue ?? 0, {
    duration: 1.2,
    suffix: label === 'Success Rate' ? '%' : '',
  });

  return (
    <div className="dash-stat-card group gsap-tilt-card" data-gsap="stat">
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <p className="text-[13px] text-[var(--text-muted)] font-medium">{label}</p>
          {isNumeric && quality !== 'off' ? (
            <p className="text-2xl font-semibold tracking-tight">
              <span ref={counterRef}>0{label === 'Success Rate' ? '%' : ''}</span>
            </p>
          ) : (
            <p className="text-2xl font-semibold tracking-tight">{value}</p>
          )}
          {sub && <p className="text-xs text-[var(--text-muted)]">{sub}</p>}
        </div>
        <div className={`dash-stat-icon ${color}`}>
          <Icon size={18} />
        </div>
      </div>
      {trend && (
        <div className="flex items-center gap-1 mt-3 text-xs text-green-400">
          <TrendingUp size={12} />
          {trend}
        </div>
      )}
    </div>
  );
}

/* ─── Mini Donut Chart ──────────────────────────────────── */
function MiniDonutChart({ data, labels, colors }: { data: number[]; labels: string[]; colors: string[] }) {
  const total = Math.max(data.reduce((a, b) => a + b, 0), 1);
  let cumulative = 0;
  const segments = data.map((v, i) => {
    const pct = (v / total) * 100;
    const start = cumulative;
    cumulative += pct;
    return { pct, start, color: colors[i] || '#6366f1', label: labels[i], value: v };
  });
  return (
    <div className="flex items-center gap-4">
      <svg viewBox="0 0 36 36" className="w-20 h-20 shrink-0">
        {segments.map((s, i) => (
          <circle
            key={i}
            cx="18" cy="18" r="15.9"
            fill="none"
            stroke={s.color}
            strokeWidth="4"
            strokeDasharray={`${s.pct} ${100 - s.pct}`}
            strokeDashoffset={-s.start + 25}
            className="transition-all duration-500"
          />
        ))}
      </svg>
      <div className="space-y-1.5">
        {segments.map((s, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: s.color }} />
            <span className="text-[var(--text-muted)]">{s.label}</span>
            <span className="font-medium text-[var(--text-secondary)]">{s.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Mini Bar Chart ────────────────────────────────────── */
function MiniBarChart({ data, labels, label }: { data: number[]; labels: string[]; label: string }) {
  const max = Math.max(...data, 1);
  return (
    <div className="dash-card p-5">
      <div className="flex items-center justify-between mb-4">
        <p className="text-[13px] font-medium text-[var(--text-muted)]">{label}</p>
        <BarChart3 size={15} className="text-[var(--text-muted)]" />
      </div>
      <div className="flex items-end gap-2 h-20">
        {data.map((v, i) => (
          <div
            key={i}
            className="dash-bar flex-1 hover:bg-brand-500/40 transition-all duration-200 relative group cursor-default"
            style={{ height: `${Math.max((v / max) * 100, 6)}%`, animationDelay: `${i * 60}ms` }}
          >
            <div className="absolute -top-7 left-1/2 -translate-x-1/2 bg-[var(--bg-elevated)] text-[11px] px-2 py-0.5 rounded-md opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap border border-[var(--glass-border)] shadow-md pointer-events-none">
              {v}
            </div>
          </div>
        ))}
      </div>
      <div className="flex justify-between mt-2.5 text-[10px] text-[var(--text-muted)]">
        {labels.map((l, i) => (
          <span key={i} className={i === labels.length - 1 ? 'font-medium text-brand-400' : ''}>{l}</span>
        ))}
      </div>
    </div>
  );
}

/* ─── Getting Started Card ────────────────────────────── */
function GettingStartedCard() {
  const { state, start, update } = useOnboarding();
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (state.completed || state.dismissedAt) return;
    setShow(true);
  }, [state.completed, state.dismissedAt]);

  if (!show) return null;

  return (
    <div className="dash-card p-5 border-l-4 border-l-[var(--accent)]" style={{ background: 'rgba(99, 102, 241, 0.04)' }}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-semibold text-sm mb-1">Welcome to VOIA! Let&apos;s get you set up.</h3>
          <p className="text-xs text-[var(--text-muted)] mb-3">
            Create your first voice agent in under 2 minutes — choose a template, customize it, and test it live.
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={() => { start(); window.dispatchEvent(new CustomEvent('open-wizard')); }}
              className="btn-primary text-xs py-1.5 px-3"
            >
              <Zap size={14} /> Start Setup
            </button>
            <button
              onClick={() => { update({ dismissedAt: new Date().toISOString() }); setShow(false); }}
              className="text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
            >
              Dismiss
            </button>
          </div>
        </div>
        <div className="hidden sm:block">
          <div className="w-12 h-12 rounded-xl bg-[var(--accent)]/10 flex items-center justify-center">
            <Bot size={24} className="text-[var(--accent)]" />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── Main Dashboard ────────────────────────────────────── */
export default function DashboardPage() {
  usePageTitle('Dashboard');
  const { quality } = usePerformance();
  const { success, apiError } = useToast();
  const pageRef = useRef<HTMLDivElement>(null);
  useGsapPageEnter(pageRef);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recentCalls, setRecentCalls] = useState<CallLog[]>([]);
  const [activeCalls, setActiveCalls] = useState<CallLog[]>([]);
  const [agentList, setAgentList] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [endingCall, setEndingCall] = useState<number | null>(null);
  const [showOutbound, setShowOutbound] = useState(false);
  const closeOutboundModal = useCallback(() => setShowOutbound(false), []);
  const outboundModalRef = useModalFocusTrap(showOutbound, closeOutboundModal);
  const [outboundTo, setOutboundTo] = useState('');
  const [outboundAgentId, setOutboundAgentId] = useState('');
  const [calling, setCalling] = useState(false);
  const [liveTranscripts, setLiveTranscripts] = useState<Record<number, { sender: string; message: string; timestamp: number }[]>>({});
  const [expandedCall, setExpandedCall] = useState<number | null>(null);
  const [trendData, setTrendData] = useState<TrendDataPoint[]>([]);
  const [analyticsSummary, setAnalyticsSummary] = useState<AnalyticsSummary | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const loadingRef = useRef(false);

  const particleNodes = useMemo(() => activeCalls.map((call, i) => ({
    id: String(call.id),
    position: [
      Math.cos((i / Math.max(activeCalls.length, 1)) * Math.PI * 2) * 2,
      Math.sin((i / Math.max(activeCalls.length, 1)) * Math.PI * 2) * 1.2,
      (Math.sin(i * 1.7) * 0.5) * 1.5,
    ] as [number, number, number],
    color: call.direction === 'inbound' ? '#3b82f6' : '#22c55e',
    pulse: true,
  })), [activeCalls]);

  // Build 7-day chart from real trend data
  const callChartData = trendData.length ? trendData.map(d => d.calls) : [0, 0, 0, 0, 0, 0, 0];
  const chartLabels = trendData.length
    ? trendData.map(d => {
        const date = new Date(d.date);
        return date.toLocaleDateString('en-US', { weekday: 'short' });
      })
    : ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  const loadData = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      const [s, r, a, t, an] = await Promise.all([
        dashboard.stats(),
        dashboard.recent(8),
        callsApi.active(),
        analytics.trends(7, 'day').catch(() => ({ data: [] })),
        analytics.summary(7).catch(() => null),
      ]);
      setStats(s);
      setRecentCalls(r.recent_calls);
      setActiveCalls(a.active_calls);
      setTrendData(t.data);
      if (an) setAnalyticsSummary(an);
    } catch (err) {
      apiError(err, 'Failed to load dashboard data');
    } finally {
      setLoading(false);
      loadingRef.current = false;
    }
  }, []);

  useEffect(() => {
    loadData();
    let interval = setInterval(loadData, 30000);

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        loadData();
        clearInterval(interval);
        interval = setInterval(loadData, 30000);
      } else {
        clearInterval(interval);
      }
    };

    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [loadData]);

  // Live transcript WebSocket with reconnection
  useEffect(() => {
    const initialToken = getToken();
    if (!initialToken) return;
    let ws: WebSocket | null = null;
    let reconnectAttempt = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
    let unmounted = false;

    async function connect() {
      if (unmounted) return;
      const token = await getValidToken();
      if (!token) {
        if (typeof window !== 'undefined') {
          window.location.href = '/login';
        }
        return;
      }
      ws = live.createWebSocket(token);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttempt = 0;
        heartbeatTimer = setInterval(() => {
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 30000);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'transcript') {
            // Find the active call matching this conversation_id
            setActiveCalls((prev) => {
              const call = prev.find((c) => c.conversation_id === msg.conversation_id);
              if (call) {
                setLiveTranscripts((lt) => ({
                  ...lt,
                  [call.id]: [...(lt[call.id] || []), {
                    sender: msg.sender,
                    message: msg.message,
                    timestamp: msg.timestamp || Date.now() / 1000,
                  }].slice(-50),
                }));
              }
              return prev;
            });
          } else if (msg.type === 'call_started' || msg.type === 'call_ended') {
            // Refresh active calls on lifecycle events
            loadData();
          }
        } catch {
          // Ignore malformed messages
        }
      };

      ws.onerror = () => {
        // Error handled by onclose reconnection logic
      };

      ws.onclose = (event) => {
        if (heartbeatTimer) {
          clearInterval(heartbeatTimer);
          heartbeatTimer = null;
        }
        if (unmounted) return;
        // 4001 = Unauthorized; refresh token before reconnecting
        if (event.code === 4001) {
          reconnectAttempt = 0;
        }
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempt), 30000);
        reconnectAttempt++;
        reconnectTimer = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      unmounted = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      ws?.close();
      wsRef.current = null;
    };
  }, [loadData]);

  const handleEndCall = async (call: CallLog) => {
    setEndingCall(call.id);
    try {
      await callsApi.end(call.id);
      await loadData();
    } catch (err) {
      apiError(err, 'Failed to end call');
    } finally {
      setEndingCall(null);
    }
  };

  const openOutboundModal = async () => {
    setShowOutbound(true);
    try {
      const data = await agentsApi.list();
      setAgentList(data.agents);
    } catch (err) {
      apiError(err, 'Failed to load agents');
    }
  };

  const makeOutboundCall = async () => {
    if (!outboundTo) return;
    setCalling(true);
    try {
      const data = await twilio.makeCall({
        to_phone: outboundTo,
        agent_id: outboundAgentId ? parseInt(outboundAgentId) : undefined,
      });
      success('Call Initiated', data.message);
      setShowOutbound(false);
      setOutboundTo('');
      setOutboundAgentId('');
      await loadData();
    } catch (err: unknown) {
      apiError(err, 'Failed to make call');
    } finally {
      setCalling(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="page-title dash-title-gradient dash-title-glow">Dashboard</h1>
            <p className="page-subtitle">Overview of your voice agent platform</p>
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="dash-skeleton p-5 h-28" />
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="dash-skeleton p-5 h-40" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div ref={pageRef} className="space-y-8 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between" data-gsap="header">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Dashboard</h1>
          <p className="page-subtitle">Overview of your voice agent platform</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadData}
            className="btn-secondary"
            title="Refresh data"
          >
            <RefreshCw size={15} />
          </button>
          <button
            onClick={openOutboundModal}
            className="btn-primary bg-green-600 hover:bg-green-500 active:bg-green-700 shimmer-sweep"
          >
            <PhoneOutgoing size={15} />
            Make Call
          </button>
        </div>
      </div>

      {/* Getting Started Card */}
      <GettingStartedCard />

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 animate-stagger">
        <StatCard
          label="Total Calls"
          value={stats?.total_calls ?? 0}
          numericValue={stats?.total_calls ?? 0}
          sub={`${stats?.calls_today ?? 0} today`}
          icon={PhoneCall}
          color="bg-blue-500/20 text-blue-400"
        />
        <StatCard
          label="Active Now"
          value={stats?.active_calls ?? 0}
          numericValue={stats?.active_calls ?? 0}
          sub={activeCalls.length > 0 ? `${activeCalls.length} live` : 'No active calls'}
          icon={Activity}
          color="bg-green-500/20 text-green-400"
        />
        <StatCard
          label="Avg Duration"
          value={formatDuration(stats?.avg_duration_secs ?? 0)}
          sub={`${(stats?.total_duration_mins ?? 0).toFixed(1)} mins total`}
          icon={Clock}
          color="bg-purple-500/20 text-purple-400"
        />
        <StatCard
          label="Success Rate"
          value={`${stats?.success_rate ?? 0}%`}
          numericValue={stats?.success_rate ?? 0}
          sub={`${stats?.completed_calls ?? 0} of ${stats?.total_calls ?? 0} completed`}
          icon={TrendingUp}
          color="bg-emerald-500/20 text-emerald-400"
        />
      </div>

      {/* Analytics Insights */}
      {analyticsSummary && analyticsSummary.total_calls > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4" data-gsap="card">
          <div className="dash-card p-5" data-gsap="content">
            <div className="flex items-center justify-between mb-3">
              <p className="text-[13px] font-medium text-[var(--text-muted)]">Sentiment</p>
              <Smile size={15} className="text-[var(--text-muted)]" />
            </div>
            <MiniDonutChart
              data={[
                analyticsSummary.sentiment_distribution?.positive || 0,
                analyticsSummary.sentiment_distribution?.negative || 0,
                analyticsSummary.sentiment_distribution?.neutral || 0,
                analyticsSummary.sentiment_distribution?.mixed || 0,
                analyticsSummary.sentiment_distribution?.unknown || 0,
              ]}
              labels={['Positive', 'Negative', 'Neutral', 'Mixed', 'Unknown']}
              colors={['#22c55e', '#ef4444', '#6b7280', '#f59e0b', '#3b82f6']}
            />
          </div>
          <div className="dash-card p-5">
            <div className="flex items-center justify-between mb-3">
              <p className="text-[13px] font-medium text-[var(--text-muted)]">Top Topics</p>
              <Tag size={15} className="text-[var(--text-muted)]" />
            </div>
            <div className="space-y-2">
              {analyticsSummary.top_topics.slice(0, 5).map((t, i) => (
                <div key={i} className="flex items-center justify-between">
                  <span className="text-xs text-[var(--text-secondary)] truncate max-w-[70%]">{t.topic}</span>
                  <div className="flex items-center gap-2 flex-1 justify-end">
                    <div className="h-1.5 bg-brand-500/20 rounded-full w-16">
                      <div
                        className="h-1.5 bg-brand-400 rounded-full"
                        style={{ width: `${Math.min((t.count / (analyticsSummary.top_topics[0]?.count || 1)) * 100, 100)}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-[var(--text-muted)] w-4 text-right">{t.count}</span>
                  </div>
                </div>
              ))}
              {analyticsSummary.top_topics.length === 0 && (
                <p className="text-xs text-[var(--text-muted)]">No topics analyzed yet</p>
              )}
            </div>
          </div>
          <div className="dash-card p-5">
            <div className="flex items-center justify-between mb-3">
              <p className="text-[13px] font-medium text-[var(--text-muted)]">Outcomes</p>
              <BarChart3 size={15} className="text-[var(--text-muted)]" />
            </div>
            <div className="space-y-2">
              {Object.entries(analyticsSummary.outcome_distribution || {}).filter(([,v]) => v > 0).map(([key, val]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-xs text-[var(--text-secondary)] capitalize">{key}</span>
                  <span className="text-xs font-medium">{val}</span>
                </div>
              ))}
              <div className="pt-2 border-t border-[var(--glass-border)]">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-[var(--text-muted)]">Avg Sentiment Score</span>
                  <span className="text-sm font-semibold">
                    {analyticsSummary.avg_sentiment_score !== null
                      ? analyticsSummary.avg_sentiment_score.toFixed(2)
                      : '—'}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-gsap="card">
        <div className="dash-card p-5 flex flex-col dash-card-hover" data-gsap="content">
          <div className="mb-4">
            <h3 className="text-xl font-semibold">{stats?.calls_today || 0} calls</h3>
            <p className="text-xs text-[var(--text-muted)]">Today vs. Yesterday</p>
          </div>
          <div className="flex-1 min-h-[150px] three-canvas-container">
            {quality !== 'off' && (
              <Bar3DChart data={callChartData.map((v, i) => ({ label: chartLabels[i] || `Day ${i+1}`, value: v }))} height={160} />
            )}
          </div>
          {quality === 'off' && (
            <div className="flex-1 min-h-[150px]">
              <MiniBarChart data={callChartData} labels={chartLabels} label="Calls (Last 7 Days)" />
            </div>
          )}
        </div>
        {/* Quick Actions — replaces redundant Quick Stats */}
        <div className="dash-card p-5 dash-card-hover" data-gsap="content">
          <div className="flex items-center justify-between mb-4">
            <p className="text-[13px] font-medium text-[var(--text-muted)]">Quick Actions</p>
            <Zap size={15} className="text-[var(--text-muted)]" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Link
              href="/dashboard/agents"
              className="dash-quick-action group"
            >
              <Bot size={16} className="text-brand-400 mb-1.5 group-hover:scale-110 transition-transform" />
              <p className="text-xs font-medium">Create Agent</p>
              <p className="text-[10px] text-[var(--text-muted)] mt-0.5">New voice AI agent</p>
            </Link>
            <Link
              href="/dashboard/templates"
              className="dash-quick-action group"
            >
              <GitBranch size={16} className="text-purple-400 mb-1.5 group-hover:scale-110 transition-transform" />
              <p className="text-xs font-medium">Browse Templates</p>
              <p className="text-[10px] text-[var(--text-muted)] mt-0.5">Ready-made agents</p>
            </Link>
            <Link
              href="/dashboard/analytics"
              className="dash-quick-action group"
            >
              <BarChart3 size={16} className="text-emerald-400 mb-1.5 group-hover:scale-110 transition-transform" />
              <p className="text-xs font-medium">Analytics</p>
              <p className="text-[10px] text-[var(--text-muted)] mt-0.5">Call insights</p>
            </Link>
            <button
              onClick={openOutboundModal}
              className="dash-quick-action group text-left w-full"
            >
              <PhoneOutgoing size={16} className="text-green-400 mb-1.5 group-hover:scale-110 transition-transform" />
              <p className="text-xs font-medium">Make Call</p>
              <p className="text-[10px] text-[var(--text-muted)] mt-0.5">Outbound dial</p>
            </button>
          </div>
        </div>
      </div>

      {/* Active Calls — always visible so users know the feature exists */}
      <div data-gsap="card">
        <h2 className="text-lg font-semibold mb-3 flex items-center gap-2" data-gsap="content">
          <span className={`dash-live-dot ${activeCalls.length > 0 ? '' : 'opacity-30'}`} />
          Live Calls ({activeCalls.length})
        </h2>
        {activeCalls.length === 0 ? (
          <EmptyState
            icon={Activity}
            title="No active calls"
            description="Live transcripts appear here during calls. Start a call from the Playground to see it in action."
          />
        ) : (
          <>
            {/* 3D Particle Network for live calls */}
            <div className="three-canvas-container mb-4" style={{ height: 250 }}>
              <ParticleNetwork
                nodes={particleNodes}
                connections={activeCalls.length > 1
                  ? activeCalls.slice(0, -1).map((_, i) => ({ from: i, to: i + 1 }))
                  : []}
                height={250}
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {activeCalls.map(call => {
              const transcripts = liveTranscripts[call.id] || [];
              const isExpanded = expandedCall === call.id;
              return (
                <div
                  key={call.id}
                  className="dash-card p-4" style={{ borderColor: 'rgba(34, 197, 94, 0.15)' }}
                >
                  <div className="flex items-center gap-4">
                    <div className="p-2 bg-green-500/20 rounded-lg text-green-400">
                      <Activity size={18} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm">{formatPhone(call.from_phone)}</p>
                      <p className="text-xs text-[var(--text-muted)]">
                        Agent: {call.agent_name || `#${call.agent_id}`} &middot; {formatTimestamp(call.started_at)}
                      </p>
                    </div>
                    <StatusBadge status={call.status} />
                    {transcripts.length > 0 && (
                      <button
                        onClick={() => setExpandedCall(isExpanded ? null : call.id)}
                        className="p-2 text-brand-400 hover:bg-brand-500/10 rounded-lg transition-colors"
                        title="Toggle transcript"
                      >
                        <MessageSquare size={16} />
                        <span className="text-[10px] ml-1">{transcripts.length}</span>
                      </button>
                    )}
                    <button
                      onClick={() => handleEndCall(call)}
                      disabled={endingCall === call.id}
                      className="p-2 text-red-400 hover:bg-red-500/20 rounded-lg transition-colors disabled:opacity-50"
                      title="End call"
                    >
                      {endingCall === call.id ? <Loader2 size={16} className="animate-spin" /> : <PhoneOff size={16} />}
                    </button>
                  </div>

                  {/* Live Transcript */}
                  {isExpanded && transcripts.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-green-500/10 space-y-2 max-h-48 overflow-y-auto">
                      {transcripts.slice(-10).map((t, i) => (
                        <div key={i} className={`flex gap-2 text-xs ${t.sender === 'human' ? 'flex-row-reverse' : ''}`}>
                          <div className={`w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 ${
                            t.sender === 'bot' ? 'bg-brand-600/20 text-brand-400' : 'bg-green-600/20 text-green-400'
                          }`}>
                            {t.sender === 'bot' ? <Bot size={10} /> : <User size={10} />}
                          </div>
                          <div className={`max-w-[80%] px-2.5 py-1.5 rounded-lg ${
                            t.sender === 'bot'
                              ? 'bg-[var(--bg-tertiary)] rounded-tl-sm'
                              : 'bg-brand-600/20 text-brand-200 rounded-tr-sm'
                          }`}>
                            {t.message}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            </div>
          </>
        )}
      </div>

      {/* Recent Calls */}
      <div data-gsap="card">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold">Recent Calls</h2>
          <Link
            href="/dashboard/calls"
            className="text-sm text-brand-400 hover:text-brand-300 flex items-center gap-1 transition-colors"
          >
            View All <ArrowRight size={14} />
          </Link>
        </div>
        <div className="dash-table overflow-x-auto">
          {recentCalls.length === 0 ? (
            <EmptyState
              icon={PhoneCall}
              title="No calls yet"
              description="Configure an agent and make your first call. Calls will appear here once they start."
            />
          ) : (
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--glass-border)]">
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">Direction</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">From</th>
                  <th className="hidden md:table-cell text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">To</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">Agent</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">Status</th>
                  <th className="hidden md:table-cell text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">Duration</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">Time</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--glass-border)]">
                {recentCalls.map(call => (
                  <tr key={call.id} className="hover:bg-brand-500/[0.04] transition-colors">
                    <td className="px-4 py-3">
                      {call.direction === 'inbound' ? (
                        <PhoneIncoming size={16} className="text-blue-400" />
                      ) : (
                        <PhoneOutgoing size={16} className="text-green-400" />
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm">{formatPhone(call.from_phone)}</td>
                    <td className="hidden md:table-cell px-4 py-3 text-sm">{formatPhone(call.to_phone)}</td>
                    <td className="px-4 py-3 text-sm text-[var(--text-secondary)]">
                      {call.agent_name || (call.agent_id ? `Agent #${call.agent_id}` : '—')}
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={call.status} /></td>
                    <td className="hidden md:table-cell px-4 py-3 text-sm text-[var(--text-secondary)]">{formatDuration(call.duration_secs)}</td>
                    <td className="px-4 py-3 text-sm text-[var(--text-muted)]" title={formatTimestamp(call.started_at)}>
                      {timeAgo(call.started_at)}
                    </td>
                    <td className="px-4 py-3">
                      {['active', 'ringing', 'initiated'].includes(call.status) && (
                        <button
                          onClick={() => handleEndCall(call)}
                          disabled={endingCall === call.id}
                          className="p-1.5 text-red-400 hover:bg-red-500/20 rounded-lg transition-colors disabled:opacity-50"
                          title="End call"
                        >
                          {endingCall === call.id ? (
                            <Loader2 size={14} className="animate-spin" />
                          ) : (
                            <PhoneOff size={14} />
                          )}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Outbound Call Modal */}
      {showOutbound && (
        <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm z-50 flex items-center justify-center animate-fade-in" onClick={closeOutboundModal}>
          <div
            ref={outboundModalRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="outbound-modal-title"
            tabIndex={-1}
            className="dash-modal w-full max-w-md mx-4 animate-scale-in"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--glass-border)]">
              <h2 id="outbound-modal-title" className="text-lg font-semibold tracking-tight">Make Outbound Call</h2>
              <button onClick={closeOutboundModal} className="btn-ghost p-1.5">
                <X size={18} />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-[13px] font-medium text-[var(--text-secondary)] mb-1.5">Phone Number</label>
                <input
                  type="text"
                  value={outboundTo}
                  onChange={e => setOutboundTo(e.target.value)}
                  placeholder="+1XXXXXXXXXX"
                  className={`input-base font-mono ${outboundTo && !/^\+[1-9]\d{1,14}$/.test(outboundTo) ? 'border-red-500/50 focus:border-red-500' : ''}`}
                />
                {outboundTo && !/^\+[1-9]\d{1,14}$/.test(outboundTo) && (
                  <p className="text-[11px] text-red-400 mt-1">Must be E.164 format (e.g. +12025551234)</p>
                )}
              </div>
              <div>
                <label className="block text-[13px] font-medium text-[var(--text-secondary)] mb-1.5">Agent</label>
                <select
                  value={outboundAgentId}
                  onChange={e => setOutboundAgentId(e.target.value)}
                  className="input-base"
                >
                  <option value="">Default agent</option>
                  {agentList.map(a => (
                    <option key={a.id} value={String(a.id)}>
                      {a.name} {a.is_active ? '(active)' : ''}
                    </option>
                  ))}
                </select>
              </div>
              <button
                onClick={makeOutboundCall}
                disabled={calling || !outboundTo || !/^\+[1-9]\d{1,14}$/.test(outboundTo)}
                className="w-full btn-primary bg-green-600 hover:bg-green-500 active:bg-green-700"
              >
                {calling ? <Loader2 size={15} className="animate-spin" /> : <PhoneOutgoing size={15} />}
                {calling ? 'Calling...' : 'Start Call'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
