'use client';

import { NodeConfigProps } from './types';

export default function LlmProcessConfig({ nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Processing Prompt</label>
        <textarea
          value={(nodeConfig.prompt as string) || ''}
          onChange={e => updateConfig('prompt', e.target.value)}
          rows={4}
          className="w-full input-base resize-none"
          placeholder="Summarize the following transcript: {{transcript}}"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Max Tokens</label>
        <input
          type="number"
          value={(nodeConfig.max_tokens as number) || 500}
          onChange={e => updateConfig('max_tokens', parseInt(e.target.value) || 500)}
          min={50}
          max={4096}
          className="w-full input-base"
        />
      </div>
    </>
  );
}
