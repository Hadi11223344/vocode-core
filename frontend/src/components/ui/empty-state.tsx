"use client";

import { type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
  className?: string;
  iconSize?: number;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  iconSize = 48,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "card-base p-12 text-center flex flex-col items-center",
        className
      )}
    >
      <div className="relative mb-5">
        <div className="absolute inset-0 bg-brand-500/10 rounded-full blur-xl" />
        <Icon
          size={iconSize}
          className="relative mx-auto text-brand-400 opacity-70"
          strokeWidth={1.2}
        />
      </div>
      <h3 className="text-lg font-semibold mb-1.5">{title}</h3>
      <p className="text-sm text-[var(--text-secondary)] max-w-sm mb-5">
        {description}
      </p>
      {action && <div className="flex items-center gap-3">{action}</div>}
    </div>
  );
}
