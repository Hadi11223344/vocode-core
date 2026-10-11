'use client';

import Link from 'next/link';
import { ArrowRight } from 'lucide-react';

interface CTAProps {
  ctaHref: string;
}

export default function CTASection({ ctaHref }: CTAProps) {
  return (
    <section className="py-24 sm:py-32 relative">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[800px] h-[400px] bg-brand-600/[0.08] rounded-full blur-[100px] will-change-transform" />
        <div className="absolute top-1/2 left-1/3 w-[400px] h-[400px] bg-purple-600/[0.05] rounded-full blur-[100px] will-change-transform" />
        <div className="absolute top-1/3 right-1/4 w-[300px] h-[300px] bg-cyan-600/[0.04] rounded-full blur-[80px] will-change-transform" />
      </div>
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 text-center relative z-10">
        <div className="glass-card glass-card-glow rounded-3xl p-10 sm:p-14">
          <div className="glass-card-border" />
          <h2 className="text-3xl sm:text-5xl font-bold tracking-tight mb-4 glow-text">Stop losing customers to <span className="text-gradient-animated">hold music.</span></h2>
          <p className="text-[var(--text-secondary)] text-lg mb-4">Deploy your first AI voice agent in under 5 minutes.</p>
          <p className="text-sm text-[var(--text-muted)] mb-10">$10 free credits &middot; No credit card required &middot; Cancel anytime</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link href={ctaHref} className="btn-primary shimmer-sweep !text-base !px-10 !py-4 !rounded-full shadow-glow hover:shadow-glow transition-all duration-300 active:opacity-75 hover:-translate-y-0.5">Start Building Free <ArrowRight className="w-4 h-4" /></Link>
            <a href="#pricing" className="btn-ghost shimmer-sweep !text-base active:opacity-75">See pricing <ArrowRight className="w-3.5 h-3.5" /></a>
          </div>
        </div>
      </div>
    </section>
  );
}
