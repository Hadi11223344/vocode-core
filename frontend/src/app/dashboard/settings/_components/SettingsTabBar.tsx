'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Shield, Key, ClipboardCheck, Plug } from 'lucide-react';
import { cn } from '@/lib/utils';

const TABS = [
  { id: 'profile', label: 'Profile', icon: Shield, href: '/dashboard/settings' },
  { id: 'integrations', label: 'Integrations', icon: Plug, href: '/dashboard/integrations' },
  { id: 'api-keys', label: 'API Keys', icon: Key, href: '/dashboard/keys' },
  { id: 'reviews', label: 'Review Queue', icon: ClipboardCheck, href: '/dashboard/reviews' },
];

export default function SettingsTabBar() {
  const pathname = usePathname();

  return (
    <div className="flex gap-1 border-b border-[var(--glass-border)]">
      {TABS.map((tab) => {
        const isActive =
          (tab.id === 'profile' && (pathname === '/dashboard/settings' || pathname === '/dashboard/settings/')) ||
          (tab.id !== 'profile' && pathname.startsWith(tab.href));
        return (
          <Link
            key={tab.id}
            href={tab.href}
            className={cn(
              'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
              isActive
                ? 'border-brand-400 text-brand-400'
                : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text-secondary)]'
            )}
          >
            <tab.icon size={16} />
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
