'use client';

import { Check, AlertTriangle } from 'lucide-react';
import { NodeConfigProps } from './types';

export default function SendEmailConfig({ nodeConfig, updateConfig, platformEmailReady }: NodeConfigProps) {
  return (
    <>
      {platformEmailReady === true && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-500/5 border border-emerald-500/20 mb-3">
          <Check size={14} className="text-emerald-400 flex-shrink-0" />
          <p className="text-xs text-emerald-300">
            Email ready — using platform SMTP (Gmail)
          </p>
        </div>
      )}
      {platformEmailReady === false && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/20 mb-3">
          <AlertTriangle size={14} className="text-amber-400 flex-shrink-0" />
          <p className="text-xs text-amber-300">
            No email integration connected. Go to Settings → Integrations to connect SMTP.
          </p>
        </div>
      )}
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">To Email</label>
        <input
          type="text"
          value={(nodeConfig.to as string) || ''}
          onChange={e => updateConfig('to', e.target.value)}
          className="w-full input-base font-mono"
          placeholder="{{caller_email}} or team@company.com"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Subject</label>
        <input
          type="text"
          value={(nodeConfig.subject as string) || ''}
          onChange={e => updateConfig('subject', e.target.value)}
          className="w-full input-base"
          placeholder="Follow-up: {{caller_name}} Call"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Body</label>
        <textarea
          value={(nodeConfig.body as string) || ''}
          onChange={e => updateConfig('body', e.target.value)}
          rows={4}
          className="w-full input-base resize-none"
          placeholder="Dear {{caller_name}},\n\nThank you for your call..."
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">CC (optional)</label>
        <input
          type="text"
          value={((nodeConfig.cc as string[]) || []).join(', ')}
          onChange={e => updateConfig('cc', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
          className="w-full input-base"
          placeholder="manager@company.com, team@company.com"
        />
      </div>
    </>
  );
}
