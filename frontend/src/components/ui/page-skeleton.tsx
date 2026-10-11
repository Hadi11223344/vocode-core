'use client';

import { cn } from '@/lib/utils';

interface PageSkeletonProps {
  cards?: number;
  rows?: number;
  className?: string;
}

export function PageSkeleton({ cards = 4, rows = 3, className }: PageSkeletonProps) {
  return (
    <div className={cn('space-y-6 animate-fade-in', className)}>
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="dash-skeleton h-7 w-48 rounded-lg" />
          <div className="dash-skeleton h-4 w-64 rounded-lg" />
        </div>
        <div className="dash-skeleton h-9 w-28 rounded-lg" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {[...Array(cards)].map((_, i) => (
          <div key={i} className="dash-skeleton h-28 rounded-xl" />
        ))}
      </div>
      <div className="dash-card p-4 space-y-3">
        {[...Array(rows)].map((_, i) => (
          <div key={i} className="dash-skeleton h-12 rounded-lg" />
        ))}
      </div>
    </div>
  );
}
