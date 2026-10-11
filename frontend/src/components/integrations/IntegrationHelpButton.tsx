'use client';

import { useState, useCallback } from 'react';
import { HelpCircle, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { integrations as integrationsApi } from '@/lib/api';
import type { IntegrationType, Integration } from '@/lib/types';
import { IntegrationHelpDrawer } from './IntegrationHelpDrawer';

interface IntegrationHelpButtonProps {
  /** The integration type object (if already available) */
  integrationType?: IntegrationType;
  /** Or just the type ID to fetch on demand */
  typeId?: string;
  /** Optional active integration instance for Test tab */
  integration?: Integration | null;
  /** Visual size */
  size?: 'sm' | 'md';
  /** Additional CSS classes */
  className?: string;
  /** Tooltip title shown on hover */
  title?: string;
}

export function IntegrationHelpButton({
  integrationType: providedType,
  typeId,
  integration,
  size = 'sm',
  className,
  title = 'Learn more about this integration',
}: IntegrationHelpButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [fetchedType, setFetchedType] = useState<IntegrationType | null>(null);

  const resolvedType = providedType || fetchedType;

  const handleOpen = useCallback(async () => {
    if (providedType) {
      setIsOpen(true);
      return;
    }
    if (typeId) {
      setLoading(true);
      try {
        const res = await integrationsApi.type(typeId);
        setFetchedType(res.type);
        setIsOpen(true);
      } catch {
        // Silently fail — user can go to Integrations page for full docs
      } finally {
        setLoading(false);
      }
    }
  }, [providedType, typeId]);

  const iconSize = size === 'sm' ? 14 : 16;

  return (
    <>
      <button
        onClick={(e) => {
          e.stopPropagation();
          handleOpen();
        }}
        disabled={loading}
        className={cn(
          'shrink-0 rounded-md transition-colors disabled:opacity-50',
          size === 'sm' ? 'p-1.5' : 'p-2',
          'text-[var(--text-muted)] hover:text-brand-400 hover:bg-brand-500/10',
          className
        )}
        title={title}
      >
        {loading ? <Loader2 size={iconSize} className="animate-spin" /> : <HelpCircle size={iconSize} />}
      </button>

      {resolvedType && (
        <IntegrationHelpDrawer
          integrationType={resolvedType}
          integration={integration}
          isOpen={isOpen}
          onClose={() => setIsOpen(false)}
        />
      )}
    </>
  );
}
