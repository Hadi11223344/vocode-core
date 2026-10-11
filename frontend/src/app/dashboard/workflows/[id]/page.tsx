'use client';

import { useCallback, useEffect, useMemo, useRef, useState, Suspense } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import dynamic from 'next/dynamic';
import { addEdge, useNodesState, useEdgesState, Connection, Edge, Node, ReactFlowProvider } from 'reactflow';
import { nodeTypes, NODE_TYPES_CONFIG, NODE_CATEGORIES, NodeType } from '@/components/workflow/WorkflowNodes';
import NodeConfigPanel from '@/components/workflow/NodeConfigPanel';

// FE-05: Lazy-load the heavy ReactFlow canvas to reduce initial bundle
const WorkflowCanvas = dynamic(() => import('@/components/workflow/WorkflowCanvas'), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full">
      <Loader2 size={32} className="animate-spin text-brand-400" />
    </div>
  ),
});
import { workflows as workflowsApi, integrations as integrationsApi, agents as agentsApi } from '@/lib/api';
import { useToast } from '@/components/ui/toast';
import { useKeyboardShortcuts } from '@/hooks/use-keyboard-shortcuts';
import { useFlowHistory } from '@/hooks/use-flow-history';
import { Workflow, WorkflowStep, Integration, Agent } from '@/lib/types';
import { validateWorkflow } from '@/lib/workflowValidation';
import {
  Save,
  ArrowLeft,
  Play,
  Plus,
  Loader2,
  X,
  LayoutTemplate,
  Search,
  Keyboard,
  Undo2,
  Redo2,
  AlertCircle,
  Wrench,
  ArrowRight,
} from 'lucide-react';

function normalizeBranchEdges(nodes: Node[], edges: Edge[]): Edge[] {
  const nodeById = new Map(nodes.map(node => [node.id, node]));
  return edges.map(edge => {
    const sourceNode = nodeById.get(edge.source);
    if (sourceNode?.data?.nodeType !== 'condition') return edge;

    const label = String(edge.label || '').trim().toLowerCase();
    const branch = edge.sourceHandle || (
      label === 'yes' || label === 'true'
        ? 'yes'
        : label === 'no' || label === 'false'
          ? 'no'
          : undefined
    );
    if (branch !== 'yes' && branch !== 'no') return edge;
    return { ...edge, sourceHandle: branch, label: branch === 'yes' ? 'Yes' : 'No' };
  });
}

/* ─── Convert workflow steps → ReactFlow nodes/edges ───── */
function workflowToFlow(workflow: Workflow | null): { nodes: Node[]; edges: Edge[] } {
  if (!workflow) return { nodes: [], edges: [] };

  // If we have stored graph state, use it for lossless round-trip
  if (workflow.graph && workflow.graph.nodes && workflow.graph.nodes.length > 0) {
    const nodes = workflow.graph.nodes.map(n => ({
      ...n,
      type: n.type || 'workflowNode',
    })) as Node[];
    const edges = (workflow.graph.edges || []).map(e => ({
      ...e,
      animated: e.animated !== false,
      style: (e.style as Record<string, unknown>) || { stroke: '#6366f1', strokeWidth: 2 },
    })) as Edge[];
    return {
      nodes,
      edges: normalizeBranchEdges(nodes, edges),
    };
  }

  // Fallback: reconstruct from flat steps (legacy workflows without graph data)

  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Trigger node
  nodes.push({
    id: 'trigger',
    type: 'workflowNode',
    position: { x: 250, y: 50 },
    data: {
      nodeType: 'trigger',
      label: workflow.name || 'Call Trigger',
      description: workflow.description || 'Triggers when call matches phrases',
      triggerPhrases: (workflow.trigger_phrases || []).join('\n'),
      isConfigured: (workflow.trigger_phrases?.length || 0) > 0,
    },
  });

  // Step nodes
  if (workflow.steps && workflow.steps.length > 0) {
    workflow.steps.forEach((step, i) => {
      const nodeId = `step-${i}`;
      const nodeType = guessNodeType(step);
      nodes.push({
        id: nodeId,
        type: 'workflowNode',
        position: { x: 250, y: 200 + i * 160 },
        data: {
          nodeType,
          label: step.action || `Step ${step.step_number}`,
          action: step.action,
          integrationId: String(step.integration_id),
          params: step.params || {},
          stepNumber: step.step_number,
          isConfigured: !!step.action,
        },
      });

      // Edge from previous
      const sourceId = i === 0 ? 'trigger' : `step-${i - 1}`;
      edges.push({
        id: `e-${sourceId}-${nodeId}`,
        source: sourceId,
        target: nodeId,
        animated: true,
        style: { stroke: '#6366f1', strokeWidth: 2 },
      });
    });
  }

  // If there's an action_url (webhook), add a webhook node
  if (workflow.action_url && (!workflow.steps || workflow.steps.length === 0)) {
    nodes.push({
      id: 'webhook-0',
      type: 'workflowNode',
      position: { x: 250, y: 200 },
      data: {
        nodeType: 'webhook',
        label: 'External Webhook',
        config: { url: workflow.action_url },
        action: workflow.action_type || 'webhook',
        isConfigured: true,
      },
    });
    edges.push({
      id: 'e-trigger-webhook',
      source: 'trigger',
      target: 'webhook-0',
      animated: true,
      style: { stroke: '#6366f1', strokeWidth: 2 },
    });
  }

  // End node
  const lastNodeId = nodes[nodes.length - 1]?.id || 'trigger';
  const endY = nodes[nodes.length - 1] ? (nodes[nodes.length - 1].position.y + 160) : 200;
  nodes.push({
    id: 'end',
    type: 'workflowNode',
    position: { x: 250, y: endY },
    data: { nodeType: 'end', label: 'Workflow Complete', isConfigured: true },
  });
  edges.push({
    id: `e-${lastNodeId}-end`,
    source: lastNodeId,
    target: 'end',
    animated: true,
    style: { stroke: '#6366f1', strokeWidth: 2 },
  });

  return { nodes, edges };
}

function guessNodeType(step: WorkflowStep): NodeType {
  if (step.action?.includes('calendar') || step.action?.includes('event')) return 'google_calendar';
  if (step.action?.includes('sheet') || step.action?.includes('row')) return 'google_sheets';
  if (step.action?.includes('webhook') || step.action?.includes('http')) return 'webhook';
  if (step.action?.includes('sms')) return 'send_sms';
  if (step.action?.includes('email')) return 'send_email';
  if (step.action?.includes('transfer')) return 'transfer_call';
  if (step.action?.includes('knowledge') || step.action?.includes('retrieve')) return 'knowledge_base';
  if (step.action?.includes('condition')) return 'condition';
  if (step.action?.includes('conversation')) return 'conversation';
  if (step.action?.includes('end_call') || step.action?.includes('hangup')) return 'end_call';
  if (step.action?.includes('voicemail')) return 'voicemail_detect';
  if (step.action?.includes('llm') || step.action?.includes('ai_process')) return 'llm_process';
  if (step.action?.includes('delay') || step.action?.includes('wait')) return 'delay';
  if (step.action?.includes('notification') || step.action?.includes('notify')) return 'notification';
  if (step.action?.includes('api') || step.action?.includes('request')) return 'api_request';
  if (step.action?.includes('cal_com') || step.action?.includes('booking')) return 'cal_com';
  // Integration-specific guesses
  if (step.action?.includes('calendly')) return 'calendly';
  if (step.action?.includes('salesforce') || step.action?.includes('sfdc')) return 'salesforce';
  if (step.action?.includes('pipedrive')) return 'pipedrive';
  if (step.action?.includes('gohighlevel') || step.action?.includes('ghl')) return 'gohighlevel';
  if (step.action?.includes('zendesk')) return 'zendesk';
  if (step.action?.includes('intercom')) return 'intercom';
  if (step.action?.includes('freshdesk')) return 'freshdesk';
  if (step.action?.includes('stripe') || step.action?.includes('payment')) return 'stripe';
  if (step.action?.includes('shopify') || step.action?.includes('order')) return 'shopify';
  if (step.action?.includes('whatsapp')) return 'whatsapp_cloud';
  if (step.action?.includes('discord')) return 'discord';
  if (step.action?.includes('teams')) return 'microsoft_teams';
  if (step.action?.includes('notion')) return 'notion';
  if (step.action?.includes('airtable')) return 'airtable';
  if (step.action?.includes('make') || step.action?.includes('integromat')) return 'make';
  if (step.action?.includes('jira')) return 'jira';
  if (step.action?.includes('linear')) return 'linear';
  if (step.action?.includes('mcp') || step.action?.includes('drive') || step.action?.includes('search_files') || step.action?.includes('read_file_content')) return 'mcp_tool';
  return 'action';
}

/* ─── Convert ReactFlow nodes → workflow steps ──────────── */
function flowToWorkflow(
  nodes: Node[],
  edges: Edge[],
  workflowName: string,
  workflowDescription: string,
  agentId: number | null,
  requiresApproval: boolean,
  transitionFlexibility: 'strict' | 'flex',
): { name: string; description: string; trigger_phrases: string[]; agent_id: number | null; steps: WorkflowStep[]; action_url?: string; action_type?: string; requires_approval: boolean; transition_flexibility: 'strict' | 'flex'; graph: { nodes: Array<{ id: string; type?: string; position: { x: number; y: number }; data: Record<string, unknown> }>; edges: Array<{ id: string; source: string; target: string; sourceHandle?: string; targetHandle?: string; label?: string; animated?: boolean; style?: Record<string, unknown> }> } } {
  const triggerNode = nodes.find(n => n.data.nodeType === 'trigger');
  const trigger_phrases = ((triggerNode?.data.triggerPhrases as string) || '')
    .split('\n')
    .map((s: string) => s.trim())
    .filter(Boolean);

  // Build ordered step nodes via edges
  const stepNodes = nodes.filter(n => n.data.nodeType !== 'trigger' && n.data.nodeType !== 'end');

  // Stable topological sort: respect graph edges while using canvas position as a tie-breaker.
  const ordered: Node[] = [];
  const inDegree = new Map<string, number>();
  const outgoing = new Map<string, Edge[]>();
  const stepNodeIds = new Set(stepNodes.map(n => n.id));

  stepNodes.forEach(n => {
    inDegree.set(n.id, 0);
    outgoing.set(n.id, []);
  });

  edges.forEach(e => {
    if (e.target === 'end' || !stepNodeIds.has(e.target)) return;
    if (e.source !== 'trigger' && !stepNodeIds.has(e.source)) return;
    outgoing.get(e.source)?.push(e);
    inDegree.set(e.target, (inDegree.get(e.target) || 0) + 1);
  });

  const nodeSortKey = (n: Node) => [n.position.y, n.position.x, n.id] as const;
  const sortNodes = (a: Node, b: Node) => {
    const [ay, ax, aid] = nodeSortKey(a);
    const [by, bx, bid] = nodeSortKey(b);
    if (ay !== by) return ay - by;
    if (ax !== bx) return ax - bx;
    return String(aid).localeCompare(String(bid));
  };

  let queue = stepNodes.filter(n => (inDegree.get(n.id) || 0) === 0).sort(sortNodes);
  while (queue.length > 0) {
    const node = queue.shift()!;
    ordered.push(node);
    (outgoing.get(node.id) || []).forEach(edge => {
      const target = stepNodes.find(n => n.id === edge.target);
      if (!target) return;
      const newDegree = (inDegree.get(target.id) || 0) - 1;
      inDegree.set(target.id, newDegree);
      if (newDegree === 0) {
        queue.push(target);
        queue.sort(sortNodes);
      }
    });
  }

  // Add any remaining unlinked step nodes (e.g., disconnected nodes)
  stepNodes.forEach(n => {
    if (!ordered.find(o => o.id === n.id)) ordered.push(n);
  });

  const steps: WorkflowStep[] = ordered.map((node, i) => {
    const cfg = (node.data.config as Record<string, unknown>) || {};
    const nodeParams = (node.data.params as Record<string, unknown>) || {};
    const configParams = (cfg.params as Record<string, unknown>) || {};
    return {
      step_number: i + 1,
      integration_id: parseInt((node.data.integrationId as string) || '0') || 0,
      action: (node.data.action as string) || (cfg.action as string) || '',
      params: Object.keys(nodeParams).length > 0 ? nodeParams : configParams,
      config: cfg,
      nodeType: (node.data.nodeType as string) || '',
    };
  });

  // Check for webhook legacy
  const webhookNode = nodes.find(n => n.data.nodeType === 'webhook');
  const webhookConfig = (webhookNode?.data.config as Record<string, unknown>) || {};
  const action_url = (webhookConfig.url as string) || undefined;
  const action_type = webhookNode ? 'action_external' : undefined;

  // Terminal nodes should never have outgoing edges; strip any that somehow exist.
  const terminalIds = new Set(
    nodes.filter(n => n.data.nodeType === 'end' || n.data.nodeType === 'end_call').map(n => n.id)
  );
  const persistEdges = edges.filter(e => !terminalIds.has(e.source));

  // Preserve full graph state for lossless round-trip
  const graph = {
    nodes: nodes.map(n => ({
      id: n.id,
      type: n.type,
      position: n.position,
      data: n.data as Record<string, unknown>,
    })),
    edges: persistEdges.map(e => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle || undefined,
      targetHandle: e.targetHandle || undefined,
      label: (e.label as string) || undefined,
      animated: e.animated,
      style: (e.style as Record<string, unknown>) || undefined,
    })),
  };

  return {
    name: workflowName || triggerNode?.data.label || 'Untitled Workflow',
    description: workflowDescription,
    trigger_phrases,
    agent_id: agentId,
    steps: steps.length > 0 ? steps : [],
    action_url,
    action_type,
    requires_approval: requiresApproval,
    transition_flexibility: transitionFlexibility,
    graph,
  };
}

/* ─── Sanitize graph — ensure structural integrity ─────── */

interface ValidationIssues {
  nodeErrors: string[];
  graphErrors: string[];
  graphWarnings: string[];
  brokenNodeIds: Set<string>;
  brokenEdgeIds: Set<string>;
}

function sanitizeGraph(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[]; repaired: boolean } {
  let repaired = false;
  let cleanNodes = [...nodes];

  // Ensure an end node exists
  const hasEnd = cleanNodes.some(n => n.data.nodeType === 'end' || n.data.nodeType === 'end_call');
  if (!hasEnd) {
    const lastNode = cleanNodes[cleanNodes.length - 1];
    const endY = lastNode ? lastNode.position.y + 160 : 200;
    cleanNodes.push({
      id: 'end',
      type: 'workflowNode',
      position: { x: 250, y: endY },
      data: { nodeType: 'end', label: 'Workflow Complete', isConfigured: true },
    });
    repaired = true;
  }

  // Identify terminal nodes (end / end_call) — these should never have outgoing edges.
  const terminalIds = new Set(
    cleanNodes
      .filter(n => n.data.nodeType === 'end' || n.data.nodeType === 'end_call')
      .map(n => n.id)
  );

  // Filter out edges that reference non-existent nodes or leave terminal nodes
  const validIds = new Set(cleanNodes.map(n => n.id));
  const cleanEdges = edges.filter(e => {
    if (!validIds.has(e.source) || !validIds.has(e.target)) {
      repaired = true;
      return false;
    }
    if (e.source === e.target) {
      repaired = true;
      return false;
    }
    if (terminalIds.has(e.source)) {
      repaired = true;
      return false;
    }
    return true;
  });

  return { nodes: cleanNodes, edges: normalizeBranchEdges(cleanNodes, cleanEdges), repaired };
}

/* ─── Node Palette (categorized) ────────────────────────── */
function NodePalette({ onAdd }: { onAdd: (type: NodeType) => void }) {
  const [open, setOpen] = useState(false);

  // Group addable node types by category
  const addableTypes: NodeType[] = [
    'conversation', 'condition', 'end_call',
    'transfer_call', 'voicemail_detect',
    'send_sms', 'send_email', 'notification',
    'whatsapp_cloud', 'discord', 'microsoft_teams',
    'mcp_tool', 'custom_api',
    'api_request', 'webhook', 'knowledge_base',
    'llm_process', 'subagent', 'extract_variable',
    'google_calendar', 'google_sheets', 'cal_com', 'calendly',
    'salesforce', 'pipedrive', 'gohighlevel',
    'zendesk', 'intercom', 'freshdesk',
    'stripe', 'shopify',
    'notion', 'airtable', 'make', 'jira', 'linear',
    'action',
    'note',
    'delay',
  ];

  const grouped = Object.entries(NODE_CATEGORIES).map(([catKey, catMeta]) => ({
    key: catKey,
    ...catMeta,
    types: addableTypes.filter(t => NODE_TYPES_CONFIG[t]?.category === catKey),
  })).filter(g => g.types.length > 0);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-2 bg-[var(--bg-card)] border border-[var(--glass-border)] rounded-lg text-sm hover:border-brand-500 transition-colors"
      >
        <Plus size={14} />
        Add Node
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute top-full right-0 mt-2 w-72 bg-[var(--bg-secondary)] border border-[var(--glass-border)] rounded-xl shadow-2xl z-20 overflow-hidden max-h-[70vh] overflow-y-auto">
            {grouped.map((group) => (
              <div key={group.key}>
                <div className="px-4 py-2 bg-[var(--bg-tertiary)] border-b border-[var(--glass-border)]">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">{group.label}</p>
                </div>
                {group.types.map(type => {
                  const cfg = NODE_TYPES_CONFIG[type];
                  const Icon = cfg.icon;
                  return (
                    <button
                      key={type}
                      onClick={() => { onAdd(type); setOpen(false); }}
                      className="flex items-center gap-3 w-full px-4 py-2.5 hover:bg-[var(--bg-tertiary)] transition-colors text-left"
                    >
                      <div className={`p-1.5 rounded ${cfg.headerColor}`}>
                        <Icon size={12} />
                      </div>
                      <div>
                        <p className="text-sm font-medium">{cfg.label}</p>
                        <p className="text-[10px] text-[var(--text-muted)]">{cfg.description}</p>
                      </div>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* ─── Template Picker ───────────────────────────────────── */
interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  trigger_phrases: string[];
  nodes: Array<{
    id: string;
    type: string;
    position: { x: number; y: number };
    data: { label: string; config?: Record<string, unknown> };
  }>;
  edges: Array<{
    source: string;
    target: string;
    sourceHandle?: string;
    label?: string;
  }>;
}

function useModalFocusTrap(active: boolean) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!active) {
      return;
    }

    const container = containerRef.current;
    if (!container) {
      return;
    }

    const focusableSelector =
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
    const getFocusableElements = () =>
      Array.from(container.querySelectorAll<HTMLElement>(focusableSelector)).filter(
        (element) => !element.hasAttribute('disabled'),
      );

    const previousActiveElement = document.activeElement as HTMLElement | null;
    const initialFocus = getFocusableElements()[0] || container;
    initialFocus.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') {
        return;
      }

      const focusableElements = getFocusableElements();
      if (focusableElements.length === 0) {
        event.preventDefault();
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement as HTMLElement | null;

      if (event.shiftKey && activeElement === firstElement) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previousActiveElement?.focus();
    };
  }, [active]);

  return containerRef;
}

function TemplatePicker({ onSelect, onClose }: { onSelect: (template: WorkflowTemplate) => void; onClose: () => void }) {
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const dialogRef = useModalFocusTrap(true);

  useEffect(() => {
    const loadTemplates = async () => {
      try {
        const res = await workflowsApi.templates();
        setTemplates((res.templates || []) as unknown as WorkflowTemplate[]);
      } catch {
        // Templates are optional
      } finally {
        setLoading(false);
      }
    };
    loadTemplates();
  }, []);

  const categories = useMemo(() => {
    const cats = new Set(templates.map(t => t.category).filter(Boolean));
    return Array.from(cats).sort();
  }, [templates]);

  const filtered = useMemo(() => {
    let list = [...templates];
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      list = list.filter(t =>
        t.name.toLowerCase().includes(q) ||
        t.description.toLowerCase().includes(q) ||
        t.category?.toLowerCase().includes(q)
      );
    }
    if (categoryFilter) {
      list = list.filter(t => t.category === categoryFilter);
    }
    return list;
  }, [templates, searchQuery, categoryFilter]);

  const CATEGORY_COLORS: Record<string, string> = {
    'Customer Service': 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
    'Sales': 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    'Scheduling': 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    'Lead Generation': 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    'Notification': 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    'Integration': 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  };

  return (
    <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="workflow-template-picker-title"
        tabIndex={-1}
        className="bg-[var(--bg-secondary)] border border-[var(--glass-border)] rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden flex flex-col shadow-modal animate-scale-in"
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--glass-border)]">
          <div>
            <h2 id="workflow-template-picker-title" className="text-lg font-semibold">Workflow Templates</h2>
            <p className="text-xs text-[var(--text-muted)]">
              {templates.length} pre-built templates &mdash; pick one and customize it
            </p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-[var(--bg-tertiary)] rounded-lg transition-colors" aria-label="Close template picker">
            <X size={16} />
          </button>
        </div>

        {/* Search & Category Filter */}
        {!loading && templates.length > 0 && (
          <div className="px-6 py-3 border-b border-[var(--glass-border)] space-y-3">
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Search templates..."
                className="w-full pl-9 input-base text-sm"
                autoFocus
              />
            </div>
            {categories.length > 1 && (
              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => setCategoryFilter('')}
                  className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                    !categoryFilter
                      ? 'bg-brand-600/20 text-brand-400 border-brand-500/30'
                      : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)] border-transparent hover:border-[var(--glass-border)]'
                  }`}
                >
                  All
                </button>
                {categories.map(cat => (
                  <button
                    key={cat}
                    onClick={() => setCategoryFilter(cat === categoryFilter ? '' : cat)}
                    className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                      categoryFilter === cat
                        ? (CATEGORY_COLORS[cat] || 'bg-brand-600/20 text-brand-400 border-brand-500/30')
                        : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)] border-transparent hover:border-[var(--glass-border)]'
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
          {loading ? (
            <div className="col-span-2 flex items-center justify-center py-12">
              <Loader2 size={24} className="animate-spin text-brand-400" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="col-span-2 text-center py-12">
              <LayoutTemplate size={32} className="mx-auto text-[var(--text-muted)] mb-3 opacity-40" />
              <p className="text-sm text-[var(--text-muted)]">
                {searchQuery || categoryFilter ? 'No templates match your search' : 'No templates available'}
              </p>
              {(searchQuery || categoryFilter) && (
                <button
                  onClick={() => { setSearchQuery(''); setCategoryFilter(''); }}
                  className="mt-2 text-xs text-brand-400 hover:underline"
                >
                  Clear filters
                </button>
              )}
            </div>
          ) : (
            filtered.map(tpl => (
              <button
                key={tpl.id}
                onClick={() => onSelect(tpl)}
                className="dash-card p-4 text-left hover:border-brand-500/40 transition-all group"
              >
                <div className="flex items-start gap-3">
                  <div className="p-2 rounded-lg bg-brand-500/10 text-brand-400 group-hover:bg-brand-500/20 transition-colors shrink-0">
                    <LayoutTemplate size={18} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm group-hover:text-brand-400 transition-colors">{tpl.name}</p>
                    <p className="text-xs text-[var(--text-muted)] mt-1 line-clamp-2">{tpl.description}</p>
                    <div className="flex items-center gap-2 mt-2">
                      {tpl.category && (
                        <span className={`text-[10px] px-2 py-0.5 rounded-full border ${CATEGORY_COLORS[tpl.category] || 'bg-[var(--bg-tertiary)] text-[var(--text-muted)] border-[var(--glass-border)]'}`}>
                          {tpl.category}
                        </span>
                      )}
                      <span className="text-[10px] text-[var(--text-muted)]">
                        {tpl.nodes?.length || 0} nodes
                      </span>
                      {tpl.trigger_phrases?.length > 0 && (
                        <span className="text-[10px] text-[var(--text-muted)]">
                          {tpl.trigger_phrases.length} triggers
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── Main Editor ───────────────────────────────────────── */
function WorkflowEditorInner() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const workflowId = params.id as string;
  const isNew = workflowId === 'new';
  const preselectedAgentIdRaw = searchParams.get('agentId');
  const preselectedAgentId = preselectedAgentIdRaw ? Number(preselectedAgentIdRaw) : null;

  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [integrationList, setIntegrationList] = useState<Integration[]>([]);
  const [agentList, setAgentList] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [showTemplatePicker, setShowTemplatePicker] = useState(false);
  const { success, warning, apiError } = useToast();
  const [isDirty, setIsDirty] = useState(false);
  const [autoSaveStatus, setAutoSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const didLoadRef = useRef(false);
  const graphHashRef = useRef<string | null>(null);
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const draftTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Navigation guard: tracks whether the user clicked Back while dirty
  const [showLeaveConfirm, setShowLeaveConfirm] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const shortcutsDialogRef = useModalFocusTrap(showShortcuts);

  // Workflow metadata
  const [wfName, setWfName] = useState('');
  const [wfDescription, setWfDescription] = useState('');
  const [wfAgentId, setWfAgentId] = useState<number | null>(null);
  const [wfRequiresApproval, setWfRequiresApproval] = useState(false);
  const [wfTransitionFlexibility, setWfTransitionFlexibility] = useState<'strict' | 'flex'>('flex');

  // Dirty-state setters — wrap each local setter
  const markDirty = useCallback(() => { if (didLoadRef.current) setIsDirty(true); }, []);
  const setWfNameDirty = useCallback((v: string) => { setWfName(v); markDirty(); }, [markDirty]);
  const setWfDescriptionDirty = useCallback((v: string) => { setWfDescription(v); markDirty(); }, [markDirty]);
  const setWfAgentIdDirty = useCallback((v: number | null) => { setWfAgentId(v); markDirty(); }, [markDirty]);
  const setWfRequiresApprovalDirty = useCallback((v: boolean) => { setWfRequiresApproval(v); markDirty(); }, [markDirty]);
  const setWfTransitionFlexibilityDirty = useCallback((v: 'strict' | 'flex') => { setWfTransitionFlexibility(v); markDirty(); }, [markDirty]);

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedEdge, setSelectedEdge] = useState<Edge | null>(null);
  const [validationIssues, setValidationIssues] = useState<ValidationIssues | null>(null);
  const [showIssuesPanel, setShowIssuesPanel] = useState(false);  const { push, undo, redo, canUndo, canRedo } = useFlowHistory();

  const nodeCounter = useRef(0);
  const isRestoringRef = useRef(false);

  // Load data
  useEffect(() => {
    const loadAll = async () => {
      didLoadRef.current = false;
      try {
        const [intData, agData] = await Promise.all([
          integrationsApi.list(),
          agentsApi.list(),
        ]);
        setIntegrationList(intData.integrations);
        setAgentList(agData.agents);

        if (!isNew) {
          const wfData = await workflowsApi.get(parseInt(workflowId));
          setWorkflow(wfData.workflow);
          graphHashRef.current = wfData.workflow.graph_hash;
          setWfName(wfData.workflow.name);
          setWfDescription(wfData.workflow.description || '');
          setWfAgentId(wfData.workflow.agent_id);
          setWfRequiresApproval(wfData.workflow.requires_approval);
          setWfTransitionFlexibility(wfData.workflow.transition_flexibility || 'flex');

          if (wfData.workflow.graph_corrupted) {
            warning('Graph Data Corrupted', 'The saved graph could not be loaded. Reconstructing from step data. Some node positions and configs may be lost.');
          }

          const { nodes: n, edges: e } = workflowToFlow(wfData.workflow);
          // Auto-repair broken graphs (orphan edges, missing end node)
          const { nodes: cleanN, edges: cleanE, repaired } = sanitizeGraph(n, e);
          setNodes(cleanN);
          setEdges(cleanE);

          // Check for localStorage draft recovery
          try {
            const rawDraft = localStorage.getItem(`voia_workflow_draft_${workflowId}`);
            if (rawDraft) {
              const draft = JSON.parse(rawDraft);
              const wfUpdated = wfData.workflow.updated_at ? new Date(wfData.workflow.updated_at).getTime() : 0;
              if (draft.timestamp && draft.timestamp > wfUpdated && draft.nodes?.length > 0) {
                draftRef.current = draft;
                setShowDraftRestore(true);
              }
            }
          } catch { /* ignore draft recovery errors */ }
          const maxNum = Math.max(0, ...cleanN.map((nd: Node) => {
            const m = nd.id.match(/node-(\d+)/);
            return m ? parseInt(m[1]) : 0;
          }));
          nodeCounter.current = maxNum;
          if (repaired) {
            // Mark dirty so user is prompted to save the repaired version
            setTimeout(() => { setIsDirty(true); }, 200);
          }
        } else {
          // New workflow — start with trigger + end
          if (preselectedAgentId !== null && Number.isFinite(preselectedAgentId) && preselectedAgentId > 0) {
            setWfAgentId(preselectedAgentId);
          }
          setShowTemplatePicker(true); // Auto-show templates for new workflows
          setNodes([
            {
              id: 'trigger',
              type: 'workflowNode',
              position: { x: 250, y: 50 },
              data: {
                nodeType: 'trigger',
                label: 'Call Trigger',
                description: 'Configure trigger phrases',
                triggerPhrases: '',
                isConfigured: false,
              },
            },
            {
              id: 'end',
              type: 'workflowNode',
              position: { x: 250, y: 350 },
              data: { nodeType: 'end', label: 'Workflow Complete', isConfigured: true },
            },
          ]);
          setEdges([
            {
              id: 'e-trigger-end',
              source: 'trigger',
              target: 'end',
              animated: true,
              style: { stroke: '#6366f1', strokeWidth: 2 },
            },
          ]);
          nodeCounter.current = 2;
        }
      } catch (err) {
        apiError(err, 'Failed to load workflow data');
      } finally {
        setLoading(false);
        // Mark clean after initial data lands
        setTimeout(() => { didLoadRef.current = true; }, 100);
      }
    };
    loadAll();
  }, [preselectedAgentId, workflowId, isNew]);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges(eds => {
        const branch = connection.sourceHandle;
        const branchLabel = branch === 'yes'
          ? 'Yes'
          : branch === 'no'
            ? 'No'
            : branch === 'error'
              ? 'Error'
              : branch === 'on_missing'
                ? 'Missing info'
                : undefined;
        const next = addEdge(
          {
            ...connection,
            label: branchLabel,
            animated: true,
            style: { stroke: '#6366f1', strokeWidth: 2 },
          },
          eds,
        );
        return next;
      });
      markDirty();
    },
    [setEdges, markDirty],
  );

  const isValidConnection = useCallback(
    (connection: Connection | Edge) => {
      // No self-loops
      if (connection.source === connection.target) return false;
      // Can't connect to trigger (no input handle)
      const targetNode = nodes.find(n => n.id === connection.target);
      if (targetNode?.data.nodeType === 'trigger') return false;
      // Can't connect from terminal nodes (end/end_call have no output handle)
      const sourceNode = nodes.find(n => n.id === connection.source);
      if (sourceNode?.data.nodeType === 'end' || sourceNode?.data.nodeType === 'end_call') return false;
      const uniqueBranchHandles = new Set(['yes', 'no', 'error', 'on_missing']);
      if (
        connection.sourceHandle
        && uniqueBranchHandles.has(connection.sourceHandle)
        && edges.some(e => e.source === connection.source && e.sourceHandle === connection.sourceHandle)
      ) return false;
      // No duplicate edges (same source → target + handles)
      const exists = edges.some(e =>
        e.source === connection.source && e.target === connection.target &&
        e.sourceHandle === (connection as Connection).sourceHandle && e.targetHandle === (connection as Connection).targetHandle
      );
      if (exists) return false;
      return true;
    },
    [nodes, edges],
  );

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node);
    setSelectedEdge(null);
  }, []);

  const onEdgeClick = useCallback((_: React.MouseEvent, edge: Edge) => {
    setSelectedEdge(edge);
    setSelectedNode(null);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
    setSelectedEdge(null);
  }, []);

  const deleteEdge = useCallback(
    (edgeId: string) => {
      setEdges(eds => eds.filter(e => e.id !== edgeId));
      setSelectedEdge(null);
      markDirty();
    },
    [setEdges, markDirty],
  );

  const addNode = useCallback(
    (type: NodeType) => {
      nodeCounter.current += 1;
      const id = `node-${nodeCounter.current}`;
      const cfg = NODE_TYPES_CONFIG[type];

      // Place the new node below the canvas without inventing graph routing.
      // In a branched workflow, the visually lowest node is not necessarily the
      // logical predecessor and imported templates commonly use end_call nodes.
      const lastStepNode = [...nodes]
        .sort((a, b) => a.position.y - b.position.y)
        .pop();

      const yPos = lastStepNode ? lastStepNode.position.y + 160 : 200;

      // Default configs per node type — generic placeholders
      const DEFAULT_CONFIGS: Partial<Record<NodeType, Record<string, unknown>>> = {
        conversation: {
          prompt: '',
          variables_to_extract: [],
        },
        knowledge_base: {
          query: '{{service_requested}}',
          max_results: 5,
        },
        send_email: {
          to: '',
          subject: 'Notification',
          body: 'Dear {{caller_name}},\n\nThis is a message from our office.\n\nBest regards,',
        },
        end_call: {
          message: 'Thank you for calling! If you need anything else, don\'t hesitate to call us back. Take care!',
        },
        condition: {
          expression: '',
        },
        llm_process: {
          prompt: 'Analyze the caller\'s request and determine the most appropriate response.',
          max_tokens: 300,
        },
        notification: {
          channel: 'slack',
          message: 'New call from {{caller_name}} ({{caller_phone}}).',
        },
        note: {
          content: '',
        },
        delay: {
          delay_seconds: 3,
        },
      };

      const defaultConfig = DEFAULT_CONFIGS[type] || {};

      const newNode: Node = {
        id,
        type: 'workflowNode',
        position: { x: 250, y: yPos },
        data: {
          nodeType: type,
          label: cfg.label,
          description: '',
          action: '',
          params: {},
          config: defaultConfig,
          isConfigured: Object.keys(defaultConfig).length > 0,
        },
      };

      setNodes(nds => [...nds, newNode]);

      setSelectedNode(newNode);
      markDirty();
    },
    [nodes, setNodes, markDirty],
  );

  const updateNodeData = useCallback(
    (nodeId: string, data: Record<string, unknown>) => {
      // Strip display-only flags so they don't persist into saved state
      const { hasError, ...cleanData } = data as Record<string, unknown> & { hasError?: boolean };
      setNodes(nds => nds.map(n => (n.id === nodeId ? { ...n, data: cleanData } : n)));
      setSelectedNode(prev => (prev?.id === nodeId ? { ...prev, data: cleanData } : prev));
      markDirty();
    },
    [setNodes, markDirty],
  );

  const deleteNode = useCallback(
    (nodeId: string) => {
      if (nodeId === 'trigger' || nodeId === 'end') return; // Can't delete trigger/end

      setNodes(nds => nds.filter(n => n.id !== nodeId));
      setEdges(current => current.filter(edge => edge.source !== nodeId && edge.target !== nodeId));
      setSelectedNode(null);
      markDirty();
    },
    [setNodes, setEdges, markDirty],
  );

  const validateNodes = (): string[] => {
    const errors: string[] = [];
    for (const node of nodes) {
      const nt = node.data.nodeType as string;
      const label = (node.data.label as string) || nt;
      const cfg = (node.data.config as Record<string, unknown>) || {};
      switch (nt) {
        case 'trigger': {
          const phrases = String(node.data.triggerPhrases || '').split('\n').map(s => s.trim()).filter(Boolean);
          if (phrases.length === 0) errors.push(`${label}: needs at least one trigger phrase`);
          break;
        }
        case 'transfer_call': {
          if (!String(cfg.transfer_number || cfg.transfer_to || '').trim()) errors.push(`${label}: transfer number is required`);
          break;
        }
        case 'api_request':
        case 'custom_api': {
          if (!String(cfg.url || '').trim()) errors.push(`${label}: request URL is required`);
          break;
        }
        case 'mcp_tool': {
          if (!String(cfg.server_url || '').trim()) errors.push(`${label}: MCP server URL is required`);
          break;
        }
        case 'knowledge_base': {
          if (!String(cfg.query || '').trim()) errors.push(`${label}: search query is required`);
          break;
        }
        case 'condition': {
          if (!String(cfg.expression || '').trim()) errors.push(`${label}: condition expression is required`);
          break;
        }
        case 'llm_process': {
          if (!String(cfg.prompt || '').trim()) errors.push(`${label}: processing prompt is required`);
          break;
        }
        case 'notification': {
          if (!String(cfg.message || '').trim()) errors.push(`${label}: notification message is required`);
          break;
        }
        case 'webhook': {
          if (!String(cfg.url || '').trim()) errors.push(`${label}: webhook URL is required`);
          break;
        }
        case 'send_sms': {
          if (!String(cfg.to || '').trim()) errors.push(`${label}: recipient phone is required`);
          if (!String(cfg.body || '').trim()) errors.push(`${label}: SMS body is required`);
          break;
        }
        case 'send_email': {
          if (!String(cfg.to || '').trim()) errors.push(`${label}: recipient email is required`);
          if (!String(cfg.subject || '').trim()) errors.push(`${label}: email subject is required`);
          if (!String(cfg.body || '').trim()) errors.push(`${label}: email body is required`);
          break;
        }
        case 'delay': {
          if (!String(cfg.delay_seconds || '').trim()) errors.push(`${label}: delay seconds is required`);
          break;
        }
        case 'note': {
          if (!String(cfg.content || '').trim()) errors.push(`${label}: note content is required`);
          break;
        }
        default: {
          // A3: Integration nodes and 'action' nodes: check integrationId and action
          const integrationNodeTypes = [
            'google_calendar', 'google_sheets', 'cal_com', 'calendly', 'salesforce',
            'pipedrive', 'gohighlevel', 'hubspot', 'zendesk', 'freshdesk', 'intercom',
            'stripe', 'shopify', 'whatsapp_cloud', 'discord', 'microsoft_teams',
            'notion', 'airtable', 'make', 'jira', 'linear', 'slack', 'google_drive_mcp',
          ];
          const isIntegrationNode = integrationNodeTypes.includes(nt) || nt === 'action';
          if (isIntegrationNode) {
            const effectiveAction = String(node.data.action || cfg.action || '').trim();
            const integrationType = String(cfg.integration_type || '').trim();
            if (!String(node.data.integrationId || '').trim() && !integrationType && nt === 'action') {
              errors.push(`${label}: integration type or integration selection is required`);
            }
            if (!effectiveAction) errors.push(`${label}: action must be selected`);
          }
          break;
        }
      }
    }
    return errors;
  };

  const validateGraph = (): { errors: string[]; warnings: string[]; brokenEdgeIds: Set<string>; brokenNodeIds: Set<string> } => {
    return validateWorkflow({ nodes, edges });
  };

  const runValidation = useCallback((): { hasBlocking: boolean; issues: ValidationIssues } => {
    const nodeErrors = validateNodes();
    const { errors: graphErrors, warnings: graphWarnings, brokenEdgeIds, brokenNodeIds: graphBrokenNodeIds } = validateGraph();
    const brokenNodeIds = new Set<string>(graphBrokenNodeIds);
    for (const node of nodes) {
      const nt = node.data.nodeType as string;
      const label = (node.data.label as string) || nt;
      if (nodeErrors.some(e => e.startsWith(`${label}:`))) {
        brokenNodeIds.add(node.id);
      }
    }
    const issues = { nodeErrors, graphErrors, graphWarnings, brokenNodeIds, brokenEdgeIds };
    setValidationIssues(issues);
    setShowIssuesPanel(nodeErrors.length > 0 || graphErrors.length > 0 || graphWarnings.length > 0);
    return { hasBlocking: nodeErrors.length > 0 || graphErrors.length > 0, issues };
  }, [nodes, edges]);

  const handleSave = async () => {
    const data = flowToWorkflow(nodes, edges, wfName, wfDescription, wfAgentId, wfRequiresApproval, wfTransitionFlexibility);
    if (!data.name.trim()) {
      warning('Validation', 'Workflow name is required');
      return;
    }
    if (data.trigger_phrases.length === 0) {
      warning('Trigger Phrases Missing', 'Click the Trigger node to add at least one trigger phrase before saving.');
      return;
    }
    // Run full validation (node config + graph integrity)
    const { hasBlocking, issues } = runValidation();
    if (hasBlocking) {
      const count = issues.nodeErrors.length + issues.graphErrors.length;
      warning('Workflow Errors', `Cannot save — ${count} blocking workflow error(s). See the Issues panel for details.`);
      return;
    }
    setSaving(true);
    try {
      if (isNew) {
        const result = await workflowsApi.create(data);
        setIsDirty(false);
        try { localStorage.removeItem(draftKey); } catch { /* ignore */ }
        success('Workflow Created', 'Redirecting to editor...');
        setTimeout(() => router.push(`/dashboard/workflows/${result.workflow.id}`), 1000);
      } else {
        const result = await workflowsApi.update(parseInt(workflowId), {
          ...data,
          expected_graph_hash: graphHashRef.current || undefined,
        });
        graphHashRef.current = result.workflow.graph_hash;
        setWorkflow(result.workflow);
        setIsDirty(false);
        try { localStorage.removeItem(draftKey); } catch { /* ignore */ }
        success('Workflow Saved', 'All changes saved successfully');
      }
    } catch (err: unknown) {
      apiError(err, 'Failed to save workflow');
    } finally {
      setSaving(false);
    }
  };

  const handleExecute = async () => {
    if (isNew) return;
    setExecuting(true);
    try {
      const result = await workflowsApi.execute(parseInt(workflowId), {
        caller_name: 'Test User',
        caller_phone: '+10000000000',
        transcript: 'Test execution from editor',
      });
      success('Workflow Executed', `${result.steps_executed} steps completed`);
    } catch (err: unknown) {
      apiError(err, 'Workflow execution failed');
    } finally {
      setExecuting(false);
    }
  };

  const handleSaveAndTest = async () => {
    if (!wfAgentId) {
      warning('No Agent', 'Assign an agent in Workflow Settings before testing.');
      return;
    }
    const data = flowToWorkflow(nodes, edges, wfName, wfDescription, wfAgentId, wfRequiresApproval, wfTransitionFlexibility);
    if (!data.name.trim()) {
      warning('Validation', 'Workflow name is required');
      return;
    }
    if (data.trigger_phrases.length === 0) {
      warning('Trigger Phrases Missing', 'Add at least one trigger phrase before testing.');
      return;
    }
    const { hasBlocking, issues } = runValidation();
    if (hasBlocking) {
      const count = issues.nodeErrors.length + issues.graphErrors.length;
      warning('Workflow Errors', `Cannot test — ${count} blocking workflow error(s). See the Issues panel.`);
      return;
    }
    setSaving(true);
    try {
      let savedWorkflowId = workflowId;
      let savedGraphHash: string | null = null;
      if (isNew) {
        const result = await workflowsApi.create(data);
        savedWorkflowId = String(result.workflow.id);
        savedGraphHash = result.workflow.graph_hash;
      } else {
        const result = await workflowsApi.update(parseInt(workflowId), {
          ...data,
          expected_graph_hash: graphHashRef.current || undefined,
        });
        savedGraphHash = result.workflow.graph_hash;
        graphHashRef.current = savedGraphHash;
        setWorkflow(result.workflow);
      }
      setIsDirty(false);
      try { localStorage.removeItem(draftKey); } catch { /* ignore */ }
      success('Saved', 'Opening test playground...');
      const graphHashParam = savedGraphHash ? `&graph_hash=${encodeURIComponent(savedGraphHash)}` : '';
      setTimeout(() => router.push(`/dashboard/playground/flow?agent_id=${wfAgentId}&workflow_id=${savedWorkflowId}${graphHashParam}`), 500);
    } catch (err: unknown) {
      apiError(err, 'Failed to save workflow');
    } finally {
      setSaving(false);
    }
  };

  const autoFixGraph = useCallback(() => {
    const { nodes: cleanN, edges: cleanE, repaired } = sanitizeGraph(nodes, edges);
    if (repaired) {
      setNodes(cleanN);
      setEdges(cleanE);
      markDirty();
      success('Auto-Fix', 'Graph repaired — invalid, self-loop, and terminal outgoing edges removed.');
    } else {
      success('Auto-Fix', 'No graph issues found.');
    }
    runValidation();
  }, [nodes, edges, setNodes, setEdges, markDirty, success, runValidation]);

  const importTemplate = useCallback((template: WorkflowTemplate) => {
    // Convert template nodes to ReactFlow format
    const rfNodes: Node[] = template.nodes.map(n => {
      const cfg = n.data.config || {};
      // A2: For 'action' nodes, promote integration_type, action, and params
      // from config to top-level data so NodeConfigPanel and flowToWorkflow work.
      if (n.type === 'action' && cfg.integration_type) {
        const { integration_type, action, params } = cfg;
        const hasParams = params && typeof params === 'object' && Object.keys(params).length > 0;
        return {
          id: n.id,
          type: 'workflowNode',
          position: n.position,
          data: {
            nodeType: integration_type || n.type,
            label: n.data.label,
            config: cfg,
            action: action || '',
            params: params || {},
            triggerPhrases: undefined,
            isConfigured: hasParams,
          },
        };
      }
      // For integration-type nodes (google_calendar, google_sheets, etc.) in templates,
      // preserve the nodeType and extract action/params from config
      if (n.type !== 'action' && n.type !== 'conversation' && n.type !== 'condition' && n.type !== 'trigger' && n.type !== 'end_call' && n.type !== 'note' && n.type !== 'delay' && cfg && Object.keys(cfg).length > 0) {
        const { action, params } = cfg;
        const hasParams = params && typeof params === 'object' && Object.keys(params).length > 0;
        return {
          id: n.id,
          type: 'workflowNode',
          position: n.position,
          data: {
            nodeType: n.type,
            label: n.data.label,
            config: cfg,
            action: action || '',
            params: params || {},
            triggerPhrases: undefined,
            isConfigured: hasParams,
          },
        };
      }
      return {
        id: n.id,
        type: 'workflowNode',
        position: n.position,
        data: {
          nodeType: n.type,
          label: n.data.label,
          config: cfg,
          triggerPhrases: n.type === 'trigger' ? (template.trigger_phrases || []).join('\n') : undefined,
          isConfigured: true,
        },
      };
    });

    const rfEdges: Edge[] = normalizeBranchEdges(rfNodes, template.edges.map((e, i) => ({
      id: `e-${e.source}-${e.target}-${i}`,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle,
      label: e.label,
      animated: true,
      style: { stroke: '#6366f1', strokeWidth: 2 },
    })));

    // Ensure graph integrity without inventing connections the template did not define.
    const { nodes: cleanNodes, edges: cleanEdges, repaired } = sanitizeGraph(rfNodes, rfEdges);

    setNodes(cleanNodes);
    setEdges(cleanEdges);
    setWfName(template.name);
    setWfDescription(template.description);
    // Use max numeric suffix to avoid ID collisions
    const maxNum = Math.max(0, ...cleanNodes.map(n => {
      const m = n.id.match(/node-(\d+)/);
      return m ? parseInt(m[1]) : 0;
    }));
    nodeCounter.current = maxNum;
    setShowTemplatePicker(false);
    success('Template Loaded', `"${template.name}" imported${repaired ? ' — graph repaired' : ''} — customize and save`);
  }, [setNodes, setEdges, success]);

  // Duplicate only the node. Copying its edges creates ambiguous parallel routes.
  const duplicateNode = useCallback(() => {
    if (!selectedNode || selectedNode.id === 'trigger' || selectedNode.id === 'end') return;
    nodeCounter.current += 1;
    const newId = `node-${nodeCounter.current}`;
    const newNode: Node = {
      ...selectedNode,
      id: newId,
      position: { x: selectedNode.position.x + 40, y: selectedNode.position.y + 40 },
      data: { ...selectedNode.data, label: `${selectedNode.data.label} (copy)` },
    };
    setNodes(nds => [...nds, newNode]);

    setSelectedNode(newNode);
    markDirty();
  }, [selectedNode, setNodes, markDirty]);

  // Undo / Redo
  const handleUndo = useCallback(() => {
    const state = undo();
    if (state) {
      isRestoringRef.current = true;
      setNodes(state.nodes);
      setEdges(state.edges);
    }
  }, [undo, setNodes, setEdges]);

  const handleRedo = useCallback(() => {
    const state = redo();
    if (state) {
      isRestoringRef.current = true;
      setNodes(state.nodes);
      setEdges(state.edges);
    }
  }, [redo, setNodes, setEdges]);

  // Push to history whenever nodes/edges change (skip during undo/redo / initial load)
  // Debounced so rapid drag frames collapse into a single undo entry
  const pushTimerRef = useRef<number | null>(null);
  useEffect(() => {
    if (isRestoringRef.current) {
      isRestoringRef.current = false;
      return;
    }
    if (!didLoadRef.current) return;
    if (nodes.length || edges.length) {
      if (pushTimerRef.current) window.clearTimeout(pushTimerRef.current);
      pushTimerRef.current = window.setTimeout(() => {
        push(nodes, edges);
        pushTimerRef.current = null;
      }, 500);
    }
  }, [nodes, edges, push]);

  // Clear pending push timer on unmount
  useEffect(() => {
    return () => {
      if (pushTimerRef.current) window.clearTimeout(pushTimerRef.current);
    };
  }, []);

  // Keyboard shortcuts
  useKeyboardShortcuts(
    [
      { key: 's', ctrl: true, meta: true, handler: () => handleSave(), description: 'Save workflow' },
      { key: 'Delete', handler: () => { if (selectedEdge) { deleteEdge(selectedEdge.id); } else if (selectedNode) { deleteNode(selectedNode.id); } }, description: 'Delete selected node or edge' },
      { key: 'Backspace', handler: () => { if (selectedEdge) { deleteEdge(selectedEdge.id); } else if (selectedNode) { deleteNode(selectedNode.id); } }, description: 'Delete selected node or edge' },
      { key: 'd', ctrl: true, meta: true, handler: () => duplicateNode(), description: 'Duplicate selected node' },
      { key: 'Escape', handler: () => { setSelectedNode(null); setSelectedEdge(null); }, description: 'Deselect node/edge / close panel' },
      { key: 'z', ctrl: true, meta: true, handler: handleUndo, description: 'Undo' },
      { key: 'y', ctrl: true, meta: true, handler: handleRedo, description: 'Redo' },
      { key: 'z', ctrl: true, shift: true, meta: true, handler: handleRedo, description: 'Redo' },
    ],
    !showTemplatePicker
  );

  // Display edges — apply red/dashed style to broken edges for visual feedback
  const displayEdges = useMemo(() => {
    if (!validationIssues?.brokenEdgeIds.size) return edges;
    return edges.map(e => {
      if (validationIssues.brokenEdgeIds.has(e.id)) {
        return { ...e, style: { stroke: '#ef4444', strokeWidth: 3, strokeDasharray: '6 4' }, animated: false };
      }
      return e;
    });
  }, [edges, validationIssues]);

  // Display nodes — mark broken nodes for visual feedback
  const displayNodes = useMemo(() => {
    if (!validationIssues?.brokenNodeIds.size) return nodes;
    return nodes.map(n => {
      if (validationIssues.brokenNodeIds.has(n.id)) {
        return { ...n, data: { ...n.data, hasError: true } };
      }
      return { ...n, data: { ...n.data, hasError: false } };
    });
  }, [nodes, validationIssues]);

  const issueCount = validationIssues
    ? validationIssues.graphErrors.length + validationIssues.nodeErrors.length + validationIssues.graphWarnings.length
    : 0;

  // ── localStorage draft backup ──────────────────────────────
  // Persist editor state to localStorage on every change (debounced 2s)
  // so that if the browser crashes or the tab is closed, we can recover.
  const draftKey = useMemo(() => `voia_workflow_draft_${workflowId}`, [workflowId]);

  useEffect(() => {
    if (!didLoadRef.current) return;
    if (!nodes.length && !edges.length) return;
    if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
    draftTimerRef.current = setTimeout(() => {
      try {
        const draft = {
          nodes,
          edges,
          wfName,
          wfDescription,
          wfAgentId,
          wfRequiresApproval,
          wfTransitionFlexibility,
          timestamp: Date.now(),
        };
        localStorage.setItem(draftKey, JSON.stringify(draft));
      } catch {
        // localStorage may be full or unavailable — silently ignore
      }
    }, 2000);
    return () => { if (draftTimerRef.current) clearTimeout(draftTimerRef.current); };
  }, [nodes, edges, wfName, wfDescription, wfAgentId, wfRequiresApproval, wfTransitionFlexibility, draftKey]);

  // ── Auto-save with debounce (30s when dirty) ───────────────
  // Auto-saves existing workflows with a name and trigger phrases.
  // For new workflows, auto-creates once a name and trigger phrases exist,
  // then redirects to the real editor URL so subsequent edits use update.
  const autoSave = useCallback(async () => {
    if (!didLoadRef.current || !isDirty || saving) return;
    if (!wfName.trim()) return;
    const triggerNode = nodes.find(n => n.data.nodeType === 'trigger');
    const phrases = ((triggerNode?.data.triggerPhrases as string) || '')
      .split('\n').map((s: string) => s.trim()).filter(Boolean);
    if (phrases.length === 0) return;

    setAutoSaveStatus('saving');
    try {
      const data = flowToWorkflow(nodes, edges, wfName, wfDescription, wfAgentId, wfRequiresApproval, wfTransitionFlexibility);
      if (isNew) {
        const result = await workflowsApi.create(data);
        setIsDirty(false);
        try { localStorage.removeItem(draftKey); } catch { /* ignore */ }
        setAutoSaveStatus('saved');
        setTimeout(() => setAutoSaveStatus('idle'), 3000);
        router.replace(`/dashboard/workflows/${result.workflow.id}`);
      } else {
        const result = await workflowsApi.update(parseInt(workflowId), {
          ...data,
          expected_graph_hash: graphHashRef.current || undefined,
        });
        graphHashRef.current = result.workflow.graph_hash;
        setWorkflow(result.workflow);
        setIsDirty(false);
        setAutoSaveStatus('saved');
        try { localStorage.removeItem(draftKey); } catch { /* ignore */ }
        setTimeout(() => setAutoSaveStatus('idle'), 3000);
      }
    } catch {
      setAutoSaveStatus('error');
      setTimeout(() => setAutoSaveStatus('idle'), 5000);
    }
  }, [isNew, isDirty, saving, wfName, wfDescription, wfAgentId, wfRequiresApproval, wfTransitionFlexibility, nodes, edges, workflowId, draftKey, router]);

  useEffect(() => {
    if (!isDirty || !didLoadRef.current) return;
    if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current);
    autoSaveTimerRef.current = setTimeout(() => {
      autoSave();
    }, 30000); // 30s debounce
    return () => { if (autoSaveTimerRef.current) clearTimeout(autoSaveTimerRef.current); };
  }, [isDirty, nodes, edges, wfName, wfDescription, wfAgentId, wfRequiresApproval, wfTransitionFlexibility, autoSave]);

  // ── Draft recovery on load ─────────────────────────────────
  // If a draft exists in localStorage and is newer than the workflow's
  // updated_at, offer to restore it.
  const [showDraftRestore, setShowDraftRestore] = useState(false);
  const draftRef = useRef<{ nodes: Node[]; edges: Edge[]; wfName: string; wfDescription: string; wfAgentId: number | null; wfRequiresApproval: boolean; wfTransitionFlexibility: 'strict' | 'flex'; timestamp: number } | null>(null);

  // Navigation guard: warn on browser close / refresh with unsaved changes
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!isDirty) return;
      // Standard way to trigger the browser's built-in "Leave site?" dialog
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [isDirty]);

  // Helper: navigate back, gated by dirty check
  const handleBack = useCallback(() => {
    if (isDirty) {
      setShowLeaveConfirm(true);
    } else {
      router.push('/dashboard/workflows');
    }
  }, [isDirty, router]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-8rem)]">
        <Loader2 size={32} className="animate-spin text-brand-400" />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-5rem)] -m-6 lg:-m-8">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--glass-border)] bg-[var(--bg-secondary)] shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={handleBack}
            aria-label="Back to workflows"
            className="p-2 btn-ghost rounded-lg"
            title="Back to workflows"
          >
            <ArrowLeft size={16} />
          </button>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={wfName}
              onChange={e => setWfNameDirty(e.target.value)}
              placeholder="Workflow name..."
              className="text-lg font-semibold bg-transparent border-none outline-none placeholder:text-[var(--text-muted)] w-64 focus:bg-[var(--bg-tertiary)] focus:px-2 focus:rounded transition-all duration-150"
            />
            {isDirty && (
              <span className="flex items-center gap-1 text-[10px] text-amber-400 bg-amber-400/10 border border-amber-400/20 px-2 py-0.5 rounded-full animate-pulse">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400 inline-block" />
                Unsaved
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowTemplatePicker(true)}
            className="flex items-center gap-2 px-3 py-2 bg-[var(--bg-card)] border border-[var(--glass-border)] rounded-lg text-sm hover:border-brand-500 transition-colors"
          >
            <LayoutTemplate size={14} />
            Templates
          </button>
          <NodePalette onAdd={addNode} />
          {!isNew && (
            <button
              onClick={handleExecute}
              disabled={executing}
              className="flex items-center gap-2 px-3 py-2 bg-green-600/20 text-green-400 hover:bg-green-600/30 border border-green-500/30 rounded-lg text-sm transition-colors disabled:opacity-50"
            >
              {executing ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              Test
            </button>
          )}
          <button
            onClick={handleSaveAndTest}
            disabled={saving || !wfAgentId}
            className="flex items-center gap-2 px-3 py-2 bg-green-600/20 text-green-400 hover:bg-green-600/30 border border-green-500/30 rounded-lg text-sm transition-colors disabled:opacity-50"
            title={wfAgentId ? 'Save and open in test playground' : 'Assign an agent first'}
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            Save & Test
            <ArrowRight size={12} />
          </button>
          <button
            onClick={handleUndo}
            disabled={!canUndo}
            aria-label="Undo last change"
            className="p-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] rounded-lg transition-colors disabled:opacity-30"
            title="Undo (⌘Z)"
          >
            <Undo2 size={16} />
          </button>
          <button
            onClick={handleRedo}
            disabled={!canRedo}
            aria-label="Redo last change"
            className="p-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] rounded-lg transition-colors disabled:opacity-30"
            title="Redo (⌘Y / ⌘Shift+Z)"
          >
            <Redo2 size={16} />
          </button>
          <button
            onClick={() => setShowShortcuts(true)}
            aria-label="Open keyboard shortcuts"
            className="p-2 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] rounded-lg transition-colors"
            title="Keyboard shortcuts"
          >
            <Keyboard size={16} />
          </button>
          {issueCount > 0 && (
            <button
              onClick={() => setShowIssuesPanel(!showIssuesPanel)}
              className={`flex items-center gap-1.5 px-2.5 py-2 rounded-lg text-sm transition-colors ${
                validationIssues?.graphErrors.length
                  ? 'bg-red-600/20 text-red-400 border border-red-500/30 hover:bg-red-600/30'
                  : 'bg-amber-600/20 text-amber-400 border border-amber-500/30 hover:bg-amber-600/30'
              }`}
              title={`${issueCount} issue(s) — click to ${showIssuesPanel ? 'hide' : 'show'} details`}
            >
              <AlertCircle size={14} />
              {issueCount}
            </button>
          )}
          {/* Auto-save status indicator */}
          {autoSaveStatus !== 'idle' && (
            <span className={`flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full transition-opacity ${
              autoSaveStatus === 'saving' ? 'text-blue-400 bg-blue-400/10' :
              autoSaveStatus === 'saved' ? 'text-green-400 bg-green-400/10' :
              'text-red-400 bg-red-400/10'
            }`}>
              {autoSaveStatus === 'saving' && <Loader2 size={10} className="animate-spin" />}
              {autoSaveStatus === 'saving' ? 'Auto-saving...' : autoSaveStatus === 'saved' ? 'Auto-saved' : 'Auto-save failed'}
            </span>
          )}
          <button
            onClick={handleSave}
            disabled={saving}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 ${
              validationIssues && (validationIssues.nodeErrors.length > 0 || validationIssues.graphErrors.length > 0)
                ? 'bg-amber-600 hover:bg-amber-500 text-white'
                : 'bg-brand-600 hover:bg-brand-500 text-white'
            }`}
            title={
              validationIssues && (validationIssues.nodeErrors.length > 0 || validationIssues.graphErrors.length > 0)
                ? `${validationIssues.nodeErrors.length + validationIssues.graphErrors.length} blocking error(s) — save will be rejected until fixed`
                : 'Save (⌘S)'
            }
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {saving ? 'Saving...' : 'Save'}
            {validationIssues && (validationIssues.nodeErrors.length > 0 || validationIssues.graphErrors.length > 0) && (
              <span className="ml-1 text-[10px] bg-white/20 rounded-full px-1.5 py-0.5">
                {validationIssues.nodeErrors.length + validationIssues.graphErrors.length} blocked
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Draft restore modal */}
      {showDraftRestore && draftRef.current && (
        <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in">
          <div className="bg-[var(--bg-secondary)] border border-[var(--glass-border)] rounded-2xl w-full max-w-md p-6 shadow-modal animate-scale-in">
            <h3 className="text-base font-semibold mb-2 flex items-center gap-2">
              <AlertCircle size={18} className="text-amber-400" />
              Unsaved draft found
            </h3>
            <p className="text-sm text-[var(--text-muted)] mb-4">
              A previous editing session from <span className="text-[var(--text-primary)] font-medium">{new Date(draftRef.current.timestamp).toLocaleString()}</span> was not saved.
              Would you like to restore your unsaved changes?
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => {
                  setShowDraftRestore(false);
                  draftRef.current = null;
                  try { localStorage.removeItem(draftKey); } catch { /* ignore */ }
                }}
                className="px-4 py-2 text-sm rounded-lg border border-[var(--glass-border)] hover:bg-[var(--bg-tertiary)] transition-colors"
              >
                Discard draft
              </button>
              <button
                onClick={() => {
                  const draft = draftRef.current;
                  if (draft) {
                    setNodes(draft.nodes);
                    setEdges(draft.edges);
                    setWfName(draft.wfName);
                    setWfDescription(draft.wfDescription);
                    setWfAgentId(draft.wfAgentId);
                    setWfRequiresApproval(draft.wfRequiresApproval);
                    setWfTransitionFlexibility(draft.wfTransitionFlexibility);
                    setIsDirty(true);
                  }
                  setShowDraftRestore(false);
                  draftRef.current = null;
                }}
                className="px-4 py-2 text-sm font-medium rounded-lg bg-brand-600 hover:bg-brand-500 text-white transition-colors"
              >
                Restore draft
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Leave without saving? confirmation modal */}
      {showLeaveConfirm && (
        <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in">
          <div className="bg-[var(--bg-secondary)] border border-[var(--glass-border)] rounded-2xl w-full max-w-sm p-6 shadow-modal animate-scale-in">
            <h3 className="text-base font-semibold mb-2">Leave without saving?</h3>
            <p className="text-sm text-[var(--text-muted)] mb-6">
              You have unsaved changes to <span className="text-[var(--text-primary)] font-medium">{wfName || 'this workflow'}</span>.
              They will be permanently lost if you leave now.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowLeaveConfirm(false)}
                className="px-4 py-2 text-sm rounded-lg border border-[var(--glass-border)] hover:bg-[var(--bg-tertiary)] transition-colors"
              >
                Keep editing
              </button>
              <button
                onClick={() => {
                  setIsDirty(false);
                  setShowLeaveConfirm(false);
                  try { localStorage.removeItem(draftKey); } catch { /* ignore */ }
                  router.push('/dashboard/workflows');
                }}
                className="px-4 py-2 text-sm font-medium rounded-lg bg-red-600/90 hover:bg-red-500 text-white transition-colors"
              >
                Leave anyway
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Template Picker Modal */}
      {showTemplatePicker && (
        <TemplatePicker
          onSelect={importTemplate}
          onClose={() => setShowTemplatePicker(false)}
        />
      )}

      {/* Editor */}
      <div className="flex flex-1 overflow-hidden">
        {/* Canvas */}
        <div className="flex-1 relative">
          <Suspense fallback={
            <div className="flex items-center justify-center h-full">
              <Loader2 size={32} className="animate-spin text-brand-400" />
            </div>
          }>
            <WorkflowCanvas
              nodes={displayNodes}
              edges={displayEdges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={onNodeClick}
              onEdgeClick={onEdgeClick}
              onPaneClick={onPaneClick}
              isValidConnection={isValidConnection}
              invalidNodeIds={validationIssues?.brokenNodeIds}
            >
              <div className="dash-card p-3 m-3 w-72 space-y-3">
                <p className="section-title">Workflow Settings</p>
                <div>
                  <label className="block text-[10px] text-[var(--text-muted)] mb-0.5">Description</label>
                  <input
                    type="text"
                    value={wfDescription}
                    onChange={e => setWfDescriptionDirty(e.target.value)}
                    className="w-full input-base text-xs"
                    placeholder="What does this workflow do?"
                  />
                </div>
                <div>
                  <label className="block text-[10px] text-[var(--text-muted)] mb-0.5">Assigned Agent</label>
                  <select
                    value={wfAgentId || ''}
                    onChange={e => setWfAgentIdDirty(e.target.value ? parseInt(e.target.value) : null)}
                    className="w-full input-base text-xs"
                  >
                    <option value="">Any agent (all agents)</option>
                    {agentList.map(a => (
                      <option key={a.id} value={a.id}>
                        {a.name}{a.mode === 'conversational_flow' ? ' \u26A0 already has a flow' : ''}
                      </option>
                    ))}
                  </select>
                  {wfAgentId && agentList.find(a => a.id === wfAgentId)?.mode === 'conversational_flow' && workflow?.agent_id !== wfAgentId && (
                    <p className="text-[9px] text-amber-400 mt-0.5">This agent already owns another flow. Unassign that workflow before saving.</p>
                  )}
                  {(!wfAgentId || agentList.find(a => a.id === wfAgentId)?.mode !== 'conversational_flow' || workflow?.agent_id === wfAgentId) && (
                    <p className="text-[9px] text-[var(--text-muted)] mt-0.5">Only runs for calls handled by this agent</p>
                  )}
                </div>
                <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)] cursor-pointer">
                  <div className="relative flex items-center">
                    <input
                      type="checkbox"
                      checked={wfRequiresApproval}
                      onChange={e => setWfRequiresApprovalDirty(e.target.checked)}
                      className="sr-only"
                    />
                    <div className={`w-4 h-4 rounded border flex items-center justify-center transition-colors ${wfRequiresApproval ? 'bg-brand-600 border-brand-500' : 'bg-[var(--bg-primary)] border-[var(--glass-border)]'}`}>
                      {wfRequiresApproval && <svg width="10" height="8" viewBox="0 0 10 8" fill="none"><path d="M1 4l3 3 5-6" stroke="var(--text-inverse)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                    </div>
                  </div>
                  <div>
                    <span>Require approval</span>
                    <p className="text-[9px] text-[var(--text-muted)]">Actions need manual approval before executing</p>
                  </div>
                </label>
                <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)] cursor-pointer">
                  <div className="relative flex items-center">
                    <input
                      type="checkbox"
                      checked={wfTransitionFlexibility === 'flex'}
                      onChange={e => setWfTransitionFlexibilityDirty(e.target.checked ? 'flex' : 'strict')}
                      className="sr-only"
                    />
                    <div className={`w-4 h-4 rounded border flex items-center justify-center transition-colors ${wfTransitionFlexibility === 'flex' ? 'bg-purple-600 border-purple-500' : 'bg-[var(--bg-primary)] border-[var(--glass-border)]'}`}>
                      {wfTransitionFlexibility === 'flex' && <svg width="10" height="8" viewBox="0 0 10 8" fill="none"><path d="M1 4l3 3 5-6" stroke="var(--text-inverse)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                    </div>
                  </div>
                  <div>
                    <span>Flex mode</span>
                    <p className="text-[9px] text-[var(--text-muted)]">LLM can dynamically choose the next step</p>
                  </div>
                </label>
                <div className="pt-2 border-t border-[var(--glass-border)]">
                  <p className="text-[9px] text-[var(--text-muted)] leading-relaxed">
                    <strong className="text-[var(--text-secondary)]">Tip:</strong> Click a node to configure it.
                    Click the trigger node to set phrases that activate this workflow.
                    {isDirty && <span className="block mt-1 text-amber-400">You have unsaved changes. Press ⌘S to save.</span>}
                  </p>
                </div>
              </div>
            </WorkflowCanvas>
          </Suspense>

          {/* Issues Panel — floating validation feedback */}
          {showIssuesPanel && validationIssues && (
            <div className="absolute bottom-4 left-4 z-30 w-96 max-h-[60vh] flex flex-col bg-[var(--bg-secondary)] border border-[var(--glass-border)] rounded-xl shadow-2xl animate-scale-in">
              <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--glass-border)] shrink-0">
                <div className="flex items-center gap-2">
                  <AlertCircle size={16} className={
                    validationIssues.graphErrors.length ? 'text-red-400' : 'text-amber-400'
                  } />
                  <h3 className="text-sm font-semibold">Issues</h3>
                  <span className="text-[10px] text-[var(--text-muted)]">
                    {validationIssues.graphErrors.length > 0
                      ? `${validationIssues.graphErrors.length} blocking · `
                      : ''}
                    {validationIssues.nodeErrors.length} config · {validationIssues.graphWarnings.length} warning{validationIssues.graphWarnings.length !== 1 ? 's' : ''}
                  </span>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={autoFixGraph}
                    className="flex items-center gap-1 px-2 py-1 text-[10px] bg-brand-600/20 text-brand-400 hover:bg-brand-600/30 border border-brand-500/30 rounded transition-colors"
                    title="Remove orphan edges and re-link to end"
                  >
                    <Wrench size={10} />
                    Auto-Fix
                  </button>
                  <button
                    onClick={() => setShowIssuesPanel(false)}
                    className="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] rounded transition-colors"
                    aria-label="Close issues panel"
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>
              <div className="overflow-y-auto p-3 space-y-2">
                {/* Blocking graph errors */}
                {validationIssues.graphErrors.map((err, i) => (
                  <div key={`ge-${i}`} className="flex items-start gap-2 p-2.5 bg-red-500/10 border border-red-500/20 rounded-lg">
                    <AlertCircle size={14} className="text-red-400 shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-red-300">{err}</p>
                      <p className="text-[10px] text-red-400/60 mt-0.5">Blocking — must fix before saving. Use Auto-Fix to repair.</p>
                    </div>
                  </div>
                ))}
                {/* Node config errors */}
                {validationIssues.nodeErrors.map((err, i) => {
                  const nodeId = [...validationIssues.brokenNodeIds][i];
                  return (
                    <button
                      key={`ne-${i}`}
                      onClick={() => {
                        if (nodeId) {
                          const node = nodes.find(n => n.id === nodeId);
                          if (node) setSelectedNode(node);
                        }
                      }}
                      className="flex items-start gap-2 p-2.5 w-full text-left bg-amber-500/10 border border-amber-500/20 rounded-lg hover:bg-amber-500/15 transition-colors"
                    >
                      <AlertCircle size={14} className="text-amber-400 shrink-0 mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-amber-300">{err}</p>
                        <p className="text-[10px] text-amber-400/60 mt-0.5">Click to configure · Non-blocking</p>
                      </div>
                    </button>
                  );
                })}
                {/* Warnings */}
                {validationIssues.graphWarnings.map((warn, i) => (
                  <div key={`gw-${i}`} className="flex items-start gap-2 p-2.5 bg-yellow-500/5 border border-yellow-500/10 rounded-lg">
                    <AlertCircle size={14} className="text-yellow-400/70 shrink-0 mt-0.5" />
                    <p className="text-xs text-yellow-300/80">{warn}</p>
                  </div>
                ))}
                {issueCount === 0 && (
                  <div className="text-center py-6">
                    <p className="text-sm text-[var(--text-muted)]">No issues found — workflow looks good!</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Config Panel — FE-11: desktop sidebar + mobile bottom sheet */}
        {selectedNode && (
          <div className="hidden lg:block">
            <NodeConfigPanel
              node={selectedNode}
              integrations={integrationList}
              onUpdate={updateNodeData}
              onDelete={deleteNode}
              onClose={() => setSelectedNode(null)}
            />
          </div>
        )}
        {/* Mobile bottom sheet for node config */}
        {selectedNode && (
          <div className="lg:hidden fixed inset-x-0 bottom-0 z-50 bg-[var(--bg-secondary)] border-t border-[var(--glass-border)] rounded-t-2xl shadow-2xl max-h-[70vh] overflow-y-auto animate-slide-up">
            <div className="flex items-center justify-center pt-2 pb-1">
              <div className="w-10 h-1 rounded-full bg-[var(--border-color)]" />
            </div>
            <NodeConfigPanel
              node={selectedNode}
              integrations={integrationList}
              onUpdate={updateNodeData}
              onDelete={deleteNode}
              onClose={() => setSelectedNode(null)}
            />
          </div>
        )}

        {/* Edge config panel — shown when an edge is selected */}
        {selectedEdge && !selectedNode && (
          <div className="w-72 border-l border-[var(--glass-border)] bg-[var(--bg-secondary)] overflow-y-auto p-4 shrink-0">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold">Connection</h3>
              <button
                onClick={() => setSelectedEdge(null)}
                className="p-1 text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] rounded transition-colors"
                aria-label="Close edge panel"
              >
                <X size={14} />
              </button>
            </div>
            <div className="space-y-3">
              <div className="text-xs text-[var(--text-muted)]">
                <p className="mb-1">
                  <span className="text-[var(--text-secondary)] font-medium">From:</span>{' '}
                  {nodes.find(n => n.id === selectedEdge.source)?.data.label || selectedEdge.source}
                </p>
                <p>
                  <span className="text-[var(--text-secondary)] font-medium">To:</span>{' '}
                  {nodes.find(n => n.id === selectedEdge.target)?.data.label || selectedEdge.target}
                </p>
              </div>
              {selectedEdge.sourceHandle && (
                <div className="text-xs text-[var(--text-muted)]">
                  <span className="text-[var(--text-secondary)] font-medium">Branch:</span>{' '}
                  <span className={selectedEdge.sourceHandle === 'yes' ? 'text-green-400' : 'text-red-400'}>
                    {selectedEdge.sourceHandle}
                  </span>
                </div>
              )}
              {selectedEdge.sourceHandle !== 'yes' && selectedEdge.sourceHandle !== 'no' && <label className="block">
                <span className="text-[10px] text-[var(--text-muted)] mb-0.5 block">Edge Label (optional)</span>
                <input
                  type="text"
                  value={(selectedEdge.label as string) || ''}
                  onChange={e => {
                    const newLabel = e.target.value;
                    setEdges(eds => eds.map(ed => ed.id === selectedEdge.id ? { ...ed, label: newLabel } : ed));
                    setSelectedEdge(prev => prev ? { ...prev, label: newLabel } : prev);
                    markDirty();
                  }}
                  placeholder="e.g. Yes, No, Continue..."
                  className="w-full text-xs bg-[var(--bg-primary)] border border-[var(--glass-border)] rounded px-2 py-1.5 outline-none focus:border-brand-500 transition-colors"
                />
              </label>}
              <button
                onClick={() => deleteEdge(selectedEdge.id)}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-red-600/20 text-red-400 hover:bg-red-600/30 border border-red-500/30 rounded-lg text-xs font-medium transition-colors"
              >
                <X size={12} />
                Delete Connection
              </button>
              <p className="text-[10px] text-[var(--text-muted)] pt-2 border-t border-[var(--glass-border)]">
                Press <kbd className="px-1 py-0.5 bg-[var(--bg-tertiary)] rounded text-[9px]">Delete</kbd> or{' '}
                <kbd className="px-1 py-0.5 bg-[var(--bg-tertiary)] rounded text-[9px]">Backspace</kbd> to remove the selected connection.
              </p>
            </div>
          </div>
        )}

        {/* Keyboard Shortcuts Modal */}
        {showShortcuts && (
            <div className="fixed inset-0 bg-[var(--bg-primary)]/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-fade-in">
              <div
                ref={shortcutsDialogRef}
                role="dialog"
                aria-modal="true"
                aria-labelledby="keyboard-shortcuts-title"
                tabIndex={-1}
                className="bg-[var(--bg-secondary)] border border-[var(--glass-border)] rounded-2xl w-full max-w-sm p-6 shadow-modal animate-scale-in"
              >
              <div className="flex items-center justify-between mb-4">
                  <h3 id="keyboard-shortcuts-title" className="text-base font-semibold flex items-center gap-2">
                  <Keyboard size={16} className="text-brand-400" />
                  Keyboard Shortcuts
                </h3>
                <button
                  onClick={() => setShowShortcuts(false)}
                  aria-label="Close keyboard shortcuts"
                  className="btn-ghost p-1"
                >
                  <X size={16} />
                </button>
              </div>
              <div className="space-y-2">
                {[
                  { keys: ['⌘', 'S'], action: 'Save workflow' },
                  { keys: ['⌘', 'Z'], action: 'Undo' },
                  { keys: ['⌘', 'Y'], action: 'Redo' },
                  { keys: ['Delete'], action: 'Delete selected node' },
                  { keys: ['⌘', 'D'], action: 'Duplicate selected node' },
                  { keys: ['Esc'], action: 'Deselect / close panel' },
                ].map((item) => (
                  <div key={item.action} className="flex items-center justify-between py-2 border-b border-[var(--glass-border)] last:border-0">
                    <span className="text-sm text-[var(--text-secondary)]">{item.action}</span>
                    <div className="flex items-center gap-1">
                      {item.keys.map((k) => (
                        <kbd key={k} className="px-1.5 py-0.5 bg-[var(--bg-tertiary)] border border-[var(--glass-border)] rounded text-[11px] font-mono text-[var(--text-muted)]">
                          {k}
                        </kbd>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function WorkflowEditorPage() {
  return (
    <ReactFlowProvider>
      <WorkflowEditorInner />
    </ReactFlowProvider>
  );
}
