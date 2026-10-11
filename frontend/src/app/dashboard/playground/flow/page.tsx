'use client';

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useSearchParams, usePathname } from 'next/navigation';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { playground as playgroundApi, agents as agentsApi } from '@/lib/api';
import { useToast } from '@/components/ui/toast';
import { EmptyState } from '@/components/ui/empty-state';
import { usePageTitle } from '@/hooks/usePageTitle';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';
import { useFlowPlayground } from '@/hooks/use-flow-playground';
import { ExecutionTrace } from '@/components/playground/ExecutionTrace';
import { MockContextEditor } from '@/components/playground/MockContextEditor';
import { VariablesPanel } from '@/components/playground/VariablesPanel';
import { CallerExperienceView } from '@/components/playground/CallerExperienceView';
import { SessionRecorder } from '@/components/playground/SessionRecorder';
import { Node, Edge } from 'reactflow';
import {
  Bot,
  Send,
  RotateCcw,
  Loader2,
  User,
  MessageSquare,
  Zap,
  GitBranch,
  Play,
  ArrowLeft,
  AlertCircle,
  Activity,
  CheckCircle,
  Clock,
  MessageCircle,
  Pencil,
  Info,
  ChevronRight,
  Settings2,
  Phone,
  Database,
} from 'lucide-react';

const FlowGraphCanvas = dynamic(
  () => import('@/components/playground/FlowGraphCanvas').then((m) => m.FlowGraphCanvas),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={32} className="animate-spin text-brand-400" />
      </div>
    ),
  }
);

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

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export default function FlowPlaygroundPage() {
  usePageTitle('Flow Playground');
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const { apiError } = useToast();
  const requestedWorkflowId = Number(searchParams.get('workflow_id')) || null;
  const expectedGraphHash = searchParams.get('graph_hash');

  const [agents, setAgents] = useState<PlaygroundAgent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<PlaygroundAgent | null>(null);
  const [loading, setLoading] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [graphNodes, setGraphNodes] = useState<Node[]>([]);
  const [graphEdges, setGraphEdges] = useState<Edge[]>([]);
  const [mockContext, setMockContext] = useState<Record<string, unknown>>({
    caller_name: '',
    caller_phone: '',
    transcript: '',
  });
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const startTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sendTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [elapsedTime, setElapsedTime] = useState<number | null>(null);
  const [rightTab, setRightTab] = useState<'trace' | 'context' | 'caller' | 'variables'>('trace');

  // Filter only conversational_flow agents
  const flowAgents = useMemo(() => agents.filter((a) => a.mode === 'conversational_flow'), [agents]);

  // Use the flow playground hook
  const flow = useFlowPlayground({
    agentId: selectedAgent?.id ?? null,
    workflowId: requestedWorkflowId,
    expectedGraphHash,
    onAgentResponse: (_nodeId, text) => {
      if (startTimeoutRef.current) { clearTimeout(startTimeoutRef.current); startTimeoutRef.current = null; }
      if (sendTimeoutRef.current) { clearTimeout(sendTimeoutRef.current); sendTimeoutRef.current = null; }
      setMessages((prev) => [...prev, { role: 'assistant', content: text }]);
      setSending(false);
    },
    onFlowEnd: () => {
      if (startTimeoutRef.current) { clearTimeout(startTimeoutRef.current); startTimeoutRef.current = null; }
      if (sendTimeoutRef.current) { clearTimeout(sendTimeoutRef.current); sendTimeoutRef.current = null; }
      setSending(false);
    },
    onError: (text) => {
      if (startTimeoutRef.current) { clearTimeout(startTimeoutRef.current); startTimeoutRef.current = null; }
      if (sendTimeoutRef.current) { clearTimeout(sendTimeoutRef.current); sendTimeoutRef.current = null; }
      setSending(false);
      apiError(new Error(text), 'Flow error');
    },
  });

  // Update elapsed time while flow is running
  useEffect(() => {
    if (!flow.flowStartTime) {
      setElapsedTime(null);
      return;
    }
    const timer = setInterval(() => {
      setElapsedTime(Date.now() - (flow.flowStartTime ?? Date.now()));
    }, 100);
    return () => clearInterval(timer);
  }, [flow.flowStartTime]);

  // Fetch agents
  useEffect(() => {
    (async () => {
      try {
        const data = await playgroundApi.agents();
        setAgents(data.agents);
        // Auto-select from query param or first flow agent
        const agentIdParam = searchParams.get('agent_id');
        if (agentIdParam) {
          const found = data.agents.find((a: PlaygroundAgent) => a.id === parseInt(agentIdParam));
          if (found && found.mode === 'conversational_flow') {
            setSelectedAgent(found);
          }
        } else if (data.agents.length > 0) {
          const firstFlow = data.agents.find((a: PlaygroundAgent) => a.mode === 'conversational_flow');
          if (firstFlow) setSelectedAgent(firstFlow);
        }
      } catch (err) {
        apiError(err, 'Failed to load agents');
      } finally {
        setLoading(false);
      }
    })();
  }, [searchParams, apiError]);

  // Fetch agent's graph when selected
  useEffect(() => {
    if (!selectedAgent) {
      setGraphNodes([]);
      setGraphEdges([]);
      return;
    }
    (async () => {
      try {
        const data = await agentsApi.get(selectedAgent.id);
        const graphJson = data.agent.graph_json;
        if (graphJson) {
          const parsed = typeof graphJson === 'string' ? JSON.parse(graphJson) : graphJson;
          if (parsed && parsed.nodes) {
            setGraphNodes(parsed.nodes.map((n: Node) => ({
              ...n,
              type: 'workflowNode',
              data: {
                ...n.data,
                nodeType: (n.data as Record<string, unknown>)?.nodeType || n.type,
              },
            })));
            setGraphEdges((parsed.edges || []).map((e: Edge) => ({
              ...e,
              animated: false,
              style: { stroke: '#6366f1', strokeWidth: 2 },
            })));
          }
        }
      } catch {
        // Graph fetch is optional — flow events will include graph data
      }
    })();
  }, [selectedAgent]);

  // Auto-scroll messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const selectAgent = useCallback((agent: PlaygroundAgent) => {
    setSelectedAgent(agent);
    setMessages([]);
    setInput('');
    setSending(false);
  }, []);

  // Cleanup timeouts on unmount
  useEffect(() => {
    return () => {
      if (startTimeoutRef.current) clearTimeout(startTimeoutRef.current);
      if (sendTimeoutRef.current) clearTimeout(sendTimeoutRef.current);
    };
  }, []);

  const handleStart = useCallback(() => {
    if (!selectedAgent || !flow.connected) return;
    if (startTimeoutRef.current) clearTimeout(startTimeoutRef.current);
    setMessages([]);
    setSending(true);
    // WebSocket messages are ordered, so the visible mock context is applied
    // before the flow starts instead of remaining a UI-only default.
    flow.setContext(mockContext);
    flow.startFlow();
    // Safety timeout: reset sending if no response within 15s
    startTimeoutRef.current = setTimeout(() => {
      startTimeoutRef.current = null;
      setSending((prev) => {
        if (prev) {
          apiError(new Error('Flow start timed out — no response from server'), 'Start Flow failed');
        }
        return false;
      });
    }, 15000);
  }, [selectedAgent, flow, mockContext, apiError]);

  const handleSend = useCallback(() => {
    if (!input.trim() || !selectedAgent || !flow.connected) return;
    if (sendTimeoutRef.current) clearTimeout(sendTimeoutRef.current);
    const userMsg = input.trim();
    setMessages((prev) => [...prev, { role: 'user', content: userMsg }]);
    setInput('');
    setSending(true);
    flow.sendMessage(userMsg);
    // Safety timeout: reset sending if no response within 30s
    sendTimeoutRef.current = setTimeout(() => {
      sendTimeoutRef.current = null;
      setSending((prev) => {
        if (prev) {
          apiError(new Error('No response from server within 30s — flow may have stalled'), 'Send timed out');
        }
        return false;
      });
    }, 30000);
  }, [input, selectedAgent, flow, apiError]);

  const handleReset = useCallback(() => {
    if (startTimeoutRef.current) { clearTimeout(startTimeoutRef.current); startTimeoutRef.current = null; }
    if (sendTimeoutRef.current) { clearTimeout(sendTimeoutRef.current); sendTimeoutRef.current = null; }
    flow.reset();
    setMessages([]);
    setSending(false);
  }, [flow]);

  const handleApplyContext = useCallback((ctx: Record<string, unknown>) => {
    setMockContext(ctx);
    flow.setContext(ctx);
  }, [flow]);

  // Build traversed edge keys set
  const traversedEdgeKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const edge of flow.traversedEdges) {
      keys.add(`${edge.source}->${edge.target}`);
    }
    return keys;
  }, [flow.traversedEdges]);

  // Build completed node IDs set
  const completedNodeIds = useMemo(() => {
    return new Set(flow.completedNodes.keys());
  }, [flow.completedNodes]);

  if (loading) {
    return (
      <GsapPageWrapper>
        <div className="flex items-center justify-center h-[calc(100vh-200px)]">
          <Loader2 size={32} className="animate-spin text-brand-400" />
        </div>
      </GsapPageWrapper>
    );
  }

  const tabBtnBase = 'flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors border-b-2';
  const tabBtnActive = 'text-brand-400 border-brand-400';
  const tabBtnInactive = 'text-[var(--text-muted)] border-transparent hover:text-[var(--text-secondary)]';

  return (
    <GsapPageWrapper>
      <div className="p-4 max-w-[1600px] mx-auto h-[calc(100vh-64px)] flex flex-col">
        {/* Header — compact single row */}
        <div className="flex items-center justify-between mb-2 flex-shrink-0">
          <div className="flex items-center gap-3">
            <Link href="/dashboard/playground" className="btn-ghost p-2 rounded-lg">
              <ArrowLeft size={18} />
            </Link>
            <div>
              <h1 className="text-lg font-bold flex items-center gap-2">
                <GitBranch size={18} className="text-purple-400" />
                Flow Playground
              </h1>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {searchParams.get('workflow_id') && (
              <Link
                href={`/dashboard/workflows/${searchParams.get('workflow_id')}`}
                className="btn-ghost px-3 py-1.5 rounded-lg text-sm flex items-center gap-1.5 transition-all"
              >
                <Pencil size={14} />
                Back to Editor
              </Link>
            )}
            <Link
              href={selectedAgent ? `/dashboard/playground?agent=${selectedAgent.id}` : '/dashboard/playground'}
              className={`btn-ghost px-3 py-1.5 rounded-lg text-sm flex items-center gap-1.5 transition-all ${
                pathname === '/dashboard/playground' ? 'text-brand-400 bg-brand-500/10' : ''
              }`}
            >
              <MessageSquare size={14} />
              Chat Playground
            </Link>
          </div>
        </div>

        {/* Agent Selector — compact */}
        <div className="mb-2 flex-shrink-0">
          {flowAgents.length === 0 ? (
            <EmptyState
              icon={GitBranch}
              title="No conversational flow agents"
              description="Create a conversational flow agent to test it in the Flow Playground."
            />
          ) : (
            <div className="flex gap-2 overflow-x-auto pb-1">
              {flowAgents.map((agent) => (
                <button
                  key={agent.id}
                  onClick={() => selectAgent(agent)}
                  className={`flex-shrink-0 text-left p-2.5 rounded-xl border transition-all ${
                    selectedAgent?.id === agent.id
                      ? 'border-purple-500/40 bg-purple-500/10'
                      : 'border-[var(--glass-border)] bg-[var(--bg-secondary)] hover:border-[var(--border-hover)]'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <div className={`p-1.5 rounded-lg ${
                      selectedAgent?.id === agent.id ? 'bg-purple-500/20' : 'bg-[var(--bg-tertiary)]'
                    }`}>
                      <Bot size={14} className={selectedAgent?.id === agent.id ? 'text-purple-400' : 'text-[var(--text-muted)]'} />
                    </div>
                    <div>
                      <p className="text-sm font-medium">{agent.name}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">
                        {agent.llm_provider} / {agent.llm_model}
                      </p>
                    </div>
                    {agent.is_active && (
                      <span className="w-2 h-2 rounded-full bg-green-400 ml-1" />
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {selectedAgent ? (
          <>
            {/* Controls + Metrics — compact single row */}
            <div className="flex items-center justify-between mb-2 flex-shrink-0 gap-2 flex-wrap">
              {/* Left: status + metrics */}
              <div className="flex items-center gap-2 text-xs flex-wrap">
                <div className={`flex items-center gap-1.5 px-2 py-1 rounded-full ${
                  flow.connected
                    ? 'bg-green-500/10 text-green-400'
                    : flow.connecting
                      ? 'bg-amber-500/10 text-amber-400'
                      : 'bg-red-500/10 text-red-400'
                }`}>
                  <Zap size={10} />
                  {flow.connected ? 'Connected' : flow.connecting ? 'Connecting…' : 'Disconnected'}
                </div>
                {!flow.connected && !flow.connecting && selectedAgent && (
                  <button
                    onClick={() => flow.connect()}
                    className="text-xs px-2 py-1 rounded-full bg-brand-500/10 text-brand-400 hover:bg-brand-500/20 transition-colors"
                  >
                    Reconnect
                  </button>
                )}
                {flow.error && (
                  <span className="flex items-center gap-1 text-red-400">
                    <AlertCircle size={12} />
                    {flow.error}
                  </span>
                )}
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400">
                  <Activity size={10} />
                  <span className="font-medium">{flow.completedNodes.size}</span> nodes
                </span>
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400">
                  <GitBranch size={10} />
                  <span className="font-medium">{flow.traversedEdges.length}</span> edges
                </span>
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-500/10 text-green-400">
                  <MessageCircle size={10} />
                  <span className="font-medium">{messages.filter(m => m.role === 'user').length}</span> turns
                </span>
                {elapsedTime !== null && (
                  <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400">
                    <Clock size={10} />
                    <span className="font-medium tabular-nums">{(elapsedTime / 1000).toFixed(1)}s</span>
                  </span>
                )}
                {flow.runtimeIdentity?.graph_hash && (
                  <span
                    className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 font-mono"
                    title={`Runtime graph: ${flow.runtimeIdentity.graph_hash}`}
                  >
                    <Database size={10} />
                    graph {flow.runtimeIdentity.graph_hash.slice(0, 8)}
                  </span>
                )}
                {flow.failedNodes.size > 0 && (
                  <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-500/10 text-red-400">
                    <AlertCircle size={10} />
                    <span className="font-medium">{flow.failedNodes.size}</span> failed
                  </span>
                )}
                {flow.activeNodeId && (
                  <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400">
                    <Loader2 size={10} className="animate-spin" />
                    <span className="font-medium">Executing…</span>
                  </span>
                )}
                {flow.started && !flow.activeNodeId && flow.completedNodes.size > 0 && flow.failedNodes.size === 0 && (
                  <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-500/10 text-green-400">
                    <CheckCircle size={10} />
                    <span className="font-medium">Completed</span>
                  </span>
                )}
              </div>
              {/* Right: action buttons */}
              <div className="flex items-center gap-2">
                <button
                  onClick={handleStart}
                  disabled={!flow.connected || flow.started || sending}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600/20 text-green-400 hover:bg-green-600/30 border border-green-500/30 rounded-lg text-sm transition-colors disabled:opacity-40"
                >
                  <Play size={12} />
                  Start Flow
                </button>
                <button
                  onClick={handleReset}
                  disabled={!flow.connected}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--bg-tertiary)] text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]/80 border border-[var(--glass-border)] rounded-lg text-sm transition-colors disabled:opacity-40"
                >
                  <RotateCcw size={12} />
                  Reset
                </button>
                <SessionRecorder
                  agentId={selectedAgent?.id ?? null}
                  sessionType="flow"
                  messages={messages.map(m => ({ role: m.role, content: m.content }))}
                  traceEvents={flow.traceEvents}
                  context={mockContext}
                  turnCount={messages.filter(m => m.role === 'user').length}
                  onReplay={(session) => {
                    setMessages(session.messages.map(m => ({
                      role: m.role as 'user' | 'assistant',
                      content: m.content,
                    })));
                    if (session.context) {
                      setMockContext(session.context);
                    }
                  }}
                />
              </div>
            </div>

            {/* Main two-column layout — fills remaining viewport */}
            <div className="flex-1 flex gap-3 min-h-0">
              {/* Left column: Graph + Chat (60%) */}
              <div className="flex flex-col gap-3 min-h-0" style={{ flex: '0 0 60%' }}>
                {/* Graph canvas — flex-grow */}
                <div className="dash-card relative flex-1 min-h-0" style={{ overflow: 'hidden' }}>
                  {graphNodes.length > 0 ? (
                    <FlowGraphCanvas
                      nodes={graphNodes}
                      edges={graphEdges}
                      activeNodeId={flow.activeNodeId}
                      completedNodeIds={completedNodeIds}
                      failedNodeIds={flow.failedNodes}
                      traversedEdgeKeys={traversedEdgeKeys}
                    />
                  ) : (
                    <div className="flex items-center justify-center h-full text-[var(--text-muted)] text-sm">
                      No graph data available for this agent
                    </div>
                  )}
                </div>

                {/* Chat area — fixed height at bottom of left column */}
                <div className="dash-card relative flex flex-col flex-shrink-0" style={{ height: '280px', overflow: 'hidden' }}>
                  {/* Messages — scrollable */}
                  <div className="flex-1 overflow-y-auto p-3 space-y-2 min-h-0">
                    {messages.length === 0 && (
                      <div className="flex items-center justify-center h-full">
                        <p className="text-[var(--text-muted)] text-sm">
                          Click "Start Flow" to begin the conversation
                        </p>
                      </div>
                    )}
                    {messages.map((msg, i) => (
                      <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                        <div className={`flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center ${
                          msg.role === 'user' ? 'bg-blue-500/20' : 'bg-purple-500/20'
                        }`}>
                          {msg.role === 'user' ? (
                            <User size={12} className="text-blue-400" />
                          ) : (
                            <Bot size={12} className="text-purple-400" />
                          )}
                        </div>
                        <div className={`max-w-[75%] rounded-xl px-3 py-2 text-sm leading-relaxed ${
                          msg.role === 'user'
                            ? 'bg-blue-500/20 text-blue-100'
                            : 'bg-[var(--bg-secondary)] border border-[var(--glass-border)]'
                        }`}>
                          {msg.content}
                          {sending && i === messages.length - 1 && msg.role === 'assistant' && (
                            <span className="inline-block w-2 h-4 ml-1 bg-purple-400 animate-pulse rounded-sm" />
                          )}
                        </div>
                      </div>
                    ))}
                    {sending && messages.length > 0 && messages[messages.length - 1].role === 'user' && (
                      <div className="flex gap-3">
                        <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center bg-purple-500/20">
                          <Bot size={12} className="text-purple-400" />
                        </div>
                        <div className="bg-[var(--bg-secondary)] border border-[var(--glass-border)] rounded-xl px-3 py-2">
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

                  {/* Input — pinned at bottom */}
                  <div className="p-3 border-t border-[var(--glass-border)] flex-shrink-0">
                    <div className="flex gap-2 items-end">
                      <textarea
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault();
                            handleSend();
                          }
                        }}
                        placeholder="Type a message..."
                        rows={1}
                        className="input-base flex-1 rounded-xl px-3 py-2.5 resize-none text-sm"
                        style={{ maxHeight: '80px' }}
                        disabled={!flow.connected || sending}
                      />
                      <button
                        onClick={handleSend}
                        disabled={!input.trim() || !flow.connected || sending}
                        className="btn-primary p-2.5 rounded-xl disabled:opacity-40"
                      >
                        {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                      </button>
                    </div>
                    <p className="text-[10px] text-[var(--text-muted)] mt-1.5 text-center opacity-60">
                      Enter to send · Shift+Enter for new line
                    </p>
                  </div>
                </div>
              </div>

              {/* Right column: Tabbed panel (40%) */}
              <div className="flex flex-col min-h-0 flex-1">
                {/* Tab bar */}
                <div className="dash-card flex items-center gap-1 px-2 flex-shrink-0 mb-3" style={{ overflow: 'hidden' }}>
                  <button
                    onClick={() => setRightTab('trace')}
                    className={`${tabBtnBase} ${rightTab === 'trace' ? tabBtnActive : tabBtnInactive}`}
                  >
                    <Play size={12} />
                    Trace
                  </button>
                  <button
                    onClick={() => setRightTab('context')}
                    className={`${tabBtnBase} ${rightTab === 'context' ? tabBtnActive : tabBtnInactive}`}
                  >
                    <Settings2 size={12} />
                    Context
                  </button>
                  <button
                    onClick={() => setRightTab('caller')}
                    className={`${tabBtnBase} ${rightTab === 'caller' ? tabBtnActive : tabBtnInactive}`}
                  >
                    <Phone size={12} />
                    Caller
                  </button>
                  <button
                    onClick={() => setRightTab('variables')}
                    className={`${tabBtnBase} ${rightTab === 'variables' ? tabBtnActive : tabBtnInactive}`}
                  >
                    <Database size={12} />
                    Variables
                  </button>
                </div>

                {/* Tab content — fills remaining height, scrollable */}
                <div className="flex-1 min-h-0">
                  {rightTab === 'trace' && (
                    <ExecutionTrace events={flow.traceEvents} activeNodeId={flow.activeNodeId} />
                  )}
                  {rightTab === 'context' && (
                    <MockContextEditor context={mockContext} onApply={handleApplyContext} />
                  )}
                  {rightTab === 'caller' && (
                    <CallerExperienceView events={flow.traceEvents} agentResponses={flow.agentResponses} />
                  )}
                  {rightTab === 'variables' && (
                    <VariablesPanel events={flow.traceEvents} />
                  )}
                </div>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </GsapPageWrapper>
  );
}
