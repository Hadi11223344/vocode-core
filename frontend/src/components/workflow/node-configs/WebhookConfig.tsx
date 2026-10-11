'use client';

import { NodeConfigProps } from './types';

export default function WebhookConfig({ nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">URL</label>
        <input
          type="text"
          value={(nodeConfig.url as string) || ''}
          onChange={e => updateConfig('url', e.target.value)}
          className="w-full input-base font-mono"
          placeholder="https://example.com/webhook"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Payload Template (JSON)</label>
        <textarea
          value={(nodeConfig.payload as string) || ''}
          onChange={e => updateConfig('payload', e.target.value)}
          rows={4}
          className="w-full input-base resize-none font-mono"
          placeholder={'{\n  "caller": "{{caller_name}}",\n  "phone": "{{caller_phone}}"\n}'}
        />
      </div>
    </>
  );
}
