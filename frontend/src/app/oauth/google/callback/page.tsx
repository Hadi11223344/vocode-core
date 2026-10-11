'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, CheckCircle, Loader2 } from 'lucide-react';
import { integrations as integrationsApi } from '@/lib/api';

export default function GoogleOAuthCallbackPage() {
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [message, setMessage] = useState('Completing Google connection...');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');

    if (!code || !state) {
      setStatus('error');
      setMessage('Missing Google OAuth code or state. Please retry the connection.');
      return;
    }

    let cancelled = false;

    integrationsApi.googleCallback(code, state)
      .then(() => {
        if (cancelled) return;
        setStatus('success');
        setMessage('Google account connected. This window will close automatically.');
        window.history.replaceState({}, document.title, window.location.pathname);
        window.setTimeout(() => {
          window.close();
        }, 500);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setStatus('error');
        setMessage(err instanceof Error ? err.message : 'Failed to complete Google OAuth.');
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg-primary)] p-6">
      <div className="w-full max-w-md rounded-2xl border border-[var(--border-color)] bg-[var(--bg-secondary)] p-6 text-center shadow-xl">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-[var(--border-color)] bg-[var(--bg-primary)]">
          {status === 'loading' && <Loader2 className="h-6 w-6 animate-spin text-brand-400" />}
          {status === 'success' && <CheckCircle className="h-6 w-6 text-green-400" />}
          {status === 'error' && <AlertTriangle className="h-6 w-6 text-amber-400" />}
        </div>

        <h1 className="text-lg font-semibold text-[var(--text-primary)]">
          {status === 'error' ? 'Google connection failed' : 'Connecting Google account'}
        </h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">{message}</p>

        <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-center">
          <button
            type="button"
            onClick={() => window.close()}
            className="btn-primary"
          >
            Close window
          </button>
          <Link
            href="/dashboard/integrations"
            className="rounded-lg border border-[var(--border-color)] px-4 py-2 text-sm text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-primary)]"
          >
            Return to integrations
          </Link>
        </div>
      </div>
    </div>
  );
}