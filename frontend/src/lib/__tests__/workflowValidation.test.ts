// @ts-nocheck
/* eslint-disable */
import type { Edge, Node } from 'reactflow';
import { validateWorkflow } from '../workflowValidation';

function makeNode(id: string, nodeType: string, extra: Record<string, unknown> = {}): Node {
  return {
    id,
    type: 'workflowNode',
    position: { x: 0, y: 0 },
    data: { nodeType, label: id, ...extra },
  };
}

function makeEdge(source: string, target: string, sourceHandle?: string): Edge {
  return {
    id: `e-${source}-${sourceHandle || 'default'}-${target}`,
    source,
    target,
    sourceHandle,
    label: sourceHandle === 'yes' ? 'Yes' : sourceHandle === 'no' ? 'No' : undefined,
    animated: true,
    style: {},
  };
}

describe('validateWorkflow', () => {
  it('accepts a simple valid graph', () => {
    const nodes = [makeNode('trigger', 'trigger'), makeNode('end', 'end')];
    const edges = [makeEdge('trigger', 'end')];
    const result = validateWorkflow({ nodes, edges });
    expect(result.errors).toEqual([]);
  });

  it('rejects missing trigger node', () => {
    const nodes = [makeNode('end', 'end')];
    const edges: Edge[] = [];
    const result = validateWorkflow({ nodes, edges });
    expect(result.errors.some(e => e.includes('trigger'))).toBe(true);
  });

  it('rejects duplicate node IDs', () => {
    const nodes = [makeNode('n1', 'conversation'), makeNode('n1', 'conversation')];
    const edges: Edge[] = [];
    const result = validateWorkflow({ nodes, edges });
    expect(result.errors.some(e => e.includes('Duplicate node ID'))).toBe(true);
    expect(result.brokenNodeIds.has('n1')).toBe(true);
  });

  it('rejects disconnected nodes', () => {
    const nodes = [makeNode('trigger', 'trigger'), makeNode('orphan', 'conversation')];
    const edges: Edge[] = [];
    const result = validateWorkflow({ nodes, edges });
    expect(result.errors.some(e => e.includes('disconnected'))).toBe(true);
  });

  it('rejects outgoing edges from end nodes', () => {
    const nodes = [makeNode('trigger', 'trigger'), makeNode('end', 'end'), makeNode('n1', 'conversation')];
    const edges = [makeEdge('trigger', 'end'), makeEdge('end', 'n1')];
    const result = validateWorkflow({ nodes, edges });
    expect(result.errors.some(e => e.includes('End') && e.includes('outgoing'))).toBe(true);
    expect(result.brokenEdgeIds.size).toBe(1);
  });

  it('rejects conversation nodes without prompt or variables', () => {
    const nodes = [
      makeNode('trigger', 'trigger'),
      makeNode('c1', 'conversation', { config: {} }),
    ];
    const edges = [makeEdge('trigger', 'c1')];
    const result = validateWorkflow({ nodes, edges });
    expect(result.errors.some(e => e.includes('Conversation') && e.includes('prompt'))).toBe(true);
    expect(result.brokenNodeIds.has('c1')).toBe(true);
  });

  it('accepts conversation nodes with variables_to_extract', () => {
    const nodes = [
      makeNode('trigger', 'trigger'),
      makeNode('c1', 'conversation', { config: { variables_to_extract: ['name'] } }),
      makeNode('end', 'end'),
    ];
    const edges = [makeEdge('trigger', 'c1'), makeEdge('c1', 'end')];
    const result = validateWorkflow({ nodes, edges });
    expect(result.errors).toEqual([]);
  });

  it('detects cycles without a condition node', () => {
    const nodes = [makeNode('a', 'conversation'), makeNode('b', 'conversation')];
    const edges = [makeEdge('a', 'b'), makeEdge('b', 'a')];
    const result = validateWorkflow({ nodes, edges });
    expect(result.errors.some(e => e.toLowerCase().includes('cycle'))).toBe(true);
  });

  it('flags missing required_inputs from upstream', () => {
    const nodes = [
      makeNode('trigger', 'trigger'),
      makeNode('ask', 'conversation', { config: { variables_to_extract: ['name'] } }),
      makeNode('action', 'action', { config: { required_inputs: ['name', 'missing'] } }),
    ];
    const edges = [makeEdge('trigger', 'ask'), makeEdge('ask', 'action')];
    const result = validateWorkflow({ nodes, edges });
    expect(result.errors.some(e => e.includes('missing required inputs'))).toBe(true);
    expect(result.brokenNodeIds.has('action')).toBe(true);
  });

  it('requires one edge from each condition handle', () => {
    const nodes = [
      makeNode('trigger', 'trigger'),
      makeNode('condition', 'condition', { config: { expression: 'approved == true' } }),
      makeNode('yes-end', 'end'),
      makeNode('no-end', 'end'),
    ];
    const edges = [
      makeEdge('trigger', 'condition'),
      makeEdge('condition', 'yes-end', 'yes'),
      makeEdge('condition', 'no-end', 'yes'),
    ];

    const result = validateWorkflow({ nodes, edges });

    expect(result.errors.some(e => e.includes('exactly one Yes edge and one No edge'))).toBe(true);
  });

  it('does not treat variables from only one branch as guaranteed', () => {
    const nodes = [
      makeNode('trigger', 'trigger'),
      makeNode('condition', 'condition', { config: { expression: 'existing == true' } }),
      makeNode('collect', 'conversation', { config: { variables_to_extract: ['caller_email'] } }),
      makeNode('skip', 'note'),
      makeNode('action', 'action', { config: { required_inputs: ['caller_email'] } }),
      makeNode('end', 'end'),
    ];
    const edges = [
      makeEdge('trigger', 'condition'),
      makeEdge('condition', 'collect', 'yes'),
      makeEdge('condition', 'skip', 'no'),
      makeEdge('collect', 'action'),
      makeEdge('skip', 'action'),
      makeEdge('action', 'end'),
    ];

    const result = validateWorkflow({ nodes, edges });

    expect(result.errors.some(e => e.includes('caller_email'))).toBe(true);
  });
});
