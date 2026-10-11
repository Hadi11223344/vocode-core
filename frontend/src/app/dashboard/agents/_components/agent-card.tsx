"use client";

import Link from "next/link";
import {
  Bot,
  ChevronDown,
  ChevronUp,
  Zap,
  Pencil,
  Trash2,
} from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { Agent } from "@/lib/types";
import { ToolsSection } from "./tools-section";

interface AgentCardProps {
  agent: Agent;
  expanded: boolean;
  onToggleExpand: () => void;
  onEdit: (agent: Agent) => void;
  onDelete: (agent: Agent) => void;
  providerBadgeColor: Record<string, string>;
}

export function AgentCard({
  agent,
  expanded,
  onToggleExpand,
  onEdit,
  onDelete,
  providerBadgeColor,
}: AgentCardProps) {
  return (
    <div className="dash-card overflow-hidden">
      <div className="flex items-center gap-4 p-5">
        <div className="w-10 h-10 rounded-lg bg-brand-600/20 flex items-center justify-center text-brand-400 shrink-0">
          <Bot size={20} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Link
              href={`/dashboard/agents/${agent.id}`}
              className="font-semibold truncate hover:text-brand-400 transition-colors"
            >
              {agent.name}
            </Link>
            {!agent.is_active && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-red-500/20 text-red-400">
                inactive
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 mt-1">
            <span
              className={cn(
                "text-xs px-2 py-0.5 rounded-full font-medium",
                providerBadgeColor[agent.llm_provider] ||
                  "bg-gray-500/20 text-gray-400"
              )}
            >
              {agent.llm_provider}
            </span>
            <span
              className={cn(
                "text-xs px-2 py-0.5 rounded-full font-medium",
                agent.mode === "conversational_flow"
                  ? "bg-purple-500/20 text-purple-400"
                  : "bg-brand-500/20 text-brand-400"
              )}
            >
              {agent.mode === "conversational_flow" ? "Flow" : "Prompt"}
            </span>
            <span className="text-xs text-[var(--text-muted)]">
              {agent.llm_model}
            </span>
            <span className="text-xs text-[var(--text-muted)] hidden md:inline">
              STT: {agent.stt_provider} &bull; TTS: {agent.tts_provider}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-[var(--text-muted)] hidden md:block">
            {timeAgo(agent.updated_at)}
          </span>
          <button
            onClick={onToggleExpand}
            className="p-2 text-[var(--text-muted)] hover:text-white rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
          <Link
            href={`/dashboard/playground?agent=${agent.id}`}
            className="p-2 text-[var(--text-muted)] hover:text-green-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
            title="Try agent in Playground"
          >
            <Zap size={16} />
          </Link>
          <button
            onClick={() => onEdit(agent)}
            className="p-2 text-[var(--text-muted)] hover:text-blue-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            <Pencil size={16} />
          </button>
          <button
            onClick={() => onDelete(agent)}
            className="p-2 text-[var(--text-muted)] hover:text-red-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
          >
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="px-5 pb-5 border-t border-[var(--glass-border)]">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4">
            <div>
              <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                System Prompt
              </label>
              <p className="text-sm text-[var(--text-secondary)] mt-1 whitespace-pre-wrap line-clamp-4">
                {agent.prompt_preamble}
              </p>
            </div>
            <div>
              <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                Initial Message
              </label>
              <p className="text-sm text-[var(--text-secondary)] mt-1">
                {agent.initial_message}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "Temperature", value: agent.temperature },
                { label: "Max Tokens", value: agent.max_tokens },
                { label: "Idle Timeout", value: `${agent.allowed_idle_time_seconds}s` },
                { label: "Interruption", value: agent.interrupt_sensitivity },
              ].map((item) => (
                <div key={item.label}>
                  <label className="text-xs font-medium text-[var(--text-muted)]">
                    {item.label}
                  </label>
                  <p className="text-sm mt-0.5">{item.value}</p>
                </div>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "Endpointing", value: agent.endpointing_type },
                { label: "Filler Audio", value: agent.filler_audio_enabled ? "On" : "Off" },
                { label: "Language", value: agent.stt_language },
                { label: "STT Model", value: agent.stt_model },
              ].map((item) => (
                <div key={item.label}>
                  <label className="text-xs font-medium text-[var(--text-muted)]">
                    {item.label}
                  </label>
                  <p className="text-sm mt-0.5">{item.value}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Tools Section */}
          <ToolsSection agentId={agent.id} />
        </div>
      )}
    </div>
  );
}
