'use client';

import { useAuth } from '@/lib/auth-context';
import { alerts as alertsApi } from '@/lib/api';
import { AlertHistoryEntry } from '@/lib/types';
import { useRouter, usePathname } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import dynamic from 'next/dynamic';
import { PerformanceProvider, usePerformance } from '@/lib/performance-context';

const DashboardBackground = dynamic(() => import('@/components/three/dashboard-background'), { ssr: false });
const PageTransition = dynamic(() => import('@/components/three/page-transition'), { ssr: false });
import {
  LayoutDashboard,
  Bot,
  Phone,
  PhoneCall,
  Settings,
  LogOut,
  Menu,
  X,
  ChevronRight,
  BarChart3,
  Megaphone,
  BookOpen,
  Sun,
  Moon,
  Home,
  Bell,
  GitBranch,
  ShieldCheck,
  Calendar,
  CreditCard,
  AlertTriangle,
} from 'lucide-react';
import { useTheme } from '@/components/ui/theme-provider';
import { cn } from '@/lib/utils';
import { OnboardingTour } from '@/components/ui/onboarding-tour';
import { OnboardingWizard } from '@/components/onboarding/wizard';
import { ResumeCard } from '@/components/onboarding/resume-card';
import { useOnboarding } from '@/hooks/useOnboarding';
import { WifiOff } from 'lucide-react';
import { CommandPalette } from '@/components/ui/command-palette';

// ── Sidebar Nav Groups ─────────────────────────────────────
// Grouped by lifecycle phase: BUILD → DEPLOY → MONITOR → SYSTEM
const NAV_GROUPS = [
  {
    label: 'BUILD',
    items: [
      { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
      { href: '/dashboard/agents', label: 'Agents', icon: Bot },
      { href: '/dashboard/templates', label: 'Templates', icon: GitBranch },
      { href: '/dashboard/knowledge-base', label: 'Knowledge Base', icon: BookOpen },
    ],
  },
  {
    label: 'DEPLOY',
    items: [
      { href: '/dashboard/numbers', label: 'Phone Numbers', icon: Phone },
      { href: '/dashboard/campaigns', label: 'Campaigns', icon: Megaphone },
      { href: '/dashboard/schedule', label: 'Schedule', icon: Calendar },
    ],
  },
  {
    label: 'MONITOR',
    items: [
      { href: '/dashboard/calls', label: 'Calls', icon: PhoneCall },
      { href: '/dashboard/analytics', label: 'Analytics', icon: BarChart3 },
      { href: '/dashboard/quality', label: 'Quality', icon: ShieldCheck },
      { href: '/dashboard/alerts', label: 'Alerts', icon: AlertTriangle },
    ],
  },
  {
    label: 'SYSTEM',
    items: [
      { href: '/dashboard/settings', label: 'Settings', icon: Settings },
      { href: '/dashboard/billing', label: 'Billing', icon: CreditCard },
    ],
  },
];

function PerfIndicator() {
  const { quality, toggleEnabled } = usePerformance();
  const label = quality === 'high' ? '3D: High' : quality === 'low' ? '3D: Low' : '3D: Off';
  return (
    <button className="perf-indicator" onClick={toggleEnabled} title="Click to toggle 3D effects" aria-label={`3D quality: ${quality}. Click to toggle.`}>
      <span className={`perf-dot ${quality}`} aria-hidden="true" />
      {label}
    </button>
  );
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <PerformanceProvider>
      <DashboardLayoutInner>{children}</DashboardLayoutInner>
    </PerformanceProvider>
  );
}

function DashboardLayoutInner({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [isOnline, setIsOnline] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const { theme, toggleTheme } = useTheme();
  const { state, hydrated, start, isResumable } = useOnboarding();
  const [wizardOpen, setWizardOpen] = useState(false);
  const [unreadAlerts, setUnreadAlerts] = useState(0);
  const scrollContentRef = useRef<HTMLDivElement>(null);
  const [scrollProgress, setScrollProgress] = useState(0);

  // Track scroll progress for the progress bar
  useEffect(() => {
    const el = scrollContentRef.current;
    if (!el) return;
    const onScroll = () => {
      const max = el.scrollHeight - el.clientHeight;
      setScrollProgress(max > 0 ? (el.scrollTop / max) * 100 : 0);
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // Poll unread alert count every 30s
  useEffect(() => {
    const fetchAlerts = async () => {
      try {
        const data = await alertsApi.history(1, 10);
        const unread = (data.history || []).filter((h: AlertHistoryEntry) => !h.acknowledged_at).length;
        setUnreadAlerts(unread);
      } catch {
        // Silently fail — bell just shows 0
      }
    };
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!loading && !user) {
      router.push('/login');
    }
  }, [loading, user, router]);

  // Trigger wizard on first login
  useEffect(() => {
    if (hydrated && user && !state.started && !state.completed && !state.dismissedAt) {
      start();
      setWizardOpen(true);
    }
  }, [hydrated, user, state.started, state.completed, state.dismissedAt, start]);

  // Listen for GettingStartedCard to trigger wizard
  useEffect(() => {
    const onOpenWizard = () => setWizardOpen(true);
    window.addEventListener('open-wizard', onOpenWizard);
    return () => window.removeEventListener('open-wizard', onOpenWizard);
  }, []);

  useEffect(() => {
    const onOnline = () => setIsOnline(true);
    const onOffline = () => setIsOnline(false);
    setIsOnline(navigator.onLine);
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);
    return () => {
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
    };
  }, []);

  useEffect(() => {
    if (!sidebarOpen) {
      return;
    }

    const sidebar = sidebarRef.current;
    if (!sidebar) {
      return;
    }

    const focusableSelector = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
    const getFocusableElements = () =>
      Array.from(sidebar.querySelectorAll<HTMLElement>(focusableSelector)).filter(
        (element) => !element.hasAttribute('disabled'),
      );

    const previousActiveElement = document.activeElement as HTMLElement | null;
    const initialFocus = getFocusableElements()[0] || sidebar;
    initialFocus.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setSidebarOpen(false);
        return;
      }

      if (event.key !== 'Tab') {
        return;
      }

      const focusableElements = getFocusableElements();
      if (focusableElements.length === 0) {
        event.preventDefault();
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement as HTMLElement | null;

      if (event.shiftKey && activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      menuButtonRef.current?.focus();
      previousActiveElement?.focus();
    };
  }, [sidebarOpen]);

  if (loading || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg-primary)]">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 rounded-2xl gradient-brand flex items-center justify-center dash-logo-pulse">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--text-inverse)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
              <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            </svg>
          </div>
          <div className="dash-progress-bar" />
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex overflow-hidden bg-[var(--bg-primary)] relative">
      {/* 3D Background */}
      <DashboardBackground />
      {/* Page Transition Overlay */}
      <PageTransition />
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-[var(--bg-primary)]/60 backdrop-blur-sm z-40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        ref={sidebarRef}
        id="dashboard-sidebar"
        role={sidebarOpen ? 'dialog' : 'navigation'}
        aria-modal={sidebarOpen ? true : undefined}
        aria-label="Dashboard navigation"
        tabIndex={-1}
        className={cn(
          'dash-sidebar fixed lg:static inset-y-0 left-0 z-50 w-[var(--sidebar-width)] h-screen flex flex-col transition-transform duration-200 ease-out',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
          !isOnline && 'pt-9',
        )}
      >
        {/* Logo */}
        <div className="h-16 flex items-center px-5 border-b border-[var(--glass-border)]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl gradient-brand flex items-center justify-center shadow-glow-sm">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--text-inverse)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              </svg>
            </div>
            <div>
              <span className="text-lg font-bold tracking-tight">VOIA</span>
              <span className="text-[10px] font-medium text-brand-400 ml-1.5 bg-brand-500/10 px-1.5 py-0.5 rounded-full">AI</span>
            </div>
          </div>
          <button
            onClick={() => setSidebarOpen(false)}
            aria-label="Close navigation menu"
            className="ml-auto lg:hidden btn-ghost p-1.5"
          >
            <X size={18} />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 min-h-0 py-3 px-3 overflow-y-auto">
          {NAV_GROUPS.map((group) => (
            <div
              key={group.label}
              className="mb-5"
              data-tour={group.label === 'BUILD' ? 'sidebar-build' : group.label === 'DEPLOY' ? 'sidebar-deploy' : group.label === 'MONITOR' ? 'sidebar-monitor' : undefined}
            >
              <p className="dash-group-label text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                {group.label}
              </p>
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const isActive =
                    item.href === '/dashboard'
                      ? pathname === '/dashboard' || pathname === '/dashboard/'
                      : pathname === item.href || pathname.startsWith(item.href + '/');
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setSidebarOpen(false)}
                      className={cn(
                        'dash-nav-item group flex items-center gap-3 px-3 py-2 rounded-lg text-[13px] font-medium transition-all duration-150 relative',
                        isActive
                          ? 'dash-nav-active text-brand-400'
                          : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]',
                      )}
                    >
                      <item.icon size={17} strokeWidth={isActive ? 2.2 : 1.8} className="transition-transform duration-200 group-hover:scale-110" />
                      <span className="flex-1">{item.label}</span>
                      {isActive && (
                        <ChevronRight size={14} className="text-brand-400/50 animate-fade-in" />
                      )}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* User */}
        <div className="p-3 border-t border-[var(--glass-border)]">
          <div className="flex items-center gap-3 px-2 py-2">
            {user.picture_url ? (
              <Image
                src={user.picture_url}
                alt={`${user.name}'s avatar`}
                width={32}
                height={32}
                className="w-8 h-8 rounded-full ring-2 ring-[var(--border-color)]"
                referrerPolicy="no-referrer"
              />
            ) : (
              <div className="w-8 h-8 rounded-full gradient-brand flex items-center justify-center text-sm font-semibold text-[var(--text-inverse)] shadow-sm">
                {user.name?.[0] || '?'}
              </div>
            )}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{user.name}</p>
              <p className="text-[11px] text-[var(--text-muted)] truncate">{user.email}</p>
            </div>
            <button
              onClick={toggleTheme}
              aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              className="p-1.5 text-[var(--text-muted)] hover:text-brand-400 hover:bg-brand-500/10 rounded-lg transition-all duration-150"
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
            </button>
            <button
              onClick={() => router.push('/dashboard/alerts')}
              aria-label="Notifications"
              className="p-1.5 text-[var(--text-muted)] hover:text-brand-400 hover:bg-brand-500/10 rounded-lg transition-all duration-150 relative"
              title="Alerts"
            >
              <Bell size={15} />
              {unreadAlerts > 0 && (
                <span className="absolute -top-0.5 -right-0.5 min-w-[14px] h-[14px] flex items-center justify-center bg-red-500 text-[var(--text-inverse)] text-[9px] font-bold rounded-full px-1">
                  {unreadAlerts > 9 ? '9+' : unreadAlerts}
                </span>
              )}
            </button>
            <button
              onClick={logout}
              aria-label="Sign out"
              className="p-1.5 text-[var(--text-muted)] hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all duration-150"
              title="Sign out"
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </aside>

      {/* FE-14: Offline indicator banner */}
      {!isOnline && (
        <div className="fixed top-0 left-0 right-0 z-[60] bg-amber-500/15 border-b border-amber-500/30 flex items-center justify-center gap-2 px-4 py-2 text-xs text-amber-400 backdrop-blur-sm">
          <WifiOff size={14} />
          <span>You are offline. Changes will not be saved until connection is restored.</span>
        </div>
      )}

      {/* Main content */}
      <main className={cn('flex-1 flex flex-col min-h-0 overflow-hidden relative z-10 bg-[var(--bg-primary)]', !isOnline && 'pt-9')}>
        {/* Top bar (mobile) */}
        <header className="dash-topbar h-14 flex items-center gap-4 px-4 lg:hidden">
          <button
            ref={menuButtonRef}
            onClick={() => setSidebarOpen(true)}
            aria-label="Open navigation menu"
            aria-controls="dashboard-sidebar"
            aria-expanded={sidebarOpen}
            className="btn-ghost p-1.5"
          >
            <Menu size={20} />
          </button>
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg gradient-brand flex items-center justify-center">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-inverse)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
              </svg>
            </div>
            <span className="text-base font-bold tracking-tight">VOIA</span>
          </div>
        </header>

        {/* Breadcrumb bar for nested pages */}
        {pathname !== '/dashboard' && pathname !== '/dashboard/' && (
          <div className="px-5 lg:px-8 pt-4 pb-0">
            <nav className="dash-breadcrumb">
              <Link href="/dashboard" className="hover:text-[var(--text-primary)] transition-colors flex items-center gap-1">
                <Home size={12} />
              </Link>
              {pathname.split('/').filter(Boolean).slice(1).map((segment, i, arr) => {
                const href = '/dashboard/' + arr.slice(0, i + 1).join('/');
                const isLast = i === arr.length - 1;
                const isNumeric = /^\d+$/.test(segment);
                const prevSegment = i > 0 ? arr[i - 1] : '';
                const label = isNumeric
                  ? `${prevSegment.replace(/-/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())} #${segment}`
                  : segment.replace(/-/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
                return (
                  <span key={href} className="flex items-center gap-1.5">
                    <ChevronRight size={12} className="opacity-40" />
                    {isLast ? (
                      <span className="text-[var(--text-primary)] font-medium">{label}</span>
                    ) : (
                      <Link href={href} className="hover:text-[var(--text-primary)] transition-colors">{label}</Link>
                    )}
                  </span>
                );
              })}
            </nav>
          </div>
        )}

        <div ref={scrollContentRef} className="flex-1 overflow-y-auto p-5 lg:p-8 bg-[var(--bg-secondary)] relative">
          {/* Scroll progress bar */}
          <div className="dash-scroll-progress">
            <div className="dash-scroll-progress-bar" style={{ width: `${scrollProgress}%` }} />
          </div>
          {/* Aurora blob accents */}
          <div className="dash-aurora dash-aurora-1" aria-hidden="true" />
          <div className="dash-aurora dash-aurora-2" aria-hidden="true" />
          {/* Noise overlay */}
          <div className="dash-noise-overlay" aria-hidden="true" />
          <div className="dash-page-animate relative z-10">{children}</div>
        </div>
      </main>
      <OnboardingTour />
      <OnboardingWizard open={wizardOpen} onClose={() => setWizardOpen(false)} />
      {isResumable && !wizardOpen && (
        <ResumeCard onResume={() => setWizardOpen(true)} />
      )}
      <CommandPalette />
      <PerfIndicator />
    </div>
  );
}
