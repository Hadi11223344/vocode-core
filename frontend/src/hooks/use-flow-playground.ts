'use client';

import { useRef, useState, useCallback, useEffect } from 'react';
import { getToken } from '@/lib/api';

export interface FlowNodeEvent {
  node_id: string;
  node_type: string;
  label: string;
  status?: string;
  result?: unknown;
  duration_ms?: number;
  error?: string;
  reason?: string;
}

export interface FlowEdgeEvent {
  source: string;
  target: string;
  label: string;
}

export interface FlowRuntimeIdentity {
  agent_id: string | null;
  workflow_id?: number | null;
  execution_channel: string;
  graph_hash: string | null;
  prompt_version_or_hash: string | null;
  thread_id: string | null;
  context_profile?: string;
  memory_mode?: string;
}

export interface FlowPlaygroundState {
  connected: boolean;
  connecting: boolean;
  started: boolean;
  activeNodeId: string | null;
  completedNodes: Map<string, FlowNodeEvent>;
  failedNodes: Set<string>;
  traversedEdges: FlowEdgeEvent[];
  traceEvents: TraceEvent[];
  agentResponses: { nodeId: string; text: string }[];
  streamingText: string;
  streamingNodeId: string | null;
  error: string | null;
  flowStartTime: number | null;
  runtimeIdentity: FlowRuntimeIdentity | null;
}

export interface TraceEvent {
  id: number;
  type: 'node_start' | 'node_result' | 'edge_traversed' | 'condition_branch' | 'agent_response' | 'flow_start' | 'flow_end' | 'error' | 'info' | 'debug' | 'context_updated' | 'variables_extracted' | 'extraction_failed' | 'slot_validation' | 'slot_exhausted';
  nodeId?: string;
  nodeType?: string;
  label?: string;
  status?: string;
  result?: unknown;
  durationMs?: number;
  error?: string;
  conditionMet?: boolean;
  source?: string;
  target?: string;
  edgeLabel?: string;
  text?: string;
  totalNodes?: number;
  variables?: string[];
  slot?: string;
  rawValue?: string;
  normalizedValue?: string;
  timestamp: number;
}

interface UseFlowPlaygroundOptions {
  agentId: number | null;
  workflowId?: number | null;
  expectedGraphHash?: string | null;
  onAgentResponse?: (nodeId: string, text: string) => void;
  onFlowEnd?: (totalNodes: number) => void;
  onError?: (text: string) => void;
}

export function useFlowPlayground(options: UseFlowPlaygroundOptions) {
  const {
    agentId,
    workflowId,
    expectedGraphHash,
    onAgentResponse,
    onFlowEnd,
    onError,
  } = options;
  const wsRef = useRef<WebSocket | null>(null);
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const traceIdRef = useRef(0);
  const pendingTokensRef = useRef<string>('');
  const streamingNodeIdRef = useRef<string | null>(null);
  const fatalErrorRef = useRef(false);

  // Refs for callbacks to avoid stale closures in WS handlers
  const onAgentResponseRef = useRef(onAgentResponse);
  onAgentResponseRef.current = onAgentResponse;
  const onFlowEndRef = useRef(onFlowEnd);
  onFlowEndRef.current = onFlowEnd;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const [state, setState] = useState<FlowPlaygroundState>({
    connected: false,
    connecting: false,
    started: false,
    activeNodeId: null,
    completedNodes: new Map(),
    failedNodes: new Set(),
    traversedEdges: [],
    traceEvents: [],
    agentResponses: [],
    streamingText: '',
    streamingNodeId: null,
    error: null,
    flowStartTime: null,
    runtimeIdentity: null,
  });

  const addTraceEvent = useCallback((event: Omit<TraceEvent, 'id' | 'timestamp'>) => {
    traceIdRef.current += 1;
    const traceEvent: TraceEvent = {
      ...event,
      id: traceIdRef.current,
      timestamp: Date.now(),
    };
    setState((prev) => ({
      ...prev,
      traceEvents: [...prev.traceEvents, traceEvent].slice(-200),
    }));
    return traceEvent;
  }, []);

  const resetState = useCallback(() => {
    traceIdRef.current = 0;
    pendingTokensRef.current = '';
    setState({
      connected: false,
      connecting: false,
      started: false,
      activeNodeId: null,
      completedNodes: new Map(),
      failedNodes: new Set(),
      traversedEdges: [],
      traceEvents: [],
      agentResponses: [],
      streamingText: '',
      streamingNodeId: null,
      error: null,
      flowStartTime: null,
      runtimeIdentity: null,
    });
  }, []);

  const resetFlowState = useCallback(() => {
    traceIdRef.current = 0;
    pendingTokensRef.current = '';
    setState((prev) => ({
      ...prev,
      started: false,
      activeNodeId: null,
      completedNodes: new Map(),
      failedNodes: new Set(),
      traversedEdges: [],
      traceEvents: [],
      agentResponses: [],
      streamingText: '',
      streamingNodeId: null,
      error: null,
      flowStartTime: null,
      runtimeIdentity: null,
    }));
  }, []);

  const connect = useCallback(() => {
    if (!agentId) return;
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    fatalErrorRef.current = false;
    setState((prev) => ({ ...prev, connecting: true, error: null }));

    const token = getToken();
    if (!token) {
      setState((prev) => ({ ...prev, connecting: false, error: 'Not authenticated' }));
      return;
    }

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3000';
    const wsUrl = apiUrl.replace(/^http/, 'ws');
    const query = new URLSearchParams();
    if (workflowId) query.set('workflow_id', String(workflowId));
    if (expectedGraphHash) query.set('graph_hash', expectedGraphHash);
    const queryString = query.toString() ? `?${query.toString()}` : '';
    const ws = new WebSocket(
      `${wsUrl}/api/playground/ws/${agentId}/flow${queryString}`,
      ['bearer', token],
    );
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectAttemptsRef.current = 0;
      setState((prev) => ({ ...prev, connected: true, connecting: false, error: null }));
      heartbeatRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 30000);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleEvent(data);
      } catch {
        // ignore non-JSON messages
      }
    };

    ws.onerror = () => {
      setState((prev) => ({ ...prev, connecting: false }));
    };

    ws.onclose = (event) => {
      if (event.code === 4009) {
        fatalErrorRef.current = true;
        const message = event.reason || 'The requested workflow revision is no longer active.';
        setState((prev) => ({
          ...prev,
          connected: false,
          connecting: false,
          error: message,
        }));
        onErrorRef.current?.(message);
      } else {
        setState((prev) => ({ ...prev, connected: false, connecting: false }));
      }
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current);
        heartbeatRef.current = null;
      }
      // Auto-reconnect with backoff (skip if fatal error)
      if (!fatalErrorRef.current && reconnectAttemptsRef.current < 5) {
        const delay = Math.min(1000 * 2 ** reconnectAttemptsRef.current, 16000);
        reconnectAttemptsRef.current += 1;
        reconnectTimerRef.current = setTimeout(() => connect(), delay);
      }
    };
  }, [agentId, workflowId, expectedGraphHash]);

  const handleEvent = useCallback((data: Record<string, unknown>) => {
    const eventType = data.type as string;
    const nodeId = (data.node_id as string) || undefined;
    const nodeType = (data.node_type as string) || undefined;
    const label = (data.label as string) || undefined;

    switch (eventType) {
      case 'flow_start':
        addTraceEvent({ type: 'flow_start' });
        setState((prev) => ({ ...prev, started: true, flowStartTime: Date.now() }));
        break;

      case 'node_start':
        addTraceEvent({ type: 'node_start', nodeId, nodeType, label });
        setState((prev) => ({ ...prev, activeNodeId: nodeId || null }));
        break;

      case 'node_result': {
        const status = (data.status as string) || 'unknown';
        const durationMs = data.duration_ms as number | undefined;
        const result = data.result;
        const error = data.error as string | undefined;
        addTraceEvent({ type: 'node_result', nodeId, nodeType, label, status, result, durationMs, error });

        setState((prev) => {
          const completed = new Map(prev.completedNodes);
          const failed = new Set(prev.failedNodes);
          if (nodeId) {
            completed.set(nodeId, {
              node_id: nodeId,
              node_type: nodeType || '',
              label: label || nodeId,
              status,
              result,
              duration_ms: durationMs,
              error,
            });
            if (status === 'error') {
              failed.add(nodeId);
            }
          }
          return {
            ...prev,
            completedNodes: completed,
            failedNodes: failed,
          };
        });
        break;
      }

      case 'edge_traversed': {
        const source = (data.source as string) || '';
        const target = (data.target as string) || '';
        const edgeLabel = (data.label as string) || '';
        addTraceEvent({ type: 'edge_traversed', source, target, edgeLabel });
        setState((prev) => ({
          ...prev,
          traversedEdges: [...prev.traversedEdges, { source, target, label: edgeLabel }],
        }));
        break;
      }

      case 'condition_branch': {
        const conditionMet = data.condition_met as boolean;
        addTraceEvent({ type: 'condition_branch', nodeId, conditionMet });
        break;
      }

      case 'agent_token': {
        const text = (data.text as string) || '';
        pendingTokensRef.current += text;
        if (nodeId) streamingNodeIdRef.current = nodeId;
        // Update streaming state so the UI can display tokens incrementally
        setState((prev) => ({
          ...prev,
          streamingText: pendingTokensRef.current,
          streamingNodeId: nodeId || prev.streamingNodeId,
        }));
        break;
      }

      case 'agent_response': {
        const text = (data.text as string) || pendingTokensRef.current;
        pendingTokensRef.current = '';
        streamingNodeIdRef.current = null;
        addTraceEvent({ type: 'agent_response', nodeId, text });
        setState((prev) => ({
          ...prev,
          agentResponses: [...prev.agentResponses, { nodeId: nodeId || '', text }],
          streamingText: '',
          streamingNodeId: null,
        }));
        onAgentResponseRef.current?.(nodeId || '', text);
        break;
      }

      case 'flow_end':
        // Flush any trailing streamed farewell that never got an agent_response.
        if (pendingTokensRef.current.trim()) {
          const leftover = pendingTokensRef.current.trim();
          const leftoverNodeId = streamingNodeIdRef.current || '';
          pendingTokensRef.current = '';
          streamingNodeIdRef.current = null;
          addTraceEvent({ type: 'agent_response', nodeId: leftoverNodeId || undefined, text: leftover });
          setState((prev) => ({
            ...prev,
            agentResponses: [...prev.agentResponses, { nodeId: leftoverNodeId, text: leftover }],
            streamingText: '',
            streamingNodeId: null,
          }));
          onAgentResponseRef.current?.(leftoverNodeId, leftover);
        }
        addTraceEvent({ type: 'flow_end', totalNodes: data.total_nodes as number });
        setState((prev) => ({ ...prev, activeNodeId: null }));
        onFlowEndRef.current?.(data.total_nodes as number);
        break;

      case 'error':
        addTraceEvent({ type: 'error', text: data.text as string, nodeId });
        setState((prev) => ({ ...prev, activeNodeId: null, error: data.text as string }));
        if (data.fatal) {
          fatalErrorRef.current = true;
        }
        onErrorRef.current?.(data.text as string);
        break;

      case 'info':
        addTraceEvent({ type: 'info', text: data.text as string });
        break;

      case 'debug':
        // Internal debug events — trace only, never shown in chat
        addTraceEvent({ type: 'debug', text: data.text as string });
        break;

      case 'context_updated':
        addTraceEvent({ type: 'context_updated' });
        break;

      case 'variables_extracted':
        addTraceEvent({ type: 'variables_extracted', result: data.variables, nodeId });
        break;

      case 'extraction_failed':
        addTraceEvent({ type: 'extraction_failed', variables: data.variables as string[], text: data.text as string, nodeId });
        break;

      case 'slot_validation':
        addTraceEvent({
          type: 'slot_validation',
          nodeId,
          slot: data.slot as string,
          rawValue: data.raw_value as string,
          normalizedValue: data.normalized_value as string,
          status: data.status as string,
          error: data.error as string,
        });
        break;

      case 'slot_exhausted':
        addTraceEvent({ type: 'slot_exhausted', nodeId, slot: data.slot as string, text: data.text as string });
        break;

      case 'agent_info':
        // Agent info received — no state change needed
        break;

      case 'runtime_identity':
        setState((prev) => ({
          ...prev,
          runtimeIdentity: (data.runtime_identity as FlowRuntimeIdentity) || null,
        }));
        break;

      case 'reset_ack':
        resetFlowState();
        break;

      case 'pong':
        break;
    }
  }, [addTraceEvent, resetFlowState]);

  const sendMessage = useCallback((text: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'message', text }));
    } else {
      setState((prev) => ({ ...prev, error: 'WebSocket not connected. Try reconnecting.' }));
    }
  }, []);

  const startFlow = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'start' }));
    } else {
      setState((prev) => ({ ...prev, error: 'WebSocket not connected. Try reconnecting.' }));
    }
  }, []);

  const setContext = useCallback((context: Record<string, unknown>) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'set_context', context }));
    } else {
      setState((prev) => ({ ...prev, error: 'WebSocket not connected. Try reconnecting.' }));
    }
  }, []);

  const reset = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'reset' }));
    }
    resetFlowState();
  }, [resetFlowState]);

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
    reconnectAttemptsRef.current = 99; // prevent auto-reconnect
    if (wsRef.current) {
      wsRef.current.close(1000, 'Manual disconnect');
      wsRef.current = null;
    }
    setState((prev) => ({ ...prev, connected: false, connecting: false }));
  }, []);

  // Cleanup on unmount or agent change
  useEffect(() => {
    return () => {
      reconnectAttemptsRef.current = 99; // prevent zombie auto-reconnect
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      if (wsRef.current) wsRef.current.close(1000, 'Component unmount');
    };
  }, []);

  // Auto-connect when agentId changes
  useEffect(() => {
    if (agentId) {
      resetState();
      connect();
    } else {
      disconnect();
    }
    return () => {
      reconnectAttemptsRef.current = 99; // prevent zombie reconnect from old WS onclose
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (heartbeatRef.current) clearInterval(heartbeatRef.current);
      if (wsRef.current) {
        wsRef.current.close(1000, 'Agent changed');
        wsRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, workflowId, expectedGraphHash]);

  return {
    ...state,
    connect,
    disconnect,
    sendMessage,
    startFlow,
    setContext,
    reset,
  };
}
