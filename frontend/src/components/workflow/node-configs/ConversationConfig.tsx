'use client';

import { NodeConfigProps } from './types';

export default function ConversationConfig({ nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Conversation Prompt</label>
        <textarea
          value={(nodeConfig.prompt as string) || ''}
          onChange={e => updateConfig('prompt', e.target.value)}
          rows={4}
          className="w-full input-base resize-none"
          placeholder="Instructions for the AI during this conversation phase..."
        />
        <p className="text-[10px] text-[var(--text-muted)] mt-1">
          What the AI should say/ask during this step. Like Retell AI&apos;s Conversation Node.
        </p>
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Variables to Extract</label>
        <input
          type="text"
          value={((nodeConfig.variables_to_extract as string[]) || []).join(', ')}
          onChange={e => updateConfig('variables_to_extract', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
          className="w-full input-base font-mono"
          placeholder="caller_name, preferred_date, issue_type"
        />
        <p className="text-[10px] text-[var(--text-muted)] mt-1">
          Comma-separated variable names the AI should extract from the conversation.
        </p>
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Max Turns</label>
        <input
          type="number"
          value={(nodeConfig.max_turns as number) || 5}
          onChange={e => updateConfig('max_turns', parseInt(e.target.value) || 5)}
          min={1}
          max={20}
          className="w-full input-base"
        />
      </div>
    </>
  );
}
