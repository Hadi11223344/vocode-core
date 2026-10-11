'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { Mic, Menu, X, ArrowRight } from 'lucide-react';
import { cn } from '@/lib/utils';

interface NavbarProps {
  scrolled: boolean;
  mobileMenuOpen: boolean;
  setMobileMenuOpen: (v: boolean) => void;
  ctaHref: string;
  user: unknown;
  navBgOpacity: number;
}

export default function Navbar({ scrolled, mobileMenuOpen, setMobileMenuOpen, ctaHref, user, navBgOpacity }: NavbarProps) {
  const links = [
    { label: 'Features', href: '#features' },
    { label: 'Use Cases', href: '#use-cases' },
    { label: 'Integrations', href: '#integrations' },
    { label: 'Pricing', href: '#pricing' },
    { label: 'Docs', href: '/docs' },
  ];

  useEffect(() => {
    if (!mobileMenuOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      const focusableElements = document.querySelectorAll<HTMLElement>(
        'a[href], button:not([aria-hidden="true"]), [tabindex]:not([tabindex="-1"])'
      );
      const menuElements = Array.from(focusableElements).filter(el => {
        const rect = el.getBoundingClientRect();
        return rect.top >= 64;
      });
      if (!menuElements.length) return;
      const firstElement = menuElements[0];
      const lastElement = menuElements[menuElements.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === firstElement) {
          e.preventDefault();
          lastElement.focus();
        }
      } else {
        if (document.activeElement === lastElement) {
          e.preventDefault();
          firstElement.focus();
        }
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    const firstLink = document.querySelector<HTMLElement>('a[href="#features"]');
    if (firstLink) setTimeout(() => firstLink.focus(), 50);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [mobileMenuOpen]);

  return (
    <nav
      className={cn('fixed top-0 left-0 right-0 z-50 transition-all duration-300 glass-nav glass-nav-border', scrolled ? 'scrolled' : '')}
      style={{
        background: `var(--glass-nav-bg)`,
        backdropFilter: navBgOpacity > 0.1 ? 'blur(20px)' : 'blur(0px)',
        borderBottom: navBgOpacity > 0.1 ? `1px solid var(--glass-border)` : '1px solid transparent',
      }}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <Link href="/" className="flex items-center gap-3 group">
            <div className="w-9 h-9 rounded-xl gradient-brand flex items-center justify-center shadow-glow-sm group-hover:shadow-glow transition-all duration-300 group-hover:scale-105">
              <Mic className="w-[18px] h-[18px] text-white" />
            </div>
            <span className="text-lg font-bold tracking-tight">VOIA</span>
          </Link>
          <div className="hidden md:flex items-center gap-1">
            {links.map((l) => (
              <a key={l.label} href={l.href} className="nav-link px-3.5 py-2 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors rounded-lg hover:bg-[var(--surface-hover)]">{l.label}</a>
            ))}
          </div>
          <div className="hidden md:flex items-center gap-3">
            <Link href={ctaHref} className="btn-ghost text-sm">{user ? 'Dashboard' : 'Log in'}</Link>
            <Link href={ctaHref} className="btn-primary shimmer-sweep text-sm !rounded-full !px-5">Get Started Free <ArrowRight className="w-3.5 h-3.5" /></Link>
          </div>
          <button
            className="md:hidden p-2 text-[var(--text-secondary)] hover:text-[var(--text-primary)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-400 rounded-lg"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label={mobileMenuOpen ? 'Close navigation menu' : 'Open navigation menu'}
            aria-expanded={mobileMenuOpen}
          >
            {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>
      {mobileMenuOpen && (
        <div className="md:hidden glass-card border-t animate-fade-in max-h-[calc(100vh-64px)] overflow-y-auto">
          <div className="px-4 py-4 space-y-1">
            {links.map((l) => (
              <a key={l.label} href={l.href} className="block px-3 py-2.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-400 transition-colors" onClick={() => setMobileMenuOpen(false)}>{l.label}</a>
            ))}
            <div className="pt-3 border-t border-[var(--border-color)]">
              <Link href={ctaHref} className="block w-full btn-primary text-sm text-center !rounded-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-400" onClick={() => setMobileMenuOpen(false)}>Get Started Free</Link>
            </div>
          </div>
        </div>
      )}
    </nav>
  );
}
