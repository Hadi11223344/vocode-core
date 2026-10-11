'use client';

import { NodeConfigProps } from './types';

export default function CodeConfig({ nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Language</label>
        <select
          value={(nodeConfig.language as string) || 'python'}
          onChange={e => updateConfig('language', e.target.value)}
          className="w-full input-base"
        >
          <option value="python">Python</option>
          <option value="javascript">JavaScript</option>
        </select>
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Code</label>
        <textarea
          value={(nodeConfig.code as string) || ''}
          onChange={e => updateConfig('code', e.target.value)}
          rows={8}
          className="w-full input-base resize-none font-mono text-xs"
          placeholder="# Available variables: context (dict), result (dict)&#10;&#10;def main(ctx):&#10;    return ctx.get('caller_name', 'Unknown')"
        />
        <p className="text-[10px] text-[var(--text-muted)] mt-1">
          Runs in a sandboxed environment. Returns are injected into context.
        </p>
      </div>
    </>
  );
}
