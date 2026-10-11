'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { cn } from '@/lib/utils';
import {
  LayoutDashboard,
  Bot,
  Phone,
  PhoneCall,
  BarChart3,
  Settings,
  Plug,
  Radio,
  Megaphone,
  BookOpen,
  Search,
  Command,
  ArrowUp,
  ArrowDown,
  CornerDownLeft,
  X,
  GitBranch,
  ClipboardCheck,
  ShieldCheck,
  Calendar,
  CreditCard,
  Key,
  AlertTriangle,
  Bell,
} from 'lucide-react';

interface CommandItem {
  id: string;
  label: string;
  href: string;
  icon: React.ElementType;
  shortcut?: string;
  category: string;
}

const COMMANDS: CommandItem[] = [
  { id: 'dash', label: 'Dashboard', href: '/dashboard', icon: LayoutDashboard, category: 'Pages' },
  { id: 'play', label: 'Playground', href: '/dashboard/playground', icon: Radio, category: 'Pages' },
  { id: 'agents', label: 'Agents', href: '/dashboard/agents', icon: Bot, category: 'Pages' },
  { id: 'templates', label: 'Templates', href: '/dashboard/templates', icon: GitBranch, category: 'Pages' },
  { id: 'workflows', label: 'Workflows', href: '/dashboard/workflows', icon: GitBranch, category: 'Pages' },
  { id: 'kb', label: 'Knowledge Base', href: '/dashboard/knowledge-base', icon: BookOpen, category: 'Pages' },
  { id: 'numbers', label: 'Phone Numbers', href: '/dashboard/numbers', icon: Phone, category: 'Pages' },
  { id: 'campaigns', label: 'Campaigns', href: '/dashboard/campaigns', icon: Megaphone, category: 'Pages' },
  { id: 'schedule', label: 'Schedule', href: '/dashboard/schedule', icon: Calendar, category: 'Pages' },
  { id: 'live', label: 'Live', href: '/dashboard/live', icon: Radio, category: 'Pages' },
  { id: 'calls', label: 'Calls', href: '/dashboard/calls', icon: PhoneCall, category: 'Pages' },
  { id: 'analytics', label: 'Analytics', href: '/dashboard/analytics', icon: BarChart3, category: 'Pages' },
  { id: 'reviews', label: 'Reviews', href: '/dashboard/reviews', icon: ClipboardCheck, category: 'Pages' },
  { id: 'quality', label: 'Quality', href: '/dashboard/quality', icon: ShieldCheck, category: 'Pages' },
  { id: 'alerts', label: 'Alerts', href: '/dashboard/alerts', icon: AlertTriangle, category: 'Pages' },
  { id: 'settings', label: 'Settings', href: '/dashboard/settings', icon: Settings, category: 'Pages' },
  { id: 'integrations', label: 'Integrations', href: '/dashboard/integrations', icon: Plug, category: 'Pages' },
  { id: 'billing', label: 'Billing', href: '/dashboard/billing', icon: CreditCard, category: 'Pages' },
  { id: 'keys', label: 'API Keys', href: '/dashboard/keys', icon: Key, category: 'Pages' },
  { id: 'new-agent', label: 'Create New Agent', href: '/dashboard/agents?create=1', icon: Bot, category: 'Actions' },
  { id: 'new-campaign', label: 'Create New Campaign', href: '/dashboard/campaigns?create=1', icon: Megaphone, category: 'Actions' },
];

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Keyboard shortcut: Cmd+K / Ctrl+K
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
      if (e.key === 'Escape') {
        setOpen(false);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  // Focus input on open
  useEffect(() => {
    if (open) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  const filtered = COMMANDS.filter((c) =>
    c.label.toLowerCase().includes(query.toLowerCase()) ||
    c.category.toLowerCase().includes(query.toLowerCase())
  );

  const handleSelect = useCallback(
    (item: CommandItem) => {
      setOpen(false);
      router.push(item.href);
    },
    [router]
  );

  const onInputKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const item = filtered[selectedIndex];
      if (item) handleSelect(item);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-start justify-center pt-[15vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm"
        onClick={() => setOpen(false)}
      />

      {/* Modal */}
      <div className="relative w-full max-w-lg bg-[var(--bg-secondary)] rounded-xl border border-[var(--border-color)] shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Search input */}
        <div className="flex items-center gap-3 px-4 py-3.5 border-b border-[var(--border-color)]">
          <Search size={18} className="text-[var(--text-muted)]" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setSelectedIndex(0); }}
            onKeyDown={onInputKeyDown}
            placeholder="Type a command or page name..."
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--text-muted)] text-[var(--text-primary)]"
          />
          <div className="flex items-center gap-1 text-[10px] text-[var(--text-muted)]">
            <kbd className="px-1.5 py-0.5 rounded bg-[var(--bg-tertiary)] border border-[var(--border-color)] font-mono">
              ESC
            </kbd>
          </div>
        </div>

        {/* Results */}
        <div className="max-h-[50vh] overflow-y-auto py-2">
          {filtered.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-[var(--text-muted)]">
              No commands found for &quot;{query}&quot;
            </div>
          ) : (
            (['Pages', 'Actions'] as const).map((category) => {
              const items = filtered.filter((c) => c.category === category);
              if (items.length === 0) return null;
              return (
                <div key={category}>
                  <div className="px-4 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                    {category}
                  </div>
                  {items.map((item, i) => {
                    const globalIndex = filtered.indexOf(item);
                    const isSelected = globalIndex === selectedIndex;
                    const Icon = item.icon;
                    return (
                      <button
                        key={item.id}
                        onClick={() => handleSelect(item)}
                        onMouseEnter={() => setSelectedIndex(globalIndex)}
                        className={cn(
                          'w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors',
                          isSelected
                            ? 'bg-brand-600/15 text-brand-400'
                            : 'text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]'
                        )}
                      >
                        <Icon size={16} strokeWidth={isSelected ? 2.2 : 1.8} />
                        <span className="flex-1 text-sm">{item.label}</span>
                        {isSelected && (
                          <CornerDownLeft size={14} className="text-[var(--text-muted)]" />
                        )}
                      </button>
                    );
                  })}
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-2 border-t border-[var(--border-color)] flex items-center gap-3 text-[10px] text-[var(--text-muted)]">
          <span className="flex items-center gap-1">
            <ArrowUp size={10} />
            <ArrowDown size={10} />
            to navigate
          </span>
          <span className="flex items-center gap-1">
            <CornerDownLeft size={10} />
            to select
          </span>
        </div>
      </div>
    </div>
  );
}
