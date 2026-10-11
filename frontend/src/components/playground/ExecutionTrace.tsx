'use client';

import { useState, useRef, useEffect } from 'react';
import {
  CheckCircle,
  XCircle,
  Loader2,
  ChevronRight,
  GitBranch,
  ArrowRight,
  AlertCircle,
  Play,
  Clock,
  SkipForward,
} from 'lucide-react';
import type { TraceEvent } from '@/hooks/use-flow-playground';

interface ExecutionTraceProps {
  events: TraceEvent[];
  activeNodeId: string | null;
}

const STATUS_ICONS: Record<string, typeof CheckCircle> = {
  success: CheckCircle,
  error: XCircle,
  running: Loader2,
  skipped: SkipForward,
};

const STATUS_COLORS: Record<string, string> = {
  success: 'text-green-400',
  error: 'text-red-400',
  running: 'text-amber-400',
  skipped: 'text-blue-400',
  unknown: 'text-[var(--text-muted)]',
};

export function ExecutionTrace({ events, activeNodeId }: ExecutionTraceProps) {
  const [filter, setFilter] = useState<'all' | 'success' | 'error'>('all');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  const filtered = events.filter((e) => {
    if (filter === 'all') return true;
    if (filter === 'error') return e.status === 'error' || e.type === 'error';
    if (filter === 'success') return e.status === 'success';
    return true;
  });

  return (
    <div className="flex flex-col h-full dash-card overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--glass-border)]">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Play size={14} className="text-brand-400" />
          Execution Trace
        </h3>
        <div className="flex gap-1">
          {(['all', 'success', 'error'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2 py-0.5 rounded text-[10px] transition-colors ${
                filter === f
                  ? 'bg-brand-500/20 text-brand-400'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-2 space-y-1">
        {filtered.length === 0 && (
          <div className="flex items-center justify-center h-full text-[var(--text-muted)] text-xs">
            No execution events yet. Start the flow to see trace.
          </div>
        )}
        {filtered.map((event) => (
          <TraceEventRow key={event.id} event={event} isActive={event.nodeId === activeNodeId} />
        ))}
      </div>
    </div>
  );
}

function TraceEventRow({ event, isActive }: { event: TraceEvent; isActive: boolean }) {
  switch (event.type) {
    case 'flow_start':
      return (
        <div className="px-2 py-1.5 rounded-lg bg-brand-500/10 border border-brand-500/20">
          <span className="text-xs text-brand-400 font-medium">▶ Flow started</span>
        </div>
      );

    case 'flow_end':
      return (
        <div className="px-2 py-1.5 rounded-lg bg-[var(--bg-tertiary)]">
          <span className="text-xs text-[var(--text-muted)]">
            ⏹ Flow ended ({event.totalNodes} nodes executed)
          </span>
        </div>
      );

    case 'node_start':
      return (
        <div className={`px-2 py-1.5 rounded-lg flex items-center gap-2 ${
          isActive ? 'bg-amber-500/10 border border-amber-500/20' : ''
        }`}>
          <Loader2 size={12} className="text-amber-400 animate-spin" />
          <div className="flex-1 min-w-0">
            <span className="text-xs font-medium text-[var(--text-secondary)] truncate">
              {event.label || event.nodeId}
            </span>
            <span className="text-[10px] text-[var(--text-muted)] ml-2">
              {event.nodeType}
            </span>
          </div>
        </div>
      );

    case 'node_result': {
      const StatusIcon = STATUS_ICONS[event.status || 'unknown'] || AlertCircle;
      const colorClass = STATUS_COLORS[event.status || 'unknown'];
      return (
        <div className="px-2 py-1.5 rounded-lg bg-[var(--bg-tertiary)]/50">
          <div className="flex items-center gap-2">
            <StatusIcon
              size={12}
              className={`${colorClass} ${event.status === 'running' ? 'animate-spin' : ''}`}
            />
            <div className="flex-1 min-w-0">
              <span className="text-xs font-medium text-[var(--text-secondary)] truncate">
                {event.label || event.nodeId}
              </span>
              {event.durationMs != null && (
                <span className="text-[10px] text-[var(--text-muted)] ml-2 flex items-center gap-0.5 inline-flex">
                  <Clock size={9} />
                  {event.durationMs}ms
                </span>
              )}
            </div>
          </div>
          {event.error && (
            <p className="text-[10px] text-red-400 mt-1 pl-5 break-all">{event.error}</p>
          )}
          {event.result != null && (
            <ResultCollapsible result={event.result} />
          )}
        </div>
      );
    }

    case 'edge_traversed':
      return (
        <div className="px-2 py-1 flex items-center gap-1 text-[10px] text-[var(--text-muted)]">
          <ChevronRight size={10} />
          <span className="truncate">{event.source}</span>
          <ArrowRight size={10} className="text-brand-400" />
          <span className="truncate">{event.target}</span>
          {event.edgeLabel && (
            <span className="ml-1 px-1.5 py-0.5 rounded bg-brand-500/10 text-brand-400 text-[9px]">
              {event.edgeLabel}
            </span>
          )}
        </div>
      );

    case 'condition_branch':
      return (
        <div className="px-2 py-1 flex items-center gap-1.5 text-[10px]">
          <GitBranch size={10} className="text-purple-400" />
          <span className="text-[var(--text-muted)]">Condition:</span>
          <span className={event.conditionMet ? 'text-green-400' : 'text-red-400'}>
            {event.conditionMet ? 'YES' : 'NO'}
          </span>
        </div>
      );

    case 'agent_response':
      return (
        <div className="px-2 py-1.5 rounded-lg bg-brand-500/5 border border-brand-500/10">
          <span className="text-[10px] text-brand-400">Agent: </span>
          <span className="text-xs text-[var(--text-secondary)]">{String(event.text || '')}</span>
        </div>
      );

    case 'error':
      return (
        <div className="px-2 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20">
          <span className="text-xs text-red-400">{event.text}</span>
        </div>
      );

    case 'info':
      return (
        <div className="px-2 py-1.5 rounded-lg bg-blue-500/10 border border-blue-500/20">
          <span className="text-xs text-blue-400">{event.text}</span>
        </div>
      );

    case 'context_updated':
      return (
        <div className="px-2 py-1 text-[10px] text-[var(--text-muted)]">
          Context updated
        </div>
      );

    case 'variables_extracted':
      return (
        <div className="px-2 py-1.5 rounded-lg bg-green-500/10 border border-green-500/20">
          <span className="text-[10px] text-green-400 font-medium flex items-center gap-1.5 mb-1">
            <CheckCircle size={10} />
            Extracted Variables
          </span>
          <div className="flex flex-wrap gap-1 mt-1">
            {Object.entries(event.result as Record<string, unknown> || {}).map(([k, v]) => (
              <span key={k} className="px-1.5 py-0.5 rounded bg-green-500/10 text-[9px] text-green-300 font-mono">
                {k}: {String(v)}
              </span>
            ))}
          </div>
        </div>
      );

    case 'extraction_failed':
      return (
        <div className="px-2 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20">
          <span className="text-[10px] text-red-400 font-medium flex items-center gap-1.5 mb-1">
            <XCircle size={10} />
            Extraction Failed
          </span>
          <div className="text-[10px] text-red-300 mt-0.5">
            {event.text}
          </div>
        </div>
      );

    case 'slot_validation':
      return (
        <div className={`px-2 py-1 flex items-center gap-2 text-[10px] ${event.status === 'invalid' ? 'text-red-400' : 'text-green-400'}`}>
          {event.status === 'invalid' ? <XCircle size={10} /> : <CheckCircle size={10} />}
          <span>Slot <strong>{event.label || event.slot}</strong>:</span>
          <span className="font-mono bg-black/20 px-1 py-0.5 rounded truncate max-w-[150px]">
            {event.text || event.rawValue || event.normalizedValue || 'empty'}
          </span>
          {event.error && <span className="text-red-400 ml-1">({event.error})</span>}
        </div>
      );

    case 'slot_exhausted':
      return (
        <div className="px-2 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
          <span className="text-[10px] text-amber-400 font-medium flex items-center gap-1.5">
            <AlertCircle size={10} />
            {event.text}
          </span>
        </div>
      );

    case 'debug':
      return (
        <div className="px-2 py-1.5 rounded-lg bg-[var(--bg-tertiary)]/30 border border-[var(--glass-border)]">
          <span className="text-[10px] text-[var(--text-muted)] flex items-center gap-1.5 font-mono break-all">
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--text-muted)] opacity-50" />
            {event.text}
          </span>
        </div>
      );

    default:
      return null;
  }
}

function ResultCollapsible({ result }: { result: unknown }) {
  const [expanded, setExpanded] = useState(false);
  const resultStr = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
  const isLong = resultStr.length > 120;

  if (!isLong) {
    return (
      <pre className="text-[10px] text-[var(--text-muted)] mt-1 pl-5 whitespace-pre-wrap break-all font-mono">
        {resultStr}
      </pre>
    );
  }

  return (
    <div className="mt-1 pl-5">
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-[10px] text-brand-400 hover:text-brand-300"
      >
        {expanded ? '▼ Collapse' : '▶ Show result'}
      </button>
      {expanded && (
        <pre className="text-[10px] text-[var(--text-muted)] mt-1 whitespace-pre-wrap break-all font-mono max-h-48 overflow-y-auto">
          {resultStr}
        </pre>
      )}
    </div>
  );
}
