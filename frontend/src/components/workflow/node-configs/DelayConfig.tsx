'use client';

import { NodeConfigProps } from './types';

export default function DelayConfig({ nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <div>
      <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Delay (seconds)</label>
      <input
        type="number"
        value={(nodeConfig.delay_seconds as number) || 1}
        onChange={e => updateConfig('delay_seconds', parseInt(e.target.value) || 1)}
        min={1}
        max={300}
        className="w-full input-base"
      />
      <p className="text-[10px] text-[var(--text-muted)] mt-1">Min 1 second, max 300 seconds (5 minutes)</p>
    </div>
  );
}
