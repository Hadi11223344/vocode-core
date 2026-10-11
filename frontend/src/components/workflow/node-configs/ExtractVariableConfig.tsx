'use client';

import { NodeConfigProps } from './types';

export default function ExtractVariableConfig({ nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Variable Name</label>
        <input
          type="text"
          value={(nodeConfig.variable_name as string) || ''}
          onChange={e => updateConfig('variable_name', e.target.value)}
          className="w-full input-base font-mono"
          placeholder="caller_email"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Extract Prompt</label>
        <textarea
          value={(nodeConfig.prompt as string) || ''}
          onChange={e => updateConfig('prompt', e.target.value)}
          rows={3}
          className="w-full input-base resize-none"
          placeholder="Extract the caller's email address from the conversation."
        />
        <p className="text-[10px] text-[var(--text-muted)] mt-1">
          The AI will try to extract this value and store it in context.
        </p>
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Required</label>
        <select
          value={(nodeConfig.required as boolean) ? 'true' : 'false'}
          onChange={e => updateConfig('required', e.target.value === 'true')}
          className="w-full input-base"
        >
          <option value="true">Yes — must extract before continuing</option>
          <option value="false">No — optional extraction</option>
        </select>
      </div>
    </>
  );
}
