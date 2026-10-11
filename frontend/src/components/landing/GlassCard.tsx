'use client';

import { forwardRef, type ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface GlassCardProps {
  children: ReactNode;
  className?: string;
  glow?: boolean;
  tilt?: boolean;
}

const GlassCard = forwardRef<HTMLDivElement, GlassCardProps>(
  ({ children, className, glow = false, tilt = false }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          'glass-card relative rounded-2xl overflow-hidden',
          glow && 'glass-card-glow',
          tilt && 'tilt-card',
          className
        )}
        {...(tilt ? { 'data-tilt-card': '' } : {})}
      >
        <div className="glass-card-border" />
        <div className="relative z-10">{children}</div>
      </div>
    );
  }
);

GlassCard.displayName = 'GlassCard';
export default GlassCard;
