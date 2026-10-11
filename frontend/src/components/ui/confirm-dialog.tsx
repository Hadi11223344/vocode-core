"use client";

import { X, AlertTriangle } from "lucide-react";
import { useEffect, useCallback } from "react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "warning" | "default";
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "danger",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter") onConfirm();
    },
    [onConfirm, onCancel]
  );

  useEffect(() => {
    if (!open) return;
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, handleKeyDown]);

  if (!open) return null;

  const confirmClasses =
    variant === "danger"
      ? "bg-red-600 hover:bg-red-500 text-white"
      : variant === "warning"
      ? "bg-amber-600 hover:bg-amber-500 text-white"
      : "btn-primary";

  return (
    <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm z-50 flex items-center justify-center animate-fade-in">
      <div className="bg-[var(--bg-secondary)] rounded-2xl border border-[var(--border-color)] w-full max-w-md mx-4 shadow-modal animate-scale-in">
        <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--border-color)]">
          <div
            className={`p-2 rounded-lg ${
              variant === "danger"
                ? "bg-red-500/20 text-red-400"
                : variant === "warning"
                ? "bg-amber-500/20 text-amber-400"
                : "bg-brand-500/20 text-brand-400"
            }`}
          >
            <AlertTriangle size={18} />
          </div>
          <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
          <button
            onClick={onCancel}
            className="ml-auto btn-ghost p-1.5"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-5">
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            {message}
          </p>
        </div>

        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-[var(--border-color)]">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-[var(--text-secondary)] hover:text-white transition-colors"
          >
            {cancelLabel}
          </button>
          <button onClick={onConfirm} className={`px-4 py-2 text-sm rounded-lg ${confirmClasses}`}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
