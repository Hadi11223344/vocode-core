"use client";

import { X, Sparkles, GitBranch, ArrowRight } from "lucide-react";

interface ModeSelectorProps {
  open: boolean;
  onClose: () => void;
  onSelectSinglePrompt: () => void;
  onSelectConversationalFlow: () => void;
}

export function ModeSelector({ open, onClose, onSelectSinglePrompt, onSelectConversationalFlow }: ModeSelectorProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm z-50 flex items-center justify-center animate-fade-in">
      <div className="bg-[var(--bg-secondary)] rounded-2xl border border-[var(--glass-border)] w-full max-w-lg mx-4 shadow-modal animate-scale-in">
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--glass-border)]">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Create Agent</h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Choose how your agent handles conversations
            </p>
          </div>
          <button onClick={onClose} className="btn-ghost p-1.5">
            <X size={18} />
          </button>
        </div>

        <div className="p-6">
          <div className="grid grid-cols-2 gap-4">
            {/* Single Prompt Mode */}
            <button
              onClick={() => {
                onClose();
                onSelectSinglePrompt();
              }}
              className="text-left p-5 rounded-xl border border-[var(--glass-border)] bg-[var(--bg-primary)] hover:border-brand-500/40 hover:bg-[var(--bg-tertiary)] transition-all group"
            >
              <div className="w-10 h-10 rounded-lg bg-brand-500/20 text-brand-400 flex items-center justify-center mb-3 group-hover:scale-110 transition-transform">
                <Sparkles size={20} />
              </div>
              <h3 className="font-semibold text-sm group-hover:text-brand-400 transition-colors">
                Single Prompt
              </h3>
              <p className="text-xs text-[var(--text-muted)] mt-1.5 leading-relaxed">
                One system prompt defines all behavior. Best for FAQs, simple tasks, and natural conversations.
              </p>
              <div className="flex items-center gap-1 mt-3 text-[10px] text-brand-400">
                <span>Quick to set up</span>
                <ArrowRight size={10} />
              </div>
            </button>

            {/* Conversational Flow Mode */}
            <button
              onClick={() => {
                onClose();
                onSelectConversationalFlow();
              }}
              className="text-left p-5 rounded-xl border border-[var(--glass-border)] bg-[var(--bg-primary)] hover:border-purple-500/40 hover:bg-[var(--bg-tertiary)] transition-all group"
            >
              <div className="w-10 h-10 rounded-lg bg-purple-500/20 text-purple-400 flex items-center justify-center mb-3 group-hover:scale-110 transition-transform">
                <GitBranch size={20} />
              </div>
              <h3 className="font-semibold text-sm group-hover:text-purple-400 transition-colors">
                Conversational Flow
              </h3>
              <p className="text-xs text-[var(--text-muted)] mt-1.5 leading-relaxed">
                Visual node editor with branching logic. Best for multi-step processes and deterministic flows.
              </p>
              <div className="flex items-center gap-1 mt-3 text-[10px] text-purple-400">
                <span>Opens workflow editor</span>
                <ArrowRight size={10} />
              </div>
            </button>
          </div>
          <p className="text-[11px] text-[var(--text-muted)] text-center mt-5">
            Both modes support MCP server and custom API tool connections
          </p>
        </div>
      </div>
    </div>
  );
}
