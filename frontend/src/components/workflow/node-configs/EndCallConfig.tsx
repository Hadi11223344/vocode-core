'use client';

import { NodeConfigProps } from './types';

export default function EndCallConfig({ nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <div>
      <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Closing Message</label>
      <textarea
        value={(nodeConfig.message as string) || ''}
        onChange={e => updateConfig('message', e.target.value)}
        rows={3}
        className="w-full input-base resize-none"
        placeholder="Thank you for calling. Have a great day!"
      />
      <p className="text-[10px] text-[var(--text-muted)] mt-1">Message spoken before hanging up</p>
    </div>
  );
}
