'use client';

import { AlertTriangle, RefreshCw } from 'lucide-react';

interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-4">
      <div className="w-14 h-14 rounded-2xl bg-red-500/10 flex items-center justify-center">
        <AlertTriangle size={28} className="text-red-400" />
      </div>
      <div className="text-center space-y-1.5">
        <h3 className="text-sm font-semibold">Something went wrong</h3>
        <p className="text-sm text-[var(--text-muted)] max-w-md">
          {message || 'An unexpected error occurred while loading this content.'}
        </p>
      </div>
      {onRetry && (
        <button onClick={onRetry} className="btn-primary">
          <RefreshCw size={15} /> Try Again
        </button>
      )}
    </div>
  );
}
