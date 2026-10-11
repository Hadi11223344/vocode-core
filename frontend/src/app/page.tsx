'use client';

import { useState, useEffect } from 'react';
import dynamic from 'next/dynamic';
import { useAuth } from '@/lib/auth-context';

import Navbar from './sections/navbar';
import HeroSection from './sections/hero';
import MetricsBar from './sections/metrics-bar';
import LogoStrip from './sections/logo-strip';
import HowItWorksSection from './sections/how-it-works';
import FeaturesSection from './sections/features';
import ConversationDemo from './sections/conversation-demo';
import ShowcaseSection from './sections/showcase';
import UseCasesSection from './sections/use-cases';
import IntegrationsSection from './sections/integrations';
import ROISection from './sections/roi';
import PricingSection from './sections/pricing';
import TestimonialsSection from './sections/testimonials';
import FAQSection from './sections/faq';
import CTASection from './sections/cta';
import Footer from './sections/footer';
import { SHOWCASES } from './sections/data';

const AnimatedBackground = dynamic(() => import('@/components/landing/AnimatedBackground'), { ssr: false });
const ScrollProgress = dynamic(() => import('@/components/landing/ScrollProgress'), { ssr: false });
const PageLoader = dynamic(() => import('@/components/landing/PageLoader'), { ssr: false });

/* ═══════════════════════════════════════════════
   MAIN PAGE
   ═══════════════════════════════════════════════ */
export default function LandingPage() {
  const { user } = useAuth();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [navBgOpacity, setNavBgOpacity] = useState(0);

  useEffect(() => {
    let rafId: number | null = null;
    const onScroll = () => {
      if (rafId) return;
      rafId = requestAnimationFrame(() => {
        const scrollY = window.scrollY;
        const opacity = Math.min(scrollY / 80, 1);
        setNavBgOpacity(opacity);
        setScrolled(opacity > 0.3);
        rafId = null;
      });
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', onScroll);
      if (rafId) cancelAnimationFrame(rafId);
    };
  }, []);

  useEffect(() => {
    const supportsPointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!supportsPointer || reducedMotion) return;

    const cards = Array.from(document.querySelectorAll<HTMLElement>('[data-tilt-card]'));
    if (!cards.length) return;

    const resetCard = (card: HTMLElement, resetPointer = false) => {
      card.classList.remove('is-tilting');
      card.style.setProperty('--tilt-rotate-x', '0deg');
      card.style.setProperty('--tilt-rotate-y', '0deg');
      if (resetPointer) {
        card.style.setProperty('--tilt-pointer-x', '50%');
        card.style.setProperty('--tilt-pointer-y', '50%');
      }
    };

    const cleanup = cards.map((card) => {
      let pendingUpdate: { x: number; y: number } | null = null;
      let rafId: number | null = null;

      const flushUpdate = () => {
        if (!pendingUpdate) return;
        const { x, y } = pendingUpdate;
        const clampedX = Math.min(1, Math.max(0, x));
        const clampedY = Math.min(1, Math.max(0, y));
        const maxTilt = 2.5;
        const rotateY = (clampedX - 0.5) * maxTilt * 2;
        const rotateX = (0.5 - clampedY) * maxTilt * 2;

        card.classList.add('is-tilting');
        card.style.setProperty('--tilt-rotate-x', `${rotateX.toFixed(2)}deg`);
        card.style.setProperty('--tilt-rotate-y', `${rotateY.toFixed(2)}deg`);
        card.style.setProperty('--tilt-pointer-x', `${(clampedX * 100).toFixed(2)}%`);
        card.style.setProperty('--tilt-pointer-y', `${(clampedY * 100).toFixed(2)}%`);
        pendingUpdate = null;
        rafId = null;
      };

      const onMouseMove = (event: MouseEvent) => {
        const rect = card.getBoundingClientRect();
        const x = (event.clientX - rect.left) / rect.width;
        const y = (event.clientY - rect.top) / rect.height;
        if (pendingUpdate && Math.abs(pendingUpdate.x - x) < 0.01 && Math.abs(pendingUpdate.y - y) < 0.01) return;
        pendingUpdate = { x, y };
        if (!rafId) {
          rafId = requestAnimationFrame(flushUpdate);
        }
      };

      const onMouseLeave = () => {
        if (rafId) cancelAnimationFrame(rafId);
        pendingUpdate = null;
        rafId = null;
        resetCard(card);
      };

      card.addEventListener('mousemove', onMouseMove, { passive: true });
      card.addEventListener('mouseleave', onMouseLeave, { passive: true });
      resetCard(card);

      return () => {
        card.removeEventListener('mousemove', onMouseMove);
        card.removeEventListener('mouseleave', onMouseLeave);
        if (rafId) cancelAnimationFrame(rafId);
      };
    });

    return () => {
      cleanup.forEach((fn) => fn());
      cards.forEach((card) => resetCard(card, true));
    };
  }, []);

  const ctaHref = user ? '/dashboard' : '/login';

  return (
    <div className="min-h-screen bg-[var(--bg-primary)] overflow-x-hidden">
      <PageLoader />
      <ScrollProgress />
      <AnimatedBackground />
      <Navbar scrolled={scrolled} mobileMenuOpen={mobileMenuOpen} setMobileMenuOpen={setMobileMenuOpen} ctaHref={ctaHref} user={user} navBgOpacity={navBgOpacity} />
      <HeroSection ctaHref={ctaHref} />
      <MetricsBar />
      <LogoStrip />
      <HowItWorksSection ctaHref={ctaHref} />
      <FeaturesSection />
      <ConversationDemo />
      {SHOWCASES.map((s, i) => <ShowcaseSection key={s.title} {...s} reversed={i % 2 === 1} />)}
      <UseCasesSection />
      <IntegrationsSection />
      <ROISection />
      <PricingSection ctaHref={ctaHref} />
      <TestimonialsSection />
      <FAQSection />
      <CTASection ctaHref={ctaHref} />
      <Footer />
    </div>
  );
}
