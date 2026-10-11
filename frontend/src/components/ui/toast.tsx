'use client';

import React, { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { CheckCircle2, AlertTriangle, Info, X, XCircle, Wifi, WifiOff } from 'lucide-react';

/* ─── Types ─────────────────────────────────────────────── */
export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface Toast {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  duration?: number; // ms, 0 = persistent
  action?: { label: string; onClick: () => void };
}

interface ToastContextType {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, 'id'>) => string;
  removeToast: (id: string) => void;
  success: (title: string, message?: string) => void;
  error: (title: string, message?: string) => void;
  warning: (title: string, message?: string) => void;
  info: (title: string, message?: string) => void;
  apiError: (err: unknown, fallback?: string) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

/* ─── Hook ─────────────────────────────────────────────── */
export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}

/* ─── Icons ────────────────────────────────────────────── */
const TOAST_CONFIG: Record<ToastType, { icon: typeof CheckCircle2; colors: string; iconColor: string; progressColor: string }> = {
  success: {
    icon: CheckCircle2,
    colors: 'bg-emerald-500/10 border-emerald-500/30',
    iconColor: 'text-emerald-400',
    progressColor: 'bg-emerald-500',
  },
  error: {
    icon: XCircle,
    colors: 'bg-red-500/10 border-red-500/30',
    iconColor: 'text-red-400',
    progressColor: 'bg-red-500',
  },
  warning: {
    icon: AlertTriangle,
    colors: 'bg-amber-500/10 border-amber-500/30',
    iconColor: 'text-amber-400',
    progressColor: 'bg-amber-500',
  },
  info: {
    icon: Info,
    colors: 'bg-blue-500/10 border-blue-500/30',
    iconColor: 'text-blue-400',
    progressColor: 'bg-blue-500',
  },
};

/* ─── Error message extraction ─────────────────────────── */
function extractErrorMessage(err: unknown): { title: string; message?: string } {
  // Structured backend errors (enriched by apiFetch)
  const anyErr = err as any;
  if (anyErr?.code && anyErr?.suggestion) {
    return {
      title: anyErr.message || 'Error',
      message: anyErr.suggestion,
    };
  }

  if (err instanceof Error) {
    const msg = err.message;
    // Network errors
    if (msg.includes('Cannot connect to backend') || msg.includes('Failed to fetch')) {
      return {
        title: 'Connection Failed',
        message: 'Cannot reach the server. Please check that the backend is running.',
      };
    }
    if (msg.includes('Unauthorized')) {
      return { title: 'Session Expired', message: 'Please log in again.' };
    }
    // Twilio-specific
    if (msg.includes('Twilio') || msg.includes('twilio')) {
      return { title: 'Twilio Error', message: msg.replace(/^.*?:\s*/, '') };
    }
    // API errors with detail
    if (msg.includes('API error')) {
      const code = msg.match(/API error (\d+)/)?.[1];
      return {
        title: `Server Error${code ? ` (${code})` : ''}`,
        message: msg.replace(/API error \d+:?\s*/, '').trim() || 'An unexpected error occurred.',
      };
    }
    return { title: 'Error', message: msg };
  }
  if (typeof err === 'string') {
    return { title: 'Error', message: err };
  }
  return { title: 'Error', message: 'An unexpected error occurred.' };
}

/* ─── Individual Toast Component ───────────────────────── */
function ToastItem({ toast, onRemove }: { toast: Toast; onRemove: () => void }) {
  const config = TOAST_CONFIG[toast.type];
  const Icon = config.icon;
  const duration = toast.duration ?? (toast.type === 'error' ? 8000 : 5000);
  const [progress, setProgress] = useState(100);
  const [exiting, setExiting] = useState(false);
  const startTimeRef = useRef(Date.now());
  const pausedRef = useRef(false);
  const remainingRef = useRef(duration);

  const handleRemove = useCallback(() => {
    setExiting(true);
    setTimeout(onRemove, 300);
  }, [onRemove]);

  useEffect(() => {
    if (duration === 0) return;

    let animFrame: number;

    const tick = () => {
      if (pausedRef.current) {
        animFrame = requestAnimationFrame(tick);
        return;
      }
      const elapsed = Date.now() - startTimeRef.current;
      const remaining = remainingRef.current - elapsed;
      if (remaining <= 0) {
        handleRemove();
        return;
      }
      setProgress((remaining / duration) * 100);
      animFrame = requestAnimationFrame(tick);
    };

    animFrame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animFrame);
  }, [duration, handleRemove]);

  return (
    <div
      className={`
        relative overflow-hidden rounded-xl border backdrop-blur-sm shadow-2xl shadow-black/30
        ${config.colors}
        ${exiting ? 'animate-slide-out' : 'animate-slide-in'}
        transition-all duration-300
      `}
      onMouseEnter={() => { pausedRef.current = true; }}
      onMouseLeave={() => {
        remainingRef.current = (progress / 100) * duration;
        startTimeRef.current = Date.now();
        pausedRef.current = false;
      }}
      role="alert"
    >
      <div className="flex items-start gap-3 p-4">
        <Icon size={20} className={`${config.iconColor} mt-0.5 flex-shrink-0`} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-[var(--text-primary)]">{toast.title}</p>
          {toast.message && (
            <p className="text-sm text-[var(--text-secondary)] mt-0.5 leading-relaxed">
              {toast.message}
            </p>
          )}
          {toast.action && (
            <button
              onClick={() => { toast.action!.onClick(); handleRemove(); }}
              className="mt-2 text-xs font-medium text-[var(--accent)] hover:text-[var(--accent-hover)] transition-colors"
            >
              {toast.action.label}
            </button>
          )}
        </div>
        <button
          onClick={handleRemove}
          className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors flex-shrink-0"
        >
          <X size={16} />
        </button>
      </div>
      {/* Progress bar */}
      {duration > 0 && (
        <div className="h-0.5 w-full bg-[var(--surface-hover)]">
          <div
            className={`h-full ${config.progressColor} opacity-40 transition-none`}
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
    </div>
  );
}

/* ─── Toast Container ──────────────────────────────────── */
function ToastContainer({ toasts, removeToast }: { toasts: Toast[]; removeToast: (id: string) => void }) {
  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-3 w-[400px] max-w-[calc(100vw-2rem)] max-h-[calc(100vh-2rem)] overflow-y-auto">
      {toasts.map(toast => (
        <ToastItem key={toast.id} toast={toast} onRemove={() => removeToast(toast.id)} />
      ))}
    </div>
  );
}

/* ─── Provider ─────────────────────────────────────────── */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const idCounter = useRef(0);

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const addToast = useCallback((toast: Omit<Toast, 'id'>) => {
    const id = `toast-${++idCounter.current}-${Date.now()}`;
    setToasts(prev => {
      // Limit to 5 visible toasts
      const next = [...prev, { ...toast, id }];
      return next.length > 5 ? next.slice(-5) : next;
    });
    return id;
  }, []);

  const success = useCallback((title: string, message?: string) => {
    addToast({ type: 'success', title, message });
  }, [addToast]);

  const error = useCallback((title: string, message?: string) => {
    addToast({ type: 'error', title, message });
  }, [addToast]);

  const warning = useCallback((title: string, message?: string) => {
    addToast({ type: 'warning', title, message });
  }, [addToast]);

  const info = useCallback((title: string, message?: string) => {
    addToast({ type: 'info', title, message });
  }, [addToast]);

  const apiError = useCallback((err: unknown, fallback?: string) => {
    const extracted = extractErrorMessage(err);
    addToast({
      type: 'error',
      title: extracted.title,
      message: extracted.message || fallback || 'Something went wrong.',
    });
  }, [addToast]);

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast, success, error, warning, info, apiError }}>
      {children}
      <ToastContainer toasts={toasts} removeToast={removeToast} />
    </ToastContext.Provider>
  );
}
