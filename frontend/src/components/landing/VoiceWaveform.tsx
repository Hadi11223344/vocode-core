'use client';

import { useEffect, useRef } from 'react';
import { cn } from '@/lib/utils';

interface VoiceWaveformProps {
  className?: string;
  bars?: number;
  active?: boolean;
  color?: string;
}

export default function VoiceWaveform({
  className,
  bars = 32,
  active = true,
  color = '#6366f1',
}: VoiceWaveformProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const barEls = container.querySelectorAll<HTMLDivElement>('[data-bar]');
    if (!barEls.length) return;

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reducedMotion || !active) {
      barEls.forEach((b) => {
        b.style.height = '20%';
      });
      return;
    }

    let rafId: number;
    let frame = 0;

    const animate = () => {
      frame++;
      barEls.forEach((bar, i) => {
        const phase = (frame / 25) + (i * 0.3);
        const amplitude = Math.sin(phase) * 0.5 + 0.5;
        const noise = Math.sin(phase * 2.7) * 0.15;
        const height = Math.max(0.1, Math.min(1, amplitude + noise));
        bar.style.height = `${height * 100}%`;
      });
      rafId = requestAnimationFrame(animate);
    };
    animate();

    return () => cancelAnimationFrame(rafId);
  }, [active, bars]);

  return (
    <div
      ref={containerRef}
      className={cn('flex items-center justify-center gap-[2px] h-8', className)}
      aria-hidden="true"
    >
      {Array.from({ length: bars }).map((_, i) => (
        <div
          key={i}
          data-bar
          className="w-[2px] rounded-full transition-[height] duration-75"
          style={{
            height: '20%',
            backgroundColor: color,
            opacity: 0.6 + (i / bars) * 0.4,
          }}
        />
      ))}
    </div>
  );
}
