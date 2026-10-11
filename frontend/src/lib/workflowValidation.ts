/**
 * Phase 5.7: Pure workflow graph validation.
 *
 * Returns human-readable errors/warnings and the IDs of the offending nodes
 * and edges so the editor can highlight them.
 */

import type { Edge, Node } from 'reactflow';

export interface WorkflowValidationResult {
  errors: string[];
  warnings: string[];
  brokenNodeIds: Set<string>;
  brokenEdgeIds: Set<string>;
}

export interface ValidationGraph {
  nodes: Node[];
  edges: Edge[];
}

/**
 * Validate a ReactFlow graph before it is published.
 */
export function validateWorkflow(graph: ValidationGraph): WorkflowValidationResult {
  const { nodes, edges } = graph;
  const errors: string[] = [];
  const warnings: string[] = [];
  const brokenNodeIds = new Set<string>();
  const brokenEdgeIds = new Set<string>();

  const nodeById = new Map<string, Node>();
  const seenIds = new Set<string>();
  let startNodeCount = 0;

  for (const node of nodes) {
    const id = node.id;
    if (seenIds.has(id)) {
      errors.push(`Duplicate node ID "${id}".`);
      brokenNodeIds.add(id);
    } else {
      seenIds.add(id);
      nodeById.set(id, node);
    }
    const nodeType = node.data?.nodeType as string | undefined;
    if (nodeType === 'trigger') startNodeCount++;
  }

  if (startNodeCount === 0) {
    errors.push('Workflow must have exactly one trigger (start) node.');
  } else if (startNodeCount > 1) {
    errors.push(`Workflow must have exactly one trigger node (found ${startNodeCount}).`);
  }

  // Build adjacency maps and validate edge endpoints/source rules.
  const outgoing = new Map<string, Edge[]>();
  const incoming = new Map<string, Edge[]>();

  for (const edge of edges) {
    const sourceNode = nodeById.get(edge.source);
    const targetNode = nodeById.get(edge.target);

    if (!sourceNode || !targetNode) {
      errors.push(`Edge "${edge.id}" references a missing node.`);
      brokenEdgeIds.add(edge.id);
      continue;
    }

    if (edge.source === edge.target) {
      errors.push(`Edge "${edge.id}" is a self-loop.`);
      brokenEdgeIds.add(edge.id);
      continue;
    }

    const sourceType = sourceNode.data?.nodeType as string | undefined;
    if (sourceType === 'end' || sourceType === 'end_call') {
      const label = (sourceNode.data?.label as string) || sourceNode.id;
      errors.push(`End/end_call node "${label}" cannot have outgoing edges.`);
      brokenEdgeIds.add(edge.id);
      brokenNodeIds.add(sourceNode.id);
      continue;
    }

    if (!outgoing.has(edge.source)) outgoing.set(edge.source, []);
    outgoing.get(edge.source)!.push(edge);
    if (!incoming.has(edge.target)) incoming.set(edge.target, []);
    incoming.get(edge.target)!.push(edge);
  }

  // Orphan / disconnected nodes (except trigger).
  for (const node of nodes) {
    const nodeType = node.data?.nodeType as string | undefined;
    const label = (node.data?.label as string) || node.id;
    if (nodeType === 'trigger') continue;
    const hasIncoming = incoming.has(node.id);
    const hasOutgoing = outgoing.has(node.id);
    if (!hasIncoming && !hasOutgoing) {
      errors.push(`Node "${label}" is disconnected (no incoming or outgoing edges).`);
      brokenNodeIds.add(node.id);
    } else if (!hasIncoming && nodeType !== 'end' && nodeType !== 'end_call') {
      warnings.push(`Node "${label}" has no incoming edges.`);
    }
  }

  const triggerNode = nodes.find(n => n.data?.nodeType === 'trigger');
  const reachable = new Set<string>();
  if (triggerNode) {
    const stack = [triggerNode.id];
    while (stack.length > 0) {
      const nodeId = stack.pop()!;
      if (reachable.has(nodeId)) continue;
      reachable.add(nodeId);
      for (const edge of outgoing.get(nodeId) || []) stack.push(edge.target);
    }
  }

  for (const node of nodes) {
    const nodeType = node.data?.nodeType as string | undefined;
    const label = (node.data?.label as string) || node.id;
    if (triggerNode && !reachable.has(node.id)) {
      errors.push(`Node "${label}" is not reachable from the trigger.`);
      brokenNodeIds.add(node.id);
    }
    const hasNoOutgoing = (outgoing.get(node.id) || []).length === 0;
    const isRuntimeTerminal = nodeType === 'end'
      || nodeType === 'end_call'
      || (nodeType === 'transfer_call' && hasNoOutgoing);
    if (!isRuntimeTerminal && hasNoOutgoing) {
      errors.push(`Non-terminal node "${label}" has no outgoing edge.`);
      brokenNodeIds.add(node.id);
    }
  }

  for (const node of nodes) {
    if (node.data?.nodeType !== 'condition') continue;
    const label = (node.data?.label as string) || node.id;
    const branches = outgoing.get(node.id) || [];
    const yesEdges = branches.filter(edge => edge.sourceHandle === 'yes');
    const noEdges = branches.filter(edge => edge.sourceHandle === 'no');
    if (yesEdges.length !== 1 || noEdges.length !== 1 || branches.length !== 2) {
      errors.push(`Condition "${label}" must have exactly one Yes edge and one No edge.`);
      brokenNodeIds.add(node.id);
      branches.forEach(edge => brokenEdgeIds.add(edge.id));
    }
    for (const edge of branches) {
      const expected = edge.sourceHandle === 'yes' ? 'yes' : edge.sourceHandle === 'no' ? 'no' : '';
      const actual = String(edge.label || '').trim().toLowerCase();
      if (!expected || (actual && actual !== expected)) {
        errors.push(`Condition edge "${edge.id}" has an inconsistent branch handle and label.`);
        brokenEdgeIds.add(edge.id);
      }
    }
  }

  // Action handlers emit the explicit on_missing branch whenever a required
  // input is absent. Publishing without exactly one matching edge would fail
  // only at runtime, so treat it as a blocking graph contract violation.
  const nonActionTypes = new Set([
    'trigger', 'condition', 'conversation', 'slot_validator',
    'end', 'end_call', 'note', 'delay', 'voicemail_detect',
  ]);
  for (const node of nodes) {
    const nodeType = String(node.data?.nodeType || '');
    if (nonActionTypes.has(nodeType)) continue;
    const cfg = (node.data?.config as Record<string, unknown> | undefined) || {};
    const required = Array.isArray(cfg.required_inputs) ? cfg.required_inputs : [];
    if (required.length === 0) continue;

    const branches = outgoing.get(node.id) || [];
    const onMissingEdges = branches.filter(edge => {
      const key = String(edge.sourceHandle || edge.label || '').trim().toLowerCase();
      return key === 'on_missing'
        || key === 'on missing'
        || key === 'missing info'
        || key === 'missing input'
        || key === 'missing inputs';
    });
    if (onMissingEdges.length !== 1) {
      const label = String(node.data?.label || node.id);
      errors.push(
        `Action "${label}" must have exactly one Missing info edge because it declares required inputs.`
      );
      brokenNodeIds.add(node.id);
      branches.forEach(edge => brokenEdgeIds.add(edge.id));
    }
  }

  const terminalIds = new Set(
    nodes
      .filter(node => {
        const nodeType = node.data?.nodeType;
        return nodeType === 'end'
          || nodeType === 'end_call'
          || (nodeType === 'transfer_call' && (outgoing.get(node.id) || []).length === 0);
      })
      .map(node => node.id)
  );
  const canReachTerminal = new Set(terminalIds);
  let terminalChanged = true;
  while (terminalChanged) {
    terminalChanged = false;
    for (const edge of edges) {
      if (canReachTerminal.has(edge.target) && !canReachTerminal.has(edge.source)) {
        canReachTerminal.add(edge.source);
        terminalChanged = true;
      }
    }
  }
  for (const nodeId of reachable) {
    if (!canReachTerminal.has(nodeId)) {
      const node = nodeById.get(nodeId);
      errors.push(`Node "${String(node?.data?.label || nodeId)}" cannot reach an end node.`);
      brokenNodeIds.add(nodeId);
    }
  }

  for (let index = 0; index < nodes.length; index++) {
    const left = nodes[index];
    for (const right of nodes.slice(index + 1)) {
      if (
        Math.abs(left.position.x - right.position.x) < 240
        && Math.abs(left.position.y - right.position.y) < 100
      ) {
        warnings.push(
          `Nodes "${String(left.data?.label || left.id)}" and "${String(right.data?.label || right.id)}" overlap on the canvas.`
        );
      }
    }
  }

  // Conversation nodes: need a prompt or variables_to_extract.
  for (const node of nodes) {
    const nodeType = node.data?.nodeType as string | undefined;
    const label = (node.data?.label as string) || node.id;
    if (nodeType !== 'conversation') continue;
    const cfg = (node.data?.config as Record<string, unknown> | undefined) || {};
    const prompt = String(cfg.prompt || node.data?.prompt || '').trim();
    const vars = Array.isArray(cfg.variables_to_extract) ? cfg.variables_to_extract : [];
    if (!prompt && vars.length === 0) {
      errors.push(`Conversation node "${label}" must have a prompt or variables to extract.`);
      brokenNodeIds.add(node.id);
    }
    if (vars.length > 3) {
      warnings.push(
        `Conversation node "${label}" extracts ${vars.length} variables at once. For one-question-at-a-time flow, limit to 3 or fewer.`
      );
    }
  }

  // Required inputs must be collected upstream.
  const upstreamVars = collectGuaranteedVariables(nodes, edges, reachable);

  for (const node of nodes) {
    const nodeType = node.data?.nodeType as string | undefined;
    if (!nodeType || nodeType === 'conversation' || nodeType === 'slot_validator') continue;
    const cfg = (node.data?.config as Record<string, unknown> | undefined) || {};
    const required = Array.isArray(cfg.required_inputs)
      ? (cfg.required_inputs as string[])
      : [];
    if (required.length === 0) continue;
    const optional = new Set(Array.isArray(cfg.optional_inputs) ? cfg.optional_inputs as string[] : []);
    const available = upstreamVars.get(node.id) || new Set<string>();
    const missing = required.filter(v => !optional.has(v) && !available.has(v));
    if (missing.length > 0) {
      const label = (node.data?.label as string) || node.id;
      errors.push(
        `Node "${label}" is missing required inputs from upstream: ${missing.join(', ')}.`
      );
      brokenNodeIds.add(node.id);
    }
  }

  const cycle = findCycle(nodes, edges);
  if (cycle) {
    const cycleNodes = cycle.map(id => nodeById.get(id)).filter(Boolean) as Node[];
    const bounded = cycleNodes.some(node => node.data?.nodeType === 'slot_validator')
      || cycleNodes.some(node => {
        if (node.data?.nodeType !== 'condition') return false;
        const cfg = (node.data?.config as Record<string, unknown> | undefined) || {};
        return String(cfg.expression || '').includes('_slot_retry_count');
      });
    if (bounded) {
      warnings.push(`Bounded retry cycle detected: ${cycle.join(' → ')}.`);
    } else {
      errors.push(`Unbounded cycle detected: ${cycle.join(' → ')}.`);
      for (const id of cycle) brokenNodeIds.add(id);
    }
  }

  return { errors, warnings, brokenNodeIds, brokenEdgeIds };
}

/** Expand a variable name to include known aliases. */
function expandVariableAliases(name: string): string[] {
  const aliases = new Set<string>([name]);
  const n = name.toLowerCase();
  if (n === 'patient_name' || n === 'caller_name') {
    aliases.add('patient_name').add('caller_name');
  }
  if (n === 'caller_email' || n === 'email') {
    aliases.add('caller_email').add('email');
  }
  if (n === 'caller_phone' || n === 'phone' || n === 'mobile') {
    aliases.add('caller_phone').add('phone').add('mobile');
  }
  return Array.from(aliases);
}

/** Collect variables guaranteed on every path to each node using dominators. */
function collectGuaranteedVariables(
  nodes: Node[],
  edges: Edge[],
  reachable: Set<string>,
): Map<string, Set<string>> {
  const result = new Map<string, Set<string>>();
  const predecessors = new Map<string, string[]>();
  for (const edge of edges) {
    if (!reachable.has(edge.source) || !reachable.has(edge.target)) continue;
    if (!predecessors.has(edge.target)) predecessors.set(edge.target, []);
    predecessors.get(edge.target)!.push(edge.source);
  }

  const nodeVars = new Map<string, Set<string>>();
  for (const node of nodes) {
    const vars = new Set<string>();
    const cfg = (node.data?.config as Record<string, unknown> | undefined) || {};
    if (node.data?.nodeType === 'conversation') {
      const extracted = Array.isArray(cfg.variables_to_extract) ? cfg.variables_to_extract : [];
      for (const v of extracted) {
        if (typeof v === 'string' && v.trim()) {
          for (const alias of expandVariableAliases(v.trim())) {
            vars.add(alias);
          }
        }
      }
    }
    const prefillMapping = cfg.prefill_mapping;
    if (prefillMapping && typeof prefillMapping === 'object') {
      for (const value of Object.values(prefillMapping as Record<string, unknown>)) {
        if (typeof value === 'string' && value.trim()) {
          for (const alias of expandVariableAliases(value.trim())) vars.add(alias);
        }
      }
    }
    const responseMappings = cfg.response_mappings;
    if (responseMappings && typeof responseMappings === 'object') {
      for (const key of Object.keys(responseMappings as Record<string, unknown>)) vars.add(key);
    }
    nodeVars.set(node.id, vars);
  }

  const trigger = nodes.find(n => n.data?.nodeType === 'trigger');
  if (!trigger) return result;

  const allReachable = new Set(reachable);
  const dominators = new Map<string, Set<string>>();
  for (const nodeId of reachable) {
    dominators.set(nodeId, nodeId === trigger.id ? new Set([nodeId]) : new Set(allReachable));
  }

  for (let iteration = 0; iteration < nodes.length + edges.length; iteration++) {
    let changed = false;
    for (const nodeId of reachable) {
      if (nodeId === trigger.id) continue;
      const preds = predecessors.get(nodeId) || [];
      if (preds.length === 0) continue;
      const intersection = new Set(dominators.get(preds[0]) || []);
      for (const predId of preds.slice(1)) {
        const predDominators = dominators.get(predId) || new Set<string>();
        for (const candidate of Array.from(intersection)) {
          if (!predDominators.has(candidate)) intersection.delete(candidate);
        }
      }
      intersection.add(nodeId);
      const previous = dominators.get(nodeId) || new Set<string>();
      if (
        previous.size !== intersection.size
        || Array.from(previous).some(candidate => !intersection.has(candidate))
      ) {
        dominators.set(nodeId, intersection);
        changed = true;
      }
    }
    if (!changed) break;
  }

  const systemVariables = new Set([
    'caller_name', 'caller_phone', 'current_date', 'current_time',
    'call_date', 'call_time', 'now', 'transcript',
  ]);
  for (const nodeId of reachable) {
    const available = new Set(systemVariables);
    for (const dominatorId of dominators.get(nodeId) || []) {
      if (dominatorId === nodeId) continue;
      for (const variable of nodeVars.get(dominatorId) || []) available.add(variable);
    }
    result.set(nodeId, available);
  }

  return result;
}

/** Find any cycle in the graph. */
function findCycle(nodes: Node[], edges: Edge[]): string[] | null {
  const outgoing = new Map<string, string[]>();
  for (const edge of edges) {
    if (!outgoing.has(edge.source)) outgoing.set(edge.source, []);
    outgoing.get(edge.source)!.push(edge.target);
  }

  const visiting = new Set<string>();
  const visited = new Set<string>();

  function dfs(nodeId: string, path: string[]): string[] | null {
    if (visiting.has(nodeId)) {
      const idx = path.indexOf(nodeId);
      return idx >= 0 ? path.slice(idx).concat([nodeId]) : null;
    }
    if (visited.has(nodeId)) return null;
    visiting.add(nodeId);
    path.push(nodeId);
    for (const nextId of outgoing.get(nodeId) || []) {
      const cycle = dfs(nextId, path);
      if (cycle) return cycle;
    }
    path.pop();
    visiting.delete(nodeId);
    visited.add(nodeId);
    return null;
  }

  for (const node of nodes) {
    if (!visited.has(node.id)) {
      const cycle = dfs(node.id, []);
      if (cycle) return cycle;
    }
  }
  return null;
}
