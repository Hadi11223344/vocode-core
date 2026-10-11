'use client';

import { NodeConfigProps } from './types';

export default function TriggerConfig({ node, updateData }: NodeConfigProps) {
  return (
    <div>
      <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Trigger Phrases</label>
      <textarea
        value={(node.data.triggerPhrases as string) || ''}
        onChange={e => updateData('triggerPhrases', e.target.value)}
        rows={3}
        className="w-full input-base resize-none font-mono"
        placeholder="One phrase per line..."
      />
      <p className="text-[10px] text-[var(--text-muted)] mt-1">One phrase per line. Triggers when caller says any of these.</p>
    </div>
  );
}
