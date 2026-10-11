'use client';

import { useEffect, useState, useCallback } from 'react';
import { calls as callsApi, agents as agentsApi, twilio, analytics as analyticsApi } from '@/lib/api';
import { usePageTitle } from '@/hooks/usePageTitle';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';
import { CallLog, Transcript, Agent, CallAnalysis, ActionLog } from '@/lib/types';
import { formatDuration, formatPhone, timeAgo, cn } from '@/lib/utils';
import { useToast } from '@/components/ui/toast';
import { EmptyState } from '@/components/ui/empty-state';
import StatusBadge from '@/components/ui/status-badge';
import { SkeletonTable, SkeletonStats } from '@/components/ui/skeleton';
import { List } from 'react-window';
import {
  PhoneCall,
  PhoneIncoming,
  PhoneOutgoing,
  X,
  ChevronLeft,
  ChevronRight,
  User,
  Bot,
  PhoneOff,
  RefreshCw,
  Loader2,
  Volume2,
  Sparkles,
  Smile,
  Frown,
  Meh,
  Tag,
  CheckSquare,
  BarChart3,
  Star,
  HardDrive,
  BookOpen,
  Calendar,
  Wrench,
  ExternalLink,
  FileText,
} from 'lucide-react';
import LiveCallsTab from './_components/LiveCallsTab';

/* FE-08: Virtual row renderer for transcript messages */
interface MessageRowData {
  messages: Transcript[];
}

function MessageRow({ index, style, messages }: MessageRowData & { index: number; style: React.CSSProperties }) {
  const t = messages[index];
  if (!t) return null;
  return (
    <div style={{ ...style, paddingBottom: 12 }} className="flex gap-3 items-start">
      <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
        t.sender === 'bot'
          ? 'bg-brand-600/20 text-brand-400'
          : 'bg-green-600/20 text-green-400'
      }`}>
        {t.sender === 'bot' ? <Bot size={14} /> : <User size={14} />}
      </div>
      <div className={`max-w-[80%] px-3.5 py-2.5 rounded-2xl text-sm ${
        t.sender === 'bot'
          ? 'bg-[var(--bg-tertiary)] rounded-tl-sm'
          : 'bg-brand-600/20 text-brand-200 rounded-tr-sm'
      }`}>
        {t.message}
      </div>
    </div>
  );
}

export default function CallsPage() {
  usePageTitle('Calls');
  const { success, apiError } = useToast();
  const [callList, setCallList] = useState<CallLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [statusFilter, setStatusFilter] = useState('');
  const [selectedCall, setSelectedCall] = useState<CallLog | null>(null);
  const [transcript, setTranscript] = useState<Transcript[]>([]);
  const [loadingTranscript, setLoadingTranscript] = useState(false);
  const [recordingUrl, setRecordingUrl] = useState<string | null>(null);
  const [loadingRecording, setLoadingRecording] = useState(false);
  const [analysis, setAnalysis] = useState<CallAnalysis | null>(null);
  const [loadingAnalysis, setLoadingAnalysis] = useState(false);
  const [actions, setActions] = useState<ActionLog[]>([]);
  const [showOutbound, setShowOutbound] = useState(false);
  const [agentList, setAgentList] = useState<Agent[]>([]);
  const [outboundTo, setOutboundTo] = useState('');
  const [outboundAgentId, setOutboundAgentId] = useState('');
  const [calling, setCalling] = useState(false);
  const [activeTab, setActiveTab] = useState<'history' | 'live'>('history');

  const loadCalls = useCallback(async () => {
    try {
      const params: { page: number; per_page: number; status?: string } = {
        page,
        per_page: 20,
      };
      if (statusFilter) params.status = statusFilter;
      const data = await callsApi.list(params);
      setCallList(data.calls);
      setTotalPages(data.pages);
    } catch (err) {
      apiError(err, 'Failed to load calls');
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter]);

  // Visibility-aware polling: run every 15s, pause when tab is hidden.
  // This avoids hammering the API while the user is on another tab and
  // ensures the list is fresh the moment they switch back.
  useEffect(() => {
    setLoading(true);
    loadCalls();

    let interval: ReturnType<typeof setInterval> | null = setInterval(loadCalls, 15000);

    const onVisibilityChange = () => {
      if (document.hidden) {
        // Tab hidden — stop polling
        if (interval) { clearInterval(interval); interval = null; }
      } else {
        // Tab visible — refresh immediately then restart polling
        loadCalls();
        if (!interval) interval = setInterval(loadCalls, 15000);
      }
    };

    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      if (interval) clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [loadCalls]);

  // Sync selectedCall with callList so the drawer reflects live status
  // changes (e.g., initiated → completed) without requiring a re-click.
  useEffect(() => {
    if (selectedCall) {
      const updated = callList.find(c => c.id === selectedCall.id);
      if (updated) {
        setSelectedCall(prev => prev ? {
          ...prev,
          status: updated.status,
          ended_at: updated.ended_at,
          duration_secs: updated.duration_secs,
          recording_url: updated.recording_url,
          quality_score: updated.quality_score,
          analysis_json: updated.analysis_json,
        } : null);
      }
    }
  }, [callList]);

  const openTranscript = async (call: CallLog) => {
    setSelectedCall(call);
    setLoadingTranscript(true);
    setLoadingRecording(true);
    setLoadingAnalysis(true);
    setRecordingUrl(null);
    setAnalysis(null);
    try {
      const [data, recData, analysisData] = await Promise.all([
        callsApi.get(call.id),
        call.status === 'completed' ? callsApi.recording(call.id).catch(() => null) : Promise.resolve(null),
        call.status === 'completed' ? analyticsApi.getAnalysis(call.id).catch(() => null) : Promise.resolve(null),
      ]);
      setTranscript(data.transcript);
      setActions(data.actions || []);
      if (recData?.recording_url) {
        setRecordingUrl(recData.recording_url);
      }
      if (analysisData?.analysis) {
        setAnalysis(analysisData.analysis);
      }
    } catch (err) {
      apiError(err, 'Failed to load transcript');
    } finally {
      setLoadingTranscript(false);
      setLoadingRecording(false);
      setLoadingAnalysis(false);
    }
  };

  const runAnalysis = async () => {
    if (!selectedCall) return;
    setLoadingAnalysis(true);
    try {
      const data = await analyticsApi.analyze(selectedCall.id);
      setAnalysis(data.analysis);
      success('Analysis Complete', 'Call analyzed successfully');
    } catch (err) {
      apiError(err, 'Failed to analyze call');
    } finally {
      setLoadingAnalysis(false);
    }
  };

  const reanalyzeCall = async () => {
    if (!selectedCall) return;
    setLoadingAnalysis(true);
    try {
      const data = await analyticsApi.reanalyze(selectedCall.id);
      setAnalysis(data.analysis);
      success('Re-analysis Complete', `Re-analyzed using ${data.provider}`);
    } catch (err) {
      apiError(err, 'Failed to re-analyze call');
    } finally {
      setLoadingAnalysis(false);
    }
  };

  const sentimentColor = (sentiment?: string) => {
    switch (sentiment) {
      case 'positive': return 'text-green-400 bg-green-500/10 border-green-500/20';
      case 'negative': return 'text-red-400 bg-red-500/10 border-red-500/20';
      case 'mixed': return 'text-amber-400 bg-amber-500/10 border-amber-500/20';
      default: return 'text-[var(--text-muted)] bg-[var(--bg-tertiary)] border-[var(--glass-border)]';
    }
  };

  const SentimentIcon = ({ sentiment }: { sentiment?: string }) => {
    if (sentiment === 'positive') return <Smile size={14} />;
    if (sentiment === 'negative') return <Frown size={14} />;
    return <Meh size={14} />;
  };

  const scoreColor = (score?: number | null) => {
    if (score === null || score === undefined) return 'text-[var(--text-muted)]';
    if (score >= 80) return 'text-green-400';
    if (score >= 60) return 'text-brand-400';
    if (score >= 40) return 'text-amber-400';
    return 'text-red-400';
  };

  const runScoreQuality = async () => {
    if (!selectedCall) return;
    setLoadingAnalysis(true);
    try {
      const data = await analyticsApi.scoreQuality(selectedCall.id);
      // Update selected call with new quality score
      setSelectedCall({ ...selectedCall, quality_score: data.quality_score, review_flag: data.review_flag, review_reason: data.review_reason });
      success('Quality Scored', `Score: ${data.quality_score}`);
    } catch (err) {
      apiError(err, 'Failed to score quality');
    } finally {
      setLoadingAnalysis(false);
    }
  };

  const endCall = async (call: CallLog) => {
    try {
      await callsApi.end(call.id);
      await loadCalls();
    } catch (err) {
      apiError(err, 'Failed to end call');
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
      await loadCalls();
    } catch (err: unknown) {
      apiError(err, 'Failed to make call');
    } finally {
      setCalling(false);
    }
  };

  return (
    <GsapPageWrapper>
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Calls</h1>
          <p className="page-subtitle">View call history and monitor live calls</p>
        </div>
        <div className={cn('flex items-center gap-2', activeTab === 'live' && 'hidden')}>
          <select
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
            className="input-base"
          >
            <option value="">All Status</option>
            <option value="active">Active</option>
            <option value="ringing">Ringing</option>
            <option value="initiated">Initiated</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
          </select>
          <button
            onClick={() => loadCalls()}
            className="p-2 text-[var(--text-secondary)] hover:text-white bg-[var(--bg-card)] border border-[var(--glass-border)] rounded-lg transition-colors"
            title="Refresh"
            aria-label="Refresh call list"
          >
            <RefreshCw size={16} />
          </button>
          <button
            onClick={openOutboundModal}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded-lg text-sm font-medium transition-colors"
          >
            <PhoneOutgoing size={16} />
            Make Call
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[var(--glass-border)]">
        <button
          onClick={() => setActiveTab('history')}
          className={cn(
            'px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
            activeTab === 'history'
              ? 'border-brand-400 text-brand-400'
              : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
          )}
        >
          History
        </button>
        <button
          onClick={() => setActiveTab('live')}
          className={cn(
            'px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
            activeTab === 'live'
              ? 'border-brand-400 text-brand-400'
              : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
          )}
        >
          Live
        </button>
      </div>

      {/* Live tab content */}
      {activeTab === 'live' && <LiveCallsTab />}

      {/* Calls Table (history tab only) */}
      {activeTab === 'history' && <div className="dash-table overflow-x-auto">
        {loading ? (
          <div className="p-5 space-y-3">
            <SkeletonStats count={3} />
            <SkeletonTable rows={5} cols={10} />
          </div>
        ) : callList.length === 0 ? (
          <EmptyState
            icon={PhoneCall}
            title="No calls yet"
            description="Calls will appear here as they happen. Start a test call from the Playground or wait for inbound calls."
          />
        ) : (
          <>
            <table className="w-full">
              <thead>
                <tr className="border-b border-[var(--glass-border)]">
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">Type</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">From</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">To</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">Agent</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">Status</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">Sentiment</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">Quality</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">Duration</th>
                  <th className="text-left text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-4 py-3">When</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-color)]">
                {callList.map(call => {
                  let sentiment: string | undefined;
                  if (call.analysis_json) {
                    try { sentiment = JSON.parse(call.analysis_json)?.sentiment; } catch { sentiment = undefined; }
                  }
                  return (
                  <tr
                    key={call.id}
                    className="hover:bg-[var(--bg-tertiary)] transition-colors cursor-pointer"
                    onClick={() => openTranscript(call)}
                  >
                    <td className="px-4 py-3">
                      {call.direction === 'inbound' ? (
                        <PhoneIncoming size={16} className="text-blue-400" />
                      ) : (
                        <PhoneOutgoing size={16} className="text-green-400" />
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm font-mono">{formatPhone(call.from_phone)}</td>
                    <td className="px-4 py-3 text-sm font-mono">{formatPhone(call.to_phone)}</td>
                    <td className="px-4 py-3 text-sm text-[var(--text-secondary)]">
                      {call.agent_name || (call.agent_id ? `Agent #${call.agent_id}` : '—')}
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={call.status} /></td>
                    <td className="px-4 py-3">
                      {sentiment ? (
                        <span className={cn('inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border', sentimentColor(sentiment))}>
                          <SentimentIcon sentiment={sentiment} />
                          {sentiment}
                        </span>
                      ) : (
                        <span className="text-xs text-[var(--text-muted)]">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {call.quality_score !== null && call.quality_score !== undefined ? (
                        <span className={cn('text-xs font-bold', scoreColor(call.quality_score))}>
                          {call.quality_score}
                        </span>
                      ) : (
                        <span className="text-xs text-[var(--text-muted)]">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-[var(--text-secondary)]">{formatDuration(call.duration_secs)}</td>
                    <td className="px-4 py-3 text-sm text-[var(--text-muted)]">{timeAgo(call.started_at)}</td>
                    <td className="px-4 py-3">
                      {['active', 'ringing', 'initiated'].includes(call.status) && (
                        <button
                          onClick={e => { e.stopPropagation(); endCall(call); }}
                          className="p-1.5 text-red-400 hover:bg-red-500/20 rounded-lg transition-colors"
                          title="End call"
                          aria-label="End active call"
                        >
                          <PhoneOff size={14} />
                        </button>
                      )}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--glass-border)]">
                <p className="text-sm text-[var(--text-muted)]">Page {page} of {totalPages}</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={page <= 1}
                    className="p-2 rounded-lg text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] disabled:opacity-30"
                    aria-label="Previous page"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <button
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={page >= totalPages}
                    className="p-2 rounded-lg text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] disabled:opacity-30"
                    aria-label="Next page"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>}

      {/* Transcript Drawer */}
      {selectedCall && (
        <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm z-50 flex justify-end">
          <div className="w-full max-w-lg bg-[var(--bg-secondary)] border-l border-[var(--glass-border)] flex flex-col h-full">
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--glass-border)]">
              <div>
                <h3 className="font-semibold tracking-tight">Call Transcript</h3>
                <p className="text-xs text-[var(--text-muted)] mt-0.5">
                  {formatPhone(selectedCall.from_phone)} → {formatPhone(selectedCall.to_phone)}
                </p>
              </div>
              <button
                onClick={() => { setSelectedCall(null); setTranscript([]); setActions([]); }}
                className="btn-ghost p-1.5"
                aria-label="Close call details"
              >
                <X size={20} />
              </button>
            </div>

            {/* Call Info */}
            <div className="px-5 py-3 border-b border-[var(--glass-border)] flex gap-4 text-xs text-[var(--text-secondary)]">
              <span>{selectedCall.direction}</span>
              <span>•</span>
              <StatusBadge status={selectedCall.status} />
              <span>•</span>
              <span>{formatDuration(selectedCall.duration_secs)}</span>
              <span>•</span>
              <span>{timeAgo(selectedCall.started_at)}</span>
            </div>

            {/* Quality Score */}
            {selectedCall?.status === 'completed' && (
              <div className="px-5 py-3 border-b border-[var(--glass-border)]">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Star size={12} className="text-brand-400" />
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">Quality Score</span>
                  </div>
                  {selectedCall.quality_score !== null && selectedCall.quality_score !== undefined ? (
                    <span className={cn('text-sm font-bold', scoreColor(selectedCall.quality_score))}>
                      {selectedCall.quality_score} / 100
                    </span>
                  ) : (
                    <button
                      onClick={runScoreQuality}
                      disabled={loadingAnalysis}
                      className="flex items-center gap-1.5 text-[10px] px-2 py-1 rounded bg-brand-500/10 text-brand-400 border border-brand-500/20 hover:bg-brand-500/20 transition-colors disabled:opacity-50"
                    >
                      {loadingAnalysis ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
                      Score Quality
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* Analysis Panel */}
            {(loadingAnalysis || analysis) && selectedCall?.status === 'completed' && (
              <div className="px-5 py-3 border-b border-[var(--glass-border)] bg-[var(--bg-tertiary)]">
                {loadingAnalysis ? (
                  <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
                    <Loader2 size={14} className="animate-spin" />
                    Analyzing call...
                  </div>
                ) : analysis ? (
                  <>
                  <div className="space-y-3">
                    {/* Summary */}
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <BarChart3 size={12} className="text-brand-400" />
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">Summary</span>
                      </div>
                      <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{analysis.summary}</p>
                    </div>
                    {/* Sentiment + Resolution */}
                    <div className="flex items-center gap-2">
                      <span className={cn('inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border', sentimentColor(analysis.sentiment))}>
                        <SentimentIcon sentiment={analysis.sentiment} />
                        {analysis.sentiment}
                      </span>
                      {analysis.resolution_status && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--glass-border)]">
                          {analysis.resolution_status}
                        </span>
                      )}
                      {analysis.customer_satisfaction && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--glass-border)]">
                          {analysis.customer_satisfaction}
                        </span>
                      )}
                    </div>
                    {/* Topics */}
                    {analysis.topics && analysis.topics.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {analysis.topics.map(t => (
                          <span key={t} className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--glass-border)]">
                            <Tag size={8} /> {t}
                          </span>
                        ))}
                      </div>
                    )}
                    {/* Action Items */}
                    {analysis.action_items && analysis.action_items.length > 0 && (
                      <div>
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)] flex items-center gap-1">
                          <CheckSquare size={10} /> Action Items
                        </span>
                        <ul className="mt-1 space-y-0.5">
                          {analysis.action_items.map((item, i) => (
                            <li key={i} className="text-[10px] text-[var(--text-secondary)] flex items-start gap-1">
                              <span className="text-brand-400 mt-0.5">•</span> {item}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                  <div className="pt-2 border-t border-[var(--glass-border)]">
                    <button
                      onClick={reanalyzeCall}
                      disabled={loadingAnalysis}
                      className="flex items-center gap-2 text-xs text-brand-400 hover:text-brand-300 transition-colors disabled:opacity-50"
                    >
                      <RefreshCw size={14} className={loadingAnalysis ? 'animate-spin' : ''} />
                      Re-analyze
                    </button>
                  </div>
                  </>
                ) : null}
              </div>
            )}
            {!loadingAnalysis && !analysis && selectedCall?.status === 'completed' && (
              <div className="px-5 py-3 border-b border-[var(--glass-border)]">
                <button
                  onClick={runAnalysis}
                  className="flex items-center gap-2 text-xs text-brand-400 hover:text-brand-300 transition-colors"
                >
                  <Sparkles size={14} />
                  Analyze this call
                </button>
              </div>
            )}

            {/* Resources Accessed During Call */}
            {actions.length > 0 && (
              <div className="px-5 py-3 border-b border-[var(--glass-border)] bg-[var(--bg-tertiary)]">
                <div className="flex items-center gap-2 mb-2">
                  <Wrench size={12} className="text-brand-400" />
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    Resources Accessed ({actions.length})
                  </span>
                </div>
                <div className="space-y-2">
                  {actions.map((action) => {
                    const params = action.params_json ? (() => { try { return JSON.parse(action.params_json); } catch { return {}; } })() : {};
                    const result = action.result_json ? (() => { try { return JSON.parse(action.result_json); } catch { return null; } })() : null;
                    const type = action.action_type;
                    let icon = Wrench;
                    let label = type;
                    let detail = '';
                    let status = 'completed';
                    if (type.includes('drive') || type === 'read_drive_file' || type === 'read_file_content') {
                      icon = HardDrive;
                      label = 'Google Drive';
                      detail = params.file_id || params.file_name || 'File read';
                    } else if (type.includes('calendar') || type === 'book_appointment' || type === 'create_event') {
                      icon = Calendar;
                      label = 'Calendar';
                      detail = params.calendar_id || params.summary || 'Appointment booked';
                    } else if (type.includes('knowledge') || type === 'recall_document' || type === 'search_knowledge') {
                      icon = BookOpen;
                      label = 'Knowledge Base';
                      detail = params.query || params.document_name || 'KB search';
                    } else if (type.includes('email') || type === 'send_email') {
                      icon = FileText;
                      label = 'Email';
                      detail = params.to || params.subject || 'Email sent';
                    } else if (type.includes('transfer')) {
                      icon = PhoneCall;
                      label = 'Transfer';
                      detail = params.destination || params.phone_number || 'Call transfer';
                    }
                    if (result && typeof result === 'object') {
                      if (result.error || result.status === 'error') status = 'error';
                    }
                    const Icon = icon;
                    return (
                      <div key={action.id} className="flex items-start gap-2 text-xs">
                        <Icon size={14} className={`shrink-0 mt-0.5 ${status === 'error' ? 'text-red-400' : 'text-brand-400'}`} />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className="font-medium">{label}</span>
                            {status === 'error' && (
                              <span className="text-[10px] px-1 py-0.5 rounded bg-red-500/10 text-red-400">Failed</span>
                            )}
                          </div>
                          <p className="text-[var(--text-muted)] truncate" title={detail}>{detail}</p>
                          {result && typeof result === 'object' && result.truncated && (
                            <p className="text-[10px] text-amber-400">Preview truncated</p>
                          )}
                        </div>
                        <span className="text-[10px] text-[var(--text-muted)] shrink-0">
                          {new Date(action.timestamp * 1000).toLocaleTimeString()}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Recording Player */}
            {(loadingRecording || recordingUrl) && (
              <div className="px-5 py-3 border-b border-[var(--glass-border)]">
                {loadingRecording ? (
                  <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
                    <Loader2 size={14} className="animate-spin" />
                    Loading recording...
                  </div>
                ) : recordingUrl ? (
                  <div className="flex items-center gap-3">
                    <Volume2 size={16} className="text-brand-400 shrink-0" />
                    <audio
                      controls
                      className="w-full h-8"
                      src={recordingUrl}
                    >
                      Your browser does not support the audio element.
                    </audio>
                  </div>
                ) : null}
              </div>
            )}

            {/* Messages — virtualized for long transcripts (FE-08) */}
            <div className="flex-1 min-h-0 p-5">
              {loadingTranscript ? (
                <div className="text-center text-[var(--text-muted)] py-8">Loading transcript...</div>
              ) : transcript.length === 0 ? (
                <div className="text-center text-[var(--text-muted)] py-8">No transcript available</div>
              ) : (
                <List<{ messages: Transcript[] }>
                  style={{ height: '100%', width: '100%' }}
                  rowComponent={MessageRow}
                  rowProps={{ messages: transcript }}
                  rowCount={transcript.length}
                  rowHeight={80}
                  overscanCount={5}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {/* Outbound Call Modal */}
      {showOutbound && (
        <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm animate-fade-in z-50 flex items-center justify-center">
          <div className="bg-[var(--bg-secondary)] rounded-2xl border border-[var(--glass-border)] w-full max-w-md mx-4 shadow-modal animate-scale-in">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--glass-border)]">
              <h2 className="text-lg font-semibold tracking-tight">Make Outbound Call</h2>
              <button onClick={() => setShowOutbound(false)} className="btn-ghost p-1.5" aria-label="Close outbound call modal">
                <X size={20} />
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
                  className="w-full input-base"
                />
              </div>
              <div>
                <label className="block text-[13px] font-medium text-[var(--text-secondary)] mb-1.5">Agent</label>
                <select
                  value={outboundAgentId}
                  onChange={e => setOutboundAgentId(e.target.value)}
                  className="w-full input-base"
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
                disabled={calling || !outboundTo}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
              >
                {calling ? <Loader2 size={16} className="animate-spin" /> : <PhoneOutgoing size={16} />}
                {calling ? 'Calling...' : 'Start Call'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </GsapPageWrapper>
  );
}
