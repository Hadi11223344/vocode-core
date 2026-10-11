'use client';

import { NodeConfigProps } from './types';

export default function TransferCallConfig({ nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Transfer Number</label>
        <input
          type="text"
          value={(nodeConfig.transfer_number as string) || (nodeConfig.transfer_to as string) || ''}
          onChange={e => updateConfig('transfer_number', e.target.value)}
          className="w-full input-base font-mono"
          placeholder="+1234567890"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Transfer Message</label>
        <textarea
          value={(nodeConfig.transfer_message as string) || ''}
          onChange={e => updateConfig('transfer_message', e.target.value)}
          rows={2}
          className="w-full input-base resize-none"
          placeholder="I'll connect you with a specialist now..."
        />
        <p className="text-[10px] text-[var(--text-muted)] mt-1">Said to caller before transferring</p>
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Whisper Message (to agent)</label>
        <textarea
          value={(nodeConfig.whisper_message as string) || ''}
          onChange={e => updateConfig('whisper_message', e.target.value)}
          rows={2}
          className="w-full input-base resize-none"
          placeholder="Caller has a billing question about {{issue_description}}"
        />
        <p className="text-[10px] text-[var(--text-muted)] mt-1">Whispered to the human agent upon connection</p>
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Transfer Type</label>
        <select
          value={(nodeConfig.transfer_type as string) || 'warm'}
          onChange={e => updateConfig('transfer_type', e.target.value)}
          className="w-full input-base"
        >
          <option value="warm">Warm Transfer (stay on line)</option>
          <option value="cold">Cold Transfer (disconnect AI)</option>
        </select>
      </div>
    </>
  );
}
