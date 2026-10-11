'use client';

import { useState, useCallback } from 'react';
import { X, BookOpen, Wand2, MessageSquare, Zap, Play, Loader2, CheckCircle, XCircle, HelpCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { integrations as integrationsApi } from '@/lib/api';
import type { IntegrationType, Integration } from '@/lib/types';

interface IntegrationHelpDrawerProps {
  integrationType: IntegrationType;
  integration?: Integration | null;
  isOpen: boolean;
  onClose: () => void;
}

type TabId = 'setup' | 'tools' | 'examples' | 'test';

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: 'setup', label: 'Setup', icon: BookOpen },
  { id: 'tools', label: 'Agent Tools', icon: Wand2 },
  { id: 'examples', label: 'Examples', icon: MessageSquare },
  { id: 'test', label: 'Test', icon: Zap },
];

export function IntegrationHelpDrawer({
  integrationType,
  integration,
  isOpen,
  onClose,
}: IntegrationHelpDrawerProps) {
  const [activeTab, setActiveTab] = useState<TabId>('setup');
  const [testLoading, setTestLoading] = useState(false);
  const [testResult, setTestResult] = useState<{ status: string; message: string } | null>(null);

  const handleTest = useCallback(async () => {
    if (!integration) return;
    setTestLoading(true);
    setTestResult(null);
    try {
      const res = await integrationsApi.test(integration.id);
      setTestResult(res);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Test failed';
      setTestResult({ status: 'error', message: msg });
    } finally {
      setTestLoading(false);
    }
  }, [integration]);

  if (!isOpen) return null;

  const guide = integrationType.setup_guide;
  const usage = integrationType.agent_usage;

  return (
    <div className="fixed inset-0 z-[60] flex justify-end">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Drawer panel */}
      <div className="relative w-full max-w-2xl h-full bg-[var(--bg-secondary)] border-l border-[var(--border-color)] shadow-2xl flex flex-col animate-in slide-in-from-right duration-300">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-color)]">
          <div>
            <h2 className="text-lg font-semibold text-white">{integrationType.name}</h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">{integrationType.description}</p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-white/5 text-[var(--text-muted)] hover:text-white transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 px-6 pt-3 border-b border-[var(--border-color)]">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-t-lg transition-colors border-b-2',
                  isActive
                    ? 'text-brand-400 border-brand-400 bg-brand-500/5'
                    : 'text-[var(--text-muted)] border-transparent hover:text-white hover:bg-white/5'
                )}
              >
                <Icon size={14} />
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          {/* ── Setup Tab ── */}
          {activeTab === 'setup' && (
            <div className="space-y-5">
              {guide?.docs_url && (
                <a
                  href={guide.docs_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 px-3 py-2 rounded-lg bg-brand-500/10 border border-brand-500/20 text-brand-400 text-xs hover:bg-brand-500/20 transition-colors"
                >
                  <BookOpen size={14} />
                  <span>Official Documentation</span>
                </a>
              )}

              {integrationType.api_key_help && (
                <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
                  <HelpCircle size={14} className="text-amber-400 mt-0.5 shrink-0" />
                  <p className="text-xs text-amber-200">{integrationType.api_key_help}</p>
                </div>
              )}

              {guide?.steps && guide.steps.length > 0 && (
                <div className="space-y-3">
                  <p className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Setup Steps</p>
                  {guide.steps.map((step, i) => (
                    <div key={i} className="flex gap-3">
                      <div className="flex-shrink-0 w-6 h-6 rounded-full bg-brand-500/20 text-brand-400 text-[10px] flex items-center justify-center font-bold">
                        {step.step ?? i + 1}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white">{step.title}</p>
                        <p className="text-xs text-[var(--text-muted)] mt-0.5">{step.description}</p>
                        {step.link && (
                          <a
                            href={step.link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-[10px] text-brand-400 hover:underline mt-1 inline-block"
                          >
                            Open link →
                          </a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {guide?.notes && guide.notes.length > 0 && (
                <div className="rounded-lg bg-[var(--bg-primary)] border border-[var(--border-color)] p-3 space-y-1.5">
                  <p className="text-[10px] font-medium text-amber-400 uppercase tracking-wider">Important Notes</p>
                  {guide.notes.map((note, i) => (
                    <p key={i} className="text-[11px] text-[var(--text-muted)] flex gap-1.5">
                      <span className="text-[var(--text-muted)]">•</span>
                      <span>{note}</span>
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── Agent Tools Tab ── */}
          {activeTab === 'tools' && (
            <div className="space-y-5">
              {usage?.tools && usage.tools.length > 0 ? (
                <div className="space-y-4">
                  <p className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                    Tools Unlocked
                  </p>
                  {usage.tools.map((toolId) => (
                    <div
                      key={toolId}
                      className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] p-4"
                    >
                      <div className="flex items-center gap-2 mb-2">
                        <Wand2 size={14} className="text-brand-400" />
                        <span className="text-sm font-medium text-white font-mono">{toolId}</span>
                      </div>
                      <p className="text-xs text-[var(--text-muted)] mb-3">
                        This tool becomes available to your AI agent during calls when this integration is active.
                      </p>

                      {usage.parameters && usage.parameters.length > 0 && (
                        <div className="mt-2">
                          <p className="text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-wider mb-2">
                            Parameters
                          </p>
                          <div className="overflow-x-auto">
                            <table className="w-full text-xs">
                              <thead>
                                <tr className="border-b border-[var(--border-color)]">
                                  <th className="text-left py-1.5 pr-3 text-[var(--text-muted)] font-medium">Name</th>
                                  <th className="text-left py-1.5 pr-3 text-[var(--text-muted)] font-medium">Description</th>
                                  <th className="text-left py-1.5 pr-3 text-[var(--text-muted)] font-medium">Required</th>
                                  <th className="text-left py-1.5 text-[var(--text-muted)] font-medium">Example</th>
                                </tr>
                              </thead>
                              <tbody>
                                {usage.parameters.map((param) => (
                                  <tr key={param.name} className="border-b border-[var(--border-color)]/50">
                                    <td className="py-1.5 pr-3 font-mono text-brand-400">{param.name}</td>
                                    <td className="py-1.5 pr-3 text-[var(--text-muted)]">{param.description}</td>
                                    <td className="py-1.5 pr-3">
                                      {param.required ? (
                                        <span className="text-red-400">Yes</span>
                                      ) : (
                                        <span className="text-[var(--text-muted)]">No</span>
                                      )}
                                    </td>
                                    <td className="py-1.5 text-[var(--text-muted)] font-mono">{param.example}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}

                  {usage.trigger_phrases && usage.trigger_phrases.length > 0 && (
                    <div>
                      <p className="text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-wider mb-2">
                        What callers say to trigger this
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {usage.trigger_phrases.map((phrase) => (
                          <span
                            key={phrase}
                            className="px-2 py-1 rounded-full bg-white/5 border border-[var(--border-color)] text-[11px] text-[var(--text-muted)]"
                          >
                            &ldquo;{phrase}&rdquo;
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-center py-10 text-[var(--text-muted)]">
                  <Wand2 size={24} className="mx-auto mb-2 opacity-40" />
                  <p className="text-sm">No specific agent tools for this integration.</p>
                  <p className="text-xs mt-1">This integration is used via workflow nodes or custom API calls.</p>
                </div>
              )}
            </div>
          )}

          {/* ── Examples Tab ── */}
          {activeTab === 'examples' && (
            <div className="space-y-5">
              {usage?.example_scenario ? (
                <div>
                  <p className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider mb-3">
                    Live Conversation Example
                  </p>
                  <div className="rounded-lg border border-[var(--border-color)] bg-[var(--bg-primary)] p-4 space-y-2.5">
                    {usage.example_scenario.split('\n').map((line, i) => {
                      const trimmed = line.trim();
                      if (!trimmed) return null;

                      if (trimmed.startsWith('Caller:')) {
                        return (
                          <div key={i} className="flex justify-start">
                            <div className="max-w-[85%] rounded-lg rounded-tl-none bg-white/5 px-3 py-2">
                              <p className="text-[10px] text-[var(--text-muted)] mb-0.5 font-medium">Caller</p>
                              <p className="text-xs text-white">{trimmed.replace('Caller:', '').trim()}</p>
                            </div>
                          </div>
                        );
                      }

                      if (trimmed.startsWith('Agent:')) {
                        return (
                          <div key={i} className="flex justify-end">
                            <div className="max-w-[85%] rounded-lg rounded-tr-none bg-brand-500/10 border border-brand-500/20 px-3 py-2">
                              <p className="text-[10px] text-brand-400 mb-0.5 font-medium">Agent</p>
                              <p className="text-xs text-white">{trimmed.replace('Agent:', '').trim()}</p>
                            </div>
                          </div>
                        );
                      }

                      if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
                        return (
                          <div key={i} className="flex justify-center">
                            <div className="px-3 py-1.5 rounded-full bg-amber-500/10 border border-amber-500/20">
                              <p className="text-[10px] text-amber-400 font-mono">{trimmed}</p>
                            </div>
                          </div>
                        );
                      }

                      return (
                        <p key={i} className="text-xs text-[var(--text-muted)] text-center">
                          {trimmed}
                        </p>
                      );
                    })}
                  </div>
                </div>
              ) : (
                <div className="text-center py-10 text-[var(--text-muted)]">
                  <MessageSquare size={24} className="mx-auto mb-2 opacity-40" />
                  <p className="text-sm">No example scenario available yet.</p>
                </div>
              )}
            </div>
          )}

          {/* ── Test Tab ── */}
          {activeTab === 'test' && (
            <div className="space-y-5">
              {integration ? (
                <>
                  <div className="flex items-start gap-3 px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-color)]">
                    <div className="w-2 h-2 rounded-full bg-green-400 mt-1.5 shrink-0" />
                    <div>
                      <p className="text-sm font-medium text-white">Integration Active</p>
                      <p className="text-xs text-[var(--text-muted)]">
                        {integration.name} — last updated {new Date(integration.updated_at).toLocaleDateString()}
                      </p>
                    </div>
                  </div>

                  <button
                    onClick={handleTest}
                    disabled={testLoading}
                    className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-brand-500/20 border border-brand-500/30 text-brand-400 text-sm font-medium hover:bg-brand-500/30 transition-colors disabled:opacity-50"
                  >
                    {testLoading ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                    {testLoading ? 'Testing...' : 'Test Connection'}
                  </button>

                  {testResult && (
                    <div
                      className={cn(
                        'rounded-lg border p-4',
                        testResult.status === 'connected' || testResult.status === 'ok'
                          ? 'bg-green-500/10 border-green-500/20'
                          : 'bg-red-500/10 border-red-500/20'
                      )}
                    >
                      <div className="flex items-center gap-2 mb-2">
                        {testResult.status === 'connected' || testResult.status === 'ok' ? (
                          <CheckCircle size={16} className="text-green-400" />
                        ) : (
                          <XCircle size={16} className="text-red-400" />
                        )}
                        <span
                          className={cn(
                            'text-sm font-medium',
                            testResult.status === 'connected' || testResult.status === 'ok'
                              ? 'text-green-400'
                              : 'text-red-400'
                          )}
                        >
                          {testResult.status === 'connected' || testResult.status === 'ok'
                            ? 'Connected'
                            : 'Error'}
                        </span>
                      </div>
                      <p className="text-xs text-[var(--text-muted)]">{testResult.message}</p>
                    </div>
                  )}
                </>
              ) : (
                <div className="text-center py-10 text-[var(--text-muted)]">
                  <Zap size={24} className="mx-auto mb-2 opacity-40" />
                  <p className="text-sm">No active integration to test.</p>
                  <p className="text-xs mt-1">Set up this integration first, then come back to test it.</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
