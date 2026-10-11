'use client';

import { memo, useMemo } from 'react';
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Node,
  Edge,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { nodeTypes } from '@/components/workflow/WorkflowNodes';

interface FlowGraphCanvasProps {
  nodes: Node[];
  edges: Edge[];
  activeNodeId: string | null;
  completedNodeIds: Set<string>;
  failedNodeIds: Set<string>;
  traversedEdgeKeys: Set<string>;
}

function FlowGraphCanvasInner({
  nodes,
  edges,
  activeNodeId,
  completedNodeIds,
  failedNodeIds,
  traversedEdgeKeys,
}: FlowGraphCanvasProps) {
  const styledNodes = useMemo(() => {
    return nodes.map((node) => {
      const isActive = node.id === activeNodeId;
      const isCompleted = completedNodeIds.has(node.id);
      const isFailed = failedNodeIds.has(node.id);

      let className = 'flow-node-idle';
      if (isActive) {
        className = 'flow-node-active';
      } else if (isFailed) {
        className = 'flow-node-failed';
      } else if (isCompleted) {
        className = 'flow-node-completed';
      }

      return {
        ...node,
        className: className || node.className,
        selected: false,
        draggable: false,
        connectable: false,
        data: {
          ...node.data,
          _playgroundStatus: isActive ? 'active' : isFailed ? 'failed' : isCompleted ? 'completed' : 'idle',
        },
      };
    });
  }, [nodes, activeNodeId, completedNodeIds, failedNodeIds]);

  const styledEdges = useMemo(() => {
    return edges.map((edge) => {
      const key = `${edge.source}->${edge.target}`;
      const isTraversed = traversedEdgeKeys.has(key);
      return {
        ...edge,
        animated: isTraversed,
        className: isTraversed ? 'flow-edge-traversed' : '',
        style: {
          ...edge.style,
          stroke: isTraversed ? 'var(--success)' : ((edge.style as Record<string, string> | undefined)?.stroke || 'var(--accent)'),
          strokeWidth: isTraversed ? 3 : 2,
        },
      };
    });
  }, [edges, traversedEdgeKeys]);

  return (
    <ReactFlow
      nodes={styledNodes}
      edges={styledEdges}
      nodeTypes={nodeTypes}
      fitView
      nodesDraggable={false}
      nodesConnectable={false}
      edgesFocusable={false}
      elementsSelectable={false}
      panOnDrag={true}
      zoomOnScroll={true}
      className="bg-[var(--bg-primary)]"
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#2a2a3a" />
      <Controls
        className="!bg-[var(--bg-secondary)] !border-[var(--border-color)] !rounded-lg [&>button]:!bg-[var(--bg-secondary)] [&>button]:!border-[var(--border-color)] [&>button]:!text-[var(--text-secondary)] [&>button:hover]:!bg-[var(--bg-tertiary)]"
        showInteractive={false}
      />
      <MiniMap
        nodeColor={(node) => {
          if (node.id === activeNodeId) return 'var(--warning)';
          if (failedNodeIds.has(node.id)) return 'var(--danger)';
          if (completedNodeIds.has(node.id)) return 'var(--success)';
          return 'var(--accent)';
        }}
        maskColor="rgba(10, 10, 15, 0.7)"
        className="!bg-[var(--bg-secondary)] !border-[var(--border-color)] !rounded-lg"
      />
    </ReactFlow>
  );
}

export const FlowGraphCanvas = memo(FlowGraphCanvasInner);
export default FlowGraphCanvas;
