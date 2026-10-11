'use client';

import { useState, useEffect, useRef } from 'react';
import { Link2, X, Loader2, Check } from 'lucide-react';
import { agents as agentsApi } from '@/lib/api';
import { useToast } from '@/components/ui/toast';

interface LinkAgentsModalProps {
  kbId: number;
  kbName: string;
  linkedAgentIds: number[];
  onLink: (agentIds: number[]) => Promise<void>;
  onClose: () => void;
}

function useModalFocusTrap(active: boolean, onClose: () => void) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!active) {
      return;
    }

    const container = containerRef.current;
    if (!container) {
      return;
    }

    const focusableSelector =
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
    const getFocusableElements = () =>
      Array.from(container.querySelectorAll<HTMLElement>(focusableSelector)).filter(
        (element) => !element.hasAttribute('disabled'),
      );

    const previousActiveElement = document.activeElement as HTMLElement | null;
    const initialFocus = getFocusableElements()[0] || container;
    initialFocus.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }

      if (event.key !== 'Tab') {
        return;
      }

      const focusableElements = getFocusableElements();
      if (focusableElements.length === 0) {
        event.preventDefault();
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement as HTMLElement | null;

      if (event.shiftKey && activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previousActiveElement?.focus();
    };
  }, [active, onClose]);

  return containerRef;
}

export function LinkAgentsModal({ kbId, kbName, linkedAgentIds, onLink, onClose }: LinkAgentsModalProps) {
  const { error: toastError } = useToast();
  const [allAgents, setAllAgents] = useState<Array<{ id: number; name: string }>>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set(linkedAgentIds));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const dialogRef = useModalFocusTrap(true, onClose);

  useEffect(() => {
    agentsApi.list().then((data) => {
      setAllAgents(data.agents.map((a) => ({ id: a.id, name: a.name })));
      setLoading(false);
    }).catch(() => {
      toastError('Failed to load agents');
      setLoading(false);
    });
  }, []);

  function toggle(agentId: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) next.delete(agentId);
      else next.add(agentId);
      return next;
    });
  }

  async function handleSave() {
    setSaving(true);
    try {
      await onLink(Array.from(selected));
      onClose();
    } catch {
      toastError('Failed to update agent links');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="link-agents-title"
        aria-describedby="link-agents-description"
        tabIndex={-1}
        className="bg-[var(--bg-secondary)] rounded-xl p-6 w-full max-w-md shadow-2xl"
      >
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 id="link-agents-title" className="font-semibold">Link to Agents</h3>
            <p id="link-agents-description" className="text-xs text-[var(--text-muted)]">
              Choose which agents can access {kbName}.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close link agents dialog" className="btn-ghost p-1">
            <X size={16} />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={20} className="animate-spin text-[var(--accent)]" />
          </div>
        ) : allAgents.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)] text-center py-6">
            No agents found. Create an agent first.
          </p>
        ) : (
          <div className="space-y-1 max-h-64 overflow-y-auto pr-1">
            {allAgents.map((agent) => {
              const isLinked = selected.has(agent.id);
              return (
                <button
                  key={agent.id}
                  onClick={() => toggle(agent.id)}
                  type="button"
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors ${
                    isLinked
                      ? 'bg-[var(--accent)]/10 border border-[var(--accent)]/20'
                      : 'hover:bg-[var(--bg-tertiary)] border border-transparent'
                  }`}
                >
                  <div
                    className={`w-5 h-5 rounded border flex items-center justify-center transition-colors ${
                      isLinked
                        ? 'bg-[var(--accent)] border-[var(--accent)]'
                        : 'border-[var(--border-color)]'
                    }`}
                  >
                    {isLinked && <Check size={12} className="text-white" />}
                  </div>
                  <span className="text-sm">{agent.name}</span>
                </button>
              );
            })}
          </div>
        )}

        <div className="flex gap-3 mt-4">
          <button onClick={onClose} type="button" className="btn-ghost flex-1">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            type="button"
            className="btn-primary flex-1 disabled:opacity-40"
          >
            {saving ? (
              <>
                <Loader2 size={14} className="animate-spin" /> Saving...
              </>
            ) : (
              <>
                <Link2 size={14} /> Save Links
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
