"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Server,
  Plug,
  Globe,
  Wrench,
  HardDrive,
  Calendar,
  Check,
  Plus,
  X,
  Loader2,
  Search,
  FileText,
  Folder,
  Save,
  ShieldCheck,
} from "lucide-react";
import { tools as toolsApi, integrations as integrationsApi } from "@/lib/api";
import { PlatformTool } from "@/lib/types";
import { useToast } from "@/components/ui/toast";

interface ToolsSectionProps {
  agentId: number;
  variant?: "card" | "builder";
  onBindingsChange?: (bindings: Record<string, unknown>) => void;
}

interface DriveFile {
  id: string;
  name: string;
  mimeType?: string;
  modifiedTime?: string;
}

export function ToolsSection({ agentId, variant = "card", onBindingsChange }: ToolsSectionProps) {
  const isBuilder = variant === "builder";
  const { success, apiError: toastError } = useToast();
  const [tools, setTools] = useState<PlatformTool[]>([]);
  const [enabled, setEnabled] = useState<string[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [savingTools, setSavingTools] = useState(false);

  // MCP bindings state
  const [bindings, setBindings] = useState<{
    drive?: { file_ids: string[]; folder_ids: string[] };
    calendar?: { calendar_ids: string[] };
  }>({});
  const [bindingsLoaded, setBindingsLoaded] = useState(false);
  const [savingBindings, setSavingBindings] = useState(false);

  // Google OAuth + Drive state
  const [googleConnected, setGoogleConnected] = useState(false);
  const [driveIntegrationId, setDriveIntegrationId] = useState<number | null>(null);
  const [driveFiles, setDriveFiles] = useState<DriveFile[]>([]);
  const [driveSearch, setDriveSearch] = useState("");
  const [driveLoading, setDriveLoading] = useState(false);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [selectedFileIds, setSelectedFileIds] = useState<string[]>([]);
  const [fileNamesMap, setFileNamesMap] = useState<Record<string, string>>({});

  // File preview state
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewFileId, setPreviewFileId] = useState<string | null>(null);
  const [previewFileName, setPreviewFileName] = useState('');
  const [previewContent, setPreviewContent] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);

  // Load tools
  useEffect(() => {
    toolsApi
      .agentTools(agentId)
      .then((data) => {
        setEnabled(data.enabled_tools || []);
        setTools(data.tools || []);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [agentId]);

  // Load MCP bindings
  useEffect(() => {
    toolsApi
      .agentMcpBindings(agentId)
      .then((data) => {
        const b = data.bindings as typeof bindings;
        setBindings(b || {});
        setSelectedFileIds(b?.drive?.file_ids || []);
        setBindingsLoaded(true);
      })
      .catch(() => setBindingsLoaded(true));
  }, [agentId]);

  // Check Google OAuth status and find Drive integration
  useEffect(() => {
    integrationsApi.googleStatus().then((data) => {
      setGoogleConnected(data.connected);
    }).catch(() => {});

    integrationsApi.list().then((data) => {
      const driveInt = data.integrations.find(
        (i) => i.service_type === "google_drive_mcp" && i.is_active
      );
      if (driveInt) setDriveIntegrationId(driveInt.id);
    }).catch(() => {});
  }, []);

  async function toggleTool(toolId: string) {
    const next = enabled.includes(toolId)
      ? enabled.filter((t) => t !== toolId)
      : [...enabled, toolId];
    setEnabled(next);
    setSavingTools(true);
    try {
      const result = await toolsApi.updateAgentTools(agentId, next);
      if (result.warning) {
        toastError(new Error(result.warning), 'Tool Warning');
      }
    } catch {
      setEnabled(enabled);
    } finally {
      setSavingTools(false);
    }
  }

  async function loadDriveFiles() {
    if (!driveIntegrationId) return;
    setDriveLoading(true);
    try {
      const data = await integrationsApi.driveFiles(
        driveIntegrationId,
        driveSearch || undefined,
        20
      );
      setDriveFiles(data.files || []);
      // Cache file names for display
      const nameMap: Record<string, string> = {};
      (data.files || []).forEach((f: DriveFile) => { nameMap[f.id] = f.name; });
      setFileNamesMap(prev => ({ ...prev, ...nameMap }));
    } catch (err) {
      toastError(err, "Failed to load Drive files");
    } finally {
      setDriveLoading(false);
    }
  }

  const toggleFileSelection = useCallback((fileId: string) => {
    setSelectedFileIds((prev) =>
      prev.includes(fileId)
        ? prev.filter((id) => id !== fileId)
        : [...prev, fileId]
    );
  }, []);

  async function openFilePreview(fileId: string) {
    if (!driveIntegrationId) return;
    setPreviewFileId(fileId);
    setPreviewFileName(fileNamesMap[fileId] || fileId);
    setPreviewOpen(true);
    setPreviewLoading(true);
    setPreviewContent('');
    try {
      const result = await integrationsApi.driveFilePreview(driveIntegrationId, fileId);
      setPreviewContent(result.preview);
    } catch (err) {
      toastError(err, 'Failed to load file preview');
      setPreviewContent('Unable to load preview.');
    } finally {
      setPreviewLoading(false);
    }
  }

  function closeFilePreview() {
    setPreviewOpen(false);
    setPreviewFileId(null);
    setPreviewFileName('');
    setPreviewContent('');
  }

  async function saveBindings() {
    setSavingBindings(true);
    try {
      const payload = {
        drive: { file_ids: selectedFileIds, folder_ids: [] },
        calendar: bindings.calendar || { calendar_ids: ["primary"] },
      };
      await toolsApi.updateAgentMcpBindings(agentId, payload);
      setBindings(payload);
      onBindingsChange?.(payload);
      success("Bindings Saved", "Agent resource access updated.");
      setShowFilePicker(false);
    } catch (err) {
      toastError(err, "Failed to save bindings");
    } finally {
      setSavingBindings(false);
    }
  }

  if (!loaded) return null;

  return (
    <div className="mt-6 pt-6 border-t border-[var(--glass-border)] space-y-8">
      {/* ── Connected Extensions CTA ─────────────────────────── */}
      <div className="bg-[var(--bg-tertiary)] border border-[var(--glass-border)] rounded-xl p-6 text-center">
        <Server className="mx-auto text-brand-400 mb-3" size={28} />
        <h3 className="text-base font-semibold mb-2">Connected Extensions</h3>
        <p className="text-sm text-[var(--text-secondary)] mb-5 max-w-md mx-auto">
          Give this agent the ability to interact with external systems using Google Drive, Calendar, and more.
        </p>
        <div className="flex justify-center gap-3 flex-wrap">
          <Link
            href="/dashboard/integrations?type=google_drive_mcp"
            className="bg-[var(--bg-primary)] border border-[var(--glass-border)] hover:border-brand-500 hover:bg-brand-500/10 transition-colors text-sm py-2 px-4 rounded-lg flex items-center gap-2"
          >
            <HardDrive size={16} className="text-brand-400" /> Connect Google Drive
          </Link>
          <Link
            href="/dashboard/integrations?type=google_calendar"
            className="bg-[var(--bg-primary)] border border-[var(--glass-border)] hover:border-brand-500 hover:bg-brand-500/10 transition-colors text-sm py-2 px-4 rounded-lg flex items-center gap-2"
          >
            <Calendar size={16} className="text-blue-400" /> Connect Calendar
          </Link>
        </div>
      </div>

      {/* ── MCP Resource Bindings ───────────────────────────── */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-base font-semibold text-[var(--text-primary)] flex items-center gap-2">
              <ShieldCheck size={16} className="text-brand-400" />
              Bound Resources
            </h3>
            <p className="text-sm text-[var(--text-muted)] mt-1">
              Control exactly which files and calendars this agent can access.
            </p>
          </div>
          {savingBindings && (
            <span className="text-[10px] text-[var(--text-muted)] animate-pulse">
              Saving...
            </span>
          )}
        </div>

        {/* Google Account Status */}
        <div className="flex items-center gap-3 text-sm">
          {googleConnected ? (
            <span className="flex items-center gap-1.5 text-green-400">
              <Check size={14} /> Google account connected
            </span>
          ) : (
            <Link
              href="/dashboard/integrations?type=google_drive_mcp"
              className="text-amber-400 hover:underline flex items-center gap-1.5"
            >
              <Plus size={14} /> Connect Google account to bind files
            </Link>
          )}
        </div>

        {/* Bound Drive Files */}
        <div className="bg-[var(--bg-primary)] border border-[var(--glass-border)] rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-medium flex items-center gap-2">
              <HardDrive size={14} className="text-brand-400" />
              Google Drive Files ({selectedFileIds.length})
            </h4>
            {googleConnected && (
              <button
                onClick={() => {
                  setShowFilePicker(!showFilePicker);
                  if (!showFilePicker) loadDriveFiles();
                }}
                className="text-xs bg-brand-500/10 text-brand-400 px-2.5 py-1.5 rounded-lg hover:bg-brand-500/20 transition-colors flex items-center gap-1"
              >
                {showFilePicker ? <X size={12} /> : <Plus size={12} />}
                {showFilePicker ? "Close" : "Add Files"}
              </button>
            )}
          </div>

          {selectedFileIds.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {selectedFileIds.map((fid) => (
                <span
                  key={fid}
                  className="inline-flex items-center gap-1.5 text-xs bg-[var(--bg-tertiary)] border border-[var(--glass-border)] px-2 py-1 rounded-md max-w-[260px]"
                  title={fid}
                >
                  <FileText size={10} className="text-brand-400 shrink-0" />
                  <button
                    onClick={() => openFilePreview(fid)}
                    className="truncate hover:text-brand-400 transition-colors text-left"
                  >
                    {fileNamesMap[fid] || fid.slice(0, 20) + '...'}
                  </button>
                  <button
                    onClick={() => toggleFileSelection(fid)}
                    className="text-[var(--text-muted)] hover:text-red-400 shrink-0"
                  >
                    <X size={10} />
                  </button>
                </span>
              ))}
            </div>
          ) : (
            <p className="text-xs text-[var(--text-muted)]">
              No files bound yet. The agent can still search all Drive files if the integration is connected.
            </p>
          )}

          {/* File Picker */}
          {showFilePicker && (
            <div className="mt-3 border border-[var(--glass-border)] rounded-lg p-3 bg-[var(--bg-secondary)] animate-in fade-in slide-in-from-top-1">
              <div className="flex gap-2 mb-3">
                <div className="relative flex-1">
                  <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
                  <input
                    type="text"
                    value={driveSearch}
                    onChange={(e) => setDriveSearch(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && loadDriveFiles()}
                    placeholder="Search Drive files..."
                    className="w-full pl-8 pr-3 py-1.5 text-xs bg-[var(--bg-primary)] border border-[var(--glass-border)] rounded-lg"
                  />
                </div>
                <button
                  onClick={loadDriveFiles}
                  disabled={driveLoading}
                  className="text-xs bg-brand-500/10 text-brand-400 px-3 py-1.5 rounded-lg hover:bg-brand-500/20 transition-colors disabled:opacity-50"
                >
                  {driveLoading ? <Loader2 size={12} className="animate-spin" /> : "Search"}
                </button>
              </div>

              <div className="max-h-48 overflow-y-auto space-y-1">
                {driveLoading ? (
                  <div className="flex items-center justify-center py-4">
                    <Loader2 size={16} className="animate-spin text-[var(--text-muted)]" />
                  </div>
                ) : driveFiles.length === 0 ? (
                  <p className="text-xs text-[var(--text-muted)] text-center py-4">
                    {driveSearch ? "No files found. Try a different search." : "Type a search and press Enter to find files."}
                  </p>
                ) : (
                  driveFiles.map((file) => (
                    <button
                      key={file.id}
                      onClick={() => toggleFileSelection(file.id)}
                      className={`w-full flex items-center gap-2 px-2.5 py-2 rounded-md text-left text-xs transition-colors ${
                        selectedFileIds.includes(file.id)
                          ? "bg-brand-500/10 border border-brand-500/20"
                          : "hover:bg-[var(--bg-tertiary)] border border-transparent"
                      }`}
                    >
                      {selectedFileIds.includes(file.id) ? (
                        <Check size={12} className="text-brand-400 shrink-0" />
                      ) : (
                        <FileText size={12} className="text-[var(--text-muted)] shrink-0" />
                      )}
                      <span className="truncate flex-1">{file.name}</span>
                      <span className="text-[10px] text-[var(--text-muted)] shrink-0">
                        {file.id.slice(0, 8)}...
                      </span>
                    </button>
                  ))
                )}
              </div>

              <div className="flex justify-end mt-3 pt-2 border-t border-[var(--glass-border)]">
                <button
                  onClick={saveBindings}
                  disabled={savingBindings}
                  className="text-xs bg-brand-500 text-white px-3 py-1.5 rounded-lg hover:bg-brand-600 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                >
                  {savingBindings ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                  Save Selection
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Bound Calendars */}
        <div className="bg-[var(--bg-primary)] border border-[var(--glass-border)] rounded-xl p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-medium flex items-center gap-2">
              <Calendar size={14} className="text-blue-400" />
              Bound Calendars
            </h4>
          </div>
          <div className="flex flex-wrap gap-2">
            {(bindings.calendar?.calendar_ids || ["primary"]).map((calId) => (
              <span
                key={calId}
                className="inline-flex items-center gap-1.5 text-xs bg-[var(--bg-tertiary)] border border-[var(--glass-border)] px-2 py-1 rounded-md"
              >
                <Calendar size={10} className="text-blue-400" />
                {calId}
              </span>
            ))}
          </div>
          <p className="text-xs text-[var(--text-muted)]">
            The agent will use these calendar IDs when booking appointments.
          </p>
        </div>
      </div>

      {/* ── Active Tools (hidden in builder — toggles are in BuilderPanels) ── */}
      {!isBuilder && (
        <div className="pt-2">
          <div className="flex items-center justify-between mb-3">
            <label className="section-title flex items-center gap-1.5">
              <Wrench size={12} /> Active Tools ({enabled.length})
            </label>
            {savingTools && (
              <span className="text-[10px] text-[var(--text-muted)] animate-pulse">
                Saving...
              </span>
            )}
          </div>

          {/* Warning: enabled tools missing integrations */}
          {(() => {
            const missing = tools.filter(
              (t) => enabled.includes(t.id) && t.integration_required && !t.integration_connected
            );
            if (missing.length === 0) return null;
            const labels = [...new Set(missing.map((t) => t.integration_label).filter(Boolean))];
            return (
              <div className="mb-3 p-3 rounded-lg border border-amber-500/20 bg-amber-500/5 text-amber-200 text-xs">
                <p className="font-medium">
                  {missing.length} enabled tool{missing.length > 1 ? 's' : ''} won't work — missing integration{labels.length > 1 ? 's' : ''}:
                </p>
                <p className="mt-1">
                  {labels.join(', ')}.{' '}
                  <Link href="/dashboard/integrations" className="underline text-amber-300 hover:text-amber-100">
                    Connect in Integrations →
                  </Link>
                </p>
              </div>
            );
          })()}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {tools.map((tool) => {
              const isEnabled = enabled.includes(tool.id);
              const isConnected = tool.integration_connected;
              const isMissing = tool.integration_required && !isConnected;
              return (
                <button
                  key={tool.id}
                  onClick={() => {
                    if (!isMissing || isEnabled) toggleTool(tool.id);
                  }}
                  disabled={isMissing && !isEnabled}
                  className={`text-left p-2.5 rounded-lg border text-xs transition-all duration-150 relative ${
                    isEnabled && !isMissing
                      ? "border-[var(--border-active)] bg-[var(--accent-muted)] shadow-glow-sm"
                      : isMissing
                      ? "border-amber-500/20 bg-amber-500/5 opacity-70 cursor-not-allowed"
                      : "border-[var(--glass-border)] bg-[var(--bg-primary)] hover:border-[var(--border-hover)]"
                  }`}
                >
                  {isMissing && (
                    <span className="absolute top-1.5 right-1.5 text-[9px] font-medium text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded">
                      Needs {tool.integration_label}
                    </span>
                  )}
                  {!isMissing && isConnected && tool.integration_required && (
                    <span className="absolute top-1.5 right-1.5 text-[9px] font-medium text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">
                      Ready
                    </span>
                  )}
                  <p className="font-medium truncate pr-16">{tool.name}</p>
                  <p className="text-[var(--text-muted)] truncate mt-0.5">
                    {tool.description.slice(0, 100)}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* File Preview Modal */}
      {previewOpen && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[var(--bg-primary)]/80 backdrop-blur-sm p-4">
          <div className="bg-[var(--bg-secondary)] rounded-xl w-full max-w-xl max-h-[80vh] flex flex-col shadow-2xl">
            <div className="flex items-center justify-between p-4 border-b border-[var(--glass-border)]">
              <div className="flex items-center gap-2 min-w-0">
                <FileText size={18} className="text-brand-400 shrink-0" />
                <h3 className="font-semibold truncate">{previewFileName}</h3>
              </div>
              <button onClick={closeFilePreview} className="btn-ghost p-1 shrink-0">
                <X size={16} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {previewLoading ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 size={24} className="animate-spin text-[var(--accent)]" />
                </div>
              ) : (
                <div className="space-y-3">
                  <pre className="text-sm text-[var(--text-secondary)] bg-[var(--bg-primary)] p-4 rounded-lg border border-[var(--glass-border)] whitespace-pre-wrap font-mono max-h-[50vh] overflow-y-auto">
                    {previewContent}
                  </pre>
                  {previewContent.length > 0 && (
                    <p className="text-[10px] text-[var(--text-muted)] text-center">
                      Read-only preview · {previewContent.length} chars shown
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
