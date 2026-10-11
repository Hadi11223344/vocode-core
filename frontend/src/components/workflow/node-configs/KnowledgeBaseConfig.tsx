'use client';

import { NodeConfigProps, INTEGRATION_ACTIONS } from './types';
import { ParameterTemplateButtons } from './shared';

export default function KnowledgeBaseConfig({ node, nodeConfig, updateConfig, updateData, parameterTemplates }: NodeConfigProps) {
  return (
    <>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Search Query</label>
        <input
          type="text"
          value={(nodeConfig.query as string) || ''}
          onChange={e => updateConfig('query', e.target.value)}
          className="w-full input-base"
          placeholder="{{issue_description}} or {{transcript}}"
        />
        <p className="text-[10px] text-[var(--text-muted)] mt-1">Query to search knowledge base with</p>
      </div>
      <ParameterTemplateButtons
        templates={parameterTemplates}
        onApply={(value) => updateConfig('query', value)}
      />
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Max Results</label>
        <input
          type="number"
          value={(nodeConfig.max_results as number) || 3}
          onChange={e => updateConfig('max_results', parseInt(e.target.value) || 3)}
          min={1}
          max={10}
          className="w-full input-base"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Action</label>
        <select
          value={(node.data.action as string) || 'retrieve'}
          onChange={e => updateData('action', e.target.value)}
          className="w-full input-base"
        >
          {(INTEGRATION_ACTIONS.knowledge_base || []).map(a => (
            <option key={a.value} value={a.value}>{a.label}</option>
          ))}
        </select>
      </div>
    </>
  );
}
