'use client';

import React from 'react';
import { NodeConfigProps } from './types';
import { X, Plus } from 'lucide-react';

const KNOWN_SLOTS = [
  'patient_name',
  'caller_name',
  'caller_phone',
  'caller_email',
  'is_new_patient',
  'is_emergency',
  'service_requested',
  'preferred_date',
  'preferred_time',
  'preferred_dentist',
  'insurance_provider',
  'confirm_booking',
  'emergency_type',
  'visit_type',
];

const EXHAUSTION_POLICIES = [
  { label: 'End Call', value: 'end_call' },
  { label: 'Transfer', value: 'transfer' },
  { label: 'Continue', value: 'continue' },
  { label: 'Use Default', value: 'use_default' },
];

export default function SlotValidatorConfig({
  nodeConfig,
  updateConfig,
}: NodeConfigProps) {
  const requiredSlots = (nodeConfig.required_slots as string[]) || [];
  const onExhausted = (nodeConfig.on_exhausted as string) || 'end_call';

  const addSlot = (slot: string) => {
    if (!slot || requiredSlots.includes(slot)) return;
    updateConfig('required_slots', [...requiredSlots, slot]);
  };

  const removeSlot = (slot: string) => {
    updateConfig(
      'required_slots',
      requiredSlots.filter((s) => s !== slot)
    );
  };

  const [customSlot, setCustomSlot] = React.useState('');

  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1 block text-xs font-medium text-zinc-400">
          Required Slots
        </label>
        <p className="mb-2 text-xs text-zinc-500">
          Slots that must be present and valid before the flow continues.
          The validator routes to a collector for each missing slot.
        </p>
        <div className="flex flex-wrap gap-1.5">
          {requiredSlots.map((slot) => (
            <span
              key={slot}
              className="inline-flex items-center gap-1 rounded-md bg-orange-500/10 px-2 py-1 text-xs text-orange-400"
            >
              {slot}
              <button
                onClick={() => removeSlot(slot)}
                className="hover:text-orange-300"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          {requiredSlots.length === 0 && (
            <span className="text-xs text-zinc-600">No slots added yet</span>
          )}
        </div>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-zinc-400">
          Add Slot
        </label>
        <div className="flex flex-wrap gap-1.5">
          {KNOWN_SLOTS.filter((s) => !requiredSlots.includes(s)).map((slot) => (
            <button
              key={slot}
              onClick={() => addSlot(slot)}
              className="inline-flex items-center gap-1 rounded-md border border-zinc-700 px-2 py-1 text-xs text-zinc-400 hover:border-orange-500/50 hover:text-orange-400"
            >
              <Plus className="h-3 w-3" />
              {slot}
            </button>
          ))}
        </div>
        <div className="mt-2 flex gap-2">
          <input
            type="text"
            value={customSlot}
            onChange={(e) => setCustomSlot(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                addSlot(customSlot);
                setCustomSlot('');
              }
            }}
            placeholder="Custom slot name..."
            className="flex-1 rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-orange-500/50 focus:outline-none"
          />
          <button
            onClick={() => {
              addSlot(customSlot);
              setCustomSlot('');
            }}
            className="rounded-md border border-zinc-700 px-2 py-1 text-xs text-zinc-400 hover:border-orange-500/50 hover:text-orange-400"
          >
            Add
          </button>
        </div>
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-zinc-400">
          On Retry Exhaustion
        </label>
        <p className="mb-2 text-xs text-zinc-500">
          What happens when a slot cannot be collected after maximum attempts.
        </p>
        <select
          value={onExhausted}
          onChange={(e) => updateConfig('on_exhausted', e.target.value)}
          className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-sm text-zinc-200 focus:border-orange-500/50 focus:outline-none"
        >
          {EXHAUSTION_POLICIES.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
