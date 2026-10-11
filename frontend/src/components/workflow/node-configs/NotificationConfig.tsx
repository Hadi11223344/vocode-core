'use client';

import { NodeConfigProps } from './types';

export default function NotificationConfig({ nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Channel</label>
        <select
          value={(nodeConfig.channel as string) || 'log'}
          onChange={e => updateConfig('channel', e.target.value)}
          className="w-full input-base"
        >
          <option value="log">Log (console only)</option>
          <option value="slack">Slack</option>
          <option value="email">Email</option>
          <option value="sms">SMS</option>
          <option value="webhook">Webhook</option>
        </select>
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Message</label>
        <textarea
          value={(nodeConfig.message as string) || ''}
          onChange={e => updateConfig('message', e.target.value)}
          rows={3}
          className="w-full input-base resize-none"
          placeholder="New call from {{caller_phone}}: {{transcript}}"
        />
      </div>
    </>
  );
}
