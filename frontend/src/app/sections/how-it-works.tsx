'use client';

import Link from 'next/link';
import { Bot, Plug, Zap, ArrowRight } from 'lucide-react';
import { useInView } from './hooks';
import { cn } from '@/lib/utils';

interface HowItWorksProps {
  ctaHref: string;
}

export default function HowItWorksSection({ ctaHref }: HowItWorksProps) {
  const { ref, inView } = useInView();
  const steps = [
    { num: '01', title: 'Configure Your Agent', description: 'Set your system prompt, pick a voice, choose your LLM, and enable the tools your agent needs — scheduling, CRM lookup, SMS, or custom functions.', icon: Bot },
    { num: '02', title: 'Connect Your Stack', description: 'Link your phone number (Twilio/Vonage), connect integrations (HubSpot, Slack, Calendar), and build post-call workflows with the visual editor.', icon: Plug },
    { num: '03', title: 'Go Live & Scale', description: 'Your agent answers calls immediately. Monitor live conversations, review analytics, refine prompts — then scale to thousands of concurrent calls.', icon: Zap },
  ];
  return (
    <section id="how-it-works" className="py-20 sm:py-28 bg-[var(--bg-secondary)]/50">
      <div ref={ref} className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto mb-16">
          <p className="text-sm font-medium text-brand-400 mb-3">How It Works</p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight mb-4">From zero to live agent in <span className="text-gradient-animated">3 steps</span></h2>
          <p className="text-[var(--text-secondary)] leading-relaxed">No telephony expertise needed. No infrastructure to manage. Just configure, connect, and deploy.</p>
        </div>
        <div className={cn('grid grid-cols-1 md:grid-cols-3 gap-8', inView ? 'animate-stagger' : 'opacity-0')}>
          {steps.map((step, i) => (
            <div key={step.num} className="relative">
              {i < 2 && <div className="hidden md:block absolute top-12 left-full w-full h-px bg-gradient-to-r from-brand-500/30 to-transparent z-10" style={{ width: 'calc(100% - 2rem)' }} />}
              {i < 2 && <div className="md:hidden absolute top-14 -left-2 w-px h-16 bg-gradient-to-b from-brand-500/30 to-transparent" />}
              <div data-tilt-card className="glass-card rounded-2xl p-6 text-center group tilt-card">
                <div className="glass-card-border" />
                <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-[var(--accent-muted)] mb-5 group-hover:bg-brand-500/20 transition-colors relative">
                  <step.icon className="w-6 h-6 text-brand-400 icon-rotate-hover" />
                  <span className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-brand-600 text-[10px] font-bold flex items-center justify-center text-white">{step.num}</span>
                </div>
                <h3 className="text-lg font-semibold mb-2">{step.title}</h3>
                <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{step.description}</p>
              </div>
            </div>
          ))}
        </div>
        <div className="text-center mt-12">
          <Link href={ctaHref} className="btn-primary shimmer-sweep !rounded-full !px-8 active:opacity-75">Try It Now &mdash; Free <ArrowRight className="w-4 h-4" /></Link>
        </div>
      </div>
    </section>
  );
}
