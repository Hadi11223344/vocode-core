'use client';

import { useState } from 'react';
import { useInView } from './hooks';
import { cn } from '@/lib/utils';

export default function ROISection() {
  const { ref, inView } = useInView();
  const [calls, setCalls] = useState(1000);
  const [avgDuration, setAvgDuration] = useState(4);
  const totalMinutes = calls * avgDuration;
  const humanCost = totalMinutes * 0.95;
  const voiaCost = totalMinutes * 0.13;
  const savings = humanCost - voiaCost;
  const savingsPercent = Math.round((savings / humanCost) * 100);

  return (
    <section className="py-24 sm:py-32 bg-[var(--bg-secondary)]/50">
      <div ref={ref} className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto mb-16">
          <p className="text-sm font-medium text-brand-400 mb-3">ROI Calculator</p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight mb-4">See how much you <span className="text-gradient-animated">save with VOIA</span></h2>
          <p className="text-[var(--text-secondary)] leading-relaxed">Compare the cost of human agents vs. AI voice agents for your call volume.</p>
        </div>
        <div className={cn('max-w-3xl mx-auto', inView ? 'animate-fade-in' : 'opacity-0')}>
          <div data-tilt-card className="glass-card rounded-2xl p-6 sm:p-8 tilt-card">
            <div className="glass-card-border" />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 mb-8">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label htmlFor="calls-slider" className="text-xs text-[var(--text-muted)] uppercase tracking-wider">Monthly calls</label>
                  <div className="text-xs text-brand-400 font-medium">{calls.toLocaleString()} calls</div>
                </div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs text-[var(--text-muted)]">100</span>
                  <input
                    id="calls-slider"
                    type="range"
                    min={100}
                    max={50000}
                    step={100}
                    value={calls}
                    onChange={(e) => setCalls(Number(e.target.value))}
                    aria-label="Select monthly call volume"
                    className="w-full accent-brand-500 roi-slider"
                  />
                  <span className="text-xs text-[var(--text-muted)]">50K</span>
                </div>
                <p className="text-2xl font-bold text-brand-400">{calls.toLocaleString()} <span className="text-sm font-normal text-[var(--text-muted)]">calls/mo</span></p>
              </div>
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label htmlFor="duration-slider" className="text-xs text-[var(--text-muted)] uppercase tracking-wider">Avg call duration</label>
                  <div className="text-xs text-brand-400 font-medium">{avgDuration}m</div>
                </div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs text-[var(--text-muted)]">1m</span>
                  <input
                    id="duration-slider"
                    type="range"
                    min={1}
                    max={15}
                    step={0.5}
                    value={avgDuration}
                    onChange={(e) => setAvgDuration(Number(e.target.value))}
                    aria-label="Select average call duration"
                    className="w-full accent-brand-500 roi-slider"
                  />
                  <span className="text-xs text-[var(--text-muted)]">15m</span>
                </div>
                <p className="text-2xl font-bold text-brand-400">{avgDuration} <span className="text-sm font-normal text-[var(--text-muted)]">minutes</span></p>
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="glass-card rounded-xl p-5 text-center" style={{ borderColor: 'rgba(239, 68, 68, 0.15)' }}>
                <p className="text-[10px] text-red-400 uppercase tracking-wider font-medium mb-1">Human Agents</p>
                <p className="text-2xl font-bold text-red-400">${humanCost.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                <p className="text-[10px] text-[var(--text-muted)] mt-1">~$0.95/min loaded cost</p>
              </div>
              <div className="glass-card rounded-xl p-5 text-center" style={{ borderColor: 'rgba(99, 102, 241, 0.2)' }}>
                <p className="text-[10px] text-brand-400 uppercase tracking-wider font-medium mb-1">VOIA AI Agents</p>
                <p className="text-2xl font-bold text-brand-400">${voiaCost.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                <p className="text-[10px] text-[var(--text-muted)] mt-1">~$0.13/min average</p>
              </div>
              <div className="glass-card rounded-xl p-5 text-center" style={{ borderColor: 'rgba(34, 197, 94, 0.2)', boxShadow: '0 0 20px rgba(34, 197, 94, 0.08)' }}>
                <p className="text-[10px] text-emerald-400 uppercase tracking-wider font-medium mb-1">Your Savings</p>
                <p className="text-2xl font-bold text-emerald-400 glow-text">${savings.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                <p className="text-[10px] text-emerald-400/70 mt-1">{savingsPercent}% cost reduction</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
