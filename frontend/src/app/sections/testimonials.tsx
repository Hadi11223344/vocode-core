'use client';

import { useInView } from './hooks';
import { cn } from '@/lib/utils';

export default function TestimonialsSection() {
  const { ref, inView } = useInView();
  const testimonials = [
    { quote: "VOIA replaced our entire after-hours support team. We went from 40% missed calls to zero overnight. The ROI paid for itself in the first week.", name: 'Sarah Chen', title: 'VP of Operations, MedFlow Health', metric: '0 missed calls' },
    { quote: "Our sales team books 3x more demos now. The AI qualifies leads and schedules meetings while we sleep. Setup took 20 minutes.", name: 'Marcus Johnson', title: 'Sales Director, ScaleUp SaaS', metric: '3x more demos' },
    { quote: "We handle 2,000+ support calls daily with 4 AI agents. The workflow automation saves our team 30 hours a week on follow-ups alone.", name: 'Priya Gupta', title: 'CTO, FastShip Logistics', metric: '30hrs/wk saved' },
  ];
  return (
    <section className="py-24 sm:py-32 bg-[var(--bg-secondary)]/50">
      <div ref={ref} className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto mb-16">
          <p className="text-sm font-medium text-brand-400 mb-3">Customer Stories</p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight mb-4">Trusted by teams <span className="text-gradient-animated">shipping fast</span></h2>
        </div>
        <div className={cn('grid grid-cols-1 md:grid-cols-3 gap-6', inView ? 'animate-stagger' : 'opacity-0')}>
          {testimonials.map((t) => (
            <div key={t.name} data-tilt-card className="glass-card rounded-2xl p-6 flex flex-col h-full tilt-card">
              <div className="glass-card-border" />
              <div className="flex-1">
                <div className="flex gap-0.5 mb-4">
                  {[...Array(5)].map((_, i) => (
                    <svg key={i} className="w-4 h-4 text-amber-400" fill="currentColor" viewBox="0 0 20 20"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" /></svg>
                  ))}
                </div>
                <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-4">&ldquo;{t.quote}&rdquo;</p>
              </div>
              <div className="flex items-center justify-between pt-4 border-t border-[var(--border-color)]">
                <div><p className="text-sm font-medium">{t.name}</p><p className="text-[11px] text-[var(--text-muted)]">{t.title}</p></div>
                <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-2 py-1 rounded-full">{t.metric}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
