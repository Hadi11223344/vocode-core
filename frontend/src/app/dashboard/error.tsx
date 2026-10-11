'use client';

import { AlertTriangle, RefreshCw } from 'lucide-react';

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 p-6">
      <div className="w-14 h-14 rounded-2xl bg-red-500/10 flex items-center justify-center">
        <AlertTriangle size={28} className="text-red-400" />
      </div>
      <div className="text-center space-y-1.5">
        <h2 className="text-lg font-semibold">Something went wrong</h2>
        <p className="text-sm text-[var(--text-muted)] max-w-md">
          {error.message || 'An unexpected error occurred while loading this page.'}
        </p>
      </div>
      <button onClick={reset} className="btn-primary">
        <RefreshCw size={15} /> Try Again
      </button>
    </div>
  );
}
