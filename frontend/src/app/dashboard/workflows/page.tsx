"use client";

import { useEffect, useState, useMemo, useRef } from "react";
import { useToast } from "@/components/ui/toast";
import {
  workflows as workflowsApi,
  agents as agentsApi,
} from "@/lib/api";
import { Workflow, Agent } from "@/lib/types";
import { timeAgo, formatTimestamp } from "@/lib/utils";
import Link from "next/link";
import {
  GitBranch,
  Plus,
  Trash2,
  Play,
  CheckCircle,
  XCircle,
  Loader2,
  Zap,
  ChevronDown,
  ChevronUp,
  Eye,
  Search,
  LayoutTemplate,
  ArrowRight,
  Sparkles,
  Calendar,
  MessageSquare,
  Users,
  PhoneCall,
  BarChart3,
} from "lucide-react";
import { cn } from "@/lib/utils";
import GsapPageWrapper from "@/components/three/gsap-page-wrapper";

/* --- Quick-start templates for new users --- */
const QUICK_STARTS = [
  {
    id: "appointment",
    title: "Appointment Booking",
    description: "Let callers schedule appointments with smart availability checking",
    icon: Calendar,
    color: "text-cyan-400 bg-cyan-400/10 border-cyan-400/20",
    steps: ["Call comes in", "Check calendar", "Book appointment", "Send confirmation SMS"],
  },
  {
    id: "support",
    title: "Customer Support",
    description: "Route support calls, create tickets, and escalate when needed",
    icon: MessageSquare,
    color: "text-purple-400 bg-purple-400/10 border-purple-400/20",
    steps: ["Greet caller", "Identify issue", "Search knowledge base", "Create ticket or escalate"],
  },
  {
    id: "lead",
    title: "Lead Qualification",
    description: "Qualify inbound leads and add them to your CRM automatically",
    icon: Users,
    color: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
    steps: ["Collect caller info", "Ask qualifying questions", "Score lead", "Push to CRM"],
  },
  {
    id: "outbound",
    title: "Outbound Follow-up",
    description: "Automated follow-up calls with meeting scheduling",
    icon: PhoneCall,
    color: "text-amber-400 bg-amber-400/10 border-amber-400/20",
    steps: ["Place call", "Deliver message", "Handle objections", "Schedule meeting"],
  },
];

export default function WorkflowsListPage() {
  const [workflowList, setWorkflowList] = useState<Workflow[]>([]);
  const [agentList, setAgentList] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [executing, setExecuting] = useState<number | null>(null);
  const [showInactive, setShowInactive] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [agentFilter, setAgentFilter] = useState<string>("");
  const [sortBy, setSortBy] = useState<"newest" | "name" | "triggers">("newest");
  const [deleteTargetId, setDeleteTargetId] = useState<number | null>(null);
  const deleteTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { success, apiError } = useToast();

  const load = async () => {
    try {
      const [w, a] = await Promise.all([
        workflowsApi.list(showInactive),
        agentsApi.list(),
      ]);
      setWorkflowList(w.workflows);
      setAgentList(a.agents);
    } catch (err) {
      apiError(err, "Failed to load workflows");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    load();
  }, [showInactive]);

  const handleDeleteRequest = (wfId: number) => {
    if (deleteTimerRef.current) clearTimeout(deleteTimerRef.current);
    setDeleteTargetId(wfId);
    // Auto-cancel confirmation after 4s
    deleteTimerRef.current = setTimeout(() => setDeleteTargetId(null), 4000);
  };

  const handleDeleteConfirm = async (wf: Workflow) => {
    setDeleteTargetId(null);
    try {
      await workflowsApi.delete(wf.id);
      await load();
      success("Workflow Deactivated", '"' + wf.name + '" has been deactivated');
    } catch (err) {
      apiError(err, "Failed to deactivate workflow");
    }
  };

  const handleExecute = async (wf: Workflow) => {
    setExecuting(wf.id);
    try {
      const result = await workflowsApi.execute(wf.id, {
        caller_name: "Test User",
        caller_phone: "+10000000000",
        transcript: "Test execution from dashboard",
      });
      success(
        "Workflow Executed",
        '"' + wf.name + '": ' + result.steps_executed + " steps completed"
      );
    } catch (err: unknown) {
      apiError(err, "Workflow execution failed");
    } finally {
      setExecuting(null);
    }
  };

  const handleToggleActive = async (wf: Workflow) => {
    try {
      await workflowsApi.update(wf.id, { is_active: !wf.is_active });
      await load();
    } catch (err) {
      apiError(err, "Failed to toggle workflow status");
    }
  };

  const getAgentName = (agentId: number | null) => {
    if (!agentId) return "Any agent";
    return agentList.find((a) => a.id === agentId)?.name || "Agent #" + agentId;
  };

  /* --- Filtered & sorted list --- */
  const filteredWorkflows = useMemo(() => {
    let list = [...workflowList];

    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (wf) =>
          wf.name.toLowerCase().includes(q) ||
          wf.description?.toLowerCase().includes(q) ||
          wf.trigger_phrases?.some((p) => p.toLowerCase().includes(q))
      );
    }

    if (agentFilter) {
      const aid = parseInt(agentFilter);
      list = list.filter((wf) => (aid === 0 ? !wf.agent_id : wf.agent_id === aid));
    }

    if (sortBy === "name") list.sort((a, b) => a.name.localeCompare(b.name));
    else if (sortBy === "triggers")
      list.sort(
        (a, b) =>
          (b.trigger_phrases?.length || 0) - (a.trigger_phrases?.length || 0)
      );
    // newest is default order from API

    return list;
  }, [workflowList, searchQuery, agentFilter, sortBy]);

  /* --- Stats --- */
  const stats = useMemo(() => {
    const active = workflowList.filter((w) => w.is_active).length;
    const totalTriggers = workflowList.reduce(
      (sum, w) => sum + (w.trigger_phrases?.length || 0),
      0
    );
    const totalSteps = workflowList.reduce(
      (sum, w) => sum + (w.graph?.nodes?.length || w.steps?.length || 0),
      0
    );
    return { total: workflowList.length, active, totalTriggers, totalSteps };
  }, [workflowList]);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="h-7 w-36 shimmer rounded" />
            <div className="h-4 w-64 shimmer rounded mt-2" />
          </div>
          <div className="h-10 w-40 shimmer rounded-lg" />
        </div>
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="dash-skeleton p-4 h-20" />
          ))}
        </div>
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="dash-skeleton p-5 h-20" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <GsapPageWrapper>
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="page-title dash-title-gradient dash-title-glow">Workflows</h1>
          <p className="page-subtitle">
            Design deterministic conversation flows with visual logic
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/dashboard/workflows/new"
            className="flex items-center gap-2 btn-primary"
          >
            <Plus size={16} />
            Create Workflow
          </Link>
        </div>
      </div>

      {/* Stats Bar */}
      {workflowList.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            {
              label: "Total Workflows",
              value: stats.total,
              icon: GitBranch,
              color: "text-brand-400",
            },
            {
              label: "Active",
              value: stats.active,
              icon: CheckCircle,
              color: "text-green-400",
            },
            {
              label: "Trigger Phrases",
              value: stats.totalTriggers,
              icon: Zap,
              color: "text-amber-400",
            },
            {
              label: "Total Steps",
              value: stats.totalSteps,
              icon: BarChart3,
              color: "text-purple-400",
            },
          ].map((stat) => (
            <div
              key={stat.label}
              className="dash-card p-4 flex items-center gap-3"
            >
              <div
                className={cn(
                  "p-2 rounded-lg bg-[var(--bg-tertiary)]",
                  stat.color
                )}
              >
                <stat.icon size={16} />
              </div>
              <div>
                <p className="text-lg font-bold">{stat.value}</p>
                <p className="text-[10px] text-[var(--text-muted)] uppercase tracking-wider">
                  {stat.label}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Search & Filters */}
      {workflowList.length > 0 && (
        <div className="flex flex-wrap gap-3 items-center">
          <div className="flex-1 relative min-w-[200px]">
            <Search
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
            />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search workflows, triggers..."
              className="w-full pl-9 input-base text-sm"
            />
          </div>
          <select
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value)}
            className="input-base text-sm min-w-[140px]"
          >
            <option value="">All Agents</option>
            <option value="0">Unassigned</option>
            {agentList.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          <select
            value={sortBy}
            onChange={(e) =>
              setSortBy(e.target.value as "newest" | "name" | "triggers")
            }
            className="input-base text-sm min-w-[120px]"
          >
            <option value="newest">Newest First</option>
            <option value="name">By Name</option>
            <option value="triggers">Most Triggers</option>
          </select>
          <label className="flex items-center gap-2 text-xs text-[var(--text-muted)] cursor-pointer whitespace-nowrap">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(e) => setShowInactive(e.target.checked)}
              className="rounded"
            />
            Show inactive
          </label>
        </div>
      )}

      {/* Empty State with Quick-Start Cards */}
      {workflowList.length === 0 && (
        <div className="space-y-6">
          <div className="dash-card p-12 text-center">
            <GitBranch
              size={48}
              className="mx-auto mb-4 text-brand-400 opacity-60"
            />
            <h3 className="text-xl font-semibold mb-2">
              Build Your First Workflow
            </h3>
            <p className="text-[var(--text-secondary)] mb-6 max-w-md mx-auto">
              Workflows automate what happens during and after calls &mdash;
              from booking appointments to updating your CRM. Start from a
              template or build from scratch.
            </p>
            <div className="flex items-center justify-center gap-3">
              <Link
                href="/dashboard/workflows/new"
                className="flex items-center gap-2 btn-primary"
              >
                <Plus size={16} />
                Start from Scratch
              </Link>
              <Link
                href="/dashboard/workflows/new"
                className="flex items-center gap-2 px-4 py-2 bg-[var(--bg-tertiary)] border border-[var(--glass-border)] rounded-lg text-sm hover:border-brand-500/40 transition-colors"
              >
                <LayoutTemplate size={16} />
                Browse Templates
              </Link>
            </div>
          </div>

          {/* Quick-start cards */}
          <div>
            <h2 className="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">
              Popular Use Cases
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {QUICK_STARTS.map((qs) => (
                <Link
                  key={qs.id}
                  href="/dashboard/workflows/new"
                  className="dash-card p-5 hover:border-brand-500/40 transition-all group"
                >
                  <div className="flex items-start gap-4">
                    <div
                      className={cn(
                        "p-3 rounded-xl border shrink-0",
                        qs.color
                      )}
                    >
                      <qs.icon size={22} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 className="font-semibold group-hover:text-brand-400 transition-colors">
                          {qs.title}
                        </h3>
                        <ArrowRight
                          size={14}
                          className="text-[var(--text-muted)] group-hover:text-brand-400 group-hover:translate-x-0.5 transition-all"
                        />
                      </div>
                      <p className="text-xs text-[var(--text-muted)] mt-1">
                        {qs.description}
                      </p>
                      <div className="flex items-center gap-1 mt-3">
                        {qs.steps.map((step, i) => (
                          <div key={i} className="flex items-center gap-1">
                            <span className="text-[10px] px-2 py-0.5 rounded-full bg-[var(--bg-tertiary)] text-[var(--text-muted)] whitespace-nowrap">
                              {step}
                            </span>
                            {i < qs.steps.length - 1 && (
                              <ArrowRight
                                size={10}
                                className="text-[var(--text-muted)] shrink-0"
                              />
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </div>

          {/* Getting Started Guide */}
          <div className="dash-card p-6">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles size={16} className="text-brand-400" />
              <h2 className="text-sm font-semibold">How Workflows Work</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {[
                {
                  step: "1",
                  title: "Define Conversation States",
                  desc: "Create nodes for each stage of the conversation — greeting, qualification, booking, confirmation. Each node has its own instructions.",
                },
                {
                  step: "2",
                  title: "Connect Tool Calls",
                  desc: "Attach MCP servers or custom APIs to any node. The agent calls these tools mid-conversation to fetch data or trigger real-world actions.",
                },
                {
                  step: "3",
                  title: "Set Transitions & Test",
                  desc: "Define how the conversation moves between nodes based on caller input. Test-execute to walk through the full flow end-to-end.",
                },
              ].map((item) => (
                <div key={item.step} className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-brand-500/20 text-brand-400 flex items-center justify-center text-sm font-bold shrink-0">
                    {item.step}
                  </div>
                  <div>
                    <p className="text-sm font-medium">{item.title}</p>
                    <p className="text-xs text-[var(--text-muted)] mt-1">
                      {item.desc}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Workflow List */}
      {filteredWorkflows.length > 0 && (
        <div className="space-y-3">
          {filteredWorkflows.map((wf) => (
            <div
              key={wf.id}
              className={cn(
                "bg-[var(--bg-card)] rounded-xl border overflow-hidden transition-colors",
                wf.is_active
                  ? "border-[var(--glass-border)]"
                  : "border-red-500/20 opacity-60"
              )}
            >
              <div className="flex items-center gap-4 p-5">
                <div
                  className={cn(
                    "w-10 h-10 rounded-lg flex items-center justify-center shrink-0",
                    wf.is_active
                      ? "bg-brand-600/20 text-brand-400"
                      : "bg-red-500/20 text-red-400"
                  )}
                >
                  <GitBranch size={20} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold truncate">{wf.name}</h3>
                    {wf.requires_approval && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400">
                        needs approval
                      </span>
                    )}
                    {!wf.is_active && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-red-500/20 text-red-400">
                        inactive
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 mt-1 text-xs text-[var(--text-muted)]">
                    <span className="flex items-center gap-1">
                      <Zap size={12} />
                      {wf.trigger_phrases?.length || 0} triggers
                    </span>
                    <span>{wf.graph?.nodes?.length || wf.steps?.length || 0} steps</span>
                    <span>Agent: {getAgentName(wf.agent_id)}</span>
                    <span className="hidden md:inline">
                      {timeAgo(wf.created_at)}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() =>
                      setExpandedId(expandedId === wf.id ? null : wf.id)
                    }
                    className="btn-ghost p-1.5 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                    title="Details"
                    aria-label={expandedId === wf.id ? 'Collapse workflow details' : 'Expand workflow details'}
                  >
                    {expandedId === wf.id ? (
                      <ChevronUp size={16} />
                    ) : (
                      <ChevronDown size={16} />
                    )}
                  </button>
                  <Link
                    href={"/dashboard/workflows/" + wf.id}
                    className="p-2 text-[var(--text-muted)] hover:text-brand-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                    title="Edit in visual editor"
                    aria-label="Edit workflow in visual editor"
                  >
                    <Eye size={16} />
                  </Link>
                  <button
                    onClick={() => handleExecute(wf)}
                    disabled={executing === wf.id || !wf.is_active}
                    className="p-2 text-[var(--text-muted)] hover:text-green-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors disabled:opacity-30"
                    title="Test execute"
                    aria-label="Test execute workflow"
                  >
                    {executing === wf.id ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <Play size={16} />
                    )}
                  </button>
                  <button
                    onClick={() => handleToggleActive(wf)}
                    className={cn(
                      "p-2 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors",
                      wf.is_active
                        ? "text-green-400 hover:text-red-400"
                        : "text-red-400 hover:text-green-400"
                    )}
                    title={wf.is_active ? "Deactivate" : "Activate"}
                    aria-label={wf.is_active ? 'Deactivate workflow' : 'Activate workflow'}
                  >
                    {wf.is_active ? (
                      <CheckCircle size={16} />
                    ) : (
                      <XCircle size={16} />
                    )}
                  </button>
                  {deleteTargetId === wf.id ? (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => handleDeleteConfirm(wf)}
                        className="text-[10px] px-2 py-1 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors font-medium"
                      >
                        Confirm
                      </button>
                      <button
                        onClick={() => setDeleteTargetId(null)}
                        className="text-[10px] px-2 py-1 rounded bg-[var(--bg-tertiary)] text-[var(--text-muted)] hover:text-white transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => handleDeleteRequest(wf.id)}
                      className="p-2 text-[var(--text-muted)] hover:text-red-400 rounded-lg hover:bg-[var(--bg-tertiary)] transition-colors"
                      title="Deactivate"
                      aria-label="Deactivate workflow"
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              </div>

              {/* Expanded Details */}
              {expandedId === wf.id && (
                <div className="px-5 pb-5 border-t border-[var(--glass-border)]">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4">
                    {wf.description && (
                      <div className="md:col-span-2">
                        <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                          Description
                        </label>
                        <p className="text-sm text-[var(--text-secondary)] mt-1">
                          {wf.description}
                        </p>
                      </div>
                    )}
                    <div>
                      <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                        Trigger Phrases
                      </label>
                      <div className="flex flex-wrap gap-1.5 mt-2">
                        {wf.trigger_phrases?.map((phrase, i) => (
                          <span
                            key={i}
                            className="text-xs px-2 py-1 rounded-full bg-brand-600/20 text-brand-400"
                          >
                            &quot;{phrase}&quot;
                          </span>
                        ))}
                        {(!wf.trigger_phrases ||
                          wf.trigger_phrases.length === 0) && (
                          <span className="text-xs text-[var(--text-muted)]">
                            No triggers configured
                          </span>
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                        Steps
                      </label>
                      <div className="mt-2 space-y-2">
                        {wf.graph?.nodes && wf.graph.nodes.length > 0 ? (
                          wf.graph.nodes
                            .filter(n => n.data?.nodeType !== 'trigger' && n.data?.nodeType !== 'end')
                            .map((node, i) => (
                            <div
                              key={i}
                              className="flex items-center gap-2 text-sm"
                            >
                              <span className="w-5 h-5 rounded-full bg-[var(--bg-tertiary)] flex items-center justify-center text-xs text-[var(--text-muted)]">
                                {i + 1}
                              </span>
                              <span className="text-[var(--text-secondary)]">
                                {(node.data?.label as string) || node.type || `Node ${i + 1}`}
                              </span>
                            </div>
                          ))
                        ) : wf.steps && wf.steps.length > 0 ? (
                          wf.steps.map((step, i) => (
                            <div
                              key={i}
                              className="flex items-center gap-2 text-sm"
                            >
                              <span className="w-5 h-5 rounded-full bg-[var(--bg-tertiary)] flex items-center justify-center text-xs text-[var(--text-muted)]">
                                {step.step_number}
                              </span>
                              <span className="text-[var(--text-secondary)]">
                                {step.action}
                              </span>
                              {step.integration_id > 0 && (
                                <span className="text-xs text-[var(--text-muted)]">
                                  (integration #{step.integration_id})
                                </span>
                              )}
                            </div>
                          ))
                        ) : (
                          <p className="text-sm text-[var(--text-muted)]">
                            No steps configured
                          </p>
                        )}
                      </div>
                    </div>
                    <div>
                      <label className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">
                        Created
                      </label>
                      <p className="text-sm text-[var(--text-secondary)] mt-1">
                        {formatTimestamp(wf.created_at)}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <Link
                        href={"/dashboard/workflows/" + wf.id}
                        className="flex items-center gap-1.5 text-xs text-brand-400 hover:underline"
                      >
                        <Eye size={12} /> Open in Visual Editor
                      </Link>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}

        </div>
      )}

      {/* Existing workflows but no filter matches */}
      {workflowList.length > 0 &&
        filteredWorkflows.length === 0 &&
        (searchQuery || agentFilter) && (
          <div className="text-center py-12 dash-card">
            <Search
              size={32}
              className="mx-auto text-[var(--text-muted)] mb-3 opacity-40"
            />
            <p className="text-sm text-[var(--text-muted)]">
              No workflows match your filters
            </p>
            <button
              onClick={() => {
                setSearchQuery("");
                setAgentFilter("");
              }}
              className="mt-2 text-xs text-brand-400 hover:underline"
            >
              Clear filters
            </button>
          </div>
        )}
    </div>
    </GsapPageWrapper>
  );
}
