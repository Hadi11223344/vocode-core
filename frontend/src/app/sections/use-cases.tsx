'use client';

import { useInView } from './hooks';
import { USE_CASES } from './data';
import { cn } from '@/lib/utils';

export default function UseCasesSection() {
  const { ref, inView } = useInView();
  return (
    <section id="use-cases" className="py-24 sm:py-32 bg-[var(--bg-secondary)]/50">
      <div ref={ref} className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto mb-16">
          <p className="text-sm font-medium text-brand-400 mb-3">Use Cases</p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight mb-4">Built for <span className="text-gradient-animated">every industry</span></h2>
          <p className="text-[var(--text-secondary)] leading-relaxed">From healthcare to e-commerce &mdash; see how teams use VOIA to automate calls and grow revenue.</p>
        </div>
        <div className={cn('grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5', inView ? 'animate-stagger' : 'opacity-0')}>
          {USE_CASES.map((uc) => (
            <div key={uc.title} data-tilt-card className="glass-card rounded-2xl p-6 group tilt-card use-case-card">
              <div className="glass-card-border" />
              <div className="flex items-center justify-between mb-4">
                <div className="w-11 h-11 rounded-xl bg-[var(--accent-muted)] flex items-center justify-center group-hover:bg-brand-500/20 transition-colors"><uc.icon className="w-5 h-5 text-brand-400 icon-rotate-hover" /></div>
                <span className="text-xs font-bold text-emerald-400 bg-emerald-500/10 px-2.5 py-1 rounded-full group-hover:bg-emerald-500/20 transition-colors">{uc.metric}</span>
              </div>
              <h3 className="text-base font-semibold mb-2">{uc.title}</h3>
              <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{uc.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
