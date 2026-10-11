'use client';

import { NodeConfigProps } from './types';

export default function NoteConfig({ nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <div>
      <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Note Content</label>
      <textarea
        value={(nodeConfig.content as string) || ''}
        onChange={e => updateConfig('content', e.target.value)}
        rows={6}
        className="w-full input-base resize-none"
        placeholder="Add instructions or context for the AI here. This is not visible to the caller."
      />
      <p className="text-[10px] text-[var(--text-muted)] mt-1">
        This note is appended to the system prompt for the AI only. Callers will not hear it.
      </p>
    </div>
  );
}
