'use client';

import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { usePerformance } from '@/lib/performance-context';

if (typeof window !== 'undefined') {
  gsap.registerPlugin(ScrollTrigger);
}

export function useGsapPageEnter(containerRef: React.RefObject<HTMLElement>) {
  const { quality } = usePerformance();

  useEffect(() => {
    if (quality === 'off' || !containerRef.current) return;

    const ctx = gsap.context(() => {
      const hasGsapAttrs = containerRef.current?.querySelector('[data-gsap]');
      if (hasGsapAttrs) {
        const tl = gsap.timeline({ defaults: { ease: 'power3.out' } });
        tl.from('[data-gsap="header"]', { y: -20, opacity: 0, duration: 0.5 });
        tl.from('[data-gsap="stat"]', { y: 30, opacity: 0, duration: 0.5, stagger: 0.08 }, '-=0.2');
        tl.from('[data-gsap="card"]', { y: 24, opacity: 0, duration: 0.45, stagger: 0.06 }, '-=0.25');
        tl.from('[data-gsap="content"]', { y: 20, opacity: 0, duration: 0.4, stagger: 0.08 }, '-=0.2');
        tl.from('[data-gsap="reveal"]', { y: 20, opacity: 0, duration: 0.4, stagger: 0.06 }, '-=0.15');
      } else {
        gsap.from(containerRef.current!.querySelectorAll('.dash-card, .page-title, .page-subtitle'), {
          y: 20, opacity: 0, duration: 0.5, stagger: 0.05, ease: 'power3.out',
        });
      }
    }, containerRef);

    return () => ctx.revert();
  }, [quality, containerRef]);
}

export function useGsapCounter(
  ref: React.RefObject<HTMLElement>,
  target: number,
  options?: { decimals?: number; duration?: number; suffix?: string; prefix?: string }
) {
  const { quality } = usePerformance();
  const { decimals = 0, duration = 1.2, suffix = '', prefix = '' } = options || {};
  const objRef = useRef({ val: 0 });

  useEffect(() => {
    if (quality === 'off' || !ref.current) {
      if (ref.current) ref.current.textContent = `${prefix}${target.toFixed(decimals)}${suffix}`;
      return;
    }

    objRef.current.val = 0;
    const tween = gsap.to(objRef.current, {
      val: target,
      duration,
      ease: 'power2.out',
      onUpdate: () => {
        if (ref.current) ref.current.textContent = `${prefix}${objRef.current.val.toFixed(decimals)}${suffix}`;
      },
    });

    return () => { tween.kill(); };
  }, [target, quality, ref, decimals, duration, suffix, prefix]);
}

export function useGsapStaggerCards(containerRef: React.RefObject<HTMLElement>) {
  const { quality } = usePerformance();

  useEffect(() => {
    if (quality === 'off' || !containerRef.current) return;

    const ctx = gsap.context(() => {
      gsap.from('.dash-card', { y: 24, opacity: 0, duration: 0.5, stagger: 0.06, ease: 'power3.out' });
    }, containerRef);

    return () => ctx.revert();
  }, [quality, containerRef]);
}

export function useGsapScrollReveal(containerRef: React.RefObject<HTMLElement>) {
  const { quality } = usePerformance();

  useEffect(() => {
    if (quality === 'off' || !containerRef.current) return;

    const ctx = gsap.context(() => {
      gsap.utils.toArray<HTMLElement>('[data-gsap="reveal"]').forEach((el) => {
        gsap.from(el, {
          y: 40, opacity: 0, duration: 0.6, ease: 'power3.out',
          scrollTrigger: { trigger: el, start: 'top 85%', toggleActions: 'play none none none' },
        });
      });
    }, containerRef);

    return () => ctx.revert();
  }, [quality, containerRef]);
}

export function useGsapTilt(ref: React.RefObject<HTMLElement>) {
  const { quality } = usePerformance();

  useEffect(() => {
    if (quality === 'off' || !ref.current) return;
    const el = ref.current;

    const onMouseMove = (e: MouseEvent) => {
      const rect = el.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width - 0.5;
      const y = (e.clientY - rect.top) / rect.height - 0.5;
      gsap.to(el, { rotateY: x * 8, rotateX: -y * 8, transformPerspective: 800, transformOrigin: 'center', duration: 0.3, ease: 'power2.out' });
    };

    const onMouseLeave = () => {
      gsap.to(el, { rotateY: 0, rotateX: 0, duration: 0.5, ease: 'power3.out' });
    };

    el.addEventListener('mousemove', onMouseMove);
    el.addEventListener('mouseleave', onMouseLeave);

    return () => {
      el.removeEventListener('mousemove', onMouseMove);
      el.removeEventListener('mouseleave', onMouseLeave);
    };
  }, [quality, ref]);
}
