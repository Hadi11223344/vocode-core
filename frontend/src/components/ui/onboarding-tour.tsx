'use client';

import { useState, useEffect, useCallback } from 'react';
import { X, ChevronRight, ChevronLeft, Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';

interface TourStep {
  target: string; // CSS selector
  title: string;
  content: string;
  position?: 'top' | 'bottom' | 'left' | 'right';
}

const TOUR_STEPS: TourStep[] = [
  {
    target: '[data-tour="sidebar-build"]',
    title: 'Build Your Agents',
    content: 'Start here to create voice agents, manage knowledge bases, and design conversational flows.',
    position: 'right',
  },
  {
    target: '[data-tour="sidebar-deploy"]',
    title: 'Deploy to Phone Numbers',
    content: 'Connect phone numbers and launch outbound campaigns to reach your customers.',
    position: 'right',
  },
  {
    target: '[data-tour="sidebar-monitor"]',
    title: 'Monitor Performance',
    content: 'Track call history, analytics, AI quality scores, and real-time alerts.',
    position: 'right',
  },
  {
    target: '[data-tour="header-new-agent"]',
    title: 'Quick Start',
    content: 'Create your first agent with one click. Choose from 30+ domain templates.',
    position: 'bottom',
  },
];

export function OnboardingTour() {
  const [show, setShow] = useState(false);
  const [step, setStep] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);

  useEffect(() => {
    const seen = localStorage.getItem('vocode-tour-completed');
    if (!seen) {
      const timer = setTimeout(() => setShow(true), 800);
      return () => clearTimeout(timer);
    }
  }, []);

  const updateTarget = useCallback(() => {
    const selector = TOUR_STEPS[step]?.target;
    if (!selector) return;
    const el = document.querySelector(selector);
    if (el) {
      setRect(el.getBoundingClientRect());
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [step]);

  useEffect(() => {
    if (show) updateTarget();
  }, [show, step, updateTarget]);

  useEffect(() => {
    const onResize = () => updateTarget();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [updateTarget]);

  const close = () => {
    setShow(false);
    localStorage.setItem('vocode-tour-completed', 'true');
  };

  const next = () => {
    if (step < TOUR_STEPS.length - 1) setStep(s => s + 1);
    else close();
  };

  const prev = () => step > 0 && setStep(s => s - 1);

  if (!show || !rect) return null;

  const current = TOUR_STEPS[step];
  const isLast = step === TOUR_STEPS.length - 1;

  // Position tooltip
  let tooltipStyle: React.CSSProperties = {};
  const pad = 12;
  switch (current.position) {
    case 'right':
      tooltipStyle = { left: rect.right + pad, top: rect.top + rect.height / 2, transform: 'translateY(-50%)' };
      break;
    case 'left':
      tooltipStyle = { right: window.innerWidth - rect.left + pad, top: rect.top + rect.height / 2, transform: 'translateY(-50%)' };
      break;
    case 'bottom':
      tooltipStyle = { left: rect.left + rect.width / 2, top: rect.bottom + pad, transform: 'translateX(-50%)' };
      break;
    case 'top':
    default:
      tooltipStyle = { left: rect.left + rect.width / 2, bottom: window.innerHeight - rect.top + pad, transform: 'translateX(-50%)' };
      break;
  }

  return (
    <div className="fixed inset-0 z-[100]">
      {/* Dark overlay with cutout */}
      <svg className="absolute inset-0 w-full h-full pointer-events-none">
        <defs>
          <mask id="tour-mask">
            <rect x="0" y="0" width="100%" height="100%" fill="white" />
            <rect
              x={rect.left - 8}
              y={rect.top - 8}
              width={rect.width + 16}
              height={rect.height + 16}
              rx={12}
              fill="black"
            />
          </mask>
        </defs>
        <rect x="0" y="0" width="100%" height="100%" fill="rgba(0,0,0,0.65)" mask="url(#tour-mask)" />
      </svg>

      {/* Highlight ring */}
      <div
        className="absolute rounded-xl border-2 border-brand-400 pointer-events-none animate-pulse"
        style={{
          left: rect.left - 6,
          top: rect.top - 6,
          width: rect.width + 12,
          height: rect.height + 12,
        }}
      />

      {/* Tooltip */}
      <div
        className={cn(
          'absolute z-10 w-80 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-xl shadow-2xl p-5 animate-scale-in',
          current.position === 'right' && 'origin-left',
          current.position === 'left' && 'origin-right',
          current.position === 'bottom' && 'origin-top',
          current.position === 'top' && 'origin-bottom'
        )}
        style={tooltipStyle}
      >
        <div className="flex items-center justify-between mb-2">
          <h4 className="font-semibold text-sm flex items-center gap-1.5">
            <Sparkles size={14} className="text-brand-400" />
            {current.title}
          </h4>
          <button onClick={close} className="btn-ghost p-1">
            <X size={14} />
          </button>
        </div>
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{current.content}</p>
        <div className="flex items-center justify-between mt-4">
          <div className="flex items-center gap-1">
            {TOUR_STEPS.map((_, i) => (
              <div
                key={i}
                className={cn(
                  'w-2 h-2 rounded-full transition-colors',
                  i === step ? 'bg-brand-400' : 'bg-[var(--bg-tertiary)]'
                )}
              />
            ))}
          </div>
          <div className="flex items-center gap-2">
            {step > 0 && (
              <button onClick={prev} className="btn-ghost text-xs px-2 py-1">
                <ChevronLeft size={14} /> Back
              </button>
            )}
            <button onClick={next} className="btn-primary text-xs px-3 py-1.5">
              {isLast ? 'Finish' : 'Next'} <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
