'use client';

import { useEffect, useState } from 'react';
import { useToast } from '@/components/ui/toast';
import { EmptyState } from '@/components/ui/empty-state';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { twilio, agents as agentsApi, apiKeys } from '@/lib/api';
import { usePageTitle } from '@/hooks/usePageTitle';
import { TwilioNumber, TwilioStatus, Agent } from '@/lib/types';
import { formatPhone } from '@/lib/utils';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';
import {
  Phone,
  Plus,
  Search,
  Trash2,
  CheckCircle,
  XCircle,
  Loader2,
  PhoneOutgoing,
  X,
  Settings,
} from 'lucide-react';

export default function PhoneNumbersPage() {
  usePageTitle('Phone Numbers');
  const [status, setStatus] = useState<TwilioStatus | null>(null);
  const [numbers, setNumbers] = useState<TwilioNumber[]>([]);
  const [loading, setLoading] = useState(true);
  const [showSearch, setShowSearch] = useState(false);
  const [showOutbound, setShowOutbound] = useState(false);
  const [releaseTarget, setReleaseTarget] = useState<string | null>(null);
  const [showWebhook, setShowWebhook] = useState<TwilioNumber | null>(null);
  const [webhookUrl, setWebhookUrl] = useState('');
  const [statusCallbackUrl, setStatusCallbackUrl] = useState('');
  const [savingWebhook, setSavingWebhook] = useState(false);
  const [searchResults, setSearchResults] = useState<{ phone_number: string; friendly_name: string; locality: string; region: string }[]>([]);
  const [searching, setSearching] = useState(false);
  const [areaCode, setAreaCode] = useState('');
  const [purchasing, setPurchasing] = useState('');
  const [outboundTo, setOutboundTo] = useState('');
  const [outboundAgentId, setOutboundAgentId] = useState('');
  const [calling, setCalling] = useState(false);
  const [agentList, setAgentList] = useState<Agent[]>([]);
  const [hasUserTwilioCredentials, setHasUserTwilioCredentials] = useState(true);
  const { success, addToast, apiError } = useToast();

  const isTwilioCredentialError = (err: unknown) =>
    err instanceof Error && /twilio credentials are required|credentials are required/i.test(err.message);

  const showTwilioCredentialRequired = () => {
    addToast({
      type: 'error',
      title: 'Twilio Credentials Required',
      message:
        'Add your Twilio Account SID and Auth Token in API Keys to buy numbers, update webhooks, release numbers, or place outbound calls.',
      action: {
        label: 'Open API Keys',
        onClick: () => {
          window.location.href = '/dashboard/keys';
        },
      },
    });
  };

  const handleTwilioMutatingError = (err: unknown, fallback: string) => {
    if (isTwilioCredentialError(err)) {
      showTwilioCredentialRequired();
      return;
    }
    apiError(err, fallback);
  };

  const load = async () => {
    try {
      const [s, n, twilioKeyValidation] = await Promise.all([
        twilio.status(),
        twilio.numbers(),
        apiKeys.validate('twilio').catch(() => null),
      ]);
      setStatus(s);
      setNumbers(n.numbers);
      if (twilioKeyValidation) {
        setHasUserTwilioCredentials(twilioKeyValidation.has_key && twilioKeyValidation.is_active);
      }
    } catch (err) {
      apiError(err, 'Failed to load phone numbers');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const searchNumbers = async () => {
    setSearching(true);
    try {
      const data = await twilio.searchNumbers({
        country: 'US',
        area_code: areaCode || undefined,
        limit: 10,
      });
      setSearchResults(data.available_numbers);
    } catch (err) {
      apiError(err, 'Failed to search numbers');
    } finally {
      setSearching(false);
    }
  };

  const purchaseNumber = async (phoneNumber: string) => {
    setPurchasing(phoneNumber);
    try {
      await twilio.purchaseNumber(phoneNumber);
      setShowSearch(false);
      setSearchResults([]);
      await load();
      success('Number Purchased', 'Your new phone number is ready to use');
    } catch (err) {
      handleTwilioMutatingError(err, 'Failed to purchase number');
    } finally {
      setPurchasing('');
    }
  };

  const releaseNumber = (sid: string) => {
    if (!hasUserTwilioCredentials) {
      showTwilioCredentialRequired();
      return;
    }
    setReleaseTarget(sid);
  };

  const confirmReleaseNumber = async () => {
    if (!releaseTarget) return;
    const sid = releaseTarget;
    setReleaseTarget(null);
    try {
      await twilio.releaseNumber(sid);
      await load();
      success('Number Released', 'Phone number has been released');
    } catch (err) {
      handleTwilioMutatingError(err, 'Failed to release number');
    }
  };

  const openWebhookConfig = (num: TwilioNumber) => {
    setShowWebhook(num);
    setWebhookUrl(num.voice_url || '');
    setStatusCallbackUrl(num.status_callback || '');
  };

  const saveWebhook = async () => {
    if (!showWebhook) return;
    if (!hasUserTwilioCredentials) {
      showTwilioCredentialRequired();
      return;
    }
    setSavingWebhook(true);
    try {
      await twilio.updateWebhook({
        phone_number_sid: showWebhook.sid,
        voice_url: webhookUrl || undefined,
        status_callback: statusCallbackUrl || undefined,
      });
      setShowWebhook(null);
      await load();
      success('Webhook Updated', 'Webhook configuration saved');
    } catch (err: unknown) {
      handleTwilioMutatingError(err, 'Failed to update webhook');
    } finally {
      setSavingWebhook(false);
    }
  };

  const makeOutboundCall = async () => {
    if (!outboundTo) return;
    setCalling(true);
    try {
      const data = await twilio.makeCall({
        to_phone: outboundTo,
        agent_id: outboundAgentId ? parseInt(outboundAgentId) : undefined,
      });
      success('Call Initiated', data.message);
      setShowOutbound(false);
      setOutboundTo('');
    } catch (err: unknown) {
      handleTwilioMutatingError(err, 'Failed to make call');
    } finally {
      setCalling(false);
    }
  };

  return (
    <GsapPageWrapper>
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Phone Numbers</h1>
          <p className="page-subtitle">Manage your Twilio phone numbers</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={async () => {
              if (!hasUserTwilioCredentials) {
                showTwilioCredentialRequired();
                return;
              }
              setShowOutbound(true);
              try {
                const data = await agentsApi.list();
                setAgentList(data.agents);
              } catch (err) {
                apiError(err, 'Failed to load agents');
              }
            }}
            disabled={!hasUserTwilioCredentials}
            className="flex items-center gap-2 btn-primary bg-green-600 hover:bg-green-500 active:bg-green-700 disabled:opacity-50"
          >
            <PhoneOutgoing size={16} />
            Outbound Call
          </button>
          <button
            onClick={() => setShowSearch(true)}
            disabled={!hasUserTwilioCredentials}
            className="flex items-center gap-2 btn-primary disabled:opacity-50"
          >
            <Plus size={16} />
            Buy Number
          </button>
        </div>
      </div>

      {/* Twilio Status */}
      <div className="dash-card p-5">
        <div className="flex items-center gap-3">
          {loading ? (
            <Loader2 size={20} className="animate-spin text-[var(--text-muted)]" />
          ) : status?.connected ? (
            <CheckCircle size={20} className="text-green-400" />
          ) : (
            <XCircle size={20} className="text-red-400" />
          )}
          <div>
            <p className="font-medium text-sm">
              Twilio {status?.connected ? 'Connected' : 'Not Connected'}
            </p>
            {status?.connected && (
              <p className="text-xs text-[var(--text-muted)] mt-0.5">
                Account: {status.account_name} • SID: {status.account_sid}
              </p>
            )}
          </div>
        </div>
      </div>

      {!hasUserTwilioCredentials && (
        <div className="dash-card p-4 border border-amber-500/30 bg-amber-500/10">
          <p className="text-sm text-amber-300 font-medium">User Twilio credentials missing</p>
          <p className="text-xs text-amber-200/80 mt-1">
            Read-only Twilio data may still work from platform defaults, but mutating actions are blocked.
            Add your own Twilio Account SID and Auth Token in API Keys.
          </p>
          <button
            onClick={() => {
              window.location.href = '/dashboard/keys';
            }}
            className="mt-3 px-3 py-1.5 rounded-lg text-xs font-medium bg-amber-400/20 text-amber-200 hover:bg-amber-400/30 transition-colors"
          >
            Open API Keys
          </button>
        </div>
      )}

      {/* Numbers List */}
      <div className="dash-table overflow-x-auto">
        {loading ? (
          <div className="p-8 text-center text-[var(--text-muted)]">Loading...</div>
        ) : numbers.length === 0 ? (
          <EmptyState
            icon={Phone}
            title="No phone numbers"
            description="Buy a Twilio number to start receiving calls. Add Twilio credentials in API Keys to enable number management."
          />
        ) : (
          <div className="divide-y divide-[var(--border-color)]">
            {numbers.map(num => (
              <div key={num.sid} className="flex items-center gap-4 p-4 hover:bg-[var(--bg-tertiary)] transition-colors">
                <div className="w-10 h-10 rounded-lg bg-brand-500/15 flex items-center justify-center text-brand-400 shrink-0">
                  <Phone size={18} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium font-mono">{formatPhone(num.phone_number)}</p>
                  <p className="text-xs text-[var(--text-muted)] mt-0.5">
                    {num.friendly_name} • SID: {num.sid.slice(0, 12)}...
                  </p>
                </div>
                <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
                  {num.voice_url ? (
                    <span className="px-2 py-0.5 bg-green-500/20 text-green-400 rounded-full">webhooks configured</span>
                  ) : (
                    <span className="px-2 py-0.5 bg-amber-500/20 text-amber-400 rounded-full">no webhook</span>
                  )}
                </div>
                <button
                  onClick={() => openWebhookConfig(num)}
                  disabled={!hasUserTwilioCredentials}
                  className="p-2 text-[var(--text-muted)] hover:text-brand-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors disabled:opacity-50"
                  title="Configure webhooks"
                >
                  <Settings size={16} />
                </button>
                <button
                  onClick={() => releaseNumber(num.sid)}
                  disabled={!hasUserTwilioCredentials}
                  className="p-2 text-[var(--text-muted)] hover:text-red-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors disabled:opacity-50"
                  title="Release number"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Search Numbers Modal */}
      {showSearch && (
        <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm animate-fade-in z-50 flex items-center justify-center">
          <div className="dash-modal w-full max-w-lg mx-4 animate-scale-in">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--glass-border)]">
              <h2 className="text-lg font-semibold tracking-tight">Search Phone Numbers</h2>
              <button onClick={() => { setShowSearch(false); setSearchResults([]); }} className="btn-ghost p-1.5">
                <X size={20} />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={areaCode}
                  onChange={e => setAreaCode(e.target.value)}
                  placeholder="Area code (e.g. 415)"
                  className="flex-1 input-base"
                />
                <button
                  onClick={searchNumbers}
                  disabled={searching}
                  className="btn-primary disabled:opacity-50"
                >
                  {searching ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
                </button>
              </div>
              {searchResults.length > 0 && (
                <div className="max-h-64 overflow-y-auto space-y-2">
                  {searchResults.map(num => (
                    <div key={num.phone_number} className="flex items-center justify-between p-3 bg-[var(--bg-primary)] rounded-lg">
                      <div>
                        <p className="font-mono text-sm">{formatPhone(num.phone_number)}</p>
                        <p className="text-xs text-[var(--text-muted)]">{num.locality}, {num.region}</p>
                      </div>
                      <button
                        onClick={() => purchaseNumber(num.phone_number)}
                        disabled={purchasing === num.phone_number || !hasUserTwilioCredentials}
                        className="btn-primary bg-green-600 hover:bg-green-500 active:bg-green-700 px-3 py-1.5 text-xs disabled:opacity-50"
                      >
                        {purchasing === num.phone_number ? 'Buying...' : 'Buy ~$1/mo'}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Outbound Call Modal */}
      {showOutbound && (
        <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm animate-fade-in z-50 flex items-center justify-center">
          <div className="dash-modal w-full max-w-md mx-4 animate-scale-in">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--glass-border)]">
              <h2 className="text-lg font-semibold tracking-tight">Make Outbound Call</h2>
              <button onClick={() => setShowOutbound(false)} className="btn-ghost p-1.5">
                <X size={20} />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-[13px] font-medium text-[var(--text-secondary)] mb-1.5">Phone Number</label>
                <input
                  type="text"
                  value={outboundTo}
                  onChange={e => setOutboundTo(e.target.value)}
                  placeholder="+1XXXXXXXXXX"
                  className="w-full input-base"
                />
              </div>
              <div>
                <label className="block text-[13px] font-medium text-[var(--text-secondary)] mb-1.5">Agent</label>
                <select
                  value={outboundAgentId}
                  onChange={e => setOutboundAgentId(e.target.value)}
                  className="w-full input-base"
                >
                  <option value="">Default agent</option>
                  {agentList.map(a => (
                    <option key={a.id} value={String(a.id)}>
                      {a.name} {a.is_active ? '(active)' : ''}
                    </option>
                  ))}
                </select>
              </div>
              <button
                onClick={makeOutboundCall}
                disabled={calling || !outboundTo}
                className="w-full flex items-center justify-center gap-2 btn-primary bg-green-600 hover:bg-green-500 active:bg-green-700 disabled:opacity-50"
              >
                <PhoneOutgoing size={16} />
                {calling ? 'Calling...' : 'Start Call'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Webhook Configuration Modal */}
      {showWebhook && (
        <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm animate-fade-in z-50 flex items-center justify-center">
          <div className="dash-modal w-full max-w-lg mx-4 animate-scale-in">
            <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--glass-border)]">
              <div>
                <h2 className="text-lg font-semibold tracking-tight">Configure Webhooks</h2>
                <p className="text-xs text-[var(--text-muted)] mt-0.5 font-mono">{formatPhone(showWebhook.phone_number)}</p>
              </div>
              <button onClick={() => setShowWebhook(null)} className="btn-ghost p-1.5">
                <X size={20} />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-[13px] font-medium text-[var(--text-secondary)] mb-1.5">Voice URL</label>
                <input
                  type="text"
                  value={webhookUrl}
                  onChange={e => setWebhookUrl(e.target.value)}
                  placeholder="https://your-server.com/inbound_call"
                  className="w-full input-base font-mono"
                />
                <p className="text-[10px] text-[var(--text-muted)] mt-1">
                  URL that Twilio will POST to when this number receives a call.
                  Use your ngrok URL + /inbound_call for development.
                </p>
              </div>
              <div>
                <label className="block text-[13px] font-medium text-[var(--text-secondary)] mb-1.5">Status Callback URL</label>
                <input
                  type="text"
                  value={statusCallbackUrl}
                  onChange={e => setStatusCallbackUrl(e.target.value)}
                  placeholder="https://your-server.com/call_status"
                  className="w-full input-base font-mono"
                />
                <p className="text-[10px] text-[var(--text-muted)] mt-1">
                  URL for call status updates (completed, busy, failed, etc.)
                </p>
              </div>
              <div className="flex gap-2 pt-2">
                <button
                  onClick={() => setShowWebhook(null)}
                  className="flex-1 px-4 py-2.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] border border-[var(--glass-border)] rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={saveWebhook}
                  disabled={savingWebhook || !hasUserTwilioCredentials}
                  className="flex-1 flex items-center justify-center gap-2 btn-primary disabled:opacity-50"
                >
                  {savingWebhook ? <Loader2 size={14} className="animate-spin" /> : <Settings size={14} />}
                  Save Webhooks
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={releaseTarget !== null}
        title="Release Phone Number"
        message="Release this phone number? This cannot be undone."
        confirmLabel="Release"
        variant="danger"
        onConfirm={confirmReleaseNumber}
        onCancel={() => setReleaseTarget(null)}
      />
    </div>
    </GsapPageWrapper>
  );
}
