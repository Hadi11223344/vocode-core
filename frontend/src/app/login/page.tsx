'use client';

import { useAuth } from '@/lib/auth-context';
import { useToast } from '@/components/ui/toast';
import { useRouter } from 'next/navigation';
import { useEffect, useCallback, useState } from 'react';
import { auth as authApi, setToken, setRefreshToken } from '@/lib/api';
import { Zap, Plug, BarChart3, ShieldCheck } from 'lucide-react';

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: Record<string, unknown>) => void;
          renderButton: (el: HTMLElement, config: Record<string, unknown>) => void;
        };
      };
    };
  }
}

export default function LoginPage() {
  const { user, loading, login } = useAuth();
  const router = useRouter();
  const [devLoading, setDevLoading] = useState(false);
  const [error, setError] = useState('');
  const { apiError: toastError } = useToast();

  useEffect(() => {
    if (!loading && user) {
      router.push('/dashboard');
    }
  }, [user, loading, router]);

  const handleCredentialResponse = useCallback(
    async (response: { credential?: string; error?: string; details?: string }) => {
      if (response.error) {
        console.error('Google sign-in error:', response.error, response.details);
        setError(`Google sign-in error: ${response.error}. Check browser console for details.`);
        return;
      }
      if (!response.credential) {
        setError('Google sign-in returned no credential. Try again.');
        return;
      }
      try {
        await login(response.credential);
        router.push('/dashboard');
      } catch (err) {
        console.error('Login failed:', err);
        const isConnectionError =
          (err instanceof TypeError && err.message === 'Failed to fetch') ||
          (err instanceof Error && err.message.includes('Cannot connect to backend'));
        const isBackendError = err instanceof Error && err.message.includes('Google account email must be verified');
        let msg: string;
        if (isConnectionError) {
          msg = 'Cannot reach backend at localhost:3000 — is the server running?';
        } else if (isBackendError) {
          msg = 'Your Google account email is not verified. Verify it and try again.';
        } else if (err instanceof Error) {
          msg = `Google login failed: ${err.message}`;
        } else {
          msg = 'Google login failed. Try Dev Login instead.';
        }
        setError(msg);
        toastError(err, msg);
      }
    },
    [login, router, toastError],
  );

  const handleDevLogin = async () => {
    setDevLoading(true);
    setError('');
    try {
      const data = await authApi.devLogin();
      setToken(data.access_token);
      setRefreshToken(data.refresh_token);
      // Force reload to pick up the new token
      window.location.href = '/dashboard';
    } catch (err) {
      console.error('Dev login failed:', err);
      const msg = err instanceof Error ? err.message : 'Dev login failed — is the backend running on localhost:3000?';
      setError(msg);
      toastError(err, msg);
    } finally {
      setDevLoading(false);
    }
  };

  const [scriptError, setScriptError] = useState('');

  useEffect(() => {
    const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
    if (!clientId) {
      setScriptError('Google Client ID not configured. Add NEXT_PUBLIC_GOOGLE_CLIENT_ID to frontend .env.local');
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.defer = true;
    script.onload = () => {
      if (!window.google?.accounts?.id) {
        setScriptError('Google Sign-In script loaded but API unavailable.');
        return;
      }
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: handleCredentialResponse,
      });
      const btnEl = document.getElementById('google-signin-btn');
      if (btnEl) {
        window.google.accounts.id.renderButton(btnEl, {
          theme: 'filled_black',
          size: 'large',
          width: 320,
          text: 'signin_with',
          shape: 'pill',
        });
      }
    };
    script.onerror = () => {
      setScriptError('Failed to load Google Sign-In script. Check your internet connection.');
    };
    document.head.appendChild(script);
    return () => { script.remove(); };
  }, [handleCredentialResponse]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg-primary)]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 rounded-2xl gradient-brand flex items-center justify-center dash-logo-pulse">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            </svg>
          </div>
          <div className="dash-progress-bar" />
        </div>
      </div>
    );
  }

  const features = [
    { icon: Zap, title: 'Deploy in 5 minutes', desc: 'From signup to first call in under 5 minutes.' },
    { icon: Plug, title: '30+ integrations', desc: 'CRM, messaging, calendars, payments & more.' },
    { icon: BarChart3, title: 'Real-time analytics', desc: 'Live transcripts, sentiment, call quality.' },
    { icon: ShieldCheck, title: 'SOC 2 & HIPAA', desc: 'Enterprise-grade security & compliance.' },
  ];

  return (
    <div className="login-split bg-[var(--bg-primary)]">
      {/* Left panel — brand + features */}
      <div className="login-split-left relative flex flex-col justify-center px-12 xl:px-20 overflow-hidden">
        {/* Aurora background */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-brand-600/[0.08] rounded-full blur-[100px]" />
          <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-purple-600/[0.06] rounded-full blur-[100px]" />
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-72 h-72 bg-cyan-600/[0.04] rounded-full blur-[80px]" />
        </div>

        <div className="relative z-10 max-w-md">
          {/* Logo */}
          <div className="flex items-center gap-3 mb-10">
            <div className="w-12 h-12 rounded-2xl gradient-brand flex items-center justify-center shadow-glow">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">VOIA</h1>
              <p className="text-[var(--text-muted)] text-xs">Voice AI Agent Platform</p>
            </div>
          </div>

          {/* Headline */}
          <h2 className="text-3xl xl:text-4xl font-bold tracking-tight leading-tight mb-3">
            Build, deploy & scale<br />
            <span className="text-gradient-animated">AI voice agents</span>
          </h2>
          <p className="text-[var(--text-secondary)] text-sm leading-relaxed mb-10">
            Production-ready voice AI for inbound support, outbound sales, and everything in between.
          </p>

          {/* Feature list */}
          <div className="space-y-5">
            {features.map((f) => (
              <div key={f.title} className="login-feature-item">
                <div className="w-10 h-10 rounded-xl bg-brand-500/10 border border-brand-500/20 flex items-center justify-center flex-shrink-0">
                  <f.icon size={18} className="text-brand-400" />
                </div>
                <div>
                  <p className="text-sm font-semibold">{f.title}</p>
                  <p className="text-xs text-[var(--text-muted)] mt-0.5">{f.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right panel — login card */}
      <div className="flex items-center justify-center p-6 relative overflow-hidden">
        {/* Subtle aurora for mobile */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-brand-600/[0.04] rounded-full blur-[100px]" />
          <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-purple-600/[0.04] rounded-full blur-[100px]" />
        </div>

        <div className="w-full max-w-sm relative z-10">
          {/* Mobile logo */}
          <div className="text-center mb-8 md:hidden">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl gradient-brand shadow-glow mb-4">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
            </div>
            <h1 className="text-2xl font-bold tracking-tight">VOIA</h1>
            <p className="text-[var(--text-muted)] text-sm mt-1.5">Voice AI Agent Platform</p>
          </div>

          {/* Glass card */}
          <div className="dash-card p-7">
            <h2 className="text-lg font-semibold text-center mb-1">Welcome back</h2>
            <p className="text-[var(--text-muted)] text-[13px] text-center mb-6">
              Sign in to manage your voice agents
            </p>

            {(error || scriptError) && (
              <div className="dash-error-banner mb-5 p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-[13px] text-center leading-relaxed">
                {error || scriptError}
              </div>
            )}

            <div className="flex justify-center">
              <div id="google-signin-btn" />
            </div>

            <div className="relative my-6">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-[var(--border-color)]" />
              </div>
              <div className="relative flex justify-center text-[11px]">
                <span className="px-3 bg-[var(--bg-card)] text-[var(--text-muted)]">or for development</span>
              </div>
            </div>

            <button
              onClick={handleDevLogin}
              disabled={devLoading}
              className="w-full btn-secondary shimmer-sweep py-3 rounded-xl"
            >
              {devLoading ? 'Signing in...' : '⚡ Dev Login (No Google Required)'}
            </button>

            <p className="text-[var(--text-muted)] text-[11px] text-center mt-5">
              Dev login requires ALLOW_DEV_LOGIN=true on the backend (local / playground only)
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
