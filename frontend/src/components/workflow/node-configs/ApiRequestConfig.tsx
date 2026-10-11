'use client';

import { NodeConfigProps, HTTP_METHODS } from './types';
import { ParameterTemplateButtons } from './shared';

export default function ApiRequestConfig({ nodeConfig, updateConfig, parameterTemplates }: NodeConfigProps) {
  return (
    <>
      <div className="flex gap-2">
        <div className="w-24">
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Method</label>
          <select
            value={(nodeConfig.method as string) || 'GET'}
            onChange={e => updateConfig('method', e.target.value)}
            className="w-full input-base font-mono"
          >
            {HTTP_METHODS.map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
        <div className="flex-1">
          <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">URL</label>
          <input
            type="text"
            value={(nodeConfig.url as string) || ''}
            onChange={e => updateConfig('url', e.target.value)}
            className="w-full input-base font-mono"
            placeholder="https://api.example.com/..."
          />
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Headers (JSON)</label>
        <textarea
          value={(nodeConfig.headers as string) || ''}
          onChange={e => updateConfig('headers', e.target.value)}
          rows={2}
          className="w-full input-base resize-none font-mono"
          placeholder={'{"Authorization": "Bearer {{api_key}}"}'}
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Request Body (JSON)</label>
        <textarea
          value={(nodeConfig.body as string) || ''}
          onChange={e => updateConfig('body', e.target.value)}
          rows={4}
          className="w-full input-base resize-none font-mono"
          placeholder={'{\n  "name": "{{caller_name}}",\n  "phone": "{{caller_phone}}"\n}'}
        />
        <ParameterTemplateButtons
          templates={parameterTemplates}
          onApply={(value) => updateConfig('body', value)}
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Response Mappings</label>
        <textarea
          value={(nodeConfig.response_mappings as string) || ''}
          onChange={e => updateConfig('response_mappings', e.target.value)}
          rows={3}
          className="w-full input-base resize-none font-mono"
          placeholder={'{\n  "order_id": "$.data.id",\n  "status": "$.data.status"\n}'}
        />
        <p className="text-[10px] text-[var(--text-muted)] mt-1">JSONPath mappings to extract data from response</p>
      </div>
    </>
  );
}
