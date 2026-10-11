'use client';

import { useState, useEffect, useCallback } from 'react';
import { SkeletonTable } from '@/components/ui/skeleton';
import {
  Plus,
  Trash2,
  Play,
  PlayCircle,
  CheckCircle2,
  XCircle,
  Loader2,
  FlaskConical,
  Clock,
  Hash,
  History,
  X,
  Pencil,
} from 'lucide-react';
import { testCases as testApi } from '@/lib/api';
import type { TestCase, TestRunResult, BatchTestSummary, CriteriaType } from '@/lib/types';
import { useToast } from '@/components/ui/toast';

interface SimulationTabProps {
  agentId: number;
}

const CRITERIA_TYPES: { value: CriteriaType; label: string }[] = [
  { value: 'keyword', label: 'Keyword (any match)' },
  { value: 'contains', label: 'Contains (exact substring)' },
  { value: 'not_contains', label: 'Not Contains' },
];

export function SimulationTab({ agentId }: SimulationTabProps) {
  const { success, apiError } = useToast();
  const [testCases, setTestCases] = useState<TestCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [showEditor, setShowEditor] = useState(false);
  const [editingTc, setEditingTc] = useState<TestCase | null>(null);
  const [runningId, setRunningId] = useState<number | null>(null);
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchResult, setBatchResult] = useState<BatchTestSummary | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const fetchTestCases = useCallback(async () => {
    setLoading(true);
    try {
      const data = await testApi.list(agentId);
      setTestCases(data.test_cases);
    } catch (err) {
      apiError(err, 'Failed to load test cases');
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    fetchTestCases();
  }, [fetchTestCases]);

  const handleRunSingle = async (tc: TestCase) => {
    setRunningId(tc.id);
    try {
      const { result } = await testApi.simulate(agentId, { test_case_id: tc.id });
      setBatchResult({
        total: 1,
        passed: result.passed ? 1 : 0,
        failed: result.passed ? 0 : 1,
        results: [{ ...result, label: tc.label }],
      });
      if (result.passed) {
        success('Test Passed', `"${tc.label}" passed`);
      } else {
        apiError(new Error('Criteria not met'), `"${tc.label}" failed`);
      }
    } catch (err) {
      apiError(err, 'Simulation failed');
    } finally {
      setRunningId(null);
    }
  };

  const handleBatchTest = async () => {
    setBatchRunning(true);
    try {
      const result = await testApi.batchTest(agentId);
      setBatchResult(result);
      success('Batch Test Complete', `${result.passed}/${result.total} passed`);
    } catch (err) {
      apiError(err, 'Batch test failed');
    } finally {
      setBatchRunning(false);
    }
  };

  const handleDelete = async (tc: TestCase) => {
    try {
      await testApi.delete(agentId, tc.id);
      setTestCases((prev) => prev.filter((t) => t.id !== tc.id));
      success('Deleted', `Test case "${tc.label}" removed`);
    } catch (err) {
      apiError(err, 'Failed to delete test case');
    }
  };

  const handleSave = async (data: {
    label: string;
    user_prompt: string;
    success_criteria: string;
    criteria_type: string;
  }) => {
    try {
      if (editingTc) {
        await testApi.update(agentId, editingTc.id, data);
        success('Updated', 'Test case updated');
      } else {
        await testApi.create(agentId, data);
        success('Created', 'Test case created');
      }
      setShowEditor(false);
      setEditingTc(null);
      fetchTestCases();
    } catch (err) {
      apiError(err, 'Failed to save test case');
    }
  };

  return (
    <div className="flex gap-4 h-full overflow-hidden">
      {/* Left: Test Cases */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <div className="flex items-center justify-between mb-4 shrink-0">
          <div className="flex items-center gap-2">
            <FlaskConical size={18} className="text-brand-400" />
            <h2 className="text-sm font-semibold">Test Cases</h2>
            <span className="text-xs text-[var(--text-muted)]">({testCases.length})</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleBatchTest}
              disabled={batchRunning || testCases.length === 0}
              className="btn-primary text-xs flex items-center gap-1.5 px-3 py-2 rounded-lg disabled:opacity-40"
            >
              {batchRunning ? <Loader2 size={14} className="animate-spin" /> : <PlayCircle size={14} />}
              Run All
            </button>
            <button
              onClick={() => { setEditingTc(null); setShowEditor(true); }}
              className="btn-ghost text-xs flex items-center gap-1.5 px-3 py-2 rounded-lg"
            >
              <Plus size={14} />
              Add Test
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto space-y-2">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={20} className="animate-spin text-[var(--text-muted)]" />
            </div>
          ) : testCases.length === 0 ? (
            <div className="text-center py-12 text-[var(--text-muted)]">
              <FlaskConical size={32} className="mx-auto mb-3 opacity-40" />
              <p className="text-sm">No test cases yet</p>
              <p className="text-xs mt-1">Create test cases to validate your agent&apos;s responses</p>
            </div>
          ) : (
            testCases.map((tc) => (
              <div
                key={tc.id}
                className="dash-card p-4 group"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <h3 className="font-medium text-sm">{tc.label}</h3>
                    <p className="text-xs text-[var(--text-muted)] mt-1 line-clamp-2">
                      <span className="text-[var(--text-secondary)]">Prompt:</span> {tc.user_prompt}
                    </p>
                    <div className="flex items-center gap-2 mt-2">
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-tertiary)] text-[var(--text-muted)]">
                        {tc.criteria_type}
                      </span>
                      <span className="text-[10px] text-[var(--text-muted)] truncate">
                        &ldquo;{tc.success_criteria}&rdquo;
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      onClick={() => handleRunSingle(tc)}
                      disabled={runningId === tc.id}
                      className="p-2 rounded-lg hover:bg-[var(--bg-tertiary)] text-brand-400 transition-colors disabled:opacity-40"
                      title="Run this test"
                    >
                      {runningId === tc.id ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                    </button>
                    <button
                      onClick={() => { setEditingTc(tc); setShowEditor(true); }}
                      className="p-2 rounded-lg hover:bg-[var(--bg-tertiary)] text-[var(--text-muted)] transition-colors"
                      title="Edit"
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={() => handleDelete(tc)}
                      className="p-2 rounded-lg hover:bg-red-500/10 text-[var(--text-muted)] hover:text-red-400 transition-colors"
                      title="Delete"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Right: Results Panel */}
      <div className="w-96 flex flex-col shrink-0 overflow-hidden">
        <div className="flex items-center justify-between mb-4 shrink-0">
          <div className="flex items-center gap-2">
            <History size={16} className="text-[var(--text-muted)]" />
            <h2 className="text-sm font-semibold">Results</h2>
          </div>
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="text-xs text-brand-400 hover:underline"
          >
            {showHistory ? 'Latest Run' : 'History'}
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {!showHistory ? (
            batchResult ? (
              <>
                {/* Summary */}
                <div className="dash-card p-4 mb-3">
                  <div className="flex items-center justify-around text-center">
                    <div>
                      <p className="text-2xl font-bold text-brand-400">{batchResult.passed}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">Passed</p>
                    </div>
                    <div className="w-px h-8 bg-[var(--glass-border)]" />
                    <div>
                      <p className="text-2xl font-bold text-red-400">{batchResult.failed}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">Failed</p>
                    </div>
                    <div className="w-px h-8 bg-[var(--glass-border)]" />
                    <div>
                      <p className="text-2xl font-bold text-[var(--text-secondary)]">{batchResult.total}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">Total</p>
                    </div>
                  </div>
                </div>

                {/* Individual results */}
                <div className="space-y-2">
                  {batchResult.results.map((r, i) => (
                    <ResultCard key={r.id || i} result={r} />
                  ))}
                </div>
              </>
            ) : (
              <div className="text-center py-12 text-[var(--text-muted)]">
                <PlayCircle size={32} className="mx-auto mb-3 opacity-40" />
                <p className="text-sm">No results yet</p>
                <p className="text-xs mt-1">Run a test case to see results</p>
              </div>
            )
          ) : (
            <HistoryPanel agentId={agentId} />
          )}
        </div>
      </div>

      {/* Editor Modal */}
      {showEditor && (
        <TestCaseEditor
          tc={editingTc}
          onSave={handleSave}
          onClose={() => { setShowEditor(false); setEditingTc(null); }}
        />
      )}
    </div>
  );
}

function ResultCard({ result }: { result: TestRunResult }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="dash-card p-3">
      <div className="flex items-start gap-2">
        {result.passed ? (
          <CheckCircle2 size={16} className="text-emerald-400 shrink-0 mt-0.5" />
        ) : (
          <XCircle size={16} className="text-red-400 shrink-0 mt-0.5" />
        )}
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium truncate">
            {result.label || 'Ad-hoc test'}
          </p>
          <div className="flex items-center gap-3 mt-1 text-[10px] text-[var(--text-muted)]">
            <span className="flex items-center gap-1">
              <Clock size={10} /> {result.latency_ms}ms
            </span>
            {result.tokens > 0 && (
              <span className="flex items-center gap-1">
                <Hash size={10} /> {result.tokens} tokens
              </span>
            )}
          </div>
          {result.error ? (
            <p className="text-xs text-red-400 mt-1">{result.error}</p>
          ) : (
            <>
              <p className="text-xs text-[var(--text-muted)] mt-1 line-clamp-2">
                <span className="text-[var(--text-secondary)]">Agent:</span> {result.agent_response}
              </p>
              {expanded && (
                <p className="text-xs text-[var(--text-secondary)] mt-1 leading-relaxed">
                  {result.agent_response}
                </p>
              )}
              <button
                onClick={() => setExpanded(!expanded)}
                className="text-[10px] text-brand-400 hover:underline mt-1"
              >
                {expanded ? 'Show less' : 'Show full response'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function HistoryPanel({ agentId }: { agentId: number }) {
  const { apiError } = useToast();
  const [runs, setRuns] = useState<import('@/lib/types').TestRunHistory[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    testApi.history(agentId)
      .then((data) => setRuns(data.test_runs))
      .catch((err) => apiError(err, 'Failed to load history'))
      .finally(() => setLoading(false));
  }, [agentId]);

  if (loading) {
    return (
      <div className="space-y-4">
        <SkeletonTable rows={4} cols={4} />
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="text-center py-12 text-[var(--text-muted)]">
        <History size={32} className="mx-auto mb-3 opacity-40" />
        <p className="text-sm">No test history</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {runs.map((run) => (
        <div key={run.id} className="dash-card p-3">
          <div className="flex items-start gap-2">
            {run.passed ? (
              <CheckCircle2 size={14} className="text-emerald-400 shrink-0 mt-0.5" />
            ) : (
              <XCircle size={14} className="text-red-400 shrink-0 mt-0.5" />
            )}
            <div className="flex-1 min-w-0">
              <p className="text-xs text-[var(--text-secondary)] line-clamp-2">
                {run.user_prompt}
              </p>
              <div className="flex items-center gap-3 mt-1 text-[10px] text-[var(--text-muted)]">
                <span>{run.latency_ms}ms</span>
                <span>{new Date(run.created_at).toLocaleDateString()}</span>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function TestCaseEditor({
  tc,
  onSave,
  onClose,
}: {
  tc: TestCase | null;
  onSave: (data: { label: string; user_prompt: string; success_criteria: string; criteria_type: string }) => void;
  onClose: () => void;
}) {
  const [label, setLabel] = useState(tc?.label || '');
  const [userPrompt, setUserPrompt] = useState(tc?.user_prompt || '');
  const [successCriteria, setSuccessCriteria] = useState(tc?.success_criteria || '');
  const [criteriaType, setCriteriaType] = useState<CriteriaType>(tc?.criteria_type || 'keyword');

  return (
    <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm z-50 flex items-center justify-center animate-fade-in">
      <div className="bg-[var(--bg-secondary)] rounded-2xl border border-[var(--glass-border)] w-full max-w-lg mx-4 shadow-modal animate-scale-in">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--glass-border)]">
          <h2 className="text-lg font-semibold tracking-tight">
            {tc ? 'Edit Test Case' : 'New Test Case'}
          </h2>
          <button onClick={onClose} className="btn-ghost p-1.5">
            <X size={18} />
          </button>
        </div>

        <div className="p-6 space-y-4">
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)]">Label</label>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Greeting test"
              className="input-base w-full mt-1 rounded-lg px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label className="text-xs font-medium text-[var(--text-muted)]">User Prompt</label>
            <textarea
              value={userPrompt}
              onChange={(e) => setUserPrompt(e.target.value)}
              placeholder="What the simulated caller says..."
              rows={3}
              className="input-base w-full mt-1 rounded-lg px-3 py-2 text-sm resize-none"
            />
          </div>

          <div>
            <label className="text-xs font-medium text-[var(--text-muted)]">Criteria Type</label>
            <select
              value={criteriaType}
              onChange={(e) => setCriteriaType(e.target.value as CriteriaType)}
              className="input-base w-full mt-1 rounded-lg px-3 py-2 text-sm"
            >
              {CRITERIA_TYPES.map((ct) => (
                <option key={ct.value} value={ct.value}>{ct.label}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs font-medium text-[var(--text-muted)]">
              {criteriaType === 'keyword' ? 'Keywords (comma-separated)' : 'Success Criteria'}
            </label>
            <input
              value={successCriteria}
              onChange={(e) => setSuccessCriteria(e.target.value)}
              placeholder={criteriaType === 'keyword' ? 'hello, welcome, help' : 'expected substring'}
              className="input-base w-full mt-1 rounded-lg px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-[var(--glass-border)]">
          <button onClick={onClose} className="btn-ghost text-sm px-4 py-2 rounded-lg">
            Cancel
          </button>
          <button
            onClick={() => onSave({ label, user_prompt: userPrompt, success_criteria: successCriteria, criteria_type: criteriaType })}
            disabled={!label.trim() || !userPrompt.trim() || !successCriteria.trim()}
            className="btn-primary text-sm px-4 py-2 rounded-lg disabled:opacity-40"
          >
            {tc ? 'Save Changes' : 'Create Test Case'}
          </button>
        </div>
      </div>
    </div>
  );
}
