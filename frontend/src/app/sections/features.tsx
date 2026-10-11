'use client';

import { useInView } from './hooks';
import { FEATURES } from './data';
import { cn } from '@/lib/utils';

export default function FeaturesSection() {
  const { ref, inView } = useInView();
  return (
    <section id="features" className="py-24 sm:py-32">
      <div ref={ref} className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto mb-16">
          <p className="text-sm font-medium text-brand-400 mb-3">Platform</p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight mb-4">Everything you need to build <span className="text-gradient-animated">production voice AI</span></h2>
          <p className="text-[var(--text-secondary)] leading-relaxed">Agents, telephony, workflows, analytics, integrations, and real-time monitoring &mdash; all in one platform.</p>
        </div>
        <div className={cn('bento-grid', inView ? 'animate-stagger' : 'opacity-0')}>
          {FEATURES.map((f, i) => (
            <div
              key={f.title}
              data-tilt-card
              className={cn(
                'glass-card rounded-2xl p-6 group tilt-card',
                i === 0 && 'bento-item-large'
              )}
            >
              <div className="glass-card-border" />
              <div className="flex items-center justify-between mb-4">
                <div className="w-11 h-11 rounded-xl bg-[var(--accent-muted)] flex items-center justify-center group-hover:bg-brand-500/20 transition-colors">
                  <f.icon className="w-5 h-5 text-brand-400 icon-rotate-hover" />
                </div>
                <span className="text-[10px] font-medium text-brand-400 bg-brand-500/10 px-2 py-0.5 rounded-full">{f.highlight}</span>
              </div>
              <h3 className={cn('text-base font-semibold mb-2', i === 0 && 'text-lg sm:text-xl')}>{f.title}</h3>
              <p className={cn('text-sm text-[var(--text-secondary)] leading-relaxed', i === 0 && 'text-base')}>{f.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
