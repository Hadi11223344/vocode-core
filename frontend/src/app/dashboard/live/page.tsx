'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { getToken, live, getValidToken } from '@/lib/api';
import { useGsapPageEnter } from '@/hooks/use-gsap-animations';
import { ActionLog, LiveCallData, LiveStats } from '@/lib/types';
import { formatDuration, formatPhone, timeAgo } from '@/lib/utils';
import {
  Radio,
  PhoneCall,
  Clock,
  Users,
  Activity,
  MessageSquare,
  Volume2,
  Loader2,
  RefreshCw,
  Wifi,
  WifiOff,
  Bot,
  User,
  TrendingUp,
} from 'lucide-react';

const VoiceOrb = dynamic(() => import('@/components/three/voice-orb'), { ssr: false });

export default function LiveCallsPage() {
  const pageRef = useRef<HTMLDivElement>(null);
  useGsapPageEnter(pageRef);
  const [activeCalls, setActiveCalls] = useState<LiveCallData[]>([]);
  const [stats, setStats] = useState<LiveStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);
  const [selectedCallId, setSelectedCallId] = useState<number | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const formatToolLabel = (actionType: string) =>
    actionType.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase()).trim();

  const parseJsonField = (value: string | null) => {
    if (!value) return null;
    try {
      return JSON.parse(value);
    } catch {
      return value;
    }
  };

  const loadData = useCallback(async () => {
    try {
      const [callsData, statsData] = await Promise.all([
        live.active(),
        live.stats(),
      ]);
      setActiveCalls(callsData.active_calls);
      setStats(statsData);
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        setConnected(true);
      }
    } catch {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        setConnected(false);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const applyLiveEvent = useCallback((event: {
    type: string;
    conversation_id?: string;
    sender?: string;
    message?: string;
    timestamp?: number;
    id?: number;
    call_log_id?: number;
    action_type?: string;
    params_json?: string | null;
    result_json?: string | null;
  }) => {
    if (!event || typeof event.type !== 'string') return;

    if (event.type === 'transcript') {
      setActiveCalls(prev => prev.map(call => {
        if (call.conversation_id !== event.conversation_id) return call;

        const nextMessages = [
          ...call.recent_messages,
          {
            id: Date.now(),
            call_log_id: call.id,
            sender: (event.sender || 'system') as 'human' | 'bot' | 'action' | 'system',
            message: event.message || '',
            timestamp: typeof event.timestamp === 'number' ? event.timestamp : Math.floor(Date.now() / 1000),
          },
        ].slice(-20);

        return {
          ...call,
          recent_messages: nextMessages,
          message_count: nextMessages.length,
        };
      }));
      return;
    }

    if (event.type === 'action') {
      setActiveCalls(prev => prev.map(call => {
        if (call.conversation_id !== event.conversation_id) return call;

        const nextActions = [
          ...(call.recent_actions || []),
          {
            id: typeof event.id === 'number' ? event.id : Date.now(),
            call_log_id: event.call_log_id ?? call.id,
            action_type: event.action_type || 'unknown',
            params_json: event.params_json ?? null,
            result_json: event.result_json ?? null,
            timestamp: typeof event.timestamp === 'number' ? event.timestamp : Math.floor(Date.now() / 1000),
          },
        ].slice(-10);

        return {
          ...call,
          recent_actions: nextActions,
        };
      }));
      return;
    }

    if (event.type === 'call_started' || event.type === 'call_ended') {
      loadData();
      return;
    }

    if (event.type === 'ping' && wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send('ping');
    }
  }, [loadData]);

  // Visibility-aware polling: only poll as fallback when WS is disconnected.
  // When WebSocket is connected, server pushes updates so REST polling is redundant.
  useEffect(() => {
    loadData();
    intervalRef.current = setInterval(() => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        loadData();
      }
    }, 5000);

    const onVisibilityChange = () => {
      if (document.hidden) {
        if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
      } else {
        loadData();
        if (!intervalRef.current) {
          intervalRef.current = setInterval(() => {
            if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
              loadData();
            }
          }, 5000);
        }
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [loadData]);

  useEffect(() => {
    const initialToken = getToken();
    if (!initialToken) return;

    let ws: WebSocket | null = null;
    let reconnectTimer: NodeJS.Timeout | null = null;
    let unmounted = false;

    async function connect() {
      if (unmounted) return;
      const token = await getValidToken();
      if (!token) return;

      ws = live.createWebSocket(token);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
      };

      ws.onmessage = (evt: MessageEvent) => {
        try {
          const data = JSON.parse(evt.data);
          applyLiveEvent(data);
        } catch {
          // Ignore malformed websocket payloads and continue polling fallback.
        }
      };

      ws.onerror = () => {
        setConnected(false);
      };

      ws.onclose = () => {
        if (wsRef.current === ws) {
          wsRef.current = null;
        }
        setConnected(false);
        if (!unmounted) {
          reconnectTimer = setTimeout(connect, 5000);
        }
      };
    }

    connect();

    return () => {
      unmounted = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
      if (wsRef.current === ws) {
        wsRef.current = null;
      }
    };
  }, [applyLiveEvent]);

  useEffect(() => {
    if (selectedCallId == null) return;
    if (!activeCalls.some(c => c.id === selectedCallId)) {
      setSelectedCallId(null);
    }
  }, [activeCalls, selectedCallId]);

  const selectedCall = activeCalls.find(c => c.id === selectedCallId);
  const selectedActions: ActionLog[] = selectedCall?.recent_actions || [];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Loader2 className="animate-spin text-[var(--accent)]" size={32} />
      </div>
    );
  }

  return (
    <div ref={pageRef} className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between" data-gsap="header">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="page-title dash-title-gradient dash-title-glow">Live Dashboard</h1>
            <span className={`badge ${connected ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
              {connected ? <><Wifi size={10} /> Connected</> : <><WifiOff size={10} /> Disconnected</>}
            </span>
          </div>
          <p className="page-subtitle">Monitor active calls in real-time</p>
        </div>
        <button onClick={loadData} className="btn-secondary text-sm">
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {/* Stats Grid */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-stagger" data-gsap="stat">
          <StatCard
            label="Active Calls"
            value={stats.active_calls}
            icon={Radio}
            color="bg-green-500/20 text-green-400"
            pulse={stats.active_calls > 0}
          />
          <StatCard
            label="Today's Calls"
            value={stats.calls_today}
            icon={PhoneCall}
            color="bg-blue-500/20 text-blue-400"
          />
          <StatCard
            label="This Week"
            value={stats.calls_this_week}
            icon={TrendingUp}
            color="bg-purple-500/20 text-purple-400"
          />
          <StatCard
            label="Avg Duration"
            value={formatDuration(stats.avg_duration_today)}
            icon={Clock}
            color="bg-amber-500/20 text-amber-400"
          />
        </div>
      )}

      {/* Active Calls */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4" data-gsap="card">
        {/* Call List */}
        <div className="lg:col-span-1 space-y-3" data-gsap="content">
          <h3 className="section-title">
            Active Calls ({activeCalls.length})
          </h3>
          {activeCalls.length === 0 ? (
            <div className="dash-card p-8 text-center">
              <Radio size={32} className="mx-auto text-[var(--text-muted)] mb-3 animate-float" />
              <p className="text-sm text-[var(--text-muted)]">No active calls</p>
              <p className="text-xs text-[var(--text-muted)] mt-1">Calls will appear here in real-time</p>
            </div>
          ) : (
            activeCalls.map(call => (
              <button
                key={call.id}
                onClick={() => setSelectedCallId(call.id)}
                className={`w-full text-left p-4 rounded-xl border transition-all duration-200 ${
                  selectedCallId === call.id
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                    : 'border-[var(--glass-border)] bg-[var(--bg-secondary)] hover:border-[var(--border-hover)]'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-green-400 pulse-live" />
                    <span className="text-sm font-medium">{call.agent_name || 'Unknown Agent'}</span>
                  </div>
                  <span className="text-xs text-[var(--text-muted)]">
                    {call.live_duration_secs ? formatDuration(call.live_duration_secs) : '—'}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs text-[var(--text-muted)]">
                  <span>{formatPhone(call.from_phone)} → {formatPhone(call.to_phone)}</span>
                  <span className="flex items-center gap-1">
                    <MessageSquare size={10} /> {call.message_count}
                  </span>
                </div>
              </button>
            ))
          )}
        </div>

        {/* Transcript Viewer */}
        <div className="lg:col-span-2 dash-card overflow-hidden flex flex-col" style={{ minHeight: '400px' }} data-gsap="content">
          {/* 3D Voice Orb */}
          {selectedCall && (
            <div className="three-canvas-container" style={{ height: 160 }}>
              <VoiceOrb amplitude={selectedCall.recent_messages.length > 0 ? 0.5 : 0.1} height={160} />
            </div>
          )}
          {!selectedCall ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <Volume2 size={36} className="mx-auto text-[var(--text-muted)] mb-3 animate-float" />
                <p className="text-sm text-[var(--text-muted)]">Select a call to view live transcript</p>
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between p-4 border-b border-[var(--glass-border)]">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-green-500/20">
                    <Radio size={16} className="text-green-400" />
                  </div>
                  <div>
                    <h3 className="text-sm font-medium">{selectedCall.agent_name || 'Unknown Agent'}</h3>
                    <p className="text-xs text-[var(--text-muted)]">
                      {formatPhone(selectedCall.from_phone)} → {formatPhone(selectedCall.to_phone)}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-4 text-xs text-[var(--text-muted)]">
                  <span className="flex items-center gap-1.5">
                    <Clock size={12} />
                    {selectedCall.live_duration_secs ? formatDuration(selectedCall.live_duration_secs) : '0:00'}
                  </span>
                  <span className="flex items-center gap-1.5">
                    <MessageSquare size={12} />
                    {selectedCall.message_count} messages
                  </span>
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {selectedCall.recent_messages.length === 0 ? (
                  <p className="text-center text-sm text-[var(--text-muted)] py-8">Waiting for conversation...</p>
                ) : (
                  selectedCall.recent_messages.map((msg, i) => (
                    <div key={i} className={`flex gap-3 dash-bubble ${msg.sender === 'human' ? 'flex-row-reverse' : ''}`}>
                      <div className={`flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center ${
                        msg.sender === 'human' ? 'bg-blue-500/20' : 'bg-[var(--accent)]/20'
                      }`}>
                        {msg.sender === 'human' ? (
                          <User size={12} className="text-blue-400" />
                        ) : (
                          <Bot size={12} className="text-[var(--accent)]" />
                        )}
                      </div>
                      <div className={`max-w-[80%] rounded-xl px-3.5 py-2 text-sm ${
                        msg.sender === 'human'
                          ? 'bg-blue-500/20 text-blue-100'
                          : 'bg-[var(--bg-secondary)] border border-[var(--glass-border)]'
                      }`}>
                        {msg.message}
                        <span className="block text-[10px] text-[var(--text-muted)] mt-1">
                          {msg.timestamp ? timeAgo(new Date(msg.timestamp * 1000).toISOString()) : ''}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </>
          )}
        </div>

        {/* Tool Events */}
        <div className="lg:col-span-1 dash-card overflow-hidden flex flex-col" style={{ minHeight: '400px' }} data-gsap="content">
          {!selectedCall ? (
            <div className="flex-1 flex items-center justify-center p-6 text-center">
              <div>
                <Activity size={32} className="mx-auto text-[var(--text-muted)] mb-3 animate-float" />
                <p className="text-sm text-[var(--text-muted)]">Select a call to inspect tool events</p>
              </div>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between p-4 border-b border-[var(--glass-border)]">
                <div>
                  <h3 className="text-sm font-medium">Tool Events</h3>
                  <p className="text-xs text-[var(--text-muted)]">Recent actions executed in this call</p>
                </div>
                <span className="text-xs text-[var(--text-muted)]">{selectedActions.length}</span>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {selectedActions.length === 0 ? (
                  <p className="text-center text-sm text-[var(--text-muted)] py-8">No tool events yet</p>
                ) : (
                  selectedActions.map((action) => (
                    <div key={action.id} className="rounded-xl border border-[var(--glass-border)] bg-[var(--bg-secondary)] p-3 space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-medium text-brand-400">{formatToolLabel(action.action_type)}</span>
                        <span className="text-[10px] text-[var(--text-muted)]">
                          {action.timestamp ? timeAgo(new Date(action.timestamp * 1000).toISOString()) : ''}
                        </span>
                      </div>
                      {action.params_json && (
                        <details className="group">
                          <summary className="cursor-pointer text-[11px] text-[var(--text-muted)]">Parameters</summary>
                          <pre className="mt-2 text-[10px] whitespace-pre-wrap break-words rounded-lg bg-[var(--bg-tertiary)] p-2 text-[var(--text-secondary)]">
                            {JSON.stringify(parseJsonField(action.params_json), null, 2)}
                          </pre>
                        </details>
                      )}
                      {action.result_json && (
                        <details className="group">
                          <summary className="cursor-pointer text-[11px] text-[var(--text-muted)]">Result</summary>
                          <pre className="mt-2 text-[10px] whitespace-pre-wrap break-words rounded-lg bg-[var(--bg-tertiary)] p-2 text-[var(--text-secondary)]">
                            {JSON.stringify(parseJsonField(action.result_json), null, 2)}
                          </pre>
                        </details>
                      )}
                    </div>
                  ))
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── Stat Card ─────────────────────────────────────────── */
function StatCard({
  label,
  value,
  icon: Icon,
  color,
  pulse,
}: {
  label: string;
  value: string | number;
  icon: React.ElementType;
  color: string;
  pulse?: boolean;
}) {
  return (
    <div className="dash-stat-card group">
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <p className="text-[13px] text-[var(--text-muted)] font-medium">{label}</p>
          <p className="text-2xl font-semibold tracking-tight">{value}</p>
        </div>
        <div className={`p-2.5 rounded-xl ${color} transition-transform duration-200 group-hover:scale-110 ${
          pulse ? 'animate-pulse' : ''
        }`}>
          <Icon size={18} />
        </div>
      </div>
    </div>
  );
}
