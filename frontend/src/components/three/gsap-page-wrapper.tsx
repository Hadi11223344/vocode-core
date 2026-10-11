'use client';

import { useRef, useEffect } from 'react';
import { useGsapPageEnter } from '@/hooks/use-gsap-animations';

export default function GsapPageWrapper({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useGsapPageEnter(ref);

  return (
    <div ref={ref} className="gsap-page-wrapper animate-fade-in">
      {children}
    </div>
  );
}
