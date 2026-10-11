'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { Settings2, Plus, Trash2, Check } from 'lucide-react';

interface MockContextEditorProps {
  context: Record<string, unknown>;
  onApply: (context: Record<string, unknown>) => void;
}

const DEFAULT_CONTEXT: Record<string, string> = {
  // Leave identity empty by default. Seeding "Test Caller" / fake ANI caused
  // Contact Details to confirm mock values instead of collecting real ones.
  caller_name: '',
  caller_phone: '',
  transcript: '',
};

export function MockContextEditor({ context, onApply }: MockContextEditorProps) {
  const [fields, setFields] = useState<Record<string, string>>({
    ...DEFAULT_CONTEXT,
    ...Object.fromEntries(
      Object.entries(context).map(([k, v]) => [k, typeof v === 'string' ? v : JSON.stringify(v)])
    ),
  });
  const [newKey, setNewKey] = useState('');
  const [newValue, setNewValue] = useState('');
  const [applied, setApplied] = useState(false);
  const appliedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setFields({
      ...DEFAULT_CONTEXT,
      ...Object.fromEntries(
        Object.entries(context).map(([k, v]) => [k, typeof v === 'string' ? v : JSON.stringify(v)])
      ),
    });
    setApplied(false);
  }, [context]);

  const updateField = useCallback((key: string, value: string) => {
    setFields((prev) => ({ ...prev, [key]: value }));
    setApplied(false);
  }, []);

  const addField = useCallback(() => {
    if (!newKey.trim()) return;
    setFields((prev) => ({ ...prev, [newKey.trim()]: newValue }));
    setNewKey('');
    setNewValue('');
    setApplied(false);
  }, [newKey, newValue]);

  const removeField = useCallback((key: string) => {
    setFields((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setApplied(false);
  }, []);

  const handleApply = useCallback(() => {
    onApply(fields);
    setApplied(true);
    if (appliedTimerRef.current) clearTimeout(appliedTimerRef.current);
    appliedTimerRef.current = setTimeout(() => setApplied(false), 2000);
  }, [fields, onApply]);

  useEffect(() => {
    return () => {
      if (appliedTimerRef.current) clearTimeout(appliedTimerRef.current);
    };
  }, []);

  return (
    <div className="flex flex-col h-full dash-card overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--glass-border)]">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Settings2 size={14} className="text-brand-400" />
          Mock Context
        </h3>
        <button
          onClick={handleApply}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs transition-colors ${
            applied
              ? 'bg-green-500/20 text-green-400'
              : 'bg-brand-500/20 text-brand-400 hover:bg-brand-500/30'
          }`}
        >
          {applied ? <Check size={12} /> : null}
          {applied ? 'Applied' : 'Apply'}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {Object.entries(fields).map(([key, value]) => (
          <div key={key} className="flex items-start gap-2">
            <div className="flex-1 min-w-0">
              <label className="text-[10px] text-[var(--text-muted)] block mb-0.5">{key}</label>
              <input
                type="text"
                value={value}
                onChange={(e) => updateField(key, e.target.value)}
                className="input-base w-full text-xs py-1.5 px-2"
                placeholder={`Value for ${key}`}
              />
            </div>
            {!DEFAULT_CONTEXT[key] && (
              <button
                onClick={() => removeField(key)}
                className="mt-5 p-1 text-[var(--text-muted)] hover:text-red-400 transition-colors"
                title="Remove field"
              >
                <Trash2 size={12} />
              </button>
            )}
          </div>
        ))}

        <div className="pt-2 border-t border-[var(--glass-border)]">
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <label className="text-[10px] text-[var(--text-muted)] block mb-0.5">New variable</label>
              <input
                type="text"
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
                className="input-base w-full text-xs py-1.5 px-2"
                placeholder="variable_name"
              />
            </div>
            <div className="flex-1">
              <label className="text-[10px] text-[var(--text-muted)] block mb-0.5">Value</label>
              <input
                type="text"
                value={newValue}
                onChange={(e) => setNewValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addField()}
                className="input-base w-full text-xs py-1.5 px-2"
                placeholder="value"
              />
            </div>
            <button
              onClick={addField}
              disabled={!newKey.trim()}
              className="btn-ghost p-1.5 rounded-lg disabled:opacity-30"
              title="Add variable"
            >
              <Plus size={14} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
