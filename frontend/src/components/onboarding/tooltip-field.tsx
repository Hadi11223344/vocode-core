'use client';

import { useState } from 'react';
import { HelpCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

interface TooltipFieldProps {
  label: string;
  tooltip: string;
  children: React.ReactNode;
  className?: string;
}

export function TooltipField({ label, tooltip, children, className }: TooltipFieldProps) {
  const [show, setShow] = useState(false);

  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-center gap-1.5">
        <label className="text-sm font-medium">{label}</label>
        <div className="relative">
          <button
            type="button"
            onMouseEnter={() => setShow(true)}
            onMouseLeave={() => setShow(false)}
            onClick={() => setShow((s) => !s)}
            className="text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors"
          >
            <HelpCircle size={14} />
          </button>
          {show && (
            <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-56 z-50">
              <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg shadow-xl p-3 text-xs text-[var(--text-secondary)] leading-relaxed">
                {tooltip}
                <div className="absolute left-1/2 -translate-x-1/2 top-full w-2 h-2 bg-[var(--bg-secondary)] border-r border-b border-[var(--border-color)] rotate-45 -mt-1" />
              </div>
            </div>
          )}
        </div>
      </div>
      {children}
    </div>
  );
}
