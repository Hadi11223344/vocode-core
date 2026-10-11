'use client';

import { NodeConfigProps } from './types';

export default function VoicemailDetectConfig({ nodeConfig, updateConfig }: NodeConfigProps) {
  return (
    <>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Detection Method</label>
        <select
          value={(nodeConfig.detection_method as string) || 'amd'}
          onChange={e => updateConfig('detection_method', e.target.value)}
          className="w-full input-base"
        >
          <option value="amd">Twilio AMD (Answering Machine Detection)</option>
          <option value="beep_detect">Beep Detection</option>
        </select>
      </div>
      <div>
        <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Voicemail Message</label>
        <textarea
          value={(nodeConfig.voicemail_message as string) || ''}
          onChange={e => updateConfig('voicemail_message', e.target.value)}
          rows={3}
          className="w-full input-base resize-none"
          placeholder="Hi, this is VOIA calling about {{reason}}. Please call us back at..."
        />
      </div>
    </>
  );
}
