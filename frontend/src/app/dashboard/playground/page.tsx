'use client';

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useSearchParams, usePathname } from 'next/navigation';
import Link from 'next/link';
import { getToken, playground, getValidToken } from '@/lib/api';
import { PlaygroundMessage } from '@/lib/types';
import { useToast } from '@/components/ui/toast';
import { EmptyState } from '@/components/ui/empty-state';
import { useVoiceChat } from '@/hooks/useVoiceChat';
import { useProductionVoice } from '@/hooks/use-production-voice';
import { usePageTitle } from '@/hooks/usePageTitle';
import { SessionRecorder } from '@/components/playground/SessionRecorder';
import { AudioVisualizer } from '@/components/ui/audio-visualizer';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';
import {
  Bot,
  Send,
  RotateCcw,
  Loader2,
  User,
  MessageSquare,
  Zap,
  Mic,
  Keyboard,
  Sparkles,
  Clock,
  Hash,
  MessageCircle,
  GitBranch,
} from 'lucide-react';

interface PlaygroundAgent {
  id: number;
  name: string;
  llm_provider: string;
  llm_model: string;
  initial_message: string;
  is_active: boolean;
  language?: string;
  stt_language?: string;
  mode?: string;
}

interface TurnMetrics {
  llm_latency_ms: number;
  tokens: number;
  tool_calls: number;
  turn: number;
}

interface Scenario {
  id: string;
  label: string;
  text: string;
}

type ChatMode = 'text' | 'voice';

export default function PlaygroundPage() {
  usePageTitle('Playground');
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const preselectAgentId = searchParams.get('agent');
  const embedded = searchParams.get('embedded') === '1';

  const { error, success: toastSuccess } = useToast();
  const errorRef = useRef(error);
  errorRef.current = error;
  const [agents, setAgents] = useState<PlaygroundAgent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<PlaygroundAgent | null>(null);
  const [messages, setMessages] = useState<PlaygroundMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [mode, setMode] = useState<ChatMode>('text');
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [lastMetrics, setLastMetrics] = useState<TurnMetrics | null>(null);
  const [browserVoiceName, setBrowserVoiceName] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const pendingAssistantRef = useRef<string>('');
  const hasStreamingAssistantRef = useRef(false);
  const lastAssistantTextRef = useRef<string>('');
  const sendMessageRef = useRef<(text?: string) => void>(() => {});
  const voiceSendTimerRef = useRef<number | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [wsReconnectAttempts, setWsReconnectAttempts] = useState(0);
  const [useProdVoice, setUseProdVoice] = useState(false);
  const useProdVoiceRef = useRef(false);
  useProdVoiceRef.current = useProdVoice;
  const reconnectFnRef = useRef<(() => void) | null>(null);

  const MAX_HISTORY_MESSAGES = 20;

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => { scrollToBottom(); }, [messages, scrollToBottom]);

  useEffect(() => {
    return () => {
      if (voiceSendTimerRef.current) {
        window.clearTimeout(voiceSendTimerRef.current);
        voiceSendTimerRef.current = null;
      }
    };
  }, []);

  // Voice chat hook — use refs for callbacks to avoid re-triggering the WS useEffect
  const voiceRef = useRef<ReturnType<typeof useVoiceChat> | null>(null);
  const modeRef = useRef<ChatMode>(mode);
  modeRef.current = mode;

  const voice = useVoiceChat({
    onTranscript: (text) => {
      setInput(text);
      if (voiceSendTimerRef.current) {
        window.clearTimeout(voiceSendTimerRef.current);
      }
      // Keep the browser preview feel responsive, but avoid sending stale partial transcripts.
      voiceSendTimerRef.current = window.setTimeout(() => {
        sendMessageRef.current(text);
      }, 250);
    },
    onListeningChange: (isListening) => {
      // Stop TTS when user starts speaking
      if (isListening) {
        voiceRef.current?.stopSpeaking();
      }
    },
    preferredVoiceName: browserVoiceName || undefined,
    preferredLanguage: selectedAgent?.stt_language || selectedAgent?.language || 'en-US',
  });
  voiceRef.current = voice;

  const prodVoice = useProductionVoice({
    agentId: useProdVoice ? (selectedAgent?.id ?? null) : null,
    onTranscript: (text) => {
      setInput(text);
      sendMessageRef.current(text);
    },
    onError: (text) => {
      error(`Production voice: ${text}`);
    },
  });
  const prodVoiceRef = useRef(prodVoice);
  prodVoiceRef.current = prodVoice;

  const browserVoices = useMemo(() => voice.availableVoices, [voice.availableVoices]);

  useEffect(() => {
    if (browserVoices.length === 0) {
      return;
    }
    if (!browserVoiceName || !browserVoices.some((item) => item.name === browserVoiceName)) {
      const preferred =
        browserVoices.find((item) => item.lang.startsWith('en')) ||
        browserVoices.find((item) => item.name.includes('Google')) ||
        browserVoices[0];
      setBrowserVoiceName(preferred?.name || '');
    }
  }, [browserVoices, browserVoiceName]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await playground.agents();
        if (cancelled) return;
        setAgents(data.agents);
        if (data.agents.length > 0 && !preselectAgentId) {
          const firstActive = data.agents.find((a) => a.is_active);
          setSelectedAgent(firstActive || data.agents[0]);
        }
      } catch {
        if (!cancelled) errorRef.current('Failed to load agents');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      wsRef.current?.close();
    };
  }, [preselectAgentId]);

  // Auto-select agent from query param
  useEffect(() => {
    if (preselectAgentId && agents.length > 0 && !selectedAgent) {
      const agent = agents.find((a) => a.id === Number(preselectAgentId));
      if (agent) selectAgent(agent);
    }
  }, [agents, preselectAgentId, selectedAgent]);

  // Load scenarios when agent changes
  useEffect(() => {
    if (!selectedAgent) {
      setScenarios([]);
      return;
    }
    playground.scenarios(selectedAgent.id)
      .then((data) => setScenarios(data.scenarios))
      .catch(() => setScenarios([]));
  }, [selectedAgent]);

  useEffect(() => {
    wsRef.current?.close();
    wsRef.current = null;

    if (!selectedAgent) {
      return;
    }

    const initialToken = getToken();
    if (!initialToken) {
      return;
    }

    let reconnectAttempts = 0;
    let reconnectTimer: number | null = null;
    let heartbeatTimer: number | null = null;
    let isManualClose = false;

    async function connect() {
      const token = await getValidToken();
      if (!token) {
        if (typeof window !== 'undefined') {
          window.location.href = '/login';
        }
        return;
      }
      const ws = playground.createWebSocket(selectedAgent!.id, token);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttempts = 0;
        setWsReconnectAttempts(0);
        setWsConnected(true);
        // Heartbeat: send ping every 30s to keep connection alive
        heartbeatTimer = window.setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, 30000);
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === 'initial_message' && data.text) {
            setMessages((prev) => {
              if (prev.length > 0) return prev;
              return [{ role: 'assistant', content: data.text, timestamp: Date.now() }];
            });
            if (modeRef.current === 'voice') {
              voiceRef.current?.speak(data.text);
            }
            return;
          }

          if (data.type === 'token') {
            const tokenText = typeof data.text === 'string' ? data.text : '';
            if (!tokenText) return;

            setStreaming(true);
            pendingAssistantRef.current += tokenText;
            lastAssistantTextRef.current = pendingAssistantRef.current;
            setMessages((prev) => {
              if (
                hasStreamingAssistantRef.current
                && prev.length > 0
                && prev[prev.length - 1].role === 'assistant'
              ) {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: pendingAssistantRef.current,
                };
                return updated;
              }
              hasStreamingAssistantRef.current = true;
              return [
                ...prev,
                { role: 'assistant', content: pendingAssistantRef.current, timestamp: Date.now() },
              ];
            });
            return;
          }

          if (data.type === 'message_end') {
            setStreaming(false);
            setSending(false);
            // Speak the completed response in voice mode (skip if prod voice is enabled)
            if (modeRef.current === 'voice' && !useProdVoiceRef.current && lastAssistantTextRef.current) {
              voiceRef.current?.speak(lastAssistantTextRef.current);
            }
            // Synthesize with production voice if enabled
            if (useProdVoiceRef.current && lastAssistantTextRef.current && prodVoiceRef.current?.connected) {
              prodVoiceRef.current?.synthesize(lastAssistantTextRef.current);
            }
            pendingAssistantRef.current = '';
            hasStreamingAssistantRef.current = false;
            lastAssistantTextRef.current = '';
            inputRef.current?.focus();
            return;
          }

          if (data.type === 'metrics') {
            setLastMetrics(data.metrics);
            return;
          }

          if (data.type === 'error') {
            setStreaming(false);
            setSending(false);
            pendingAssistantRef.current = '';
            hasStreamingAssistantRef.current = false;
            lastAssistantTextRef.current = '';
            errorRef.current(data.text || 'Playground stream error');
            if (data.fatal) {
              isManualClose = true;
            }
          }
        } catch {
          setStreaming(false);
          setSending(false);
          pendingAssistantRef.current = '';
          hasStreamingAssistantRef.current = false;
          lastAssistantTextRef.current = '';
        }
      };

      ws.onerror = () => {
        setStreaming(false);
        setSending(false);
        pendingAssistantRef.current = '';
        hasStreamingAssistantRef.current = false;
        lastAssistantTextRef.current = '';
      };

      ws.onclose = () => {
        if (wsRef.current === ws) {
          wsRef.current = null;
        }
        if (heartbeatTimer) {
          window.clearInterval(heartbeatTimer);
          heartbeatTimer = null;
        }
        setWsConnected(false);
        setStreaming(false);
        setSending(false);
        pendingAssistantRef.current = '';
        hasStreamingAssistantRef.current = false;
        lastAssistantTextRef.current = '';

        // Attempt reconnection with exponential backoff (max 3 attempts)
        if (!isManualClose && reconnectAttempts < 3) {
          reconnectAttempts += 1;
          setWsReconnectAttempts(reconnectAttempts);
          const delay = Math.pow(2, reconnectAttempts - 1) * 1000; // 1s, 2s, 4s
          reconnectTimer = window.setTimeout(() => {
            connect();
          }, delay);
        } else if (!isManualClose) {
          setWsReconnectAttempts(reconnectAttempts);
        }
      };
    }

    reconnectFnRef.current = () => {
      reconnectAttempts = 0;
      setWsReconnectAttempts(0);
      connect();
    };

    connect();

    return () => {
      isManualClose = true;
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
      }
      if (heartbeatTimer) {
        window.clearInterval(heartbeatTimer);
      }
      wsRef.current?.close();
      wsRef.current = null;
      setWsConnected(false);
      setWsReconnectAttempts(0);
    };
  }, [selectedAgent]);

  // ── localStorage message persistence ──
  const SESSION_KEY_PREFIX = 'playground_session_';
  const SESSION_MAX_MESSAGES = 50;
  const SESSION_MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24 hours
  const sessionSaveTimerRef = useRef<number | null>(null);

  // Save messages to localStorage (debounced)
  useEffect(() => {
    if (!selectedAgent || messages.length === 0) return;
    if (sessionSaveTimerRef.current) window.clearTimeout(sessionSaveTimerRef.current);
    sessionSaveTimerRef.current = window.setTimeout(() => {
      try {
        const key = `${SESSION_KEY_PREFIX}${selectedAgent.id}`;
        const payload = {
          messages: messages.slice(-SESSION_MAX_MESSAGES),
          savedAt: Date.now(),
        };
        localStorage.setItem(key, JSON.stringify(payload));
      } catch {
        // localStorage might be full or unavailable; silently ignore
      }
    }, 1000);
    return () => {
      if (sessionSaveTimerRef.current) window.clearTimeout(sessionSaveTimerRef.current);
    };
  }, [messages, selectedAgent]);

  function selectAgent(agent: PlaygroundAgent) {
    wsRef.current?.close();
    setSelectedAgent(agent);
    setLastMetrics(null);

    // Try restoring previous session from localStorage
    try {
      const key = `${SESSION_KEY_PREFIX}${agent.id}`;
      const raw = localStorage.getItem(key);
      if (raw) {
        const payload = JSON.parse(raw);
        if (payload.savedAt && Date.now() - payload.savedAt < SESSION_MAX_AGE_MS && Array.isArray(payload.messages) && payload.messages.length > 0) {
          setMessages(payload.messages);
          toastSuccess('Session restored', `Restored ${payload.messages.length} message${payload.messages.length !== 1 ? 's' : ''} from your last visit`);
          pendingAssistantRef.current = '';
          hasStreamingAssistantRef.current = false;
          lastAssistantTextRef.current = '';
          return;
        }
      }
    } catch {
      // localStorage unavailable; fall through to default
    }

    const token = getToken();
    if (!token && agent.initial_message) {
      setMessages([{ role: 'assistant', content: agent.initial_message, timestamp: Date.now() }]);
    } else {
      setMessages([]);
    }
    pendingAssistantRef.current = '';
    hasStreamingAssistantRef.current = false;
    lastAssistantTextRef.current = '';
  }

  function resetConversation() {
    voice.stopSpeaking();
    if (voiceSendTimerRef.current) {
      window.clearTimeout(voiceSendTimerRef.current);
      voiceSendTimerRef.current = null;
    }
    // Clear localStorage session for this agent
    if (selectedAgent) {
      try {
        localStorage.removeItem(`${SESSION_KEY_PREFIX}${selectedAgent.id}`);
      } catch {
        // ignore
      }
    }
    const canUseSocket = wsRef.current && wsRef.current.readyState === WebSocket.OPEN;
    if (canUseSocket) {
      setMessages([]);
    } else if (selectedAgent?.initial_message) {
      setMessages([{ role: 'assistant', content: selectedAgent.initial_message, timestamp: Date.now() }]);
    } else {
      setMessages([]);
    }
    pendingAssistantRef.current = '';
    hasStreamingAssistantRef.current = false;
    lastAssistantTextRef.current = '';
    setLastMetrics(null);
    if (canUseSocket) {
      wsRef.current?.send(JSON.stringify({ type: 'reset' }));
    }
    inputRef.current?.focus();
  }

  async function sendMessage(overrideText?: string) {
    const text = overrideText || input;
    if (!text.trim() || !selectedAgent || sending) return;
    const userMsg: PlaygroundMessage = { role: 'user', content: text.trim(), timestamp: Date.now() };
    const priorConversation = messages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .slice(-MAX_HISTORY_MESSAGES)
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setSending(true);
    setStreaming(false);
    pendingAssistantRef.current = '';
    hasStreamingAssistantRef.current = false;
    lastAssistantTextRef.current = '';
    if (voiceSendTimerRef.current) {
      window.clearTimeout(voiceSendTimerRef.current);
      voiceSendTimerRef.current = null;
    }

    try {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'message', text: userMsg.content }));
      } else {
        const data = await playground.message(selectedAgent.id, userMsg.content, priorConversation);
        setMessages((prev) => [...prev, { role: 'assistant', content: data.response, timestamp: Date.now() }]);
        if (modeRef.current === 'voice') {
          voice.speak(data.response);
        }
        setLastMetrics(data.metrics || null);
        setSending(false);
        inputRef.current?.focus();
      }
    } catch {
      error('Failed to get response');
      setSending(false);
      setStreaming(false);
      pendingAssistantRef.current = '';
      hasStreamingAssistantRef.current = false;
      lastAssistantTextRef.current = '';
      inputRef.current?.focus();
    }
  }

  // Keep sendMessageRef in sync so voice callbacks always use the latest version
  sendMessageRef.current = sendMessage;

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function runScenario(text: string) {
    setInput(text);
    sendMessage(text);
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <Loader2 className="animate-spin text-[var(--accent)]" size={32} />
      </div>
    );
  }

  return (
    <GsapPageWrapper>
    <div className={`flex flex-col gap-5 ${embedded ? 'h-screen p-4' : 'h-[calc(100vh-8rem)]'}`}>
      {/* Header */}
      {!embedded && (
      <div className="flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Agent Playground</h1>
          <p className="page-subtitle">Test your agents in real-time conversations</p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href={selectedAgent ? `/dashboard/playground/flow?agent_id=${selectedAgent.id}` : '/dashboard/playground/flow'}
            className={`btn-ghost text-xs flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-all ${
              pathname === '/dashboard/playground/flow' ? 'text-purple-400 bg-purple-500/10' : 'text-purple-400 hover:bg-purple-500/10'
            }`}
            title="Open Flow Playground for conversational flow agents"
          >
            <GitBranch size={14} />
            Flow Playground
          </Link>
          {/* Production voice toggle */}
          {selectedAgent && (
            <button
              onClick={() => setUseProdVoice(!useProdVoice)}
              className={`btn-ghost text-xs flex items-center gap-1.5 px-3 py-1.5 rounded-lg ${
                useProdVoice ? 'text-green-400 bg-green-500/10' : ''
              }`}
              title={useProdVoice ? 'Using server-side production voice (real TTS/STT providers)' : 'Click to use server-side production voice'}
            >
              <Zap size={14} />
              {useProdVoice ? `Prod Voice: ${prodVoice.ttsProvider || '…'}` : 'Prod Voice'}
            </button>
          )}
          {/* Mode toggle */}
          {selectedAgent && (
            <button
              onClick={() => {
                const next = mode === 'text' ? 'voice' : 'text';
                if (voiceSendTimerRef.current) {
                  window.clearTimeout(voiceSendTimerRef.current);
                  voiceSendTimerRef.current = null;
                }
                setMode(next);
                if (next === 'text') voice.stopSpeaking();
              }}
              className={`btn-ghost text-xs flex items-center gap-1.5 px-3 py-1.5 rounded-lg ${
                mode === 'voice' ? 'text-green-400 bg-green-500/10' : ''
              }`}
              title={mode === 'voice' ? 'Switch to text mode' : 'Switch to voice mode'}
            >
              {mode === 'voice' ? <Mic size={14} /> : <Keyboard size={14} />}
              {mode === 'voice' ? 'Voice' : 'Text'}
            </button>
          )}
          <SessionRecorder
            agentId={selectedAgent?.id ?? null}
            sessionType="chat"
            messages={messages.map(m => ({ role: m.role, content: m.content, timestamp: m.timestamp }))}
            voiceMode={useProdVoice ? 'production' : mode}
            ttsProvider={useProdVoice ? prodVoice.ttsProvider ?? undefined : undefined}
            turnCount={messages.filter(m => m.role === 'user').length}
            onReplay={(session) => {
              setLastMetrics(null);
              setMessages(session.messages.map((m, i) => ({
                role: m.role as 'user' | 'assistant',
                content: m.content,
                timestamp: Date.now() + i,
              })));
            }}
          />
          <button onClick={resetConversation} className="btn-secondary text-sm">
            <RotateCcw size={14} /> Reset Chat
          </button>
        </div>
      </div>
      )}

      <div className="flex gap-4 flex-1 min-h-0">
        {/* Agent Sidebar */}
        {!embedded && (
        <div className="w-72 flex-shrink-0 space-y-3 overflow-y-auto">
          <h3 className="section-title px-1">Select Agent</h3>
          {agents.length === 0 ? (
            <EmptyState
              icon={Bot}
              title="No agents yet"
              description="Create an agent first to test it in the Playground."
            />
          ) : (
            agents.map((agent) => (
              <button
                key={agent.id}
                onClick={() => selectAgent(agent)}
                className={`w-full text-left p-3.5 rounded-xl border transition-all duration-200 ${
                  selectedAgent?.id === agent.id
                    ? 'border-[var(--accent)] bg-[var(--accent)]/10 shadow-lg shadow-[var(--accent)]/5'
                    : 'border-[var(--glass-border)] bg-[var(--bg-secondary)] hover:border-[var(--border-hover)]'
                } ${!agent.is_active ? 'opacity-50' : ''}`}
              >
                <div className="flex items-center gap-2.5">
                  <div className={`p-1.5 rounded-lg ${
                    selectedAgent?.id === agent.id ? 'bg-[var(--accent)]/20' : 'bg-[var(--bg-tertiary)]'
                  }`}>
                    <Bot size={16} className={selectedAgent?.id === agent.id ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">{agent.name}</p>
                    <p className="text-xs text-[var(--text-muted)] truncate">
                      {agent.llm_provider} / {agent.llm_model}
                    </p>
                  </div>
                  {agent.is_active ? (
                    <span className="w-2 h-2 rounded-full bg-green-400 flex-shrink-0" />
                  ) : (
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 flex-shrink-0">Inactive</span>
                  )}
                </div>
              </button>
            ))
          )}
        </div>
        )}

        {/* Chat Area */}
        <div className="flex-1 flex flex-col dash-card overflow-hidden">
          {!selectedAgent ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <MessageSquare size={40} className="mx-auto text-[var(--text-muted)] mb-3 animate-float" />
                <p className="text-[var(--text-muted)]">Select an agent to start chatting</p>
              </div>
            </div>
          ) : (
            <>
              {/* Chat header */}
              <div className="flex items-center gap-3 p-4 border-b border-[var(--glass-border)]">
                <div className="p-2 rounded-lg bg-[var(--accent)]/20">
                  <Bot size={18} className="text-[var(--accent)]" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-medium truncate">{selectedAgent.name}</h3>
                  <p className="text-xs text-[var(--text-muted)]">
                    {selectedAgent.llm_provider} &middot; {selectedAgent.llm_model}
                  </p>
                </div>
                {/* Metrics */}
                {lastMetrics && (
                  <div className="hidden sm:flex items-center gap-3 text-xs text-[var(--text-muted)]">
                    <span className="flex items-center gap-1" title="LLM latency">
                      <Clock size={10} />
                      {lastMetrics.llm_latency_ms}ms
                    </span>
                    <span className="flex items-center gap-1" title="Tokens used">
                      <Hash size={10} />
                      {lastMetrics.tokens}
                    </span>
                    <span className="flex items-center gap-1" title="Turn count">
                      <MessageCircle size={10} />
                      #{lastMetrics.turn}
                    </span>
                  </div>
                )}
                <div className={`flex items-center gap-1.5 px-2 py-1 rounded-full text-xs ${
                  wsConnected
                    ? 'bg-green-500/10 text-green-400'
                    : 'bg-amber-500/10 text-amber-400'
                }`}>
                  <Zap size={10} /> {wsConnected ? 'Connected' : wsReconnectAttempts >= 3 ? 'Disconnected' : 'Connecting…'}
                </div>
                {!wsConnected && wsReconnectAttempts >= 3 && selectedAgent && (
                  <button
                    onClick={() => reconnectFnRef.current?.()}
                    className="text-xs px-2 py-1 rounded-full bg-brand-500/10 text-brand-400 hover:bg-brand-500/20 transition-colors"
                  >
                    Reconnect
                  </button>
                )}
                {selectedAgent.mode === 'conversational_flow' && (
                  <span className="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-1 rounded-full" title="Conversational flow agents use graph-based logic that the playground doesn't fully simulate">
                    Flow mode (limited)
                  </span>
                )}
                {embedded && (
                  <button onClick={resetConversation} className="btn-ghost text-xs flex items-center gap-1 px-2 py-1 rounded-lg" title="Reset conversation">
                    <RotateCcw size={12} /> Reset
                  </button>
                )}
              </div>

              {/* Messages */}
              <div className="flex-1 overflow-y-auto p-4 space-y-4">
                {messages.length === 0 && (
                  <div className="flex items-center justify-center h-full">
                    <EmptyState
                      icon={MessageSquare}
                      title="Start a conversation"
                      description="Send a message to test your agent's responses."
                      className="border-0 bg-transparent"
                    />
                  </div>
                )}
                {messages.map((msg, i) => (
                  <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                    <div className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${
                      msg.role === 'user'
                        ? 'bg-brand-500/15'
                        : 'bg-[var(--accent)]/20'
                    }`}>
                      {msg.role === 'user' ? (
                        <User size={14} className="text-brand-400" />
                      ) : (
                        <Bot size={14} className="text-[var(--accent)]" />
                      )}
                    </div>
                    <div
                      className={`max-w-[75%] rounded-xl px-4 py-2.5 text-sm leading-relaxed ${
                        msg.role === 'user'
                          ? 'bg-brand-500/15 text-[var(--text-primary)]'
                          : 'bg-[var(--bg-secondary)] border border-[var(--glass-border)]'
                      }`}
                    >
                      {msg.content}
                      {streaming && i === messages.length - 1 && msg.role === 'assistant' && (
                        <span className="inline-block w-2 h-4 ml-1 bg-[var(--accent)] animate-pulse rounded-sm" />
                      )}
                    </div>
                  </div>
                ))}
                {sending && (
                  <div className="flex gap-3">
                    <div className="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent)]/20">
                      <Bot size={14} className="text-[var(--accent)]" />
                    </div>
                    <div className="bg-[var(--bg-secondary)] border border-[var(--glass-border)] rounded-xl px-4 py-3">
                      <div className="flex gap-1.5">
                        <span className="w-2 h-2 rounded-full bg-[var(--text-muted)] animate-bounce" style={{ animationDelay: '0ms' }} />
                        <span className="w-2 h-2 rounded-full bg-[var(--text-muted)] animate-bounce" style={{ animationDelay: '150ms' }} />
                        <span className="w-2 h-2 rounded-full bg-[var(--text-muted)] animate-bounce" style={{ animationDelay: '300ms' }} />
                      </div>
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* Scenario quick-test panel */}
              {scenarios.length > 0 && (
                <div className="px-4 pt-2 border-t border-[var(--glass-border)]">
                  <div className="flex gap-2 overflow-x-auto pb-2">
                    {scenarios.map((s) => (
                      <button
                        onClick={() => runScenario(s.text)}
                        disabled={sending || !selectedAgent.is_active}
                        className="btn-ghost text-xs whitespace-nowrap px-3 py-1.5 rounded-lg flex items-center gap-1.5 disabled:opacity-40"
                        title={s.text}
                      >
                        <Sparkles size={12} className="text-[var(--accent)]" />
                        {s.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Input */}
              <div className="p-4 border-t border-[var(--glass-border)]">
                {mode === 'voice' ? (
                  <div className="flex flex-col items-center gap-3 py-2">
                    <AudioVisualizer isListening={voice.isListening} />
                    <div className="w-full max-w-sm rounded-xl border border-[var(--glass-border)] bg-[var(--bg-secondary)] px-3 py-2 text-xs text-[var(--text-muted)]">
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-medium text-[var(--text-secondary)]">Browser preview</span>
                        <span>SpeechSynthesis TTS</span>
                      </div>
                      <p className="mt-1 leading-relaxed">
                        This mode uses your browser&apos;s speech recognition and speech synthesis, not the production TTS voice.
                      </p>
                    </div>
                    <div className="w-full max-w-sm space-y-2">
                      <label className="text-xs text-[var(--text-muted)]">Browser voice</label>
                      <select
                        value={browserVoiceName}
                        onChange={(e) => setBrowserVoiceName(e.target.value)}
                        className="input-base w-full"
                        disabled={browserVoices.length === 0}
                      >
                        {browserVoices.length === 0 ? (
                          <option value="">Loading browser voices…</option>
                        ) : (
                          browserVoices.map((item) => (
                            <option key={`${item.name}-${item.lang}`} value={item.name}>
                              {item.name} ({item.lang})
                            </option>
                          ))
                        )}
                      </select>
                    </div>
                    <p className="text-[11px] text-[var(--text-muted)] text-center max-w-sm">
                      {browserVoiceName
                        ? `Using ${browserVoiceName} for browser preview.`
                        : 'Choose a browser voice to preview speech output.'}
                    </p>
                     <button
                      onClick={voice.toggleListening}
                      disabled={!selectedAgent.is_active}
                      className={`w-16 h-16 rounded-full flex items-center justify-center transition-all select-none disabled:opacity-40 disabled:cursor-not-allowed ${
                        voice.isListening
                          ? 'bg-red-500 scale-110 shadow-lg shadow-red-500/30'
                          : 'bg-[var(--accent)] hover:scale-105'
                      }`}
                    >
                      <Mic size={28} className="text-[var(--text-inverse)]" />
                    </button>
                    <p className="text-xs text-[var(--text-muted)]">
                      {voice.isListening
                        ? 'Listening... tap to stop'
                        : voice.isSupported
                        ? 'Tap to speak'
                        : 'Voice not supported in this browser'}
                    </p>
                    {!voice.isSupported && (
                      <p className="text-[11px] text-amber-400 text-center max-w-xs">
                        Your browser doesn't support speech recognition. Use Chrome or Safari for voice mode.
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="flex gap-3 items-end">
                    <textarea
                      ref={inputRef}
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={handleKeyDown}
                      placeholder="Type a message..."
                      rows={1}
                      className="input-base flex-1 rounded-xl px-4 py-3 resize-none"
                      style={{ maxHeight: '120px' }}
                      disabled={sending || !selectedAgent.is_active}
                    />
                    <button
                      onClick={() => sendMessage()}
                      disabled={!input.trim() || sending || !selectedAgent.is_active}
                      className="btn-primary p-3 rounded-xl disabled:opacity-40"
                    >
                      {sending ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
                    </button>
                  </div>
                )}
                {!selectedAgent.is_active && (
                  <p className="text-[11px] text-amber-400 mt-2 text-center">
                    {mode === 'voice'
                      ? 'This agent is inactive. Activate it to use voice mode.'
                      : 'This agent is inactive. Activate it to chat in Playground.'}
                  </p>
                )}
                {mode !== 'voice' && (
                  <p className="text-[11px] text-[var(--text-muted)] mt-2 text-center opacity-60">
                    Enter to send &middot; Shift+Enter for new line
                  </p>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
    </GsapPageWrapper>
  );
}
