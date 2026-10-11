'use client';

import { useRef, useEffect, useMemo } from 'react';
import { Bot, Wrench, GitBranch, FileText, Phone } from 'lucide-react';
import type { TraceEvent } from '@/hooks/use-flow-playground';

interface CallerExperienceProps {
  events: TraceEvent[];
  agentResponses: { nodeId: string; text: string }[];
}

interface TimelineEntry {
  timestamp: number;
  callerText?: string;
  agentText?: string;
  internalActions: { icon: typeof Wrench; label: string; detail?: string }[];
}

export function CallerExperienceView({ events, agentResponses }: CallerExperienceProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events, agentResponses]);

  // Build timeline from events
  const timeline = useMemo(() => buildTimeline(events), [events]);

  return (
    <div className="flex flex-col h-full dash-card overflow-hidden">
      <div className="flex items-center px-4 py-3 border-b border-[var(--glass-border)]">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Phone size={14} className="text-brand-400" />
          Caller Experience
        </h3>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-3">
        {timeline.length === 0 && (
          <div className="flex items-center justify-center h-full text-[var(--text-muted)] text-xs">
            Start the flow to see what the caller experiences.
          </div>
        )}
        {timeline.map((entry, i) => (
          <TimelineRow key={i} entry={entry} />
        ))}
      </div>
    </div>
  );
}

function buildTimeline(
  events: TraceEvent[]
): TimelineEntry[] {
  const entries: TimelineEntry[] = [];
  let currentEntry: TimelineEntry | null = null;

  for (const event of events) {
    switch (event.type) {
      case 'flow_start':
        currentEntry = { timestamp: event.timestamp, internalActions: [] };
        entries.push(currentEntry);
        break;

      case 'node_result':
        if (!currentEntry) {
          currentEntry = { timestamp: event.timestamp, internalActions: [] };
          entries.push(currentEntry);
        }

        if (event.nodeType === 'conversation' && event.status === 'success') {
          // Agent response is handled separately via agentResponses
        } else if (event.nodeType && !['trigger', 'end', 'end_call', 'conversation'].includes(event.nodeType)) {
          const icon = getActionIcon(event.nodeType);
          const label = event.label || event.nodeId || event.nodeType;
          const detail = event.error
            ? `Error: ${event.error}`
            : event.result
              ? truncateResult(event.result)
              : undefined;
          currentEntry.internalActions.push({ icon, label, detail });
        }
        break;

      case 'condition_branch':
        if (!currentEntry) {
          currentEntry = { timestamp: event.timestamp, internalActions: [] };
          entries.push(currentEntry);
        }
        currentEntry.internalActions.push({
          icon: GitBranch,
          label: `Condition evaluated`,
          detail: `Branch: ${event.conditionMet ? 'YES' : 'NO'}`,
        });
        break;

      case 'agent_response':
        if (!currentEntry) {
          currentEntry = { timestamp: event.timestamp, internalActions: [] };
          entries.push(currentEntry);
        }
        currentEntry.agentText = event.text;
        break;

      case 'flow_end':
        currentEntry = null;
        break;
    }
  }

  return entries;
}

function truncateResult(result: unknown): string {
  const str = typeof result === 'string' ? result : JSON.stringify(result);
  return str.length > 100 ? str.slice(0, 100) + '...' : str;
}

function getActionIcon(nodeType: string): typeof Wrench {
  const iconMap: Record<string, typeof Wrench> = {
    google_calendar: FileText,
    google_sheets: FileText,
    google_drive_mcp: FileText,
    sms: Phone,
    email: FileText,
    knowledge_base: FileText,
    webhook: Wrench,
    delay: Wrench,
    notification: Wrench,
    transfer_call: Phone,
    send_sms: Phone,
    send_email: FileText,
    mcp_tool: Wrench,
    custom_api: Wrench,
    note: FileText,
    code: Wrench,
    extract_variable: GitBranch,
    subagent: Bot,
    llm_process: Bot,
  };
  return iconMap[nodeType] || Wrench;
}

function TimelineRow({ entry }: { entry: TimelineEntry }) {
  return (
    <div className="space-y-2">
      {/* Agent response (what caller hears) */}
      {entry.agentText && (
        <div className="flex gap-2.5">
          <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center bg-brand-500/20">
            <Bot size={14} className="text-brand-400" />
          </div>
          <div className="flex-1">
            <div className="text-[10px] text-[var(--text-muted)] mb-0.5">Caller hears</div>
            <div className="bg-[var(--bg-secondary)] border border-[var(--glass-border)] rounded-xl px-3 py-2 text-sm text-[var(--text-secondary)] leading-relaxed">
              {entry.agentText}
            </div>
          </div>
        </div>
      )}

      {/* Internal actions (what agent does) */}
      {entry.internalActions.length > 0 && (
        <div className="flex gap-2.5">
          <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center bg-purple-500/20">
            <Wrench size={12} className="text-purple-400" />
          </div>
          <div className="flex-1 space-y-1">
            <div className="text-[10px] text-[var(--text-muted)] mb-0.5">Agent does</div>
            {entry.internalActions.map((action, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                <action.icon size={11} className="text-purple-400 flex-shrink-0" />
                <span className="text-[var(--text-secondary)]">{action.label}</span>
                {action.detail && (
                  <span className="text-[10px] text-[var(--text-muted)] truncate">{action.detail}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
