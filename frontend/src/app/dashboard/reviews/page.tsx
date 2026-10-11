'use client';

import { useEffect, useState, useCallback } from 'react';
import { useToast } from '@/components/ui/toast';
import { EmptyState } from '@/components/ui/empty-state';
import { reviews as reviewsApi } from '@/lib/api';
import { ReviewItem } from '@/lib/types';
import { timeAgo } from '@/lib/utils';
import { useModalFocusTrap } from '@/hooks/use-modal-focus-trap';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';
import SettingsTabBar from '../settings/_components/SettingsTabBar';
import { SkeletonTable } from '@/components/ui/skeleton';
import {
  ClipboardCheck,
  CheckCircle2,
  XCircle,
  Clock,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Loader2,
  Eye,
  X,
  MessageSquare,
  Zap,
  FileText,
  Phone,
} from 'lucide-react';

/* ─── Status Badge ──────────────────────────────────────── */
function ReviewBadge({ status }: { status: string }) {
  const config: Record<string, { bg: string; text: string; icon: React.ElementType }> = {
    pending: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', icon: Clock },
    approved: { bg: 'bg-green-500/20', text: 'text-green-400', icon: CheckCircle2 },
    rejected: { bg: 'bg-red-500/20', text: 'text-red-400', icon: XCircle },
  };
  const c = config[status] || config.pending;
  const Icon = c.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${c.bg} ${c.text}`}>
      <Icon size={12} />
      {status}
    </span>
  );
}

/* ─── Detail Modal ──────────────────────────────────────── */
function ReviewDetailModal({
  item,
  onClose,
  onApprove,
  onReject,
  acting,
}: {
  item: ReviewItem;
  onClose: () => void;
  onApprove: (id: number, notes: string) => void;
  onReject: (id: number, notes: string) => void;
  acting: boolean;
}) {
  const [notes, setNotes] = useState('');
  const isPending = item.status === 'pending';
  const dialogRef = useModalFocusTrap(true, onClose);

  // Parse action_params JSON
  let params: Record<string, unknown> = {};
  try {
    if (item.action_params) params = JSON.parse(item.action_params);
  } catch { /* ignore */ }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm" onClick={onClose} />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-detail-title"
        tabIndex={-1}
        className="relative w-full max-w-2xl bg-[var(--bg-secondary)] rounded-2xl border border-[var(--glass-border)] shadow-2xl shadow-modal animate-scale-in max-h-[90vh] overflow-y-auto"
      >
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-[var(--glass-border)]">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-yellow-500/20 text-yellow-400">
              <ClipboardCheck size={20} />
            </div>
            <div>
              <h2 id="review-detail-title" className="text-lg font-semibold">Review Item #{item.id}</h2>
              <p className="text-xs text-[var(--text-muted)]">
                Created {item.created_at ? timeAgo(item.created_at) : 'recently'}
              </p>
            </div>
          </div>
          <button onClick={onClose} className="btn-ghost p-1.5" aria-label="Close review details">
            <X size={20} />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-5">
          {/* Status */}
          <div className="flex items-center gap-3">
            <span className="text-sm text-[var(--text-secondary)]">Status:</span>
            <ReviewBadge status={item.status} />
          </div>

          {/* Action Type */}
          <div className="bg-[var(--bg-tertiary)] rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <Zap size={14} className="text-brand-400" />
              <span className="text-sm font-medium">Action</span>
            </div>
            <p className="text-sm text-[var(--text-secondary)]">{item.action_type || 'workflow_execution'}</p>
            {item.action_url && (
              <p className="text-xs text-[var(--text-muted)] font-mono mt-1 break-all">{item.action_url}</p>
            )}
          </div>

          {/* Workflow / Call Info */}
          <div className="grid grid-cols-2 gap-4">
            {item.workflow_id && (
              <div className="bg-[var(--bg-tertiary)] rounded-lg p-4">
                <div className="flex items-center gap-2 mb-1">
                  <FileText size={14} className="text-purple-400" />
                  <span className="text-sm font-medium">Workflow</span>
                </div>
                <p className="text-sm text-[var(--text-secondary)]">ID: {item.workflow_id}</p>
              </div>
            )}
            {item.call_log_id && (
              <div className="bg-[var(--bg-tertiary)] rounded-lg p-4">
                <div className="flex items-center gap-2 mb-1">
                  <Phone size={14} className="text-blue-400" />
                  <span className="text-sm font-medium">Call</span>
                </div>
                <p className="text-sm text-[var(--text-secondary)]">ID: {item.call_log_id}</p>
              </div>
            )}
          </div>

          {/* Action Params */}
          {Object.keys(params).length > 0 && (
            <div className="bg-[var(--bg-tertiary)] rounded-lg p-4">
              <p className="text-sm font-medium mb-2">Parameters</p>
              <div className="space-y-1.5">
                {Object.entries(params).map(([k, v]) => (
                  <div key={k} className="flex items-start gap-2 text-sm">
                    <span className="text-[var(--text-muted)] font-mono text-xs min-w-[120px]">{k}:</span>
                    <span className="text-[var(--text-secondary)] break-all">{String(v)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Trigger Context (transcript excerpt) */}
          {item.trigger_context && (
            <div className="bg-[var(--bg-tertiary)] rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <MessageSquare size={14} className="text-green-400" />
                <span className="text-sm font-medium">Trigger Context</span>
              </div>
              <p className="text-sm text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto">
                {item.trigger_context}
              </p>
            </div>
          )}

          {/* Review Info (if already reviewed) */}
          {item.reviewed_at && (
            <div className="bg-[var(--bg-tertiary)] rounded-lg p-4 border border-[var(--glass-border)]">
              <p className="text-sm font-medium mb-1">Review Decision</p>
              <p className="text-xs text-[var(--text-muted)]">
                Reviewed {timeAgo(item.reviewed_at)}
                {item.review_notes && ` — "${item.review_notes}"`}
              </p>
            </div>
          )}

          {/* Approve / Reject Actions */}
          {isPending && (
            <div className="border-t border-[var(--glass-border)] pt-5 space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1.5">Review Notes (optional)</label>
                <textarea
                  value={notes}
                  onChange={e => setNotes(e.target.value)}
                  placeholder="Add notes about your decision..."
                  rows={2}
                  className="w-full bg-[var(--bg-primary)] border border-[var(--glass-border)] rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-brand-500 focus:border-transparent outline-none resize-none"
                />
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => onApprove(item.id, notes)}
                  disabled={acting}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-green-600 hover:bg-green-500 text-[var(--text-inverse)] font-medium text-sm transition-colors disabled:opacity-50"
                >
                  {acting ? <Loader2 size={16} className="animate-spin" /> : <CheckCircle2 size={16} />}
                  Approve & Execute
                </button>
                <button
                  onClick={() => onReject(item.id, notes)}
                  disabled={acting}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-red-600/80 hover:bg-red-500 text-[var(--text-inverse)] font-medium text-sm transition-colors disabled:opacity-50"
                >
                  {acting ? <Loader2 size={16} className="animate-spin" /> : <XCircle size={16} />}
                  Reject
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── Main Page ─────────────────────────────────────────── */
export default function ReviewsPage() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [pendingCount, setPendingCount] = useState(0);
  const [statusFilter, setStatusFilter] = useState<string>('pending');
  const [selectedItem, setSelectedItem] = useState<ReviewItem | null>(null);
  const [acting, setActing] = useState(false);
  const { success, apiError } = useToast();

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await reviewsApi.list({
        status: statusFilter || undefined,
        page,
        per_page: 20,
      });
      setItems(res.reviews);
      setTotalPages(res.pages);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load reviews');
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter]);

  const loadPendingCount = useCallback(async () => {
    try {
      const data = await reviewsApi.list({ status: 'pending', page: 1, per_page: 1 });
      setPendingCount(data.total);
    } catch {
      // silent
    }
  }, []);

  useEffect(() => { load(); loadPendingCount(); }, [load, loadPendingCount]);

  const handleApprove = async (id: number, notes: string) => {
    try {
      setActing(true);
      const res = await reviewsApi.approve(id, notes || undefined);
      success('Approved', res.message);
      setSelectedItem(null);
      load();
    } catch (err) {
      apiError(err, 'Approval failed');
    } finally {
      setActing(false);
    }
  };

  const handleReject = async (id: number, notes: string) => {
    try {
      setActing(true);
      const res = await reviewsApi.reject(id, notes || undefined);
      success('Rejected', res.message);
      setSelectedItem(null);
      load();
    } catch (err) {
      apiError(err, 'Rejection failed');
    } finally {
      setActing(false);
    }
  };

  return (
    <GsapPageWrapper>
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow flex items-center gap-3">
            <ClipboardCheck size={28} className="text-yellow-400" />
            Review Queue
            {pendingCount > 0 && (
              <span className="ml-2 px-2.5 py-0.5 rounded-full text-sm font-medium bg-yellow-500/20 text-yellow-400">
                {pendingCount} pending
              </span>
            )}
          </h1>
          <p className="page-subtitle">
            Approve or reject workflow actions that require human review
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-[var(--glass-border)] hover:bg-[var(--bg-tertiary)] transition-colors disabled:opacity-50"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Settings Tabs */}
      <SettingsTabBar />

      {/* Filters */}
      <div className="flex items-center gap-2">
        {['', 'pending', 'approved', 'rejected'].map(s => (
          <button
            key={s}
            onClick={() => { setStatusFilter(s); setPage(1); }}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              statusFilter === s
                ? 'bg-brand-600/20 text-brand-400 border border-brand-500/30'
                : 'text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] border border-transparent'
            }`}
          >
            {s === '' ? 'All' : s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
        <span className="ml-auto text-xs text-[var(--text-muted)]">{total} item{total !== 1 ? 's' : ''}</span>
      </div>

      {/* Error State */}
      {error && (
        <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 rounded-lg p-4">
          <AlertTriangle className="text-red-400 flex-shrink-0" size={18} />
          <div>
            <p className="text-sm font-medium text-red-400">Failed to load reviews</p>
            <p className="text-xs text-red-400/70 mt-0.5">{error}</p>
          </div>
          <button onClick={load} className="ml-auto text-sm text-red-400 hover:underline">Retry</button>
        </div>
      )}

      {/* Loading */}
      {loading && !error && (
        <SkeletonTable rows={5} cols={5} />
      )}

      {/* Empty State */}
      {!loading && !error && items.length === 0 && (
        <EmptyState
          icon={ClipboardCheck}
          title="No review items"
          description={
            statusFilter === 'pending'
              ? 'All caught up! No actions waiting for review.'
              : `No ${statusFilter || ''} review items found.`
          }
        />
      )}

      {/* Items Table */}
      {!loading && !error && items.length > 0 && (
        <div className="dash-table overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--glass-border)] text-left">
                <th className="px-4 py-3 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">ID</th>
                <th className="px-4 py-3 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Action</th>
                <th className="px-4 py-3 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Trigger</th>
                <th className="px-4 py-3 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Status</th>
                <th className="px-4 py-3 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Created</th>
                <th className="px-4 py-3 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map(item => (
                <tr
                  key={item.id}
                  className="border-b border-[var(--glass-border)] hover:bg-[var(--bg-tertiary)] transition-colors cursor-pointer"
                  onClick={() => setSelectedItem(item)}
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') setSelectedItem(item); }}
                >
                  <td className="px-4 py-3 font-mono text-xs text-[var(--text-muted)]">#{item.id}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Zap size={14} className="text-brand-400" />
                      <span>{item.action_type || 'workflow_execution'}</span>
                    </div>
                    {item.workflow_id && <p className="text-xs text-[var(--text-muted)] mt-0.5">Workflow #{item.workflow_id}</p>}
                  </td>
                  <td className="px-4 py-3 max-w-[200px]">
                    <p className="text-xs text-[var(--text-secondary)] truncate">
                      {item.trigger_context || '—'}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    <ReviewBadge status={item.status} />
                  </td>
                  <td className="px-4 py-3 text-xs text-[var(--text-muted)]">
                    {item.created_at ? timeAgo(item.created_at) : '—'}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => setSelectedItem(item)}
                        className="p-1.5 rounded-lg hover:bg-[var(--bg-secondary)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                        title="View details"
                        aria-label="View review details"
                      >
                        <Eye size={14} />
                      </button>
                      {item.status === 'pending' && (
                        <>
                          <button
                            onClick={() => handleApprove(item.id, '')}
                            className="p-1.5 rounded-lg hover:bg-green-500/20 text-[var(--text-muted)] hover:text-green-400 transition-colors"
                            title="Quick approve"
                            aria-label="Approve review"
                          >
                            <CheckCircle2 size={14} />
                          </button>
                          <button
                            onClick={() => handleReject(item.id, '')}
                            className="p-1.5 rounded-lg hover:bg-red-500/20 text-[var(--text-muted)] hover:text-red-400 transition-colors"
                            title="Quick reject"
                            aria-label="Reject review"
                          >
                            <XCircle size={14} />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--glass-border)]">
              <p className="text-xs text-[var(--text-muted)]">
                Page {page} of {totalPages} ({total} items)
              </p>
              <div className="flex gap-1">
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="p-1.5 rounded-lg hover:bg-[var(--bg-tertiary)] disabled:opacity-30 transition-colors"
                  aria-label="Previous page"
                >
                  <ChevronLeft size={16} />
                </button>
                <button
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="p-1.5 rounded-lg hover:bg-[var(--bg-tertiary)] disabled:opacity-30 transition-colors"
                  aria-label="Next page"
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Detail Modal */}
      {selectedItem && (
        <ReviewDetailModal
          item={selectedItem}
          onClose={() => setSelectedItem(null)}
          onApprove={handleApprove}
          onReject={handleReject}
          acting={acting}
        />
      )}
    </div>
    </GsapPageWrapper>
  );
}
