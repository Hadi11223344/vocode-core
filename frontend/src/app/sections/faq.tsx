'use client';

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { useInView } from './hooks';
import { FAQS } from './data';
import { cn } from '@/lib/utils';

export default function FAQSection() {
  const [open, setOpen] = useState<number | null>(null);
  const { ref, inView } = useInView();
  return (
    <section id="faq" className="py-24 sm:py-32">
      <div ref={ref} className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto mb-16">
          <p className="text-sm font-medium text-brand-400 mb-3">FAQ</p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight mb-4">Frequently asked <span className="text-gradient-animated">questions</span></h2>
          <p className="text-[var(--text-secondary)] leading-relaxed">Scroll through our most commonly asked questions, or <a href="mailto:support@voia.ai" className="text-brand-400 hover:text-brand-300 font-medium underline transition-colors">reach out to support</a> for more help.</p>
        </div>
        <div className={cn('space-y-3', inView ? 'animate-fade-in' : 'opacity-0')}>
          {FAQS.map((faq, i) => (
            <div key={i} data-tilt-card className="glass-card rounded-2xl overflow-hidden tilt-card">
              <div className="glass-card-border" />
              <button
                className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-white/[0.02] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-400 transition-all duration-200"
                onClick={() => setOpen(open === i ? null : i)}
                aria-expanded={open === i}
                aria-controls={`faq-answer-${i}`}
              >
                <span className="text-sm font-medium pr-4">{faq.q}</span>
                <ChevronDown className={cn('w-4 h-4 text-[var(--text-muted)] transition-transform duration-300 ease-out flex-shrink-0', open === i && 'rotate-180 text-brand-400')} />
              </button>
              {open === i && <div id={`faq-answer-${i}`} className="px-5 pb-4 animate-fade-in"><p className="text-sm text-[var(--text-secondary)] leading-relaxed">{faq.a}</p></div>}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
