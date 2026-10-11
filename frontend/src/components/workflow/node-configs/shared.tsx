'use client';

import { useState, useEffect } from 'react';
import { Integration } from '@/lib/types';
import { integrations as integrationsApi, apiKeys } from '@/lib/api';
import { useToast } from '@/components/ui/toast';
import { TEMPLATE_VARS } from './types';

/* ── Reusable Field Components ─────────────────────────────────────── */

export function TextField({
  label,
  value,
  onChange,
  placeholder,
  mono,
  type = 'text',
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  mono?: boolean;
  type?: string;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        className={`w-full input-base ${mono ? 'font-mono' : ''}`}
        placeholder={placeholder}
      />
    </div>
  );
}

export function TextArea({
  label,
  value,
  onChange,
  rows = 3,
  placeholder,
  mono,
  resizeNone = true,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
  mono?: boolean;
  resizeNone?: boolean;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">{label}</label>
      <textarea
        value={value}
        onChange={e => onChange(e.target.value)}
        rows={rows}
        className={`w-full input-base ${resizeNone ? 'resize-none' : ''} ${mono ? 'font-mono' : ''}`}
        placeholder={placeholder}
      />
    </div>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  options,
  mono,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Array<{ label: string; value: string }>;
  mono?: boolean;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">{label}</label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className={`w-full input-base ${mono ? 'font-mono' : ''}`}
      >
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}

export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  placeholder,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">{label}</label>
      <input
        type="number"
        value={value}
        onChange={e => onChange(parseInt(e.target.value) || 0)}
        min={min}
        max={max}
        className="w-full input-base"
        placeholder={placeholder}
      />
    </div>
  );
}

export function TemplateVarsReference() {
  return (
    <div className="pt-2 border-t border-[var(--border-color)]">
      <p className="text-xs font-medium text-[var(--text-muted)] mb-2">Template Variables</p>
      <div className="space-y-1">
        {TEMPLATE_VARS.map(v => (
          <div key={v.var} className="flex items-center justify-between text-[10px]">
            <code className="text-brand-400 font-mono">{v.var}</code>
            <span className="text-[var(--text-muted)]">{v.desc}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Parameter Template Buttons ────────────────────────────────────── */

export function ParameterTemplateButtons({
  templates,
  onApply,
}: {
  templates: Array<{ label: string; value: string }>;
  onApply: (value: string) => void;
}) {
  if (templates.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2">
      {templates.map((template) => (
        <button
          key={template.label}
          type="button"
          onClick={() => onApply(template.value)}
          className="text-[10px] px-2.5 py-1 rounded-full border border-[var(--border-color)] bg-[var(--bg-tertiary)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:border-brand-500 transition-colors"
        >
          {template.label}
        </button>
      ))}
    </div>
  );
}

/* ── Drive File Browser Sub-component ──────────────────────────────── */

export function DriveFileBrowser({
  integrations,
  onSelect,
}: {
  integrations: Integration[];
  onSelect: (fileId: string, fileName: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [files, setFiles] = useState<Array<{ id: string; name: string; mimeType: string; modifiedTime: string }>>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { apiError } = useToast();

  const driveIntegration = integrations.find(
    (i) => i.service_type === 'google_drive_mcp' && i.is_active
  );

  const fetchFiles = async (search?: string) => {
    if (!driveIntegration) return;
    setLoading(true);
    setError('');
    try {
      const result = await integrationsApi.driveFiles(driveIntegration.id, search, 20);
      setFiles(result.files || []);
    } catch (err) {
      setError('Failed to load files');
      apiError(err, 'Failed to load Drive files');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open && driveIntegration) {
      fetchFiles();
    }
  }, [open, driveIntegration?.id]);

  if (!driveIntegration) {
    return (
      <div className="p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
        <p className="text-xs text-amber-400">
          No Google Drive integration connected. Add one in Settings → Integrations.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-[var(--bg-tertiary)] hover:bg-[var(--bg-tertiary)]/80 border border-[var(--border-color)] text-xs transition-colors"
      >
        <span className="flex items-center gap-2">
          <span>📁</span>
          <span className="font-medium">Browse Google Drive</span>
        </span>
        <span className="text-[var(--text-muted)]">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="p-3 rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border-color)] space-y-3">
          <div className="flex gap-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && fetchFiles(query)}
              placeholder="Search files..."
              className="flex-1 input-base text-xs"
            />
            <button
              onClick={() => fetchFiles(query)}
              disabled={loading}
              className="px-3 py-1.5 rounded-lg bg-brand-500/10 text-brand-400 text-xs font-medium hover:bg-brand-500/20 transition-colors disabled:opacity-50"
            >
              {loading ? '...' : 'Search'}
            </button>
          </div>

          {error && <p className="text-xs text-red-400">{error}</p>}

          <div className="max-h-48 overflow-y-auto space-y-1">
            {files.length === 0 && !loading && (
              <p className="text-xs text-[var(--text-muted)] py-2">No files found</p>
            )}
            {files.map((file) => (
              <button
                key={file.id}
                onClick={() => {
                  onSelect(file.id, file.name);
                  setOpen(false);
                }}
                className="w-full flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-[var(--bg-secondary)] text-left transition-colors"
              >
                <span className="text-xs">{file.mimeType?.includes('folder') ? '📂' : '📄'}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate">{file.name}</p>
                  <p className="text-[10px] text-[var(--text-muted)]">
                    {file.modifiedTime ? new Date(file.modifiedTime).toLocaleDateString() : ''}
                  </p>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
