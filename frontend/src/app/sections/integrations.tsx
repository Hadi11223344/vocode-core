'use client';

import { useState } from 'react';
import { AlertCircle } from 'lucide-react';
import { useInView } from './hooks';
import { INTEGRATIONS } from './data';
import { cn } from '@/lib/utils';

export default function IntegrationsSection() {
  const [activeCategory, setActiveCategory] = useState('All');
  const { ref, inView } = useInView();

  const categories = ['All', 'Telephony', 'AI / LLM', 'CRM', 'Messaging', 'Productivity', 'Payments'];
  const filteredIntegrations = activeCategory === 'All'
    ? INTEGRATIONS
    : INTEGRATIONS.filter(ig => ig.category === activeCategory);

  return (
    <section id="integrations" className="py-24 sm:py-32">
      <div ref={ref} className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto mb-16">
          <p className="text-sm font-medium text-brand-400 mb-3">Integrations</p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight mb-4">Connects to your <span className="text-gradient-animated">entire stack</span></h2>
          <p className="text-[var(--text-secondary)] leading-relaxed">30+ pre-built integrations for CRM, messaging, calendars, payments, and more. Or build your own with webhooks and our REST API.</p>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-2.5 sm:gap-3 mb-12">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              aria-current={activeCategory === cat ? 'page' : undefined}
              aria-label={`Filter integrations by ${cat} category`}
              className={cn(
                'px-2 sm:px-3.5 lg:px-4 py-2.5 sm:py-3 min-h-[44px] sm:min-h-auto rounded-full text-xs sm:text-sm font-semibold transition-all duration-200 cursor-pointer',
                'border border-transparent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-400',
                activeCategory === cat
                  ? 'bg-brand-600 text-white shadow-md hover:shadow-lg hover:bg-brand-500'
                  : 'bg-[var(--bg-hover)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] hover:border-brand-500/30'
              )}
            >
              {cat}
            </button>
          ))}
        </div>
        <div className={cn('grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-4 transition-all duration-400', inView ? 'animate-stagger' : 'opacity-0')}>
          {filteredIntegrations.map((ig) => (
            <div
              key={ig.name}
              data-tilt-card
              role="button"
              tabIndex={0}
              aria-label={`${ig.name} integration (${ig.category}): Click to filter integrations by this provider`}
              title={`${ig.name} - ${ig.category}`}
              className="glass-card flex flex-col items-center justify-center p-4 aspect-square group tilt-card relative overflow-hidden integration-icon-card cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-400 rounded-xl"
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') e.preventDefault(); }}
            >
              <div className="absolute inset-0 bg-gradient-to-br opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none" style={{ backgroundImage: `linear-gradient(135deg, ${ig.color}12 0%, ${ig.color}04 100%)` }} />
              <div className="relative z-10 w-10 h-10 sm:w-11 sm:h-11 md:w-12 md:h-12 rounded-xl flex items-center justify-center mb-2 text-sm sm:text-base md:text-lg font-bold shadow-sm transition-all duration-300 group-hover:scale-110 group-hover:shadow-md" style={{ backgroundColor: `${ig.color}20`, color: ig.color, border: `1.5px solid ${ig.color}40` }}>
                {ig.name.charAt(0)}
              </div>
              <span className="text-[10px] sm:text-[11px] md:text-[12px] text-[var(--text-muted)] group-hover:text-[var(--text-primary)] text-center leading-tight transition-colors duration-300 relative z-10 font-medium">{ig.name}</span>
            </div>
          ))}
        </div>
        {filteredIntegrations.length === 0 && (
          <div
            role="alert"
            aria-live="polite"
            aria-atomic="true"
            className="col-span-full text-center py-12 border border-dashed border-[var(--border-color)] rounded-xl p-8"
          >
            <AlertCircle className="w-10 h-10 text-brand-400 mx-auto mb-3 opacity-50" />
            <p className="text-sm text-brand-400 font-medium">No integrations found in the <span className="font-semibold">{activeCategory}</span> category.</p>
            <p className="text-xs text-[var(--text-muted)] mt-1">Try selecting a different category</p>
          </div>
        )}
      </div>
    </section>
  );
}
