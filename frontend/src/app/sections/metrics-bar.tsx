'use client';

import { useInView, useCounter } from './hooks';

export default function MetricsBar() {
  const { ref, inView } = useInView(0.5);
  const calls = useCounter(2400000, 2000, inView);
  const agents = useCounter(850, 1500, inView);
  const uptime = useCounter(99, 1200, inView);
  return (
    <section ref={ref} className="py-12 border-y border-[var(--border-color)] bg-[var(--bg-secondary)]/50">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-8 text-center">
          {[
            { value: calls > 999999 ? `${(calls / 1000000).toFixed(1)}M+` : `${Math.floor(calls / 1000)}K+`, label: 'Calls Handled' },
            { value: `${agents}+`, label: 'Agents Deployed' },
            { value: `${uptime}.99%`, label: 'Uptime SLA' },
            { value: '<800ms', label: 'Avg Latency' },
          ].map((m) => (
            <div key={m.label} className="relative">
              <p className="text-2xl sm:text-3xl font-bold text-gradient-animated">{m.value}</p>
              <p className="text-xs text-[var(--text-muted)] mt-1">{m.label}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
