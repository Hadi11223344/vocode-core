'use client';

import { NodeConfigProps } from './types';

export default function SendSmsConfig({ nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">To Number</label>
        <input
          type="text"
          value={(nodeConfig.to as string) || ''}
          onChange={e => updateConfig('to', e.target.value)}
          className="w-full input-base font-mono"
          placeholder="{{caller_phone}}"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Message Body</label>
        <textarea
          value={(nodeConfig.body as string) || ''}
          onChange={e => updateConfig('body', e.target.value)}
          rows={3}
          className="w-full input-base resize-none"
          placeholder="Hi {{caller_name}}, your appointment is confirmed for {{preferred_date}}."
        />
        <p className="text-[10px] text-[var(--text-muted)] mt-1">Max 1600 characters. Supports template variables.</p>
      </div>
    </>
  );
}
