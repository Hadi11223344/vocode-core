'use client';

import { NodeConfigProps } from './types';

export default function SubagentConfig({ nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Subagent ID</label>
        <input
          type="text"
          value={(nodeConfig.subagent_id as string) || ''}
          onChange={e => updateConfig('subagent_id', e.target.value)}
          className="w-full input-base font-mono"
          placeholder="Agent ID or agent name"
        />
        <p className="text-[10px] text-[var(--text-muted)] mt-1">
          The agent to delegate this part of the conversation to.
        </p>
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Delegation Prompt</label>
        <textarea
          value={(nodeConfig.prompt as string) || ''}
          onChange={e => updateConfig('prompt', e.target.value)}
          rows={3}
          className="w-full input-base resize-none"
          placeholder="Handle the billing portion of this call."
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Timeout (seconds)</label>
        <input
          type="number"
          value={(nodeConfig.timeout as number) || 60}
          onChange={e => updateConfig('timeout', parseInt(e.target.value) || 60)}
          min={10}
          max={300}
          className="w-full input-base"
        />
      </div>
    </>
  );
}
