'use client';

import { AlertTriangle, RefreshCw } from 'lucide-react';

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4 p-6 bg-[var(--bg-primary)]">
      <div className="w-14 h-14 rounded-2xl bg-red-500/10 flex items-center justify-center">
        <AlertTriangle size={28} className="text-red-400" />
      </div>
      <div className="text-center space-y-1.5">
        <h2 className="text-lg font-semibold text-[var(--text-primary)]">Application Error</h2>
        <p className="text-sm text-[var(--text-muted)] max-w-md">
          {error.message || 'An unexpected error occurred.'}
        </p>
      </div>
      <button onClick={reset} className="btn-primary">
        <RefreshCw size={15} /> Try Again
      </button>
    </div>
  );
}
