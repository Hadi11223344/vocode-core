'use client';

import { NodeConfigProps } from './types';

export default function ConditionConfig({ node, nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Condition Expression</label>
        <input
          type="text"
          value={(nodeConfig.expression as string) || (node.data.condition as string) || ''}
          onChange={e => updateConfig('expression', e.target.value)}
          className="w-full input-base font-mono"
          placeholder='result.available == true'
        />
        <p className="text-[10px] text-[var(--text-muted)] mt-1">
          Supported: {'>'} {'<'} == != contains not_empty. Routes to Yes/No outputs.
        </p>
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">True Branch Label</label>
        <input
          type="text"
          value={(nodeConfig.true_label as string) || ''}
          onChange={e => updateConfig('true_label', e.target.value)}
          className="w-full input-base"
          placeholder="Yes"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">False Branch Label</label>
        <input
          type="text"
          value={(nodeConfig.false_label as string) || ''}
          onChange={e => updateConfig('false_label', e.target.value)}
          className="w-full input-base"
          placeholder="No"
        />
      </div>
    </>
  );
}
