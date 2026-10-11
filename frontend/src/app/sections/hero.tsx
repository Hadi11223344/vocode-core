'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import { ArrowRight, Play, Sparkles, Mic } from 'lucide-react';
import { cn } from '@/lib/utils';

const HeroScene3D = dynamic(() => import('@/components/landing/HeroScene3D'), {
  ssr: false,
  loading: () => null,
});

interface HeroProps {
  ctaHref: string;
}

export default function HeroSection({ ctaHref }: HeroProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const headlineWords = ['AI', 'Voice', 'Agents'];

  return (
    <section className="relative min-h-screen pt-32 pb-20 sm:pt-36 sm:pb-28 overflow-hidden">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-8 items-center">
          {/* Left: Text content */}
          <div className="text-center lg:text-left max-w-2xl mx-auto lg:mx-0">
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full glass-card border border-brand-500/20 mb-8 text-sm text-brand-300 animate-fade-in promo-ripple">
              <Sparkles className="w-3.5 h-3.5" />
              <span>$10 free credits to get started &mdash; no card required</span>
            </div>

            <h1 className="text-5xl sm:text-6xl lg:text-7xl font-extrabold tracking-tight leading-[1.08] mb-6">
              <span className="block mb-1">
                {headlineWords.map((word, i) => (
                  <span
                    key={word}
                    className="word-reveal text-gradient-animated glow-text"
                    style={{ animationDelay: `${i * 100}ms`, marginRight: '0.25em' }}
                  >
                    {word}
                  </span>
                ))}
              </span>
              <span className="block text-[var(--text-primary)] word-reveal" style={{ animationDelay: '350ms' }}>
                That Close Deals &amp;
              </span>
              <span className="block text-[var(--text-primary)] word-reveal" style={{ animationDelay: '450ms' }}>
                Delight Customers
              </span>
            </h1>

            <p
              className="text-lg sm:text-xl text-[var(--text-secondary)] max-w-xl mx-auto lg:mx-0 leading-relaxed mb-10 word-reveal"
              style={{ animationDelay: '550ms' }}
            >
              Deploy human-sounding AI agents that handle inbound support, qualify leads, book meetings, and automate post-call workflows &mdash; in minutes, not months.
            </p>

            <div
              className="flex flex-col sm:flex-row items-center justify-center lg:justify-start gap-4 mb-6 word-reveal"
              style={{ animationDelay: '650ms' }}
            >
              <Link
                href={ctaHref}
                className="btn-primary shimmer-sweep !text-base !px-8 !py-3.5 !rounded-full shadow-glow hover:shadow-glow transition-all duration-300 active:opacity-75 hover:-translate-y-0.5"
              >
                Start Building Free <ArrowRight className="w-4 h-4" />
              </Link>
              <a
                href="#how-it-works"
                className="btn-secondary shimmer-sweep !text-base !px-8 !py-3.5 !rounded-full active:opacity-75 hover:-translate-y-0.5 transition-all duration-300"
              >
                <Play className="w-4 h-4" /> See How It Works
              </a>
            </div>

            <div
              className="flex flex-wrap items-center justify-center lg:justify-start gap-x-4 gap-y-2 text-xs text-[var(--text-muted)] word-reveal"
              style={{ animationDelay: '750ms' }}
            >
              {['No credit card', '5 concurrent calls included', 'Pay only for what you use'].map((item) => (
                <span key={item} className="flex items-center gap-1.5">
                  <span className="w-1 h-1 rounded-full bg-brand-400" />
                  {item}
                </span>
              ))}
            </div>
          </div>

          {/* Right: 3D Scene */}
          <div className="relative h-[400px] sm:h-[500px] lg:h-[600px] hidden lg:block">
            {mounted && (
              <div className="absolute inset-0">
                <HeroScene3D />
              </div>
            )}
            <div className="absolute inset-0 flex items-end justify-center pointer-events-none">
              <div className="glass-card rounded-2xl px-6 py-4 mb-8 float-animation">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl gradient-brand flex items-center justify-center">
                    <Mic className="w-5 h-5 text-white" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-[var(--text-primary)]">Voice Engine Active</p>
                    <p className="text-[10px] text-[var(--text-muted)]">Sub-800ms latency</p>
                  </div>
                  <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse ml-2" />
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Dashboard mockup */}
        <div className="mt-16 sm:mt-20 max-w-5xl mx-auto w-full overflow-x-hidden animate-fade-in" style={{ animationDelay: '400ms' }}>
          <div className="relative">
            <div className="absolute -inset-4 bg-gradient-to-b from-brand-600/[0.08] to-transparent rounded-3xl blur-2xl" />
            <div data-tilt-card className="relative rounded-2xl glass-card overflow-hidden shadow-2xl tilt-card">
              <div className="glass-card-border" />
              <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]/50">
                <div className="flex gap-1.5">
                  <div className="w-3 h-3 rounded-full bg-red-500/60" />
                  <div className="w-3 h-3 rounded-full bg-yellow-500/60" />
                  <div className="w-3 h-3 rounded-full bg-green-500/60" />
                </div>
                <div className="flex-1 flex justify-center">
                  <div className="px-4 py-1 rounded-md bg-[var(--bg-primary)] text-[11px] text-[var(--text-muted)] font-mono">app.voia.ai/dashboard</div>
                </div>
                <div className="w-16" />
              </div>
              <div className="p-6 sm:p-8 bg-[var(--bg-primary)]/50">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
                  {[
                    { label: 'Total Calls', value: '12,847', trend: '+24% this month', color: 'text-brand-400' },
                    { label: 'Active Agents', value: '8', trend: 'All online', color: 'text-emerald-400' },
                    { label: 'Avg Duration', value: '3m 42s', trend: '-8% vs last week', color: 'text-amber-400' },
                    { label: 'Resolution Rate', value: '94.2%', trend: '+3.1% improvement', color: 'text-brand-400' },
                  ].map((s) => (
                    <div key={s.label} className="glass-card rounded-xl p-4">
                      <p className="text-[11px] text-[var(--text-muted)] uppercase tracking-wider mb-1">{s.label}</p>
                      <p className="text-xl font-bold">{s.value}</p>
                      <p className={cn('text-[11px] mt-1', s.color)}>{s.trend}</p>
                    </div>
                  ))}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <div className="sm:col-span-2 glass-card rounded-xl p-4">
                    <div className="flex items-center justify-between mb-4">
                      <p className="text-sm font-medium">Call Volume</p>
                      <span className="text-[11px] text-[var(--text-muted)]">Last 7 days</span>
                    </div>
                    <div className="flex items-end gap-1 h-20">
                      {[40,65,45,80,55,90,70,60,85,50,75,95,55,70,80,60,90,45,85,65,75,50,88,72].map((h, i) => (
                        <div key={i} className="flex-1 rounded-sm bg-brand-500/40 hover:bg-brand-500/60 transition-colors" style={{ height: `${h}%` }} />
                      ))}
                    </div>
                  </div>
                  <div className="glass-card rounded-xl p-4 hero-live-card">
                    <p className="text-sm font-medium mb-3">Live Now</p>
                    <div className="space-y-3">
                      {[
                        { name: 'Sales Agent', status: 'In call', phone: '+1 (555) 0123' },
                        { name: 'Support Bot', status: 'In call', phone: '+1 (555) 4567' },
                        { name: 'Booking Agent', status: 'Idle', phone: '\u2014' },
                      ].map((a, i) => (
                        <div key={a.name} className={cn('flex items-center gap-3 hero-live-row', a.status === 'In call' && 'hero-live-row-active')} style={{ animationDelay: `${i * 140}ms` }}>
                          <div className={cn('w-2 h-2 rounded-full hero-live-dot', a.status === 'In call' ? 'bg-emerald-400' : 'bg-[var(--text-muted)]')} />
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium truncate">{a.name}</p>
                            <p className="text-[10px] text-[var(--text-muted)]">{a.phone}</p>
                          </div>
                          <span className={cn('text-[10px] font-medium', a.status === 'In call' ? 'text-emerald-400' : 'text-[var(--text-muted)]')}>{a.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Scroll indicator */}
        <div className="hidden sm:flex flex-col items-center justify-center mt-12">
          <div className="w-5 h-9 rounded-full border-2 border-[var(--border-color)] flex items-start justify-center pt-1.5">
            <div className="w-1 h-2 rounded-full bg-brand-400 scroll-indicator-dot" />
          </div>
        </div>
      </div>
    </section>
  );
}
