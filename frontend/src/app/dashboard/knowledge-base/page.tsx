'use client';

import { useState, useEffect } from 'react';
import { usePageTitle } from '@/hooks/usePageTitle';
import { SkeletonCard } from '@/components/ui/skeleton';
import {
  BookOpen,
  Plus,
  Upload,
  Trash2,
  Link2,
  FileText,
  File,
  Loader2,
  ChevronRight,
  X,
  Search,
  Sparkles,
} from 'lucide-react';
import { knowledgeBases } from '@/lib/api';
import { useToast } from '@/components/ui/toast';
import { EmptyState } from '@/components/ui/empty-state';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { UploadDialog } from '@/components/knowledge-base/upload-dialog';
import { LinkAgentsModal } from '@/components/knowledge-base/link-agents-modal';
import GsapPageWrapper from '@/components/three/gsap-page-wrapper';

interface KnowledgeBase {
  id: number;
  name: string;
  description: string | null;
  source_type: string;
  chunk_count: number;
  agent_ids: number[];
  is_active: boolean;
  created_at: string;
}

export default function KnowledgeBasePage() {
  usePageTitle('Knowledge Base');
  const { success, error } = useToast();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeBase | null>(null);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [uploadKbId, setUploadKbId] = useState<number | null>(null);
  const [uploadKbName, setUploadKbName] = useState('');
  const [linkKbId, setLinkKbId] = useState<number | null>(null);
  const [linkKbName, setLinkKbName] = useState('');
  const [linkAgentIds, setLinkAgentIds] = useState<number[]>([]);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [previewLoading, setPreviewLoading] = useState<number | null>(null);
  const [previewData, setPreviewData] = useState<{
    content_preview: string;
    chunks_preview: Array<{ index: number; text: string }>;
  } | null>(null);

  // Query playground state
  const [queryText, setQueryText] = useState('');
  const [queryResults, setQueryResults] = useState<Array<{
    text: string; score: number; index: number;
  }> | null>(null);
  const [queryLoading, setQueryLoading] = useState(false);
  const [queryMethod, setQueryMethod] = useState('');

  useEffect(() => {
    loadKBs();
  }, []);

  async function loadKBs() {
    try {
      const data = await knowledgeBases.list();
      setKbs(data.knowledge_bases);
    } catch {
      error('Failed to load knowledge bases');
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      await knowledgeBases.create({
        name: newName.trim(),
        description: newDesc.trim() || undefined,
      });
      success('Created', `Knowledge base "${newName}" created`);
      setNewName('');
      setNewDesc('');
      setShowCreate(false);
      loadKBs();
    } catch {
      error('Failed to create knowledge base');
    }
  }

  function handleDelete(kb: KnowledgeBase) {
    setDeleteTarget(kb);
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    const kb = deleteTarget;
    setDeleteTarget(null);
    try {
      await knowledgeBases.delete(kb.id);
      success('Deleted', `"${kb.name}" removed`);
      loadKBs();
    } catch {
      error('Failed to delete knowledge base');
    }
  }

  async function handleUpload(kbId: number, file: File) {
    await knowledgeBases.upload(kbId, file);
    success('Uploaded', `File processed and chunked`);
    loadKBs();
  }

  async function handleLinkAgents(agentIds: number[]) {
    if (!linkKbId) return;
    await knowledgeBases.update(linkKbId, { agent_ids: agentIds });
    success('Updated', 'Agent links saved');
    loadKBs();
  }

  async function toggleActive(kb: KnowledgeBase) {
    try {
      await knowledgeBases.update(kb.id, { is_active: !kb.is_active });
      loadKBs();
    } catch {
      error('Failed to update status');
    }
  }

  async function loadPreview(kbId: number) {
    if (expandedId === kbId) {
      setExpandedId(null);
      setPreviewData(null);
      setQueryResults(null);
      setQueryText('');
      return;
    }
    setExpandedId(kbId);
    setPreviewLoading(kbId);
    setQueryResults(null);
    setQueryText('');
    try {
      const data = await knowledgeBases.preview(kbId);
      setPreviewData(data);
    } catch {
      setPreviewData(null);
    } finally {
      setPreviewLoading(null);
    }
  }

  async function runQuery(kbId: number) {
    if (!queryText.trim()) return;
    setQueryLoading(true);
    setQueryResults(null);
    try {
      const data = await knowledgeBases.query(kbId, queryText.trim());
      setQueryResults(data.chunks);
      setQueryMethod(`${data.method} · ${data.model}`);
    } catch {
      error('Query failed');
      setQueryResults([]);
    } finally {
      setQueryLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <h1 className="page-title dash-title-gradient dash-title-glow">Knowledge Bases</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </div>
    );
  }

  return (
    <GsapPageWrapper>
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Knowledge Bases</h1>
          <p className="page-subtitle">
            Upload documents to ground your agents with real data
          </p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary">
          <Plus size={16} /> New Knowledge Base
        </button>
      </div>

      {/* Create dialog */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--bg-primary)]/80 backdrop-blur-sm">
          <div className="bg-[var(--bg-secondary)] rounded-xl p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold">Create Knowledge Base</h3>
              <button onClick={() => setShowCreate(false)} className="btn-ghost p-1">
                <X size={16} />
              </button>
            </div>
            <form onSubmit={handleCreate} className="space-y-3">
              <div>
                <label className="text-sm font-medium">Name</label>
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="e.g., Product FAQ"
                  className="input-base w-full mt-1"
                  autoFocus
                />
              </div>
              <div>
                <label className="text-sm font-medium">Description</label>
                <input
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  placeholder="Optional description"
                  className="input-base w-full mt-1"
                />
              </div>
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowCreate(false)} className="btn-ghost flex-1">
                  Cancel
                </button>
                <button type="submit" disabled={!newName.trim()} className="btn-primary flex-1 disabled:opacity-40">
                  Create
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Upload dialog */}
      {uploadKbId && (
        <UploadDialog
          kbId={uploadKbId}
          kbName={uploadKbName}
          onUpload={(file) => handleUpload(uploadKbId, file)}
          onClose={() => { setUploadKbId(null); setUploadKbName(''); }}
        />
      )}

      {/* Link agents modal */}
      {linkKbId && (
        <LinkAgentsModal
          kbId={linkKbId}
          kbName={linkKbName}
          linkedAgentIds={linkAgentIds}
          onLink={handleLinkAgents}
          onClose={() => { setLinkKbId(null); setLinkKbName(''); setLinkAgentIds([]); }}
        />
      )}

      {kbs.length === 0 ? (
        <EmptyState
          icon={BookOpen}
          title="No knowledge bases yet"
          description="Upload PDFs or text files so your agents can reference real information during calls."
          action={
            <button onClick={() => setShowCreate(true)} className="btn-primary">
              <Plus size={16} /> Create Knowledge Base
            </button>
          }
        />
      ) : (
        <div className="grid gap-3 mt-6">
          {kbs.map((kb) => (
            <div key={kb.id} className="dash-card overflow-hidden">
              <div className="flex items-center gap-4 p-4">
                <div className="p-2.5 rounded-lg bg-[var(--bg-tertiary)]">
                  {kb.source_type === 'file' ? (
                    <File size={20} className="text-[var(--accent)]" />
                  ) : (
                    <FileText size={20} className="text-[var(--accent)]" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="font-medium truncate">{kb.name}</h3>
                    {!kb.is_active && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400">
                        Inactive
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-[var(--text-muted)]">
                    {kb.chunk_count} chunks · {kb.agent_ids.length} agent{kb.agent_ids.length !== 1 ? 's' : ''} linked
                    {kb.description && ` · ${kb.description}`}
                  </p>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => toggleActive(kb)}
                    className={`px-2 py-1 rounded-lg text-xs transition-colors ${
                      kb.is_active
                        ? 'bg-green-500/10 text-green-400 hover:bg-green-500/20'
                        : 'bg-amber-500/10 text-amber-400 hover:bg-amber-500/20'
                    }`}
                    title={kb.is_active ? 'Deactivate' : 'Activate'}
                  >
                    {kb.is_active ? 'Active' : 'Inactive'}
                  </button>
                  <button
                    onClick={() => { setUploadKbId(kb.id); setUploadKbName(kb.name); }}
                    className="p-2 text-[var(--text-muted)] hover:text-[var(--accent)] rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                    title="Upload document"
                  >
                    <Upload size={16} />
                  </button>
                  <button
                    onClick={() => {
                      setLinkKbId(kb.id);
                      setLinkKbName(kb.name);
                      setLinkAgentIds(kb.agent_ids);
                    }}
                    className="p-2 text-[var(--text-muted)] hover:text-blue-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                    title="Link to agents"
                  >
                    <Link2 size={16} />
                  </button>
                  <button
                    onClick={() => loadPreview(kb.id)}
                    className="p-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                    title="Preview content"
                  >
                    <ChevronRight
                      size={16}
                      className={`transition-transform ${expandedId === kb.id ? 'rotate-90' : ''}`}
                    />
                  </button>
                  <button
                    onClick={() => handleDelete(kb)}
                    className="p-2 text-[var(--text-muted)] hover:text-red-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                    title="Delete"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>

              {/* Expanded preview */}
              {expandedId === kb.id && (
                <div className="px-4 pb-4 border-t border-[var(--glass-border)]">
                  {previewLoading === kb.id ? (
                    <div className="flex items-center justify-center py-6">
                      <Loader2 size={18} className="animate-spin text-[var(--accent)]" />
                    </div>
                  ) : previewData ? (
                    <div className="space-y-3 pt-3">
                      <div>
                        <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                          Content Preview
                        </label>
                        <p className="text-sm text-[var(--text-secondary)] mt-1 whitespace-pre-wrap line-clamp-6 bg-[var(--bg-tertiary)] rounded-lg p-3">
                          {previewData.content_preview || 'No content preview available.'}
                        </p>
                      </div>
                      {previewData.chunks_preview.length > 0 && (
                        <div>
                          <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                            First {previewData.chunks_preview.length} Chunks
                          </label>
                          <div className="space-y-2 mt-1">
                            {previewData.chunks_preview.map((chunk) => (
                              <div
                                key={chunk.index}
                                className="text-sm text-[var(--text-secondary)] bg-[var(--bg-tertiary)] rounded-lg p-3 border border-[var(--glass-border)]"
                              >
                                <span className="text-[10px] text-[var(--text-muted)] font-mono">
                                  Chunk {chunk.index + 1}
                                </span>
                                <p className="mt-1">{chunk.text}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* ── Query Playground ── */}
                      <div className="mt-4 pt-4 border-t border-[var(--glass-border)]">
                        <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-1.5">
                          <Search size={12} />
                          Test Semantic Retrieval
                        </label>
                        <div className="flex gap-2 mt-2">
                          <input
                            value={queryText}
                            onChange={(e) => setQueryText(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Enter') runQuery(kb.id); }}
                            placeholder="Ask a question about this knowledge base..."
                            className="input-base flex-1 text-sm"
                          />
                          <button
                            onClick={() => runQuery(kb.id)}
                            disabled={queryLoading || !queryText.trim()}
                            className="btn-primary px-3 disabled:opacity-40"
                          >
                            {queryLoading ? (
                              <Loader2 size={16} className="animate-spin" />
                            ) : (
                              <Sparkles size={16} />
                            )}
                          </button>
                        </div>

                        {queryResults !== null && (
                          <div className="mt-3 space-y-2">
                            {queryResults.length === 0 ? (
                              <p className="text-sm text-[var(--text-muted)]">
                                No relevant chunks found for this query.
                              </p>
                            ) : (
                              <>
                                <div className="flex items-center gap-2">
                                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono">
                                    {queryMethod}
                                  </span>
                                  <span className="text-[10px] text-[var(--text-muted)]">
                                    {queryResults.length} result{queryResults.length !== 1 ? 's' : ''}
                                  </span>
                                </div>
                                {queryResults.map((result) => (
                                  <div
                                    key={result.index}
                                    className="text-sm text-[var(--text-secondary)] bg-[var(--bg-tertiary)] rounded-lg p-3 border border-[var(--glass-border)]"
                                  >
                                    <div className="flex items-center justify-between mb-1">
                                      <span className="text-[10px] text-[var(--text-muted)] font-mono">
                                        Chunk {result.index + 1}
                                      </span>
                                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-brand-500/10 text-brand-400 font-mono">
                                        score {(result.score * 100).toFixed(1)}%
                                      </span>
                                    </div>
                                    <p className="line-clamp-4">{result.text}</p>
                                  </div>
                                ))}
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm text-[var(--text-muted)] py-4 text-center">
                      No preview available.
                    </p>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete Knowledge Base"
        message={`Delete "${deleteTarget?.name}"? This cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
    </GsapPageWrapper>
  );
}
