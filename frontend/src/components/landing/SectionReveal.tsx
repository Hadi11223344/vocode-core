'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface SectionRevealProps {
  children: ReactNode;
  className?: string;
  delay?: number;
  y?: number;
  once?: boolean;
}

export default function SectionReveal({
  children,
  className,
  delay = 0,
  y = 30,
  once = true,
}: SectionRevealProps) {
  const ref = useRef<HTMLDivElement>(null);
  const visibleRef = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reducedMotion) {
      el.style.opacity = '1';
      el.style.transform = 'none';
      return;
    }

    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          if (once && visibleRef.current) return;
          visibleRef.current = true;
          el.style.transition = `opacity 0.6s cubic-bezier(0.16, 1, 0.3, 1) ${delay}ms, transform 0.6s cubic-bezier(0.16, 1, 0.3, 1) ${delay}ms`;
          el.style.opacity = '1';
          el.style.transform = 'translateY(0)';
          if (once) obs.disconnect();
        } else if (!once) {
          visibleRef.current = false;
          el.style.opacity = '0';
          el.style.transform = `translateY(${y}px)`;
        }
      },
      { threshold: 0.12 }
    );

    el.style.opacity = '0';
    el.style.transform = `translateY(${y}px)`;
    obs.observe(el);

    return () => obs.disconnect();
  }, [delay, y, once]);

  return (
    <div ref={ref} className={cn('will-change-transform', className)}>
      {children}
    </div>
  );
}
