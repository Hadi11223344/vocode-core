'use client';

import { useCallback, useState } from 'react';
import { Upload, FileText, X, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useToast } from '@/components/ui/toast';
import { useModalFocusTrap } from '@/hooks/use-modal-focus-trap';

interface UploadDialogProps {
  kbId: number;
  kbName: string;
  onUpload: (file: File) => Promise<void>;
  onClose: () => void;
}

const ALLOWED_EXTENSIONS = ['.md', '.txt', '.pdf', '.docx', '.csv', '.json'];
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

function validateFile(file: File): string | null {
  const ext = file.name.toLowerCase().match(/\.[^.]+$/)?.[0] || '';
  if (!ALLOWED_EXTENSIONS.includes(ext)) {
    return `Unsupported file type. Allowed: ${ALLOWED_EXTENSIONS.join(', ')}`;
  }
  if (file.size > MAX_FILE_SIZE) {
    return `File is too large (${(file.size / 1024 / 1024).toFixed(1)}MB). Maximum size is 10MB.`;
  }
  return null;
}

export function UploadDialog({ kbId, kbName, onUpload, onClose }: UploadDialogProps) {
  const { error: toastError } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const dialogRef = useModalFocusTrap(true, onClose);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const dropped = e.dataTransfer.files[0];
      if (!dropped) return;
      const validationError = validateFile(dropped);
      if (validationError) {
        toastError(validationError);
        return;
      }
      setFile(dropped);
    },
    []
  );

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (!selected) return;
    const validationError = validateFile(selected);
    if (validationError) {
      toastError(validationError);
      return;
    }
    setFile(selected);
  };

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    try {
      await onUpload(file);
      onClose();
    } catch {
      toastError('Upload failed. Please try again.');
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="upload-dialog-title"
        tabIndex={-1}
        className="bg-[var(--bg-secondary)] rounded-xl p-6 w-full max-w-md shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 id="upload-dialog-title" className="font-semibold">Upload Document</h3>
            <p className="text-xs text-[var(--text-muted)]">{kbName}</p>
          </div>
          <button onClick={onClose} className="btn-ghost p-1">
            <X size={16} />
          </button>
        </div>

        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={cn(
            'border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer',
            dragOver
              ? 'border-[var(--accent)] bg-[var(--accent)]/5'
              : 'border-[var(--border-color)] hover:border-[var(--border-hover)]'
          )}
        >
          <input
            type="file"
            accept=".md,.txt,.pdf,.docx,.csv,.json"
            onChange={handleFileSelect}
            className="hidden"
            id="kb-file-input"
          />
          <label htmlFor="kb-file-input" className="cursor-pointer block">
            {file ? (
              <>
                <FileText size={32} className="mx-auto mb-3 text-[var(--accent)]" />
                <p className="text-sm font-medium text-[var(--text-secondary)]">{file.name}</p>
                <p className="text-xs text-[var(--text-muted)] mt-1">
                  {(file.size / 1024).toFixed(1)} KB
                </p>
              </>
            ) : (
              <>
                <Upload size={32} className="mx-auto mb-3 text-[var(--text-muted)]" />
                <p className="text-sm text-[var(--text-secondary)]">
                  Drop a file here, or click to browse
                </p>
                <p className="text-xs text-[var(--text-muted)] mt-2">
                  Allowed: .md, .txt, .pdf, .docx, .csv, .json &middot; Max: 10MB
                </p>
              </>
            )}
          </label>
        </div>

        <div className="flex gap-3 mt-4">
          <button onClick={onClose} className="btn-ghost flex-1">
            Cancel
          </button>
          <button
            onClick={handleUpload}
            disabled={!file || uploading}
            className="btn-primary flex-1 disabled:opacity-40"
          >
            {uploading ? (
              <>
                <Loader2 size={14} className="animate-spin" /> Uploading...
              </>
            ) : (
              'Upload'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
