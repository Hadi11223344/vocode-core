'use client';

import { Play, X } from 'lucide-react';
import { useOnboarding } from '@/hooks/useOnboarding';

interface ResumeCardProps {
  onResume: () => void;
}

export function ResumeCard({ onResume }: ResumeCardProps) {
  const { dismiss, state } = useOnboarding();

  if (!state.started || state.completed) return null;

  return (
    <div className="fixed bottom-6 right-6 z-40 animate-slide-up">
      <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-xl shadow-2xl p-4 w-72">
        <div className="flex items-start justify-between mb-2">
          <div>
            <h4 className="font-semibold text-sm">Getting Started</h4>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Step {state.currentStep + 1} of 5
            </p>
          </div>
          <button onClick={dismiss} className="btn-ghost p-1 -mt-1 -mr-1">
            <X size={14} />
          </button>
        </div>
        <p className="text-xs text-[var(--text-secondary)] mb-3">
          You were creating your first agent. Pick up where you left off.
        </p>
        <button onClick={onResume} className="btn-primary w-full text-xs py-2">
          <Play size={14} /> Resume
        </button>
      </div>
    </div>
  );
}
