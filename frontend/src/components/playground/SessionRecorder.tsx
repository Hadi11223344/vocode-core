'use client';

import { useState, useEffect, useCallback } from 'react';
import { Save, History, Trash2, Play, X, Clock, MessageSquare } from 'lucide-react';
import { playground as playgroundApi } from '@/lib/api';
import { useToast } from '@/components/ui/toast';

interface SessionRecorderProps {
  agentId: number | null;
  sessionType: 'chat' | 'flow';
  messages: Array<{ role: string; content: string; timestamp?: number }>;
  traceEvents?: unknown[];
  context?: Record<string, unknown>;
  voiceMode?: string;
  ttsProvider?: string;
  turnCount?: number;
  totalTokens?: number;
  totalLatencyMs?: number;
  onReplay?: (session: {
    messages: Array<{ role: string; content: string }>;
    trace_events: unknown[];
    context: Record<string, unknown>;
  }) => void;
}

interface SessionListItem {
  id: number;
  agent_id: number;
  agent_name: string | null;
  session_type: string;
  turn_count: number;
  status: string;
  created_at: string;
}

export function SessionRecorder({
  agentId,
  sessionType,
  messages,
  traceEvents,
  context,
  voiceMode = 'text',
  ttsProvider,
  turnCount,
  totalTokens,
  totalLatencyMs,
  onReplay,
}: SessionRecorderProps) {
  const { success, apiError } = useToast();
  const [showHistory, setShowHistory] = useState(false);
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const fetchSessions = useCallback(async () => {
    if (!agentId) return;
    setLoading(true);
    try {
      const data = await playgroundApi.listSessions({
        agent_id: agentId,
        session_type: sessionType,
        limit: 10,
      });
      setSessions(data.sessions);
    } catch (err) {
      apiError(err, 'Failed to load sessions');
    } finally {
      setLoading(false);
    }
  }, [agentId, sessionType]);

  useEffect(() => {
    if (showHistory && agentId) {
      fetchSessions();
    }
  }, [showHistory, agentId, fetchSessions]);

  useEffect(() => {
    if (!showHistory) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowHistory(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showHistory]);

  const handleSave = useCallback(async () => {
    if (!agentId || messages.length === 0) return;
    setSaving(true);
    try {
      await playgroundApi.saveSession({
        agent_id: agentId,
        session_type: sessionType,
        messages,
        trace_events: traceEvents,
        context,
        voice_mode: voiceMode,
        tts_provider: ttsProvider,
        turn_count: turnCount,
        total_tokens: totalTokens,
        total_latency_ms: totalLatencyMs,
      });
      success('Session saved', `Saved ${messages.length} messages`);
      fetchSessions();
    } catch (err) {
      apiError(err, 'Failed to save session');
    } finally {
      setSaving(false);
    }
  }, [agentId, messages, sessionType, traceEvents, context, voiceMode, ttsProvider, turnCount, totalTokens, totalLatencyMs, success, apiError, fetchSessions]);

  const handleReplay = useCallback(async (sessionId: number) => {
    try {
      const data = await playgroundApi.getSession(sessionId);
      onReplay?.({
        messages: data.session.messages,
        trace_events: data.session.trace_events,
        context: data.session.context,
      });
      setShowHistory(false);
      success('Session loaded', `Replaying ${data.session.messages.length} messages`);
    } catch (err) {
      apiError(err, 'Failed to load session');
    }
  }, [onReplay, success, apiError]);

  const handleDelete = useCallback(async (sessionId: number) => {
    if (!window.confirm('Delete this session? This cannot be undone.')) return;
    try {
      await playgroundApi.deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      success('Session deleted');
    } catch (err) {
      apiError(err, 'Failed to delete session');
    }
  }, [success, apiError]);

  return (
    <>
      <div className="flex items-center gap-1">
        <button
          onClick={handleSave}
          disabled={!agentId || messages.length === 0 || saving}
          className="btn-ghost text-xs flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg disabled:opacity-40"
          title="Save session for replay"
        >
          <Save size={14} />
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          onClick={() => setShowHistory(!showHistory)}
          className="btn-ghost text-xs flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg"
          title="View saved sessions"
        >
          <History size={14} />
          History
        </button>
      </div>

      {showHistory && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setShowHistory(false)}>
          <div
            className="dash-card max-w-md w-full mx-4 p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold flex items-center gap-2">
                <History size={16} className="text-brand-400" />
                Session History
              </h3>
              <button onClick={() => setShowHistory(false)} className="btn-ghost p-1 rounded">
                <X size={16} />
              </button>
            </div>

            {loading && (
              <div className="flex items-center justify-center py-8 text-[var(--text-muted)] text-sm">
                Loading…
              </div>
            )}

            {!loading && sessions.length === 0 && (
              <div className="flex flex-col items-center justify-center py-8 text-[var(--text-muted)] text-sm">
                <MessageSquare size={24} className="mb-2 opacity-50" />
                No saved sessions yet
              </div>
            )}

            <div className="space-y-2 max-h-80 overflow-y-auto">
              {sessions.map((session) => (
                <div
                  key={session.id}
                  className="flex items-center justify-between p-3 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--glass-border)]"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium">{session.agent_name || `Agent #${session.agent_id}`}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-brand-500/10 text-brand-400">
                        {session.session_type}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 mt-1 text-[10px] text-[var(--text-muted)]">
                      <span className="flex items-center gap-0.5">
                        <Clock size={9} />
                        {new Date(session.created_at).toLocaleDateString()} {new Date(session.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                      <span>{session.turn_count} turns</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleReplay(session.id)}
                      className="p-1.5 rounded-lg text-brand-400 hover:bg-brand-500/10 transition-colors"
                      title="Replay session"
                    >
                      <Play size={14} />
                    </button>
                    <button
                      onClick={() => handleDelete(session.id)}
                      className="p-1.5 rounded-lg text-red-400 hover:bg-red-500/10 transition-colors"
                      title="Delete session"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
