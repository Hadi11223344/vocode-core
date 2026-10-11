'use client';

import Link from 'next/link';
import { Check } from 'lucide-react';
import { useInView } from './hooks';
import { cn } from '@/lib/utils';

interface PricingProps {
  ctaHref: string;
}

export default function PricingSection({ ctaHref }: PricingProps) {
  const { ref, inView } = useInView();
  const pricingRows = [
    { component: 'VOIA Voice Engine', cost: '$0.05/min', note: 'Includes STT + orchestration' },
    { component: 'GPT-4o', cost: '$0.04/min', note: 'Or bring your own LLM' },
    { component: 'GPT-4o-mini', cost: '$0.015/min', note: 'Budget-friendly option' },
    { component: 'Claude Sonnet', cost: '$0.06/min', note: 'Anthropic models supported' },
    { component: 'ElevenLabs TTS', cost: '$0.04/min', note: 'Premium voices' },
    { component: 'Deepgram TTS', cost: '$0.015/min', note: 'Cost-effective voices' },
    { component: 'Twilio Telephony', cost: '$0.015/min', note: 'Or BYO telephony ($0)' },
    { component: 'Extra Concurrency', cost: '$15/line/mo', note: '5 included free' },
    { component: 'Knowledge Base', cost: '$5/KB/mo', note: '3 included free' },
    { component: 'Phone Number', cost: '$2/mo', note: 'US numbers' },
  ];

  return (
    <section id="pricing" className="py-24 sm:py-32">
      <div ref={ref} className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto mb-16">
          <p className="text-sm font-medium text-brand-400 mb-3">Pricing</p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight mb-4">No platform fees. <span className="text-gradient-animated">Pay only for what you use.</span></h2>
          <p className="text-[var(--text-secondary)] leading-relaxed">Transparent per-minute pricing. Start free with $10 in credits. Scale to millions of minutes.</p>
        </div>

        <div className={cn('grid grid-cols-1 md:grid-cols-2 gap-6 max-w-4xl mx-auto mb-16', inView ? 'animate-stagger' : 'opacity-0')}>
          <div data-tilt-card className="glass-card rounded-2xl p-6 sm:p-8 tilt-card">
            <div className="glass-card-border" />
            <h3 className="text-lg font-semibold mb-1">Pay As You Go</h3>
            <p className="text-xs text-[var(--text-muted)] mb-5">Start instantly. Scale when ready.</p>
            <div className="flex items-baseline gap-1 mb-2"><span className="text-4xl font-bold">$0</span><span className="text-sm text-[var(--text-muted)]">to start</span></div>
            <p className="text-sm text-brand-400 font-medium mb-6">$10 free credits included</p>
            <ul className="space-y-3 mb-8">
              {['Usage-based: ~$0.07\u20130.15/min', 'Unlimited voice agents', '5 concurrent calls included', 'All 30+ integrations', 'Visual workflow builder', 'Analytics dashboard', 'Community & email support', 'API & webhook access'].map((f) => (
                <li key={f} className="flex items-center gap-2.5"><Check className="w-3.5 h-3.5 text-brand-400 flex-shrink-0" /><span className="text-sm text-[var(--text-secondary)]">{f}</span></li>
              ))}
            </ul>
            <Link href={ctaHref} className="block w-full text-center btn-secondary shimmer-sweep py-2.5 rounded-xl text-sm font-medium">Get Started Free</Link>
          </div>

          <div data-tilt-card className="glass-card glass-card-glow rounded-2xl p-6 sm:p-8 relative tilt-card" style={{ borderColor: 'rgba(99, 102, 241, 0.3)', boxShadow: '0 0 30px rgba(99, 102, 241, 0.1)' }}>
            <div className="glass-card-border" style={{ opacity: 1 }} />
            <div className="absolute -top-3 left-1/2 -translate-x-1/2"><span className="badge bg-brand-600 text-white text-[10px] !px-3 !py-1 shimmer-sweep">For Scale</span></div>
            <h3 className="text-lg font-semibold mb-1">Enterprise</h3>
            <p className="text-xs text-[var(--text-muted)] mb-5">For teams with 10K+ minutes/month.</p>
            <div className="flex items-baseline gap-1 mb-2"><span className="text-4xl font-bold">Custom</span></div>
            <p className="text-sm text-brand-400 font-medium mb-6">Volume discounts available</p>
            <ul className="space-y-3 mb-8">
              {['Everything in Pay As You Go', 'Volume-based pricing', 'Unlimited concurrent calls', 'Dedicated infrastructure', '99.99% uptime SLA', 'HIPAA & SOC 2 compliance', 'Private Slack + dedicated CSM', 'Custom integrations & onboarding'].map((f) => (
                <li key={f} className="flex items-center gap-2.5"><Check className="w-3.5 h-3.5 text-brand-400 flex-shrink-0" /><span className="text-sm text-[var(--text-secondary)]">{f}</span></li>
              ))}
            </ul>
            <a href="mailto:sales@voia.ai" className="block w-full text-center btn-primary shimmer-sweep py-2.5 rounded-xl text-sm font-medium">Contact Sales</a>
          </div>
        </div>

        <div className="max-w-3xl mx-auto">
          <h3 className="text-lg font-semibold text-center mb-6">Transparent Component Pricing</h3>
          <div data-tilt-card className="glass-card rounded-2xl overflow-hidden tilt-card">
            <div className="glass-card-border" />
            <table className="w-full text-sm">
              <caption className="sr-only">VOIA component pricing breakdown with costs and notes for each integration component</caption>
              <thead>
                <tr className="border-b border-[var(--border-color)]">
                  <th scope="col" className="text-left px-3 sm:px-5 py-2 sm:py-3 text-[9px] sm:text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Component</th>
                  <th scope="col" className="text-left px-3 sm:px-5 py-2 sm:py-3 text-[9px] sm:text-[10px] text-[var(--text-muted)] uppercase tracking-wider">Cost</th>
                  <th scope="col" className="text-left px-3 sm:px-5 py-2 sm:py-3 text-[9px] sm:text-[10px] text-[var(--text-muted)] uppercase tracking-wider hidden sm:table-cell">Notes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-color)]">
                {pricingRows.map((r) => (
                  <tr key={r.component} className="hover:bg-brand-500/[0.04] transition-colors">
                    <td scope="row" className="px-3 sm:px-5 py-2 sm:py-3 font-medium text-[var(--text-primary)] text-xs sm:text-sm">{r.component}</td>
                    <td className="px-3 sm:px-5 py-2 sm:py-3 text-brand-400 font-mono text-[10px] sm:text-xs">{r.cost}</td>
                    <td className="px-3 sm:px-5 py-2 sm:py-3 text-[var(--text-muted)] text-[9px] sm:text-xs hidden sm:table-cell">{r.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-center text-[11px] text-[var(--text-muted)] mt-4">Typical all-in cost: <span className="text-brand-400 font-semibold">$0.11&ndash;0.15/min</span> with GPT-4o + Deepgram + Twilio. No hidden fees.</p>
        </div>
      </div>
    </section>
  );
}
