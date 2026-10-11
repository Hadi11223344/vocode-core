'use client';

import React from 'react';

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-500/20 text-green-400',
  completed: 'bg-blue-500/20 text-blue-400',
  failed: 'bg-red-500/20 text-red-400',
  ringing: 'bg-yellow-500/20 text-yellow-400',
  initiated: 'bg-purple-500/20 text-purple-400',
  'no-answer': 'bg-orange-500/20 text-orange-400',
  busy: 'bg-red-500/20 text-red-400',
  canceled: 'bg-gray-500/20 text-gray-400',
};

interface StatusBadgeProps {
  status: string;
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const colorClass = STATUS_COLORS[status] || 'bg-gray-500/20 text-gray-400';
  const isPulsing = status === 'active' || status === 'ringing';

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${colorClass}`}
    >
      {isPulsing && (
        <span
          className={`w-1.5 h-1.5 rounded-full animate-pulse flex-shrink-0 ${
            status === 'active' ? 'bg-green-400' : 'bg-yellow-400'
          }`}
        />
      )}
      {status}
    </span>
  );
}
