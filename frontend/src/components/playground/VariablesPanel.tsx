'use client';

import { useMemo } from 'react';
import type { TraceEvent } from '@/hooks/use-flow-playground';
import { Database } from 'lucide-react';

interface VariablesPanelProps {
  events: TraceEvent[];
}

export function VariablesPanel({ events }: VariablesPanelProps) {
  // Aggregate all extracted variables sequentially to get current state
  const currentVariables = useMemo(() => {
    const vars: Record<string, string> = {};
    events.forEach(event => {
      if (event.type === 'variables_extracted' && event.result) {
        const extracted = event.result as Record<string, unknown>;
        for (const [key, val] of Object.entries(extracted)) {
          if (val !== undefined && val !== null) {
            vars[key] = String(val);
          }
        }
      }
    });
    return vars;
  }, [events]);

  const hasVariables = Object.keys(currentVariables).length > 0;

  return (
    <div className="flex flex-col h-full dash-card overflow-hidden bg-[var(--bg-secondary)]">
      <div className="flex items-center px-4 py-3 border-b border-[var(--glass-border)] bg-[var(--bg-primary)]">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Database size={14} className="text-brand-400" />
          Extracted Variables
        </h3>
      </div>
      
      <div className="flex-1 overflow-y-auto p-4">
        {!hasVariables ? (
          <div className="flex flex-col items-center justify-center h-full text-[var(--text-muted)] space-y-2">
            <Database size={24} className="opacity-20" />
            <span className="text-xs">No variables extracted yet.</span>
            <span className="text-[10px] text-center max-w-[200px] opacity-70">
              Variables will appear here as the caller provides them during the conversation.
            </span>
          </div>
        ) : (
          <div className="space-y-2">
            {Object.entries(currentVariables).map(([key, value]) => (
              <div 
                key={key} 
                className="flex flex-col p-2 rounded-md bg-[var(--bg-tertiary)] border border-[var(--glass-border)]"
              >
                <span className="text-[10px] text-[var(--text-muted)] font-mono mb-1">{key}</span>
                <span className="text-xs text-[var(--text-primary)] font-medium break-all">{value}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
