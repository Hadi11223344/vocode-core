'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import gsap from 'gsap';
import { usePerformance } from '@/lib/performance-context';

export default function PageTransition() {
  const { quality } = usePerformance();
  const pathname = usePathname();
  const overlayRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(false);

  useEffect(() => {
    if (quality === 'off') return;
    setActive(true);

    const overlay = overlayRef.current;
    if (!overlay) return;

    const tl = gsap.timeline({
      onComplete: () => setActive(false),
    });

    tl.set(overlay, { display: 'block' });
    tl.fromTo(overlay,
      { clipPath: 'inset(0 0 100% 0)', opacity: 0.8 },
      { clipPath: 'inset(0 0 0% 0)', opacity: 0.6, duration: 0.35, ease: 'power3.in' }
    );
    tl.to(overlay, {
      clipPath: 'inset(0 0 0% 0)',
      opacity: 0,
      duration: 0.35,
      ease: 'power3.out',
    });
    tl.set(overlay, { display: 'none' });

    return () => { tl.kill(); };
  }, [pathname, quality]);

  if (quality === 'off' || !active) return null;

  return (
    <div
      ref={overlayRef}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        pointerEvents: 'none',
        display: 'none',
        background: 'linear-gradient(180deg, rgba(99,102,241,0.15) 0%, rgba(168,85,247,0.1) 50%, transparent 100%)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
      }}
    />
  );
}
